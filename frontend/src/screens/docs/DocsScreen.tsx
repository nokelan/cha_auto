/**
 * [파일 역할] 개발문서 열람 화면. 서버의 /api/devdocs 목록과 문서 본문(마크다운)을 읽어 화면에 렌더한다.
 * 선택 문서·목차는 App이 소유한 상태로 오른쪽 관련 링크(RelatedLinks)와 공유한다(localStorage 미사용).
 * 렌더 세부(정화·링크 분류·mermaid)는 renderMarkdown.ts가 맡는다.
 */
import {useEffect, useRef, useState} from 'react';
import {api, apiText} from '../../api';
import type {DevDocInfo, DocToc} from '../../types';
import {errorMessage} from '../../utils/error';
import {decodeSafe, renderMarkdownInto, renderMermaidJobs} from './renderMarkdown';
import './docs.css';

/** [상수 명세] FIRST_DOC — 첫 진입 때 기본으로 여는 문서 파일명. */
const FIRST_DOC = '00_문서목록.md';

/**
 * [기능명세] scrollToAnchor
 * 목적: 현재 문서 안에서 앵커(제목 id 또는 GitHub식 슬러그)로 스크롤한다.
 * 입력: root 본문 컨테이너, anchor 앵커 문자열. 출력: 이동했으면 true.
 * 부수효과: 가장 가까운 스크롤 조상(.workspace-main)의 스크롤 위치 변경
 */
function scrollToAnchor(root: HTMLElement, anchor: string): boolean {
  const key = decodeSafe(anchor);
  const el = Array.from(root.querySelectorAll<HTMLElement>('h1,h2,h3,h4')).find(h => h.id === key || h.dataset.slug === key);
  el?.scrollIntoView({block: 'start'});
  return !!el;
}

/**
 * [기능명세] DocsScreen
 * 목적: 개발문서 한 건을 읽기 전용으로 보여 준다.
 * 입력: name(선택 문서 파일명, 빈 문자열이면 아직 없음), onSelect(문서 전환), onDocs(목록 전달), onToc(목차 전달)
 * 출력: 상태 문구(불러오는 중·오류·빈 목록) 또는 문서 본문 article JSX.
 * 처리 규칙: 마운트 시 목록 조회 → name이 비어 있으면 00_문서목록.md(없으면 첫 문서) 선택. name이 바뀌면 본문 조회·렌더·목차 전달.
 *   본문 안 `NN_*.md#앵커` 링크 클릭은 onSelect로 문서 전환(앵커는 렌더 후 이동), `#앵커`는 현재 문서 안 이동.
 *   응답이 오기 전에 문서가 바뀌면 이전 응답은 버린다.
 * 예외: 목록·본문 조회 실패는 한글 오류 문구로 화면에 표시(401은 api 흐름이 잠금 화면으로 복귀시킴). 목록이 비면 빈 상태 문구.
 * 부수효과: GET /api/devdocs, GET /api/devdocs/{name}, 본문 DOM 직접 갱신, mermaid 동적 로딩
 */
export function DocsScreen({name, onSelect, onDocs, onToc}: {
  name: string;
  onSelect: (name: string) => void;
  onDocs: (docs: DevDocInfo[]) => void;
  onToc: (toc: DocToc[]) => void;
}) {
  const [listState, setListState] = useState<'loading' | 'ready' | 'empty' | 'error'>('loading');
  const [bodyState, setBodyState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [message, setMessage] = useState('');
  const articleRef = useRef<HTMLElement>(null);
  const pendingAnchor = useRef('');
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;

  /** [효과 명세] 목록 조회: 마운트 한 번. 성공 시 onDocs 전달, 선택 문서가 없으면 기본 문서 선택. */
  useEffect(() => {
    let off = false;
    api<{docs: DevDocInfo[]}>('devdocs').then(r => {
      if (off) return;
      onDocs(r.docs);
      if (!r.docs.length) { setListState('empty'); return; }
      setListState('ready');
      if (!name) selectRef.current((r.docs.find(d => d.name === FIRST_DOC) ?? r.docs[0]).name);
    }).catch(e => {
      if (off) return;
      setMessage(errorMessage(e));
      setListState('error');
    });
    return () => { off = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** [효과 명세] 본문 조회·렌더: 목록 준비 후 name 변경 때마다. 이전 요청 결과는 폐기한다. */
  useEffect(() => {
    if (!name || listState !== 'ready') return;
    let off = false;
    setBodyState('loading');
    apiText('devdocs/' + encodeURIComponent(name)).then(md => {
      const el = articleRef.current;
      if (off || !el) return;
      const {toc, mermaid} = renderMarkdownInto(el, md);
      onToc(toc);
      setBodyState('ready');
      const anchor = pendingAnchor.current;
      pendingAnchor.current = '';
      // hidden 해제(상태 반영) 후에 스크롤해야 하므로 다음 프레임에 이동한다.
      requestAnimationFrame(() => { if (!off) { if (anchor) scrollToAnchor(el, anchor); else el.scrollIntoView({block: 'start'}); } });
      void renderMermaidJobs(mermaid, () => off).then(() => {
        // 도형이 그려져 높이가 바뀐 뒤에도 앵커 위치를 다시 맞춘다.
        if (!off && anchor) scrollToAnchor(el, anchor);
      });
    }).catch(e => {
      if (off) return;
      onToc([]);
      setMessage(errorMessage(e));
      setBodyState('error');
    });
    return () => { off = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, listState]);

  /** [콜백 명세] 본문 클릭 위임: data-doc/data-anchor 링크만 처리하고 그 외 클릭은 그대로 둔다. */
  const onClick = (e: React.MouseEvent<HTMLElement>) => {
    const a = (e.target as HTMLElement).closest<HTMLElement>('a[data-doc],a[data-anchor]');
    if (!a) return;
    e.preventDefault();
    const doc = a.dataset.doc;
    const anchor = a.dataset.anchor ?? '';
    if (doc && doc !== name) {
      pendingAnchor.current = anchor;
      onSelect(doc);
    } else if (articleRef.current && anchor) {
      scrollToAnchor(articleRef.current, anchor);
    } else if (doc) {
      articleRef.current?.scrollIntoView({block: 'start'});
    }
  };

  return (
    <>
      {listState === 'loading' && <div className="docs-state" role="status">개발문서 목록을 불러오는 중입니다…</div>}
      {listState === 'error' && <div className="docs-state error" role="alert">{message || '개발문서 목록을 불러오지 못했습니다.'}</div>}
      {listState === 'empty' && <div className="docs-state">열람할 개발문서가 없습니다.</div>}
      {listState === 'ready' && bodyState === 'loading' && <div className="docs-state" role="status">문서를 불러오는 중입니다…</div>}
      {listState === 'ready' && bodyState === 'error' && <div className="docs-state error" role="alert">{message || '문서를 불러오지 못했습니다.'}</div>}
      <article ref={articleRef} className="docs-article" onClick={onClick} hidden={listState !== 'ready' || bodyState !== 'ready'}/>
    </>
  );
}
