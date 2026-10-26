/**
 * [파일 역할] 지출결의서 초안 확인·수정 → 자동 상신 → 작성본 검토 결과를 표시하는 확인 창.
 * 입력 단계는 초안을 마크다운 문서로 바꿔 3단 편집 화면(DocEditor: 좌 마크다운·중 워드형·우 목차)에서 고치고,
 * 문서를 다시 필드(제목·월·금액·첨부·특이사항)로 읽어 검증·상신한다(markdownToExpense). 검토 8항목은 이 필드를 기준으로 서버가 대조한다.
 * 편집 중 닫으려 하면(변경이 있을 때) 창 안 확인 줄(DiscardBar)로 먼저 묻는다.
 * 서버 작업의 완료는 App의 jobs 폴링으로 감지한다. 상신 요청을 임의로 다시 보내지 않는다.
 * 금액/사용월 검증은 화면 편의용이며 서버에서 다시 검증한다. 기안 작성·검토는 AI 없이 스크립트가 수행한다.
 * 창 틀(포털·dialog·Esc·포커스 트랩·스크롤 잠금·포커스 복귀)은 공용 Modal이 담당하고, 금액 해석은 utils/amount를 쓴다.
 */
import {useCallback, useEffect, useMemo, useRef, useState, type RefObject} from 'react';
import {AlertTriangle, CheckCircle2, ExternalLink, LoaderCircle, Send, X, XCircle} from 'lucide-react';
import {api, display} from '../api';
import {SITE_DRAFT_WARNING} from '../screens/contracts/ContractActions';
import type {ExpenseDraft, ExpenseRequest, ImportedContract, Job} from '../types';
import {parseNonNegativeAmount as amount} from '../utils/amount';
import {errorMessage} from '../utils/error';
import {Modal} from './Modal';
import {DiscardBar} from './docedit/DiscardBar';
import DocEditor from './docedit/DocEditor';
import {expenseToMarkdown, markdownToExpense} from './docedit/docMarkdown';

/**
 * [기능명세] ExpenseModal
 * 목적: 사람이 계약 초안을 확인한 뒤 자동 상신하고 금액 검토 결과를 확인하게 한다.
 * 입력: 서버 draft, App의 jobs, busy, onClose, returnFocus(선택: 닫을 때 포커스를 돌려줄 버튼 ref). 출력: 공용 Modal(포털 dialog) JSX.
 * 처리/예외: 제목·월·정수 금액·합계 검산을 통과해야 상신한다. 요청/진행 중에는 닫기·중복 상신을 막는다.
 *   작업 실패는 오류로, 검토 불일치는 상태 없음과 실제/기준값 표로 표시한다. 완료 결과 조회만 재시도할 수 있다.
 *   approval.site_draft(그룹웨어에 기안이 이미 만들어졌을 수 있음)가 true이면 입력 단계(이전 상신 기록)와 결과 단계 모두에
 *   SITE_DRAFT_WARNING을 role=alert로 표시한다. 상신은 막지 않는다(사용자가 그룹웨어 확인 후 판단). review·doc_url이 없는
 *   부분 approval(오류만 기록된 경우)도 깨지지 않게 표/링크를 생략한다.
 *   Esc·닫기는 진행 중(running)에는 막는다(Modal의 closable=false). 첫 입력 포커스·스크롤 잠금·포커스 복귀는 Modal이 처리한다.
 * 부수효과: POST expense, 완료 후 GET contracts, 입력/작업/결과 상태 변경. 키보드·포커스·스크롤은 Modal이 관리.
 */
export function ExpenseModal({draft, jobs, busy, onClose, returnFocus}: {
  draft: ExpenseDraft; jobs: Job[]; busy: boolean; onClose: () => void; returnFocus?: RefObject<HTMLElement | null>;
}) {
  // 편집 문서(마크다운)가 단일 원천이다. 초안은 창이 열릴 때 한 번만 문서로 바꾼다.
  const [md, setMd] = useState(() => expenseToMarkdown({
    title: draft.title || '', month: draft.month || '',
    supply: String(draft.supply ?? ''), vat: String(draft.vat ?? ''), total: String(draft.total ?? ''),
    attachments: draft.attachments || [], note: draft.note || '',
  }));
  const initialMd = useRef(md);
  const [confirmClose, setConfirmClose] = useState(false);
  const parsed = useMemo(() => markdownToExpense(md), [md]);
  const {title, month, supply: supplyText, vat: vatText, total: totalText, attachments, note} = parsed.fields;
  const [phase, setPhase] = useState<'input' | 'running' | 'result' | 'failed' | 'load-error'>('input');
  const [jobId, setJobId] = useState('');
  const [error, setError] = useState('');
  const [result, setResult] = useState<ImportedContract | null>(null);
  const dialog = useRef<HTMLElement>(null);
  const submitLock = useRef(false);
  const handledJob = useRef('');
  const mounted = useRef(true);
  const running = phase === 'running';
  /**
   * [기능명세] close
   * 목적: X·취소·닫기 버튼과 Esc 처리(입력 단계에서 변경이 있으면 닫기 전에 확인한다)
   * 입력: 없음. 출력: void
   * 처리/실패: 진행 중이면 무시한다. 입력 단계에서 문서가 처음과 다르면 DiscardBar만 띄우고 닫지 않는다
   * 부수효과: confirmClose 상태 변경 또는 onClose 호출
   */
  const close = () => {
    if (running) return;
    if (phase === 'input' && md !== initialMd.current) setConfirmClose(true);
    else onClose();
  };
  const job = jobs.find(item => item.id === jobId);
  const supply = amount(supplyText), vat = amount(vatText), total = amount(totalText);
  const validMonth = /^\d{4}-(0[1-9]|1[0-2])$/.test(month);
  const balanced = supply !== null && vat !== null && total !== null && supply + vat === total;
  const problems: string[] = [...parsed.problems];
  if (!title.trim()) problems.push('제목을 입력하세요.');
  if (!validMonth) problems.push('청구·사용 월을 입력하세요.');
  if (supply === null || supply <= 0) problems.push('공급가액은 양의 정수로 입력하세요.');
  if (vat === null) problems.push('부가세는 0 이상 정수로 입력하세요.');
  if (total === null || total <= 0) problems.push('합계는 양의 정수로 입력하세요.');
  if (!balanced) problems.push('공급가액 + 부가세가 합계와 같아야 합니다.');
  if (busy) problems.push('다른 작업이 끝난 뒤 상신할 수 있습니다.');
  const approval = result?.approval;
  const duplicate = draft.approval?.month === month && !!draft.approval.review?.length && draft.approval.review.every(item => item.ok);
  // 중복 경고는 입력한 월에 맞춰 아래에서 계산한다. 초안 고정 경고의 같은 내용은 중복 표시하지 않는다.
  const draftWarnings = (draft.warnings || []).filter(warning => !(warning.includes('품의완료') && (warning.includes('같은') || warning.includes('이미'))));

  /**
   * [기능명세] 마운트 표시 효과
   * 입력: 없음. 출력: 정리 함수. 처리: 마운트 중임을 표시한다(스크롤 잠금·포커스는 Modal이 담당).
   * 예외: 언마운트 뒤 비동기 응답이 상태를 바꾸지 않도록 정리 때 표시를 내린다. 부수효과: mounted ref 변경.
   */
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  /** [기능명세] 단계 전환 포커스: 입력 외 단계가 되면 dialog를 포커스한다. 입력 phase, 출력 없음, 부수효과 DOM 포커스. */
  useEffect(() => {
    if (phase !== 'input') dialog.current?.focus();
  }, [phase]);

  /**
   * [기능명세] loadResult
   * 목적: 완료한 작업의 계약 상태와 작성본 검토를 조회한다.
   * 입력: 없음. 출력: Promise<void>. 처리/예외: 계약·상신 정보가 없으면 다시 조회할 수 있는 오류를 표시한다.
   * 부수효과: GET contracts, 결과/단계/오류 상태 변경. 상신 POST는 다시 보내지 않는다.
   */
  const loadResult = useCallback(async () => {
    setError('');
    try {
      const contracts = await api<ImportedContract[]>('contracts');
      const contract = contracts.find(item => item.id === draft.contract_id);
      if (!contract?.approval) throw new Error('상신 결과 정보를 찾지 못했습니다.');
      if (!mounted.current) return;
      setResult(contract);
      setPhase('result');
    } catch (e) {
      if (!mounted.current) return;
      setError('상신 작업은 끝났지만 결과를 조회하지 못했습니다. ' + errorMessage(e));
      setPhase('load-error');
    }
  }, [draft.contract_id]);

  /**
   * [기능명세] 작업 완료 효과
   * 입력: 접수 작업의 App 폴링 상태. 출력: 없음.
   * 처리/예외: 같은 완료 작업은 한 번만 처리한다. 실패면 오류, 완료면 계약의 마지막 검토 결과를 조회한다.
   * 부수효과: 결과 조회, 오류·단계 상태 변경. 별도 폴링 타이머 없음.
   */
  useEffect(() => {
    if (!job || job.status === 'running' || handledJob.current === job.id) return;
    handledJob.current = job.id;
    if (job.status === 'failed') {
      setError(job.message + (job.errors?.length ? ' ' + job.errors.join(' / ') : ''));
      setPhase('failed');
    } else {
      void loadResult();
    }
  }, [job, loadResult]);

  /**
   * [기능명세] submit
   * 목적: 사람이 확인한 값으로 지출결의서 상신 작업을 한 번 접수한다.
   * 입력: 폼 상태. 출력: Promise<void>. 처리/예외: 검증 실패·중복 클릭 차단, 접수 오류는 입력 화면에 보존한다.
   * 부수효과: POST expense, 접수 ID·단계·오류·중복 방지 잠금 변경. 실제 작성/검토는 서버 작업이 수행한다.
   */
  const submit = async () => {
    if (submitLock.current || phase !== 'input' || problems.length) return;
    submitLock.current = true;
    setPhase('running');
    setError('');
    try {
      const body: ExpenseRequest = {
        title: title.trim(), month, supply: supply!, vat: vat!, total: total!,
        attachments: attachments.map(text => text.trim()).filter(Boolean), note,
      };
      const response = await api<{id: string}>('contracts/' + encodeURIComponent(draft.contract_id) + '/expense', body);
      if (mounted.current) setJobId(response.id);
    } catch (e) {
      if (!mounted.current) return;
      setError(errorMessage(e));
      setPhase('input');
      submitLock.current = false;
    }
  };

  return (
    <Modal dialogRef={dialog} labelledBy="expense-title" className={'statement-modal expense-modal' + (phase === 'input' ? ' doc-edit-modal' : '')}
      testId="expense-modal" closable={!running} returnFocus={returnFocus} onClose={close}>
        <header><div><h2 id="expense-title"><Send size={19}/>지출결의서 상신</h2><p>{draft.contract_id} · {draft.partner}</p></div>
          <button className="icon-btn" aria-label="지출결의서 창 닫기" disabled={running} onClick={close}><X size={19}/></button></header>
        <div className={'statement-body' + (phase === 'input' ? ' doc-edit-body' : '')}>
          {error && <div role="alert" className="alert error"><XCircle size={17}/>{error}</div>}
          {phase === 'input' && <>
            {draft.approval?.site_draft && <div role="alert" className="alert amber" data-testid="expense-site-draft"><AlertTriangle size={17}/>
              {SITE_DRAFT_WARNING}{draft.approval.error ? ' (' + draft.approval.error + ')' : ''}</div>}
            <DocEditor markdown={md} onChange={setMd} testIdPrefix="expense-editor" sideInfo={<>
              {(draftWarnings.length > 0 || duplicate) && <div className="alert amber statement-notes"><AlertTriangle size={17}/><ul>
                {draftWarnings.map((warning, index) => <li key={index}>{warning}</li>)}
                {duplicate && <li>같은 청구월에 품의완료된 상신이 있습니다. 다시 상신하면 새 기안이 만들어집니다.</li>}
              </ul></div>}
              <dl className="statement-info"><div><dt>양식</dt><dd>지출결의서</dd></div>
                <div><dt>계약기간</dt><dd>{draft.period_start || '미확인'} ~ {draft.period_end || '미확인'}</dd></div></dl>
              <p className="statement-issue-hint">첨부는 사이트의 첨부 후보 중 이름이 일치하는 파일만 선택하며, 없는 파일은 경고로 남깁니다.</p>
              <div className="statement-preview" aria-live="polite"><p>{balanced ? '합계 검산 일치' : '합계 검산 확인 필요'} · 공급가액 + 부가세 = 합계</p>
                <dl className="statement-totals"><div><dt>공급가액</dt><dd>{supply === null ? '미확인' : display(supply)}원</dd></div>
                  <div><dt>부가세</dt><dd>{vat === null ? '미확인' : display(vat)}원</dd></div>
                  <div><dt>합계</dt><dd>{total === null ? '미확인' : display(total)}원</dd></div></dl></div>
            </>}/>
            {problems.length > 0 && <ul className="statement-problems" aria-label="상신 전에 확인할 것">{problems.map(problem => <li key={problem}>{problem}</li>)}</ul>}
            {confirmClose && <DiscardBar onKeep={() => setConfirmClose(false)} onDiscard={onClose}/>}
          </>}
          {running && <div className="expense-progress" role="status"><LoaderCircle size={28} className="spin"/><h3>지출결의서를 상신하고 검토하고 있습니다</h3>
            <p>{job?.message || '상신 작업을 접수하고 있습니다.'}</p><p>작업이 끝날 때까지 창을 닫지 마세요.</p>
            {job && <progress value={job.done} max={job.total || 1}/>}</div>}
          {phase === 'result' && approval && <div data-testid="expense-result" className="expense-result">
            <div className={'alert ' + (result.status === '품의완료' ? 'success' : 'amber')}>
              {result.status === '품의완료' ? <CheckCircle2 size={20}/> : <AlertTriangle size={20}/>}
              <strong>{result.status === '품의완료' ? '품의완료' : '없음 — 작성본 검토 확인 필요'}</strong></div>
            {approval.site_draft && <div role="alert" className="alert amber" data-testid="expense-site-draft"><AlertTriangle size={17}/>
              {SITE_DRAFT_WARNING}</div>}
            <dl className="statement-info"><div><dt>문서번호</dt><dd>{approval.doc_no}</dd></div><div><dt>청구월</dt><dd>{approval.month}</dd></div>
              <div><dt>작성본 금액</dt><dd>{approval.document_total == null ? '미확인' : display(approval.document_total) + '원'}</dd></div></dl>
            <div className="expense-review" role="region" aria-label="지출결의서 작성본 검토"><table>
              <thead><tr><th>검토 항목</th><th>작성본</th><th>기준값</th><th>결과</th></tr></thead>
              <tbody>{(approval.review ?? []).map((review, index) => <tr key={index}><th>{review.label}</th><td>{display(review.actual)}</td>
                <td>{display(review.expected)}</td><td className={review.ok ? 'review-ok' : 'review-fail'}>{review.ok ? '일치' : '불일치'}</td></tr>)}</tbody>
            </table></div>
            {approval.warnings?.length > 0 && <div className="alert amber statement-notes"><AlertTriangle size={17}/><ul>
              {approval.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></div>}
            {approval.doc_url && <a className="secondary expense-document" href={approval.doc_url} target="_blank" rel="noreferrer"><ExternalLink size={16}/>그룹웨어 작성본 열기</a>}
            <small>기안은 앱의 전용 브라우저에 저장됩니다. 다른 브라우저에서는 작성본이 보이지 않을 수 있습니다.</small>
          </div>}
          {phase === 'failed' && <p>상신·검토를 완료하지 못했습니다. 안내와 그룹웨어 작성본을 확인한 뒤 다시 시도하세요.</p>}
          {phase === 'load-error' && <button className="secondary" onClick={() => void loadResult()}>결과 다시 조회</button>}
        </div>
        <div className="modal-actions"><button className="secondary" disabled={running} onClick={close}>{phase === 'input' ? '취소' : '닫기'}</button>
          {phase === 'input' && <button className="primary" data-testid="expense-submit" disabled={problems.length > 0} onClick={() => void submit()}><Send size={16}/>상신</button>}</div>
    </Modal>
  );
}
