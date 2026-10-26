/**
 * [파일 역할] '로컬 세금계산서 대조' 화면의 오른쪽 상세 패널(LocalAuditScreen에서 분리).
 * 선택한 세금계산서의 판정 설명·후보 계약·판독값·항목별 판정(CheckList)·계약서 원문(Pdf)을 보여 준다.
 * 로컬 세금계산서 파일 자체는 문서 저장소에 없으므로 원문 뷰어로 보여 주지 않는다.
 */
import {useRef, useState} from 'react';
import {AlertTriangle} from 'lucide-react';
import {display} from '../../api';
import {Badge} from '../../components/Badge';
import {CheckList} from '../../components/CheckList';
import {Pdf} from '../../components/Pdf';
import type {Doc} from '../../types';
import {fileSize, INVOICE_FIELDS, invoiceText, type ViewRow} from './localRows';

/**
 * [기능명세] LocalDetail
 * 목적: 선택한 세금계산서 한 건의 대조 상세 표시
 * 입력: row(선택한 ViewRow)
 * 출력: 제목(파일명·판정 배지)·판정 설명·후보 계약·판독값·항목별 판정(CheckList)·계약서 원문(Pdf) JSX
 * 처리/실패: 대조 전 행은 판독값과 '아직 대조하지 않았습니다' 안내만 보인다. 판독 오류(invoice.error)는 amber 경고.
 *   후보는 2건 이상이거나, 고른 계약 없이 1건 이상일 때 목록으로 보인다.
 *   contract_doc.available이면 Pdf로 원문을 보이고, CheckList의 '계약서 해당 페이지 보기'로 근거 페이지로 이동한다.
 *   원문이 없으면 안내 문구를 보인다
 * 부수효과: 원문 뷰어가 /api/documents/{id}를 요청한다(Pdf 담당). 페이지 이동 시 뷰어를 새로 만들고 화면을 뷰어로 스크롤한다
 */
export function LocalDetail({row}: {row: ViewRow}) {
  const [pdfPage, setPdfPage] = useState(1);
  const pdfBox = useRef<HTMLDivElement>(null);
  const f = row.invoice?.fields;
  const doc: Doc | null = row.contract_doc;
  const showCandidates = row.candidates.length > 1 || (!row.contract && row.candidates.length > 0);

  /**
   * [기능명세] goPage
   * 목적: 판정 항목의 계약서 근거 페이지로 원문 뷰어 이동(CheckList onPage)
   * 입력: page(1부터 시작하는 페이지 번호, 없으면 1)
   * 출력: void
   * 처리/실패: 페이지를 바꾸면 Pdf를 새 key로 다시 만들어 그 페이지부터 그린다. 뷰어가 없으면 스크롤만 생략한다
   * 부수효과: pdfPage 상태 변경, 원문 뷰어 영역으로 부드럽게 스크롤
   */
  const goPage = (page: number) => {
    setPdfPage(page);
    pdfBox.current?.scrollIntoView({behavior: 'smooth', block: 'start'});
  };

  return (
    <>
      <div className="panel-heading">
        <div>
          <h2>{row.file} <span>{row.type === 'png' ? 'PNG' : 'PDF'}</span></h2>
          <p>
            {display(row.partner)}{row.partner_source === 'filename' ? ' (파일명에서 읽음)' : ''} · {fileSize(row.size)}
            {row.contract && <> · 관련 계약 {row.contract.id} {row.contract.kind} · {row.contract.title}</>}
          </p>
        </div>
        <Badge status={row.status}/>
      </div>
      <div className="contracts-detail-body">
        {!row.audited && (
          <div role="status" className="alert amber"><AlertTriangle size={17}/>아직 대조하지 않았습니다. 위 [웹 계약서와 대조]를 누르세요.</div>
        )}
        {row.note && <p className="local-note">{row.note}</p>}
        {row.invoice?.error && (
          <div role="alert" className="alert amber"><AlertTriangle size={17}/>{row.invoice.error}</div>
        )}
        {row.contract && (
          <dl className="contracts-fields">
            <div><dt>관련 계약</dt><dd>{row.contract.id} · {row.contract.kind}</dd></div>
            <div><dt>거래처</dt><dd>{row.contract.partner}</dd></div>
            <div><dt>계약기간</dt><dd>{row.contract.period || '미확인'}</dd></div>
            <div><dt>계약 금액</dt><dd>{row.contract.amount_text || '미확인'}</dd></div>
            <div><dt>기대 공급가액</dt><dd className={row.expected?.supply == null ? 'missing' : ''}>{display(row.expected?.supply)}</dd></div>
            <div><dt>기대 세액 / 합계</dt><dd>{display(row.expected?.vat)} / {display(row.expected?.total)}</dd></div>
          </dl>
        )}
        {showCandidates && (
          <div className="local-candidates">
            <h3>상호가 맞는 웹 계약 후보 {row.candidates.length}건</h3>
            <ul>
              {row.candidates.map(c => (
                <li key={c.id} className={c.id === row.contract?.id ? 'chosen' : ''}>
                  <b>{c.id}</b>
                  <span className={'badge ' + (c.kind === '수입' ? 'green' : 'amber')}>{c.kind}</span>
                  <span>{c.partner}</span>
                  <small>{c.title}</small>
                </li>
              ))}
            </ul>
          </div>
        )}
        <div>
          <h3 className="local-subtitle">세금계산서 판독값</h3>
          <dl className="contracts-fields">
            {INVOICE_FIELDS.map(([key, label]) => {
              const value = invoiceText(f, key);
              return (
                <div key={key}>
                  <dt>{label}</dt>
                  <dd className={value === '미확인' ? 'missing' : ''}>{value}</dd>
                </div>
              );
            })}
          </dl>
        </div>
      </div>
      {row.checks.length > 0 && (
        <div className="local-checks">
          <h3 className="local-subtitle">항목별 판정</h3>
          <CheckList
            checks={row.checks}
            onPage={doc?.available ? c => goPage(c.contract_source?.page || 1) : undefined}
            pageLabel="계약서 해당 페이지 보기"
          />
        </div>
      )}
      {row.audited && row.contract && (
        <div className="contracts-detail-body local-pdf" ref={pdfBox}>
          <h3 className="local-subtitle">계약서 원문</h3>
          {doc && doc.available
            ? <div className="contracts-pdf-view"><Pdf key={doc.id + ':' + pdfPage} doc={doc} initialPage={pdfPage}/></div>
            : <div className="empty"><h3>원문 PDF가 없습니다</h3><p>그룹웨어에 계약서 파일이 없거나 저장된 파일을 찾지 못했습니다.</p></div>}
        </div>
      )}
    </>
  );
}
