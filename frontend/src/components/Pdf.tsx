/**
 * [파일 역할] PDF.js로 저장된 원본 PDF 한 건을 Canvas에 그리는 뷰어 컴포넌트.
 * 페이지 이동, 버튼·클릭 확대(1~3배), 확대 상태에서 마우스 드래그 이동을 지원한다.
 * PDF.js worker와 글꼴·CMap·WASM은 서버의 로컬 자산(/pdfjs/...)을 사용한다(인터넷 불필요).
 */
import {useEffect, useRef, useState, type MouseEvent, type PointerEvent} from 'react';
import {ChevronLeft, ChevronRight, LoaderCircle} from 'lucide-react';
import {getDocument, GlobalWorkerOptions, type PDFDocumentProxy, type RenderTask} from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import type {Doc} from '../types';
import {errorMessage} from '../utils/error';

GlobalWorkerOptions.workerSrc = workerUrl;

/**
 * [기능명세] Pdf
 * 목적: 문서별 페이지·확대 상태를 갖는 PDF 뷰어
 * 입력: doc: 문서 ID/이름, initialPage: 처음 표시할 페이지(기본 1)
 * 출력: PDF 도구 막대·배율 도구·Canvas JSX
 * 처리/실패: 영역 너비 측정 → (문서가 바뀔 때만) /api/documents/{id} 요청·해석 → 보관한 pdf로 페이지 렌더 → 확대 후 스크롤 보정.
 *   페이지 이동·확대·폭 변화는 문서를 다시 받지 않고 렌더만 다시 한다. 읽기 실패 시 안내 문구를 표시한다.
 *   도구 막대에 "원본 열기"(새 탭)와 "내려받기"(?download=1, 서버가 attachment로 응답하는 <a download>) 링크를 둔다.
 * 부수효과: PDF 요청·worker·Canvas·ResizeObserver 사용. 문서 효과 정리에서 문서 해제, 렌더 효과 정리에서 렌더 취소
 */
export function Pdf({doc, initialPage = 1}: {doc: Doc; initialPage?: number}) {
  const [page, setPage] = useState(initialPage);
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [count, setCount] = useState(0);
  const [err, setErr] = useState('');
  const [loading, setLoading] = useState(true);
  const [zoom, setZoom] = useState(1);
  const [fitWidth, setFitWidth] = useState(600);
  const [panning, setPanning] = useState(false);
  const canvas = useRef<HTMLCanvasElement>(null);
  const body = useRef<HTMLDivElement>(null);
  /** 클릭 확대 시 가운데로 맞출 Canvas 상대 좌표(0~1). 스크롤 보정 후 비운다. */
  const anchor = useRef<{x: number; y: number} | null>(null);
  /** 진행 중인 마우스 드래그의 시작 좌표·스크롤 위치. */
  const pan = useRef<{id: number; x: number; y: number; left: number; top: number; moved: boolean} | null>(null);
  /** 드래그 직후 발생하는 click을 한 번 무시하기 위한 표시. */
  const suppressClick = useRef(false);

  /**
   * [기능명세] startPan
   * 입력: Canvas의 PointerEvent. 출력: void.
   * 처리/실패: 로딩·오류 중이거나 왼쪽 마우스가 아니면 무시하고 시작 좌표·스크롤을 보관한다.
   * 부수효과: 포인터를 Canvas에 캡처한다. 터치의 기본 스크롤은 변경하지 않는다.
   */
  const startPan = (e: PointerEvent<HTMLCanvasElement>) => {
    if (e.pointerType !== 'mouse' || e.button !== 0 || loading || err || !body.current) return;
    suppressClick.current = false;
    pan.current = {
      id: e.pointerId,
      x: e.clientX,
      y: e.clientY,
      left: body.current.scrollLeft,
      top: body.current.scrollTop,
      moved: false,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  /**
   * [기능명세] movePan
   * 입력: 캡처된 PointerEvent. 출력: void.
   * 처리/실패: 시작점에서 4px 이상 움직였을 때만 드래그로 판정하고 이동량 반대로 스크롤한다.
   * 부수효과: PDF 본문 스크롤·커서 상태를 변경하며 드래그 직후 확대 클릭을 억제한다.
   */
  const movePan = (e: PointerEvent<HTMLCanvasElement>) => {
    const start = pan.current;
    if (!start || start.id !== e.pointerId || !body.current) return;
    const dx = e.clientX - start.x;
    const dy = e.clientY - start.y;
    if (!start.moved && Math.hypot(dx, dy) < 4) return;
    start.moved = true;
    suppressClick.current = true;
    setPanning(true);
    e.preventDefault();
    body.current.scrollTo(start.left - dx, start.top - dy);
  };

  /**
   * [기능명세] finishPan
   * 입력: 포인터 종료·취소·캡처 해제 이벤트. 출력: void.
   * 처리/실패: 다른 포인터는 무시하고 캡처를 해제한다. 짧은 클릭은 확대 동작에 넘긴다.
   * 부수효과: 드래그 참조·커서를 정리한다. 이동 뒤의 click은 toggleZoom이 한 번 무시한다.
   */
  const finishPan = (e: PointerEvent<HTMLCanvasElement>) => {
    if (pan.current?.id !== e.pointerId) return;
    pan.current = null;
    setPanning(false);
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
  };

  /**
   * [효과 명세] 표시 영역 크기 관찰
   * 입력: 없음(마운트 1회). 출력: 정리 함수.
   * 처리: ResizeObserver로 본문 너비를 관찰해 좌우 여백 32px를 뺀 맞춤 너비(최소 100)를 설정한다.
   * 부수효과/정리: fitWidth 변경. 언마운트 시 observer.disconnect.
   */
  useEffect(() => {
    const el = body.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setFitWidth(Math.max(100, el.clientWidth - 32)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  /**
   * [기능명세] changeZoom
   * 목적: 버튼 배율 변경
   * 입력: value: 화면 맞춤 기준 배율
   * 출력: void
   * 처리/실패: 클릭 앵커를 비우고 1~3으로 제한하며 소수 두 자리로 정리
   * 부수효과: zoom 상태 변경으로 재렌더링 요청
   */
  const changeZoom = (value: number) => {
    anchor.current = null;
    setZoom(Math.max(1, Math.min(3, Math.round(value * 100) / 100)));
  };

  /**
   * [기능명세] toggleZoom
   * 목적: 클릭·키보드 확대 전환
   * 입력: 선택적 Canvas 마우스 이벤트(키보드 호출은 없음)
   * 출력: void
   * 처리/실패: 드래그 직후 클릭·로딩/오류 중에는 무시. 맞춤(1배)→2배, 그 외→맞춤.
   *   마우스로 확대할 때만 클릭 위치의 상대 좌표를 보관한다
   * 부수효과: zoom·anchor 변경. 실제 스크롤은 렌더 완료 효과가 담당
   */
  const toggleZoom = (e?: MouseEvent<HTMLCanvasElement>) => {
    if (e && suppressClick.current) {
      suppressClick.current = false;
      return;
    }
    if (loading || err) return;
    if (zoom === 1 && e) {
      const rect = e.currentTarget.getBoundingClientRect();
      anchor.current = {x: (e.clientX - rect.left) / rect.width, y: (e.clientY - rect.top) / rect.height};
    } else {
      anchor.current = null;
    }
    setZoom(zoom === 1 ? 2 : 1);
  };

  /**
   * [효과 명세] PDF 문서 로드 수명
   * 입력: doc.id만. 출력: 정리 함수.
   * 처리: 문서가 바뀔 때 /api/documents/{id}를 한 번 요청·해석해 pdf 객체를 상태로 보관하고 페이지 수를 정한다.
   *   페이지 이동·확대·폭 변화에는 다시 요청하지 않는다(렌더 효과가 보관한 pdf를 재사용).
   * 실패: 요청·해석 실패 시 저장 경로 확인 안내와 오류 메시지를 표시하고 로딩을 끝낸다.
   * 부수효과/정리: 로딩·오류·pdf·페이지 수 변경. 정리 시 disposed 표시·로딩 작업 해제(문서 destroy).
   */
  useEffect(() => {
    let disposed = false;
    setPdf(null);
    setLoading(true);
    setErr('');
    const task = getDocument({
      url: '/api/documents/' + doc.id,
      cMapUrl: '/pdfjs/cmaps/',
      cMapPacked: true,
      standardFontDataUrl: '/pdfjs/standard_fonts/',
      wasmUrl: '/pdfjs/wasm/',
    });
    task.promise
      .then(loaded => {
        if (disposed) return;
        setCount(loaded.numPages);
        setPdf(loaded);
      })
      .catch((e: unknown) => {
        if (!disposed) {
          setErr('PDF를 표시할 수 없습니다. 저장 경로와 파일을 확인해 주세요. ' + errorMessage(e));
          setLoading(false);
        }
      });
    return () => {
      disposed = true;
      void task.destroy();
    };
  }, [doc.id]);

  /**
   * [효과 명세] PDF 페이지 렌더 수명
   * 입력: pdf(보관된 문서)·page·zoom·fitWidth. 출력: 정리 함수.
   * 처리: pdf가 준비되면 요청 페이지(문서 페이지 수보다 크면 마지막 페이지)를 맞춤 너비×배율×(최대 2배 DPR) 크기로 Canvas에 렌더한다.
   *   입력이 바뀌면 진행 중 렌더를 취소하고 다시 그린다. 네트워크 요청은 하지 않는다.
   * 실패: 페이지 읽기·렌더 실패 시 저장 경로 확인 안내와 오류 메시지를 표시한다(취소된 렌더는 무시).
   * 부수효과/정리: 로딩·오류 변경, Canvas 크기·그림 변경. 정리 시 disposed 표시·렌더 취소.
   */
  useEffect(() => {
    if (!pdf) return;
    let disposed = false;
    let renderTask: RenderTask | undefined;
    setLoading(true);
    setErr('');
    void (async () => {
      try {
        const p = await pdf.getPage(Math.min(page, pdf.numPages));
        if (disposed || !canvas.current) return;
        const scale = fitWidth * zoom / p.getViewport({scale: 1}).width * Math.min(window.devicePixelRatio || 1, 2);
        const viewport = p.getViewport({scale});
        const el = canvas.current;
        el.width = viewport.width;
        el.height = viewport.height;
        renderTask = p.render({canvas: el, viewport});
        await renderTask.promise;
        if (!disposed) setLoading(false);
      } catch (e: unknown) {
        if (!disposed) {
          setErr('PDF를 표시할 수 없습니다. 저장 경로와 파일을 확인해 주세요. ' + errorMessage(e));
          setLoading(false);
        }
      }
    })();
    return () => {
      disposed = true;
      renderTask?.cancel();
    };
  }, [pdf, page, zoom, fitWidth]);

  /**
   * [효과 명세] 렌더 완료 후 스크롤 보정
   * 입력: loading·zoom. 출력: void.
   * 처리: 로딩이 끝나면 맞춤(1배)은 좌상단으로, 클릭 확대는 저장한 상대 좌표가 가운데 오도록 스크롤한다.
   * 부수효과: PDF 본문 scrollLeft/scrollTop 변경, anchor 참조 비움.
   */
  useEffect(() => {
    if (loading || !body.current || !canvas.current) return;
    if (zoom === 1) {
      body.current.scrollTo(0, 0);
    } else if (anchor.current) {
      const point = anchor.current;
      body.current.scrollTo(
        point.x * canvas.current.clientWidth - body.current.clientWidth / 2,
        point.y * canvas.current.clientHeight - body.current.clientHeight / 2,
      );
      anchor.current = null;
    }
  }, [loading, zoom]);

  // 같은 문서 URL에 download=1을 붙여 서버가 attachment로 응답하게 한다(이미 쿼리가 있으면 &로 잇는다).
  const docUrl = '/api/documents/' + doc.id;
  const downloadUrl = docUrl + (docUrl.includes('?') ? '&' : '?') + 'download=1';

  return (
    <div className="pdf">
      <div className="pdf-tools">
        <span title={doc.name}>{doc.name}</span>
        <div>
          <button aria-label="이전 페이지" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            <ChevronLeft size={16}/>
          </button>
          <b>{page} / {count || '…'}</b>
          <button aria-label="다음 페이지" disabled={page >= count} onClick={() => setPage(page + 1)}>
            <ChevronRight size={16}/>
          </button>
        </div>
        <a href={'/api/documents/' + doc.id} target="_blank" rel="noreferrer">원본 열기</a>
        <a href={downloadUrl} download aria-label={doc.name + ' 내려받기'}>내려받기</a>
      </div>
      <div className="pdf-zoom-tools">
        <span>클릭해서 {zoom === 1 ? '확대' : '화면 맞춤'} · 드래그해서 이동</span>
        <button aria-label="문서 축소" disabled={zoom <= 1 || loading || !!err} onClick={() => changeZoom(zoom - .25)}>−</button>
        <output aria-label="문서 확대 비율" title="화면 맞춤 크기 기준">{Math.round(zoom * 100)}%</output>
        <button aria-label="문서 확대" disabled={zoom >= 3 || loading || !!err} onClick={() => changeZoom(zoom + .25)}>+</button>
        <button className="fit-button" disabled={zoom === 1} onClick={() => changeZoom(1)}>화면 맞춤</button>
      </div>
      <div className="pdf-body" ref={body} aria-busy={loading}>
        {loading && <p><LoaderCircle className="spin" size={16}/> 문서 불러오는 중</p>}
        {err && <p className="error">{err}</p>}
        <canvas
          ref={canvas}
          hidden={loading || !!err}
          style={{
            width: fitWidth * zoom,
            maxWidth: 'none',
            cursor: panning ? 'grabbing' : zoom === 1 ? 'zoom-in' : 'grab',
            userSelect: 'none',
          }}
          role="button"
          tabIndex={loading || err ? -1 : 0}
          aria-label={zoom === 1 ? '문서 이미지 클릭하여 확대' : '문서 이미지 클릭하여 화면 맞춤'}
          aria-pressed={zoom > 1}
          draggable={false}
          onPointerDown={startPan}
          onPointerMove={movePan}
          onPointerUp={finishPan}
          onPointerCancel={finishPan}
          onLostPointerCapture={finishPan}
          onClick={toggleZoom}
          onKeyDown={e => {
            // Enter·Space로 클릭 확대와 같은 전환을 수행한다(스크롤 기본 동작은 막음).
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              toggleZoom();
            }
          }}
        />
      </div>
    </div>
  );
}
