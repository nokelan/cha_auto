/** [파일 역할] 계약 구분에 따른 작업 버튼·비활성 사유와 품의 상태를 공통 표시한다. */
import {useId, type MouseEvent} from 'react';
import {FileSpreadsheet, LoaderCircle, Send} from 'lucide-react';
import type {ImportedContract} from '../../types';
import {Badge} from '../../components/Badge';

/**
 * [기능명세] contractBlock
 * 목적: 계약 작업을 사용할 수 없는 이유 결정.
 * 입력: 계약, 다른 작업 진행 여부. 출력: 사유 문자열 또는 빈 문자열.
 * 처리/예외: 원문 PDF 없음, 작업 진행 중 순으로 검사한다. 부수효과: 없음.
 */
export function contractBlock(contract: ImportedContract, busy: boolean): string {
  if (!contract.document?.available) return '원문 PDF가 없습니다';
  if (busy) return '다른 작업이 끝난 뒤 사용할 수 있습니다';
  return '';
}

/** [상수 명세] SITE_DRAFT_WARNING — 상신 이후 오류·검토 불일치로 그룹웨어에 기안이 남았을 수 있을 때의 안내 문구. */
export const SITE_DRAFT_WARNING = '그룹웨어에 기안이 이미 만들어졌을 수 있습니다. 그룹웨어에서 확인한 뒤 다시 상신하세요.';

/**
 * [기능명세] ContractStatus
 * 목적: 목록과 상세에 계약의 마지막 품의 상태 표시.
 * 입력: 계약. 출력: 품의완료/없음 배지, approval.site_draft가 true이면 '기안 확인 필요' 경고 배지를 추가한다.
 * 처리/예외: 누락 상태는 없음으로 표시한다. '없음'/'품의완료' 의미는 site_draft와 무관하게 유지한다.
 *   경고 배지의 전체 문구는 title(툴팁)로 제공하고, 상세 화면은 SITE_DRAFT_WARNING을 role=alert로 따로 표시한다. 부수효과: 없음.
 */
export function ContractStatus({contract}: {contract: ImportedContract}) {
  const status = contract.status === '품의완료' ? '품의완료' : '없음';
  return (
    <>
      <span data-testid="contract-status" className={'badge ' + (status === '품의완료' ? 'green' : 'gray')}>{status}</span>
      {contract.approval?.site_draft && (
        <span data-testid="contract-site-draft" className="badge red" title={SITE_DRAFT_WARNING}>
          기안 확인 필요
        </span>
      )}
    </>
  );
}

/**
 * [기능명세] CompareBadge
 * 목적: 계약서 목록·상세에 문서비교 화면의 대표 판정 표시.
 * 입력: 계약, onOpenResult(결과·메일 ID로 비교 결과 화면 열기, 선택).
 * 출력: 비교된 계약은 판정 배지(일치/불일치/확인 필요/처리 실패), 아직이면 회색 '미비교' 배지.
 *   여러 메일과 비교됐으면 판정별 건수를 title(툴팁)에 적는다. onOpenResult가 있으면 배지를 눌러 해당 결과로 이동한다.
 * 처리/예외: compare가 없으면 미비교. 클릭은 행 선택으로 전파하지 않는다. 부수효과: 클릭 시 상위 콜백 호출.
 */
export function CompareBadge({contract, onOpenResult}: {contract: ImportedContract; onOpenResult?: (resultId: string, mailId: string) => void}) {
  const compare = contract.compare;
  if (!compare) return <span data-testid="contract-compare" data-compare="미비교" className="badge gray" title="문서비교 화면에서 아직 비교하지 않았습니다">미비교</span>;
  const counts = Object.entries(compare.counts).map(([k, n]) => k + ' ' + n).join(' · ');
  const title = '문서비교 ' + compare.count + '건 (' + counts + ') · 눌러서 비교 결과 보기';
  if (!onOpenResult) return <span data-testid="contract-compare" data-compare={compare.status} title={title}><Badge status={compare.status}/></span>;
  return (
    <button type="button" data-testid="contract-compare" data-compare={compare.status} className="compare-badge" title={title}
      onClick={event => { event.stopPropagation(); onOpenResult(compare.result_id, compare.mail_id); }}>
      <Badge status={compare.status}/>
    </button>
  );
}

/**
 * [기능명세] ContractActions
 * 목적: 수입은 거래명세서 생성, 지출은 지출결의서 상신 버튼 표시.
 * 입력: 계약, busy, loading, compact(목록용), onOpen(초안 열기).
 * 출력: 작업 버튼·사유 JSX. 처리/예외: 원문 없음 또는 작업 중이면 버튼을 끈다.
 * 부수효과: 클릭은 행 선택으로 전파하지 않고 상위 초안 열기 콜백을 호출한다.
 */
export function ContractActions({contract, busy, loading, compact = false, onOpen}: {
  contract: ImportedContract; busy: boolean; loading: boolean; compact?: boolean; onOpen: (contract: ImportedContract) => void;
}) {
  const hintId = useId();
  const block = contractBlock(contract, busy);
  const expense = contract.kind === '지출';
  /** [기능명세] open: 마우스 이벤트를 받아 행 선택 전파를 막고 현재 계약의 초안을 연다. 반환 없음, 부수효과 상위 콜백. */
  const open = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    onOpen(contract);
  };
  return (
    <div className={'statement-action' + (compact ? ' contract-row-action' : '')}>
      <button className="secondary" disabled={!!block || loading} data-testid={expense ? 'expense-open' : 'statement-open'}
        title={block || (expense ? '계약서 값으로 지출결의서를 상신합니다' : '계약서 값으로 거래명세서 엑셀을 만듭니다')}
        aria-describedby={block ? hintId : undefined} onClick={open}>
        {loading ? <LoaderCircle size={16} className="spin"/> : expense ? <Send size={16}/> : <FileSpreadsheet size={16}/>}
        {expense ? '지출결의서 상신' : '거래명세서 생성'}
      </button>
      {block && <small id={hintId} className="statement-hint">{block}</small>}
    </div>
  );
}
