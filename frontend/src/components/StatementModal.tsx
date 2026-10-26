/**
 * [파일 역할] 수입 계약서로 거래명세서 엑셀을 만들기 전에 값을 확인·수정하는 확인 창.
 * 처리 흐름: 서버 초안(StatementDraft)을 마크다운 문서로 바꿔 3단 편집 화면(DocEditor: 좌 마크다운·중 워드형·우 목차)에 띄움
 *   → 사람이 수신·작성 일자·청구 월 범위·품목 표를 문서에서 고침 → 마크다운을 다시 필드로 읽어(markdownToStatement)
 *   줄 수(청구월 × 품목)와 예상 총계를 실시간으로 보여 줌 → POST /api/contracts/{id}/statement로 생성
 *   → 결과(파일명·저장 경로·총계·경고·내려받기 링크) 화면으로 전환.
 * 편집 중 닫으려 하면(변경이 있을 때) 창 안 확인 줄(DiscardBar)로 먼저 묻는다.
 * 앱은 AI·OCR을 쓰지 않으므로 원문 대조는 이 창에서 사람이 한다. 입력 검사는 화면 편의용이며 서버가 다시 검증한다.
 * 창 틀(포털·dialog·Esc·포커스 트랩·스크롤 잠금·포커스 복귀)은 공용 Modal이 담당하고, 월금액 해석은 utils/amount(양의 정수)를 쓴다.
 */
import {useEffect, useMemo, useRef, useState, type RefObject} from 'react';
import {AlertTriangle, CheckCircle2, Copy, Download, FileSpreadsheet, LoaderCircle, X, XCircle} from 'lucide-react';
import {api} from '../api';
import type {StatementDraft, StatementRequest, StatementResult} from '../types';
import {parsePositiveAmount as parseAmount} from '../utils/amount';
import {errorMessage} from '../utils/error';
import {Modal} from './Modal';
import {DiscardBar} from './docedit/DiscardBar';
import DocEditor from './docedit/DocEditor';
import {markdownToStatement, statementToMarkdown} from './docedit/docMarkdown';

/** [상수 명세] MAX_ROWS — 거래명세서 템플릿의 품목 줄 수. 청구월 × 품목이 이보다 많으면 생성하지 않는다(서버와 같다). */
const MAX_ROWS = 12;

/** [상수 명세] MISSING_LABELS — 초안 missing 키를 사람이 읽는 이름으로 바꾸는 표(품목 키는 missingLabel이 따로 처리). */
const MISSING_LABELS: Record<string, string> = {
  customer: '수신(거래처)',
  customer_biz: '거래처 사업자등록번호',
  contract_date: '계약체결일',
  issue_date: '작성 일자',
  period_start: '계약 시작일',
  period_end: '계약 종료일',
  from_month: '청구 시작 월',
  to_month: '청구 끝 월',
  items: '품목',
};

/** [상수 명세] ITEM_FIELD_LABELS — 품목 한 줄의 필드 키와 표시 이름. */
const ITEM_FIELD_LABELS: Record<string, string> = {name: '품목명', spec: '규격', monthly_amount: '월금액'};

/**
 * [기능명세] missingLabel
 * 목적: 초안 missing 키를 확인 창에 보일 한글 이름으로 변환
 * 입력: key: 'contract_date', 'items[0].spec' 같은 서버 키
 * 출력: 예) '계약체결일', '품목 1의 규격'. 모르는 키는 그대로 돌려준다
 * 처리/실패: items[N].필드 형식이면 N+1번째 품목과 필드 이름으로 바꾼다
 * 부수효과: 없음
 */
function missingLabel(key: string): string {
  const m = /^items\[(\d+)\]\.(\w+)$/.exec(key);
  if (m) return '품목 ' + (Number(m[1]) + 1) + '의 ' + (ITEM_FIELD_LABELS[m[2]] ?? m[2]);
  return MISSING_LABELS[key] ?? key;
}

/**
 * [기능명세] monthIndex
 * 목적: 'YYYY-MM' 문자열을 월 단위 일련번호로 변환해 범위 계산에 쓴다
 * 입력: ym: month 입력값
 * 출력: 연×12+월 정수, 형식이 틀리면 null
 * 처리/실패: 월이 1~12가 아니면 null
 * 부수효과: 없음
 */
function monthIndex(ym: string): number | null {
  const m = /^(\d{4})-(\d{2})$/.exec(ym);
  if (!m) return null;
  const month = Number(m[2]);
  return month >= 1 && month <= 12 ? Number(m[1]) * 12 + month : null;
}

/** [기능명세] won — 금액을 천 단위 구분 문자열로 표시한다. 입력 숫자, 출력 '1,234,000' 형식, 부수효과 없음. */
const won = (n: number) => n.toLocaleString('ko-KR');

/**
 * [기능명세] StatementModal
 * 목적: 거래명세서 생성 확인 창(입력·미리보기·생성·결과 표시)
 * 입력: draft(서버 초안, eligible=true인 것), title(계약명, 부제 표시용),
 *   busy(앱의 다른 요청·작업 진행 중이면 생성 버튼 비활성), onClose(창 닫기),
 *   returnFocus(선택: 닫을 때 포커스를 돌려줄 버튼 ref)
 * 출력: 공용 Modal(role=dialog, document.body 포털 — 계약 상세 영역의 쌓임 맥락·접근성 트리와 분리).
 *   생성 전에는 입력 폼, 성공 뒤에는 결과 화면
 * 처리/실패:
 *   - 생성 버튼 비활성 조건: 수신·작성 일자·월 범위가 비었거나, 품목명·규격이 비었거나, 월금액이 양의 정수가 아니거나,
 *     시작 월이 끝 월보다 늦거나, 줄 수가 12를 넘거나, 요청 중이거나 busy일 때. 막힌 이유는 버튼 위에 목록으로 보인다.
 *   - 요청 실패(서버 400 detail 등)는 창 안 오류 알림(role=alert)으로 보이고 입력값은 그대로 둔다.
 *   - 요청 중에는 Esc·X·취소로 닫지 않는다(만든 파일 결과를 잃지 않게. Esc는 Modal의 closable=false로 막는다).
 * 부수효과: POST /api/contracts/{id}/statement(서버가 PDF 보관 폴더/거래명세서/에 xlsx 저장),
 *   클립보드 쓰기(경로 복사), 모달 내부 상태 변경, onClose 호출. 키보드·스크롤·포커스 복귀는 Modal이 관리
 */
export function StatementModal({draft, title, busy, onClose, returnFocus}: {
  draft: StatementDraft;
  title: string;
  busy: boolean;
  onClose: () => void;
  returnFocus?: RefObject<HTMLElement | null>;
}) {
  // 편집 문서(마크다운)가 단일 원천이다. 초안은 창이 열릴 때 한 번만 문서로 바꾼다.
  const [md, setMd] = useState(() => statementToMarkdown({
    customer: draft.customer || '',
    issueDate: draft.issue_date || '',
    fromMonth: draft.from_month || '',
    toMonth: draft.to_month || '',
    items: draft.items.length
      ? draft.items.map(it => ({
        name: it.name || '',
        spec: it.spec || '',
        amount: it.monthly_amount === null || it.monthly_amount === undefined ? '' : String(it.monthly_amount),
      }))
      : [{name: '', spec: '', amount: ''}],
  }));
  const initialMd = useRef(md);
  const [confirmClose, setConfirmClose] = useState(false);
  const parsed = useMemo(() => markdownToStatement(md), [md]);
  const {customer, issueDate, fromMonth, toMonth, items} = parsed.fields;
  const [requesting, setRequesting] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<StatementResult | null>(null);
  const [copied, setCopied] = useState('');
  const downloadLink = useRef<HTMLAnchorElement>(null);
  const pathInput = useRef<HTMLInputElement>(null);

  // ── 실시간 계산: 청구월 수·줄 수·예상 총계와 생성을 막는 이유 ──
  const fromIdx = monthIndex(fromMonth);
  const toIdx = monthIndex(toMonth);
  const months = fromIdx !== null && toIdx !== null && fromIdx <= toIdx ? toIdx - fromIdx + 1 : 0;
  const rowCount = months * items.length;
  const amounts = items.map(it => parseAmount(it.amount));
  const monthlySum = amounts.reduce<number>((s, a) => s + (a ?? 0), 0);
  const supply = months * monthlySum;
  const vat = Math.round(supply / 10);
  const tooMany = rowCount > MAX_ROWS;

  const problems: string[] = [...parsed.problems];
  if (!customer.trim()) problems.push('수신을 입력하세요.');
  if (!issueDate) problems.push('작성 일자를 입력하세요.');
  if (fromIdx === null || toIdx === null) problems.push('청구 시작 월과 끝 월을 입력하세요.');
  else if (fromIdx > toIdx) problems.push('청구 시작 월이 끝 월보다 늦습니다.');
  items.forEach((it, i) => {
    const lacks = [
      !it.name.trim() && '품목명',
      !it.spec.trim() && '규격',
      amounts[i] === null && '월금액(양의 정수)',
    ].filter(Boolean);
    if (lacks.length) problems.push('품목 ' + (i + 1) + ': ' + lacks.join(', ') + '을(를) 확인하세요.');
  });
  if (tooMany) problems.push('줄 수가 ' + MAX_ROWS + '줄을 넘습니다.');
  if (busy) problems.push('다른 작업이 끝난 뒤 생성할 수 있습니다.');
  const canSubmit = !problems.length && !requesting;

  /**
   * [효과 명세] 결과 화면 포커스
   * 처리: 생성에 성공해 결과 화면으로 바뀌면 내려받기 링크에 포커스를 둔다
   * 부수효과: DOM 포커스 이동
   */
  useEffect(() => {
    if (result) downloadLink.current?.focus();
  }, [result]);

  /**
   * [기능명세] close
   * 목적: X·취소·닫기 버튼과 Esc 처리(편집 단계에서 변경이 있으면 닫기 전에 확인한다)
   * 입력: 없음
   * 출력: void
   * 처리/실패: 요청 중이면 무시한다. 결과 화면이 아니고 문서가 처음과 다르면 DiscardBar만 띄우고 닫지 않는다
   * 부수효과: confirmClose 상태 변경 또는 onClose 호출
   */
  const close = () => {
    if (requesting) return;
    if (!result && md !== initialMd.current) setConfirmClose(true);
    else onClose();
  };

  /**
   * [기능명세] submit
   * 목적: 확인한 값으로 거래명세서 엑셀 생성 요청
   * 입력: 편집 문서에서 읽은 값(수신·작성 일자·월 범위·품목)
   * 출력: Promise<void>
   * 처리/실패: canSubmit이 아니면 아무것도 하지 않는다. 문자열은 앞뒤 공백을 지우고 월금액은 정수로 보낸다.
   *   성공하면 결과 화면으로 바꾸고, 실패하면 서버 detail을 오류로 보이며 입력값은 유지한다
   * 부수효과: POST /api/contracts/{id}/statement(서버 xlsx 저장), requesting·error·result 상태 변경
   */
  const submit = async () => {
    if (!canSubmit) return;
    const body: StatementRequest = {
      customer: customer.trim(),
      issue_date: issueDate,
      from_month: fromMonth,
      to_month: toMonth,
      items: items.map((it, i) => ({name: it.name.trim(), spec: it.spec.trim(), monthly_amount: amounts[i] as number})),
    };
    setRequesting(true);
    setError('');
    try {
      setResult(await api<StatementResult>('contracts/' + encodeURIComponent(draft.contract_id) + '/statement', body));
    } catch (e) {
      setError('거래명세서를 만들지 못했습니다. ' + errorMessage(e));
    } finally {
      setRequesting(false);
    }
  };

  /**
   * [기능명세] copyPath
   * 목적: 저장 경로를 클립보드에 복사
   * 입력: path(결과의 전체 경로)
   * 출력: Promise<void>
   * 처리/실패: Clipboard API가 실패하면 경로 입력칸을 선택해 사람이 Ctrl+C로 복사하도록 안내한다
   * 부수효과: 클립보드 쓰기, 입력칸 선택, copied 안내 문구 변경
   */
  const copyPath = async (path: string) => {
    try {
      await navigator.clipboard.writeText(path);
      setCopied('경로를 복사했습니다.');
    } catch {
      pathInput.current?.select();
      setCopied('경로를 선택했습니다. Ctrl+C로 복사하세요.');
    }
  };

  const issueHint = draft.contract_date
    ? '기본값: 계약체결일 ' + draft.contract_date
    : '계약체결일을 찾지 못했습니다. 직접 입력하세요.';
  const missing = draft.missing.map(missingLabel);

  return (
    <Modal labelledBy="statement-title" className={result ? 'statement-modal' : 'statement-modal doc-edit-modal'} closable={!requesting} returnFocus={returnFocus} onClose={close}>
        <header>
          <div>
            <h2 id="statement-title">거래명세서 생성</h2>
            <p>{draft.contract_id} · {title}</p>
          </div>
          <button className="icon-btn" aria-label="거래명세서 생성 닫기" disabled={requesting} onClick={close}><X size={20}/></button>
        </header>

        {result
          ? (
            <>
              <div className="statement-body">
                <div role="status" className="alert success"><CheckCircle2 size={17}/>거래명세서를 만들었습니다</div>
                <dl className="statement-info">
                  <div><dt>파일명</dt><dd>{result.file}</dd></div>
                  <div><dt>채운 줄 수</dt><dd>{result.rows}줄</dd></div>
                </dl>
                <div className="statement-path">
                  <label htmlFor="statement-path">저장 경로</label>
                  <div>
                    <input id="statement-path" ref={pathInput} readOnly value={result.path} onFocus={e => e.currentTarget.select()}/>
                    <button className="secondary" onClick={() => void copyPath(result.path)}><Copy size={15}/>복사</button>
                  </div>
                  {copied && <small aria-live="polite">{copied}</small>}
                </div>
                <dl className="statement-totals">
                  <div><dt>공급가액</dt><dd>{won(result.supply)}원</dd></div>
                  <div><dt>세액</dt><dd>{won(result.vat)}원</dd></div>
                  <div><dt>합계</dt><dd>{won(result.total)}원</dd></div>
                </dl>
                {result.warnings.length > 0 && (
                  <div className="alert amber statement-notes">
                    <AlertTriangle size={17}/>
                    <ul>{result.warnings.map(w => <li key={w}>{w}</li>)}</ul>
                  </div>
                )}
              </div>
              <div className="modal-actions">
                <button className="secondary" onClick={close}>닫기</button>
                <a ref={downloadLink} className="primary" href={'/api/statements/' + encodeURIComponent(result.file)}>
                  <Download size={16}/>내려받기
                </a>
              </div>
            </>
          )
          : (
            <>
              <div className="statement-body doc-edit-body">
                {error && <div role="alert" className="alert error"><XCircle size={17}/>{error}</div>}
                <DocEditor markdown={md} onChange={setMd} disabled={requesting} testIdPrefix="statement-editor" sideInfo={(
                  <>
                    {(draft.notes.length > 0 || missing.length > 0) && (
                      <div className="alert amber statement-notes">
                        <AlertTriangle size={17}/>
                        <ul>
                          {draft.notes.map(n => <li key={n}>{n}</li>)}
                          {missing.length > 0 && <li>원문에서 찾지 못한 값: {missing.join(', ')} — 원문을 보고 직접 입력하세요.</li>}
                        </ul>
                      </div>
                    )}
                    <dl className="statement-info">
                      <div><dt>계약기간</dt><dd>{(draft.period_start || '미확인') + ' ~ ' + (draft.period_end || '미확인')}</dd></div>
                      <div><dt>거래처 사업자등록번호</dt><dd>{draft.customer_biz || '미확인'}</dd></div>
                      <div><dt>저장 폴더</dt><dd>{draft.folder}</dd></div>
                    </dl>
                    <p className="statement-issue-hint">{issueHint}</p>
                    <div className="statement-preview" aria-live="polite">
                      <p>
                        청구월 <b>{months}</b>개월 × 품목 <b>{items.length}</b>개 = <b className={tooMany ? 'over' : ''}>{rowCount}</b>줄
                        <span> / 최대 {MAX_ROWS}줄</span>
                      </p>
                      {tooMany && (
                        <div role="alert" className="alert error"><XCircle size={17}/>템플릿은 {MAX_ROWS}줄입니다. 청구 범위를 나누세요.</div>
                      )}
                      <dl className="statement-totals">
                        <div><dt>예상 공급가액</dt><dd>{won(supply)}원</dd></div>
                        <div><dt>세액(10%)</dt><dd>{won(vat)}원</dd></div>
                        <div><dt>합계</dt><dd>{won(supply + vat)}원</dd></div>
                      </dl>
                    </div>
                  </>
                )}/>
                {problems.length > 0 && (
                  <ul className="statement-problems" aria-label="생성 전에 확인할 것">
                    {problems.map(p => <li key={p}>{p}</li>)}
                  </ul>
                )}
                {confirmClose && <DiscardBar onKeep={() => setConfirmClose(false)} onDiscard={onClose}/>}
              </div>
              <div className="modal-actions">
                <button className="secondary" disabled={requesting} onClick={close}>취소</button>
                <button className="primary" disabled={!canSubmit} onClick={() => void submit()}>
                  {requesting
                    ? <><LoaderCircle size={16} className="spin"/>만드는 중…</>
                    : <><FileSpreadsheet size={16}/>거래명세서 생성</>}
                </button>
              </div>
            </>
          )}
    </Modal>
  );
}
