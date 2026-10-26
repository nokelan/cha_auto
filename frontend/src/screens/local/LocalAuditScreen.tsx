/**
 * [파일 역할] '로컬 세금계산서 대조' 화면.
 * 내 PC 폴더의 세금계산서(PDF·PNG) 목록을 보여 주고, 웹(그룹웨어) 계약서와 대조한 결과를 표·상세로 보여 준다.
 * 처리 흐름: 마운트 시 GET /api/local-audit → [폴더 선택] POST pick-folder → PUT folder(저장·목록 갱신)
 *   → [웹 계약서와 대조] App.act('local-audit/run') 작업 접수 → App의 state 폴링으로 '로컬 세금계산서 대조'
 *   작업이 새로 끝난 것이 보이면 다시 GET. 이 화면은 자체 폴링 타이머를 만들지 않는다(ContractsScreen 패턴).
 * 표시 규칙: 마지막 대조 결과(last)가 현재 폴더의 것이면 그 행을, 아니면 폴더 파일을 '대조 전'으로 보여 준다.
 *   대조 뒤에 폴더에 새로 생긴 파일도 '대조 전' 행으로 덧붙인다.
 * 상세: 판정 설명·후보 계약·세금계산서 판독값·항목별 판정(CheckList)·계약서 원문(Pdf).
 *   로컬 세금계산서 파일 자체는 문서 저장소에 없으므로 원문 뷰어로 보여 주지 않는다.
 * 검증용 data-testid: local-folder, local-pick, local-run, local-row, local-detail.
 * 분할: 표는 LocalTable, 상세는 LocalDetail, 순수 변환 함수·상수는 localRows.ts, 이 파일은 상태·조회·폴더 선택·요약을 맡는 컨테이너다.
 */
import {useEffect, useState} from 'react';
import {AlertTriangle, FileText, FolderOpen, FolderSearch, GitCompareArrows, LoaderCircle, XCircle} from 'lucide-react';
import {api, display, LOCAL_STATUS_ORDER, stamp} from '../../api';
import {Badge} from '../../components/Badge';
import {useJobDone} from '../../hooks/useJobDone';
import type {Doc, Job, LocalAuditState} from '../../types';
import {errorMessage} from '../../utils/error';
import {LocalDetail} from './LocalDetail';
import {LocalTable} from './LocalTable';
import {buildRows, runBlock, type Tab} from './localRows';


/** [상수 명세] LOCAL_JOB — 서버가 state.jobs[].kind에 쓰는 로컬 대조 작업 이름. */
const LOCAL_JOB = '로컬 세금계산서 대조';

/**
 * [기능명세] LocalAuditScreen
 * 목적: 로컬 세금계산서 폴더 선택·대조 작업 접수와 대조 결과 표·상세 표시
 * 입력: jobs(App state 폴링의 작업 목록), busy(App의 다른 요청·작업 진행 중이면 true),
 *   onRun(App.act('local-audit/run')를 감싼 접수 함수. 접수 실패 표시는 App이 담당),
 *   onRelatedDocument(선택 계약 원문을 부모 관련 링크에 전달, 선택)
 * 출력: 폴더 패널 + 요약 + 표/상세 2단(1900px 미만은 표 위·상세 아래 1단) JSX
 * 처리/실패: 조회·폴더 선택·저장 실패는 화면 안 오류 알림(role=alert)에 api()가 던진 메시지로 보인다(기존 목록 유지).
 *   folder_error가 있으면 경고(amber)로 보인다. 검색어는 파일명·상호·관리번호에 대소문자 무시로 적용하고,
 *   탭은 판정이 같은 행만 남긴다('전체'는 모두)
 * 부수효과: GET /api/local-audit, POST /api/local-audit/pick-folder, PUT /api/local-audit/folder, onRun 호출,
 *   화면 상태(data·검색·탭·선택·오류) 변경. 상세(LocalDetail)는 행 키와 실행 시각을 key로 새로 만들어 PDF 페이지 상태를 초기화한다.
 *   목록 표는 LocalTable, 상세는 LocalDetail로 위임한다
 */
export function LocalAuditScreen({jobs, busy, onRun, onRelatedDocument}: {
  jobs: Job[]; busy: boolean; onRun: () => void; onRelatedDocument?: (document: Doc | null) => void;
}) {
  const [data, setData] = useState<LocalAuditState | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [q, setQ] = useState('');
  const [tab, setTab] = useState<Tab>('전체');
  const [selectedFile, setSelectedFile] = useState('');

  const folder = data?.folder || null;
  const last = data?.last || null;
  const rows = buildRows(data);
  const audited = rows.some(r => r.audited);
  const needle = q.trim().toLowerCase();
  const filtered = rows.filter(r =>
    (tab === '전체' || r.status === tab)
    && (!needle || [r.file, r.partner, r.contract?.id].some(s => (s || '').toLowerCase().includes(needle))));
  const selected = rows.find(r => r.file === selectedFile) || null;
  /** [효과 명세] 선택 계약 원문 전달: 저장된 contract_doc 또는 null을 부모에 알린다.
   * 문서/콜백 변경에만 반응하며 네트워크 요청 없이 관련 링크 상태만 바꾼다. */
  useEffect(() => {
    onRelatedDocument?.(selected?.contract_doc ?? null);
  }, [selected?.contract_doc, onRelatedDocument]);
  const block = runBlock(folder, busy, saving);
  const stale = !!last && !!folder && last.folder !== folder;

  /**
   * [기능명세] load
   * 목적: 로컬 대조 상태 조회
   * 입력: 없음
   * 출력: Promise<void>
   * 처리/실패: GET /api/local-audit 성공 시 data를 바꾸고 오류를 지운다. 실패하면 오류 문구를 남기고 기존 data는 유지한다
   * 부수효과: 네트워크 요청, data·loaded·error 상태 변경
   */
  const load = async () => {
    try {
      setData(await api<LocalAuditState>('local-audit'));
      setError('');
    } catch (e) {
      setError('로컬 세금계산서 목록을 불러오지 못했습니다. ' + errorMessage(e));
    } finally {
      setLoaded(true);
    }
  };

  /**
   * [기능명세] pickAndSave
   * 목적: Windows 폴더 선택 대화상자로 세금계산서 폴더를 골라 바로 저장
   * 입력: 없음
   * 출력: Promise<void>
   * 처리/실패: POST pick-folder → 취소(null)면 아무것도 바꾸지 않는다 → PUT folder {folder} 응답으로 data 교체.
   *   어느 단계든 실패하면 api()가 던진 메시지를 화면 오류로 보인다. 저장하면 선택 행·탭을 초기화한다
   * 부수효과: 네이티브 대화상자 요청, 서버 설정(마지막 폴더) 저장, saving·data·error·selectedFile·tab 변경
   */
  const pickAndSave = async () => {
    setSaving(true);
    setError('');
    try {
      const r = await api<{folder: string | null}>('local-audit/pick-folder', {});
      if (!r.folder) return;
      setData(await api<LocalAuditState>('local-audit/folder', {folder: r.folder}, 'PUT'));
      setSelectedFile('');
      setTab('전체');
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  /**
   * [효과 명세] 마운트 시 조회
   * 처리: 화면이 열릴 때 한 번 load()를 호출한다
   * 부수효과: GET /api/local-audit
   */
  useEffect(() => {
    void load();
  }, []);

  /**
   * [효과 명세] 대조 작업 완료 감지 (useJobDone)
   * 입력: jobs(App state 폴링 결과)
   * 처리: 처음 실행 때는 이미 끝나 있던 로컬 대조 작업 ID를 기억만 한다(마운트 조회가 반영함).
   *   이후 running이 아닌 상태로 새로 보이는 작업이 있으면 상태를 한 번 다시 조회한다
   * 부수효과: 필요 시 GET /api/local-audit
   */
  useJobDone(jobs, [LOCAL_JOB], () => void load());

  return (
    <div className="contracts-screen local-screen">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2><FolderOpen size={16}/>세금계산서 폴더</h2>
            <p>폴더 바로 아래의 PDF·PNG만 읽습니다(하위 폴더 제외). PNG는 목록에만 보이고 '확인 필요'로 둡니다.</p>
          </div>
        </div>
        <div className="local-folder-body">
          <div className="local-folder">
            <span className="field-label">현재 폴더</span>
            <code data-testid="local-folder" className={folder ? '' : 'missing'} title={folder || undefined}>
              {folder || '아직 폴더를 선택하지 않았습니다. [폴더 선택]을 눌러 세금계산서가 있는 폴더를 고르세요.'}
            </code>
          </div>
          <div className="local-actions">
            <button className="secondary" data-testid="local-pick" disabled={saving || busy} onClick={() => void pickAndSave()}>
              {saving ? <LoaderCircle size={16} className="spin"/> : <FolderSearch size={16}/>}폴더 선택
            </button>
            <button
              className="primary"
              data-testid="local-run"
              disabled={!!block}
              title={block || '폴더의 세금계산서를 웹 계약서와 대조합니다'}
              aria-describedby={block ? 'local-run-block' : undefined}
              onClick={onRun}
            >
              <GitCompareArrows size={16}/>웹 계약서와 대조
            </button>
          </div>
          <p className="local-meta" aria-live="polite">
            {block && <small id="local-run-block" className="statement-hint">{block}</small>}
            <span>
              {last
                ? '마지막 대조 ' + stamp(last.ran_at) + ' · 웹 계약 ' + display(last.contracts_total) + '건'
                : '아직 대조하지 않았습니다.'}
              {data && folder && ' · 폴더 파일 ' + data.files.length + '개'}
            </span>
            {stale && <small className="statement-hint">폴더가 바뀌어 이전 대조 결과({last!.folder})는 표시하지 않습니다.</small>}
          </p>
        </div>
      </section>

      {error && <div role="alert" className="alert error contracts-alert"><XCircle size={17}/>{error}</div>}
      {data?.folder_error && (
        <div role="alert" className="alert amber contracts-alert"><AlertTriangle size={17}/>{data.folder_error}</div>
      )}

      <div className="result-summary local-summary">
        <div>
          <span className="eyebrow">LOCAL INVOICE AUDIT</span>
          <h2>{audited ? rows.filter(r => r.audited).length + '건의 대조 결과' : '대조 전'}</h2>
          <p>{last && audited ? stamp(last.ran_at) + ' · 웹 계약 ' + display(last.contracts_total) + '건과 대조' : '[웹 계약서와 대조]를 누르면 판정이 표시됩니다.'}</p>
        </div>
        <div className="result-counts">
          {LOCAL_STATUS_ORDER.map(s => (
            <div key={s}>
              <Badge status={s}/>
              <strong>{rows.filter(r => r.status === s).length}</strong>
            </div>
          ))}
        </div>
      </div>

      <div className="contracts-layout local-layout">
        <LocalTable
          loaded={loaded}
          folder={folder}
          rows={rows}
          filtered={filtered}
          q={q}
          onQ={setQ}
          tab={tab}
          onTab={setTab}
          selectedFile={selectedFile}
          onSelect={setSelectedFile}
        />

        <section className="panel contracts-detail local-detail" aria-label="세금계산서 대조 상세" data-testid="local-detail">
          {!selected
            ? (
              <div className="empty">
                <span className="empty-icon"><FileText size={30}/></span>
                <h3>세금계산서를 선택하세요</h3>
                <p>표에서 행을 누르면 판정 근거와 계약서 원문을 볼 수 있습니다.</p>
              </div>
            )
            : <LocalDetail key={selected.file + '|' + (last?.ran_at || '')} row={selected}/>}
        </section>
      </div>
    </div>
  );
}
