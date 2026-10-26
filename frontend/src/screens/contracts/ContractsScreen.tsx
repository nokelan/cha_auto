/**
 * [파일 역할] '계약서 목록' 화면.
 * 그룹웨어 계약 문서함에서 계약서를 가져오는 조건(구분·개수·새 계약만)을 정해 작업을 접수하고,
 * 가져온 계약 목록(GET /api/contracts)을 검색·구분 탭으로 거른 뒤 선택한 계약의 추출값과 PDF 원문을 보여 준다.
 * 처리 흐름: 마운트 시 목록 조회 → 가져오기 접수(App.act) → App의 state 폴링으로 '계약서 가져오기' 작업이
 *   새로 끝난 것이 보이면 목록 재조회. 이 화면은 자체 폴링 타이머를 만들지 않는다.
 * 계약 작업: 목록/상세 공통 버튼 → 구분별 초안 GET → 거래명세서 또는 지출결의서 확인 창.
 * 원문 PDF가 있고 다른 작업이 없을 때만 버튼을 켠다. 상신 완료는 App의 작업 폴링으로 목록에 반영한다.
 */
import {useCallback, useEffect, useRef, useState} from 'react';
import {Download, FileText, XCircle} from 'lucide-react';
import {api} from '../../api';
import type {Doc, ExpenseDraft, ImportedContract, Job, StatementDraft} from '../../types';
import {StatementModal} from '../../components/StatementModal';
import {ExpenseModal} from '../../components/ExpenseModal';
import {ContractList} from './ContractList';
import {ContractDetail} from './ContractDetail';
import {KINDS, type CompareFilter, type Kind} from './contracts';
import {contractBlock} from './ContractActions';
import {useJobDone} from '../../hooks/useJobDone';
import {errorMessage} from '../../utils/error';
import './contracts.css';

/** [상수 명세] IMPORT_JOB — 서버가 state.jobs[].kind에 쓰는 계약서 가져오기 작업 이름. */
const IMPORT_JOB = '계약서 가져오기';

/** [상수 명세] EXPENSE_JOB — 서버가 state.jobs[].kind에 쓰는 지출결의서 상신 작업 이름. 끝나면 목록의 품의 상태를 다시 읽는다. */
const EXPENSE_JOB = '지출결의서 상신';

/** [상수 명세] LIMIT_MIN/LIMIT_MAX — 가져올 개수 입력 허용 범위(서버 검증과 같다). */
const LIMIT_MIN = 1;
const LIMIT_MAX = 500;

/**
 * [기능명세] parseLimit
 * 목적: 개수 입력 문자열을 import API의 limit 값으로 변환
 * 입력: text: 개수 입력 상자의 문자열
 * 출력: {ok, limit} — 빈 값이면 {ok:true, limit:null}(전체), 1~500 정수면 {ok:true, limit:정수}
 * 처리/실패: 공백 제거 후 정수가 아니거나 범위 밖이면 {ok:false, limit:null}
 * 부수효과: 없음
 */
function parseLimit(text: string): {ok: boolean; limit: number | null} {
  const t = text.trim();
  if (t === '') return {ok: true, limit: null};
  const n = Number(t);
  if (!Number.isInteger(n) || n < LIMIT_MIN || n > LIMIT_MAX) return {ok: false, limit: null};
  return {ok: true, limit: n};
}

/**
 * [기능명세] summarize
 * 목적: 가져오기 조건을 사람이 읽는 한 문장으로 요약
 * 입력: kind(전체/수입/지출), limit(정수 또는 null=전체), onlyNew(아직 가져오지 않은 계약만)
 * 출력: 요약 문자열. 예: '지출 계약 중 아직 가져오지 않은 최근 10개를 가져옵니다.', '전체 계약을 모두 가져옵니다.'
 * 처리/실패: 조건 조합별 문구를 만든다. 입력 검증은 하지 않는다(호출자가 parseLimit로 처리)
 * 부수효과: 없음
 */
function summarize(kind: Kind, limit: number | null, onlyNew: boolean): string {
  const target = kind + ' 계약';
  if (limit === null) {
    return onlyNew ? target + ' 중 아직 가져오지 않은 계약을 모두 가져옵니다.' : target + '을 모두 가져옵니다.';
  }
  return target + ' 중 ' + (onlyNew ? '아직 가져오지 않은 ' : '') + '최근 ' + limit + '개를 가져옵니다.';
}

/**
 * [기능명세] ContractsScreen
 * 목적: 계약서 가져오기 조건 입력·작업 접수와 가져온 계약 목록·상세(추출값·PDF 원문) 표시
 * 입력: jobs(App state 폴링의 작업 목록), busy(다른 요청·작업 진행 중이면 true),
 *   onImport(App.act('contracts/import', body)를 감싼 접수 함수), onRelatedDocument(선택 원문을 관련 링크에 전달, 선택),
 *   onOpenResult(문서비교 판정 배지를 눌렀을 때 해당 결과·메일을 '비교 결과' 화면으로 여는 콜백, 선택)
 *   목록의 문서비교 상태(compare)는 서버가 계산해 주며 이 화면은 필터와 배지 표시만 한다.
 * 출력: 조건 패널 + 목록/상세 2단(1024px 이하 1단) JSX
 * 처리/실패: 개수가 1~500 정수 또는 빈 값이 아니면 가져오기 버튼을 비활성화한다.
 *   목록 조회 실패는 화면 안 경고(role=alert)로 보이고, 접수 실패 표시는 App이 담당한다
 * 부수효과: GET /api/contracts 요청, onImport 호출(POST /api/contracts/import), 화면 상태(조건·검색·탭·선택) 변경.
 *   상세는 선택 ID를 key로 새로 만든다. 초안/모달은 이 화면에서 목록·상세 공통으로 관리한다.
 */
export function ContractsScreen({jobs, busy, onImport, onRelatedDocument, onOpenResult}: {
  jobs: Job[];
  busy: boolean;
  onImport: (body: {kind: Kind; limit: number | null; only_new: boolean}) => void;
  onRelatedDocument?: (document: Doc | null) => void;
  onOpenResult?: (resultId: string, mailId: string) => void;
}) {
  const [kind, setKind] = useState<Kind>('전체');
  const [limitText, setLimitText] = useState('');
  const [onlyNew, setOnlyNew] = useState(false);
  const [items, setItems] = useState<ImportedContract[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [q, setQ] = useState('');
  const [tab, setTab] = useState<Kind>('전체');
  const [compareFilter, setCompareFilter] = useState<CompareFilter>('전체');
  const [selectedId, setSelectedId] = useState('');
  const [loadingId, setLoadingId] = useState('');
  const [draftError, setDraftError] = useState('');
  const [statement, setStatement] = useState<{draft: StatementDraft; title: string} | null>(null);
  const [expense, setExpense] = useState<ExpenseDraft | null>(null);
  const opening = useRef(false);
  /** 확인 창을 연 버튼. 초안을 불러오는 동안 버튼이 비활성화돼 포커스를 잃으므로, 창이 닫힐 때 여기로 포커스를 돌려준다. */
  const opener = useRef<HTMLElement | null>(null);

  const parsed = parseLimit(limitText);
  const needle = q.trim().toLowerCase();
  const filtered = items.filter(c =>
    (tab === '전체' || c.kind === tab)
    && (compareFilter === '전체' || (compareFilter === '미비교' ? !c.compare : c.compare?.status === compareFilter))
    && (!needle || [c.id, c.partner, c.title].some(s => (s || '').toLowerCase().includes(needle))));
  const selected = items.find(c => c.id === selectedId) || null;

  /** [효과 명세] 선택 원문 전달: 선택 계약의 저장 문서 또는 null을 부모 관련 링크에 전달한다.
   * 입력은 선택 문서와 콜백, 출력 없음. 네트워크 요청 없이 부모 화면 상태만 갱신한다. */
  useEffect(() => {
    onRelatedDocument?.(selected?.document ?? null);
  }, [selected?.document, onRelatedDocument]);

  /**
   * [기능명세] load
   * 목적: 가져온 계약 목록 조회
   * 입력: 없음
   * 출력: Promise<void>
   * 처리/실패: GET /api/contracts 성공 시 목록을 바꾸고 경고를 지운다. 실패하면 경고 문구를 남기고 기존 목록은 유지한다
   * 부수효과: 네트워크 요청, items·loaded·loadError 상태 변경
   */
  const load = async () => {
    try {
      setItems(await api<ImportedContract[]>('contracts'));
      setLoadError('');
    } catch (e) {
      setLoadError('계약서 목록을 불러오지 못했습니다. ' + errorMessage(e));
    } finally {
      setLoaded(true);
    }
  };

  /**
   * [효과 명세] 마운트 시 목록 조회
   * 처리: 화면이 열릴 때 한 번 load()를 호출한다
   * 부수효과: GET /api/contracts
   */
  useEffect(() => {
    void load();
  }, []);

  /**
   * [효과 명세] 가져오기·상신 작업 완료 감지 (useJobDone)
   * 입력: jobs(App state 폴링 결과)
   * 처리: 처음 실행 때는 이미 끝나 있던 '계약서 가져오기'·'지출결의서 상신' 작업 ID를 기억만 한다(마운트 조회가 반영함).
   *   이후 running이 아닌 상태로 새로 보이는 작업이 있으면 목록을 한 번 다시 조회한다(상신 완료의 상태 배지 반영 포함)
   * 부수효과: 필요 시 GET /api/contracts
   */
  useJobDone(jobs, [IMPORT_JOB, EXPENSE_JOB], () => void load());

  /**
   * [기능명세] openContract
   * 목적: 목록/상세 공통 계약 작업의 초안을 가져와 확인 창을 연다.
   * 입력: 계약. 출력: Promise<void>.
   * 처리/예외: 작업 중·원문 없음·중복 클릭은 무시한다. 부적격/요청 오류는 화면 경고로 표시한다.
   * 부수효과: 초안 GET, 선택 계약·요청 상태·오류·모달 상태 변경, 누른 버튼 기억(창을 닫을 때 포커스 복귀용). 상신은 확인 창에서만 실행한다.
   */
  const openContract = async (contract: ImportedContract) => {
    if (opening.current || statement || expense || contractBlock(contract, busy)) return;
    opening.current = true;
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setLoadingId(contract.id);
    setSelectedId(contract.id);
    setDraftError('');
    try {
      const path = 'contracts/' + encodeURIComponent(contract.id);
      if (contract.kind === '수입') {
        const draft = await api<StatementDraft>(path + '/statement');
        if (!draft.eligible) throw new Error(draft.reason || '이 계약으로는 거래명세서를 만들 수 없습니다.');
        setStatement({draft, title: contract.title});
      } else {
        const draft = await api<ExpenseDraft>(path + '/expense');
        if (!draft.eligible) throw new Error(draft.reason || '이 계약으로는 상신할 수 없습니다.');
        setExpense(draft);
      }
    } catch (error) {
      setDraftError('초안을 불러오지 못했습니다. ' + errorMessage(error));
    } finally {
      opening.current = false;
      setLoadingId('');
    }
  };

  /** [기능명세] closeStatement: 입력/출력 없음. 초안 상태를 비워 거래명세서 확인 창을 닫는다. 실패 없음, 부수효과 화면 상태 변경. */
  const closeStatement = useCallback(() => setStatement(null), []);
  /** [기능명세] closeExpense: 입력/출력 없음. 지출결의서 확인 창을 닫는다. 실행 중 차단은 모달이 담당하며 부수효과 화면 상태 변경. */
  const closeExpense = useCallback(() => setExpense(null), []);

  return (
    <div className="contracts-screen">
      <section className="panel contracts-import">
        <div className="panel-heading">
          <div>
            <h2><Download size={16}/>가져오기 조건</h2>
            <p>그룹웨어 계약 문서함에서 조건에 맞는 계약서를 내려받아 저장합니다.</p>
          </div>
        </div>
        <div className="contracts-import-body">
          <label>
            <span className="field-label">구분</span>
            <select aria-label="가져올 계약 구분" value={kind} onChange={e => setKind(e.target.value as Kind)}>
              {KINDS.map(k => <option key={k} value={k}>{k}</option>)}
            </select>
          </label>
          <label>
            <span className="field-label">개수 (비우면 전체)</span>
            <input
              type="number"
              aria-label="가져올 개수"
              placeholder="전체"
              min={LIMIT_MIN}
              max={LIMIT_MAX}
              step={1}
              value={limitText}
              aria-invalid={!parsed.ok}
              onChange={e => setLimitText(e.target.value)}
            />
          </label>
          <label className="contracts-check">
            <input type="checkbox" checked={onlyNew} onChange={e => setOnlyNew(e.target.checked)}/> 아직 가져오지 않은 계약만
          </label>
          <div className="contracts-import-action">
            <button
              className="primary"
              disabled={busy || !parsed.ok}
              onClick={() => onImport({kind, limit: parsed.limit, only_new: onlyNew})}
            >
              <Download size={16}/>계약서 가져오기
            </button>
            <p className="contracts-summary" aria-live="polite">
              {parsed.ok
                ? summarize(kind, parsed.limit, onlyNew)
                : '개수는 ' + LIMIT_MIN + '~' + LIMIT_MAX + ' 사이의 정수로 입력하거나 비워 두세요.'}
              <small>최근 순서는 관리번호가 큰 계약부터입니다.</small>
            </p>
          </div>
        </div>
      </section>

      {loadError && (
        <div role="alert" className="alert error contracts-alert"><XCircle size={17}/>{loadError}</div>
      )}
      {draftError && <div role="alert" className="alert error contracts-alert"><XCircle size={17}/>{draftError}</div>}

      <div className="contracts-layout">
        <ContractList items={items} filtered={filtered} loaded={loaded} q={q} tab={tab} compareFilter={compareFilter} selectedId={selectedId}
          onQ={setQ} onTab={setTab} onCompareFilter={setCompareFilter} onSelect={setSelectedId} busy={busy || !!loadingId}
          loadingId={loadingId} onOpen={contract => void openContract(contract)} onOpenResult={onOpenResult}/>

        <section className="panel contracts-detail" aria-label="계약 상세">
          {!selected
            ? (
              <div className="empty">
                <span className="empty-icon"><FileText size={30}/></span>
                <h3>계약을 선택하세요</h3>
                <p>목록에서 계약을 누르면 추출값과 원문을 볼 수 있습니다.</p>
              </div>
            )
            : <ContractDetail key={selected.id} contract={selected} busy={busy || !!loadingId}
                loading={loadingId === selected.id} onOpen={contract => void openContract(contract)} onOpenResult={onOpenResult}/>}
        </section>
      </div>
      {statement && <StatementModal draft={statement.draft} title={statement.title} busy={busy} returnFocus={opener} onClose={closeStatement}/>}
      {expense && <ExpenseModal draft={expense} jobs={jobs} busy={busy} returnFocus={opener} onClose={closeExpense}/>}
    </div>
  );
}

