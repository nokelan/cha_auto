/** [파일 역할] 계약 추출값·원문·상태와 작업 버튼 표시. 초안 요청과 모달은 상위 컨테이너가 담당한다. */
import {AlertTriangle} from 'lucide-react';
import {display} from '../../api';
import {Pdf} from '../../components/Pdf';
import type {Field, ImportedContract} from '../../types';
import {CompareBadge, ContractActions, ContractStatus, SITE_DRAFT_WARNING} from './ContractActions';
/**
 * [기능명세] fieldText
 * 목적: 계약서 추출 필드 하나를 상세 화면 문자열로 변환
 * 입력: fields(추출 필드 사전, 없을 수 있음), key(필드 키), map(코드값→표시 문구 변환표, 선택)
 * 출력: 표시 문자열. 값이 없으면 '미확인'
 * 처리/실패: map에 해당 값이 있으면 그 문구를, 아니면 display()로 숫자 천 단위·배열 쉼표 연결 처리
 * 부수효과: 없음
 */
function fieldText(fields: Record<string, Field> | undefined, key: string, map?: Record<string, string>): string {
  const v = fields?.[key]?.value;
  if (v === null || v === undefined || v === '') return '미확인';
  if (map && typeof v === 'string' && map[v]) return map[v];
  return display(v);
}

/**
 * [기능명세] ContractDetail
 * 목적: 선택한 계약 한 건의 상태·추출값 표·PDF 원문과 작업 버튼 표시
 * 입력: contract(선택 계약), busy(작업 중), loading(초안 요청 중), onOpen(작업 열기 콜백)
 * 출력: 제목·상태·작업 버튼·추출값 목록·판독 오류 경고·원문 뷰어 또는 원문 없음 안내 JSX
 * 처리/실패: document가 없거나 available이 false면 뷰어 대신 안내 문구를 보인다.
 *   extraction.error가 있으면 경고로 표시한다. 없는 추출값은 '미확인'.
 *   approval.site_draft가 true이면 기안 확인 경고(role=alert)를 본문 맨 위에 표시한다. 작업 버튼은 ContractActions에서 비활성 사유를 표시하며 초안 실패는 상위 화면에서 알린다.
 * 부수효과: 원문 뷰어가 /api/documents/{id}를 요청한다(Pdf 담당). 문서가 바뀌면 key로 뷰어를 새로 만든다.
 *   작업 버튼을 누르면 onOpen으로 선택 계약을 전달한다.
 */
export function ContractDetail({contract, busy, loading, onOpen, onOpenResult}: {
  contract: ImportedContract; busy: boolean; loading: boolean; onOpen: (contract: ImportedContract) => void;
  onOpenResult?: (resultId: string, mailId: string) => void;
}) {
  const doc = contract.document;
  const f = doc?.extraction?.fields;
  const start = fieldText(f, 'start');
  const end = fieldText(f, 'end');
  const rows: [string, string][] = [
    ['거래처', fieldText(f, 'partner')],
    ['사업자등록번호', fieldText(f, 'biz')],
    ['계약기간', start === '미확인' && end === '미확인' ? '미확인' : start + ' ~ ' + end],
    ['금액 기준', fieldText(f, 'basis', {monthly: '월', total: '총'})],
    ['금액', fieldText(f, 'amount')],
    ['부가세', fieldText(f, 'vat_mode', {included: '포함', excluded: '별도'})],
    ['분할 비율', fieldText(f, 'ratios')],
    ['지급 조건', fieldText(f, 'payment')],
    ['검수 조건', fieldText(f, 'condition')],
  ];
  return (
    <>
      <div className="panel-heading">
        <div>
          <h2>{contract.id} <span>{contract.kind}</span> <ContractStatus contract={contract}/> <CompareBadge contract={contract} onOpenResult={onOpenResult}/></h2>
          <p>{contract.title}</p>
        </div>
        <ContractActions contract={contract} busy={busy} loading={loading} onOpen={onOpen}/>
      </div>
      <div className="contracts-detail-body">
        {contract.approval?.site_draft && (
          <div role="alert" className="alert amber" data-testid="detail-site-draft">
            <AlertTriangle size={17}/>{SITE_DRAFT_WARNING}{contract.approval.error ? ' (' + contract.approval.error + ')' : ''}
          </div>
        )}
        {doc?.extraction?.error && (
          <div role="alert" className="alert amber"><AlertTriangle size={17}/>{doc.extraction.error}</div>
        )}
        <dl className="contracts-fields">
          {rows.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd className={value === '미확인' ? 'missing' : ''}>{value}</dd>
            </div>
          ))}
        </dl>
        {doc && doc.available
          ? <div className="contracts-pdf-view"><Pdf key={doc.id} doc={doc}/></div>
          : <div className="empty"><h3>원문 PDF가 없습니다</h3><p>그룹웨어에 계약서 파일이 없거나 저장된 파일을 찾지 못했습니다.</p></div>}
      </div>
    </>
  );
}
