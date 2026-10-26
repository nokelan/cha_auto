/**
 * [파일 역할] 잠금 해제 후의 새봄 문서비교 메인 화면 컨테이너.
 * 책임: 사이드바·상단바·작업 진행 표시와 화면 전환(메일·문서 선택 / 비교 결과 / 계약서 목록 / 로컬 세금계산서 대조 /
 *   작업 이력 / 설정 / 개발문서), 작업 요청(sync·download·compare·contracts/import·local-audit/run·browser·correct·settings·shutdown),
 *   보정·원문 모달 표시. 모든 업무 메뉴는 한 viewport 안의 왼쪽 본문·오른쪽 관련 링크로 배치한다.
 * 상태 계약: 서버 데이터(state·결과 요약·결과 상세)는 useAppState가 재조회하고,
 *   선택·검색어·배율·단 너비·현재 행은 화면 상태이며 자동 영속화하지 않는다.
 * 하위 구성: screens/*(화면), components/*(배지·PDF·모달), hooks/*(조회·선택·단 너비·설정·보정), navigation.ts(메뉴·제목 상수).
 *   저장 위치 동작은 useSettings, 보정 폼·재비교 요청은 useCorrection이 맡고 App은 화면 전환과 작업 요청(act)을 조율한다.
 */
import {useEffect, useRef, useState} from 'react';
import {CheckCircle2, ChevronRight, Leaf, LoaderCircle, Power, RefreshCw, ShieldCheck, X, XCircle} from 'lucide-react';
import {api} from './api';
import {EditModal} from './components/EditModal';
import {PreviewModal} from './components/PreviewModal';
import {RelatedLinks} from './components/RelatedLinks';
import {useAppState} from './hooks/useAppState';
import {useColumnResize} from './hooks/useColumnResize';
import {useCorrection} from './hooks/useCorrection';
import {useSelection} from './hooks/useSelection';
import {useSettings} from './hooks/useSettings';
import {HEADINGS, NAV} from './navigation';
import {ContractsScreen} from './screens/contracts/ContractsScreen';
import {HistoryScreen} from './screens/compare/HistoryScreen';
import {LocalAuditScreen} from './screens/local/LocalAuditScreen';
import {MailsScreen} from './screens/compare/MailsScreen';
import {ResultView} from './screens/compare/ResultView';
import {DocsScreen} from './screens/docs/DocsScreen';
import {SettingsScreen} from './screens/SettingsScreen';
import type {DevDocInfo, Doc, DocToc, Mail, Preview} from './types';
import {errorMessage} from './utils/error';

/**
 * [기능명세] App
 * 목적: 기업 선택·비교·이력·설정 화면 컨테이너
 * 입력: 컴포넌트 인자 없음
 * 출력: 독립 스크롤하는 본문/관련 링크 2단 화면·모달 JSX, 종료 후에는 종료 안내 JSX
 * 처리/실패: 서버 상태 조회와 사용자 선택을 합쳐 버튼·결과·모달을 구성한다.
 *   요청 실패 메시지는 상단 오류 알림(role=alert)으로 표시한다
 * 부수효과: 주기 요청·작업 API 호출, 선택/미리보기 상태 관리(설정·보정 상태는 각 훅이 관리)
 */
export function App() {
  const [screen, setScreen] = useState('mails');
  const [q, setQ] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [rowIndex, setRowIndex] = useState(0);
  const [focusedMail, setFocusedMail] = useState('');
  const [notice, setNotice] = useState('');
  const [requesting, setRequesting] = useState(false);
  const [stopped, setStopped] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  /** 각 하위 화면이 선택한 저장 문서. 관련 링크는 현재 화면의 값만 사용한다. */
  const [contractDocument, setContractDocument] = useState<Doc | null>(null);
  const [localDocument, setLocalDocument] = useState<Doc | null>(null);
  /** 개발문서 화면의 문서 목록·선택 문서·목차. 관련 링크(RelatedLinks)와 공유하며 영속화하지 않는다. */
  const [devDocs, setDevDocs] = useState<DevDocInfo[]>([]);
  const [devDocName, setDevDocName] = useState('');
  const [devDocToc, setDevDocToc] = useState<DocToc[]>([]);
  /** 기업 카드 클릭으로 고른 결과의 상세가 아직 안 왔을 때, 도착 후 맞출 행(메일 ID). */
  const pendingRow = useRef<{resultId: string; mailId: string} | null>(null);

  const selection = useSelection();
  const columns = useColumnResize();
  // 새 완료 결과가 생기면 첫 행·포커스 해제, 3단 화면이 아니면 '비교 결과' 화면으로 이동한다.
  const {state, results, resultId, setResultId, current, detailPending, loading, error, setError, reload, running} = useAppState(stopped, () => {
    setRowIndex(0);
    setFocusedMail('');
    setScreen(s => (s === 'mails' ? 'mails' : 'results'));
  });
  const {folder, setFolder, picking, moving, saveFolder, pickFolder} = useSettings(state.document_root, setError, setNotice, reload);
  const busy = requesting || moving || running;

  /** 현재 행: 3단 화면에서 기업에 포커스가 있으면 그 메일의 행, 아니면 rowIndex 행(없으면 첫 행). */
  const currentRow = screen === 'mails' && focusedMail
    ? current?.rows.find(r => r.mail_id === focusedMail)
    : current?.rows[rowIndex] || current?.rows[0];
  const latestJob = state.jobs[0];
  const heading = HEADINGS[screen] ?? HEADINGS.settings;
  const relatedDocuments = screen === 'contracts' ? [contractDocument]
    : screen === 'local' ? [localDocument]
    : ['mails', 'results', 'history'].includes(screen) ? [currentRow?.invoice, currentRow?.contract] : [];

  /**
   * [효과 명세] 상세 도착 후 행 맞춤
   * 처리: 기업 카드 클릭으로 예약한 결과의 상세(current)가 도착하면 그 메일의 행 번호로 rowIndex를 맞춘다.
   * 부수효과: rowIndex 변경, pendingRow 비움
   */
  useEffect(() => {
    const p = pendingRow.current;
    if (!p || !current || current.id !== p.resultId) return;
    pendingRow.current = null;
    setRowIndex(current.rows.findIndex(x => x.mail_id === p.mailId));
  }, [current]);

  /**
   * [기능명세] act
   * 목적: 작업 요청 공통 실행
   * 입력: path(/api/ 뒤 경로), body(기본 {}), method(기본 POST)
   * 출력: Promise<boolean> — API 호출이 성공하면 true, 실패하면 false
   * 처리/실패: 요청 중 표시·안내/오류 비우기 → API 호출 → reload. 실패하면 오류를 화면에 표시하고 false 반환
   *   (reload 자체의 실패는 reload가 오류 배너로 표시하며 호출 성공 여부에는 영향 없음)
   * 부수효과: 작업 API 호출, requesting·error·notice 상태 변경
   */
  const act = async (path: string, body: unknown = {}, method = 'POST'): Promise<boolean> => {
    setRequesting(true);
    setError('');
    setNotice('');
    try {
      await api(path, body, method);
      await reload();
      return true;
    } catch (e) {
      setError(errorMessage(e));
      return false;
    } finally {
      setRequesting(false);
    }
  };

  const {editing, edits, editErrors, openEdits, closeEdits, changeEdit, correct} = useCorrection(current, currentRow, resultId, rowIndex, act);

  /**
   * [기능명세] focusMail
   * 목적: 3단 화면 기업 카드 클릭 처리
   * 입력: m: 클릭한 메일
   * 출력: void
   * 처리/실패: 선택을 토글하고 포커스를 둔다. 결과 요약 중 mail_ids에 이 메일이 포함된 첫(최신) 결과를
   *   resultId로 정한다. 그 상세가 이미 화면에 있으면 바로 행 번호를 맞추고, 아니면 상세 도착 후 맞추도록 예약한다.
   *   포함된 결과가 없으면 결과 선택은 바꾸지 않는다
   * 부수효과: selected·focusedMail·resultId·rowIndex 변경(상세 조회는 useAppState가 수행)
   */
  const focusMail = (m: Mail) => {
    selection.toggle(m);
    setFocusedMail(m.id);
    const r = results.find(x => x.mail_ids.includes(m.id));
    if (!r) return;
    setResultId(r.id);
    if (current?.id === r.id) {
      pendingRow.current = null;
      setRowIndex(current.rows.findIndex(x => x.mail_id === m.id));
    } else {
      pendingRow.current = {resultId: r.id, mailId: m.id};
    }
  };

  /**
   * [기능명세] openHistory
   * 목적: 이력 행 클릭 시 해당 결과를 '비교 결과' 화면으로 열기
   * 입력: id: 결과 ID
   * 출력: void
   * 처리/실패: 첫 행부터 표시하며, 대기 중인 행 맞춤 예약은 취소한다
   * 부수효과: resultId·rowIndex·screen 변경
   */
  const openHistory = (id: string) => {
    pendingRow.current = null;
    setResultId(id);
    setRowIndex(0);
    setScreen('results');
  };

  /**
   * [기능명세] openCompareResult
   * 목적: 계약서 목록의 문서비교 배지에서 해당 결과·메일 행을 '비교 결과' 화면으로 열기
   * 입력: id(결과 ID), mailId(그 계약과 비교된 메일 ID)
   * 출력: void
   * 처리/실패: 결과 상세가 이미 화면에 있으면 바로 메일 행으로, 아니면 상세 도착 후 맞추도록 예약한다(행을 못 찾으면 0번 행)
   * 부수효과: resultId·rowIndex·pendingRow·screen 변경
   */
  const openCompareResult = (id: string, mailId: string) => {
    setResultId(id);
    if (current?.id === id) {
      pendingRow.current = null;
      setRowIndex(Math.max(0, current.rows.findIndex(x => x.mail_id === mailId)));
    } else {
      pendingRow.current = {resultId: id, mailId};
    }
    setScreen('results');
  };

  /**
   * [기능명세] shutdown
   * 목적: 프로그램 종료 요청
   * 입력: 없음
   * 출력: Promise<void>
   * 처리/실패: shutdown API 성공 시 종료 안내 화면으로 바꾸고 폴링을 멈춘다. 실패하면 오류 표시
   * 부수효과: 서버 종료 요청, stopped·error 변경
   */
  const shutdown = async () => {
    try {
      await api('shutdown', {});
      setStopped(true);
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const resultView = (
    <ResultView
      current={current}
      pending={detailPending}
      currentRow={currentRow}
      rowIndex={rowIndex}
      onSelectRow={(i, mailId) => {
        setRowIndex(i);
        setFocusedMail(mailId);
      }}
      onPreview={setPreview}
      onEdit={openEdits}
      onStart={() => setScreen('mails')}
    />
  );

  if (stopped) {
    return (
      <div className="closed">
        <Leaf size={40}/>
        <h1>새봄 문서비교를 종료했습니다.</h1>
        <p>저장한 문서와 비교 이력은 유지됩니다. 다시 사용하려면 EXE를 실행해 주세요.</p>
      </div>
    );
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" onClick={() => setScreen('mails')}>
          <span className="brand-icon"><Leaf size={23}/></span>
          <div>새봄<span>문서비교</span></div>
        </a>
        <div className="workspace-label">DOCUMENT WORKSPACE</div>
        <nav>
          {NAV.map(n => (
            <button key={n.id} className={screen === n.id ? 'active' : ''} onClick={() => setScreen(n.id)}>
              <n.icon size={18}/>{n.label}{n.id === 'mails' && state.mails.length > 0 && <span>{state.mails.length}</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="privacy">
            <ShieldCheck size={18}/>
            <div>
              <strong>내 PC에서 안전하게</strong>
              <p>AI 없이, 저장 문서는 오프라인 비교</p>
            </div>
          </div>
          <button className="exit" disabled={busy} onClick={() => void shutdown()}><Power size={16}/>프로그램 종료</button>
          <small>SAEBOM COMPARE · v1.0</small>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <span>내 작업 공간 <ChevronRight size={13}/> {NAV.find(n => n.id === screen)?.label}</span>
          <div><span className="local-dot"/> 로컬 실행 중 <i/> <ShieldCheck size={14}/> AI 미사용</div>
        </header>
        <div className="content workspace-layout">
          <div className="workspace-main" role="region" aria-label="업무 본문" tabIndex={0}>
          <div className="page-heading">
            <div className="eyebrow">SAEBOM DOCUMENT REVIEW</div>
            <div className="heading-line">
              <div>
                <h1>{heading.title}</h1>
                <p>{heading.desc}</p>
              </div>
              {screen === 'mails' && (
                <button className="primary" disabled={busy} onClick={() => void act('sync')}>
                  <RefreshCw size={16} className={busy ? 'spin' : ''}/>목록 새로고침
                </button>
              )}
            </div>
          </div>
          {error && (
            <div role="alert" className="alert error">
              <XCircle size={17}/>{error}
              <button onClick={() => setError('')} aria-label="오류 닫기"><X size={16}/></button>
            </div>
          )}
          {notice && <div role="status" className="alert success"><CheckCircle2 size={17}/>{notice}</div>}
          {latestJob && (
            <div className={'job ' + (latestJob.status === 'failed' ? 'job-failed' : '')}>
              <div>
                {latestJob.status === 'running'
                  ? <LoaderCircle size={17} className="spin"/>
                  : latestJob.status === 'failed'
                    ? <XCircle size={17}/>
                    : <CheckCircle2 size={17}/>}
                <b>{latestJob.kind}</b>
                <span>{latestJob.message}</span>
                <small>{latestJob.done} / {latestJob.total}</small>
              </div>
              {latestJob.status === 'running' && <progress value={latestJob.done} max={latestJob.total}/>}
              {latestJob.errors?.length > 0 && (
                <details>
                  <summary>실패 파일 {latestJob.errors.length}건 보기</summary>
                  {latestJob.errors.map((e, i) => <p key={i}>{e}</p>)}
                </details>
              )}
            </div>
          )}

          {screen === 'mails' && (
            <MailsScreen
              state={state}
              loading={loading}
              busy={busy}
              q={q}
              from={from}
              to={to}
              onQ={setQ}
              onFrom={setFrom}
              onTo={setTo}
              selection={selection}
              columns={columns}
              onFocusMail={focusMail}
              onRequest={(path, body) => void act(path, body)}
              resultView={resultView}
            />
          )}

          {screen === 'results' && resultView}

          {screen === 'contracts' && (
            <ContractsScreen jobs={state.jobs} busy={busy} onImport={body => void act('contracts/import', body)} onRelatedDocument={setContractDocument} onOpenResult={openCompareResult}/>
          )}

          {screen === 'local' && (
            <LocalAuditScreen jobs={state.jobs} busy={busy} onRun={() => void act('local-audit/run')} onRelatedDocument={setLocalDocument}/>
          )}

          {screen === 'history' && <HistoryScreen results={results} onOpen={openHistory}/>}

          {screen === 'docs' && <DocsScreen name={devDocName} onSelect={setDevDocName} onDocs={setDevDocs} onToc={setDevDocToc}/>}

          {screen === 'settings' && (
            <SettingsScreen
              state={state}
              folder={folder}
              picking={picking}
              moving={moving}
              busy={busy}
              onFolderChange={setFolder}
              onPickFolder={() => void pickFolder()}
              onSaveFolder={() => void saveFolder()}
              onOpenBrowser={() => void act('browser')}
            />
          )}
          <footer className="footer">새봄 문서비교 <span>문서가 머무는 곳, 내 PC</span></footer>
          </div>
          <RelatedLinks screen={screen} documents={relatedDocuments}
            resultId={['mails', 'results', 'history'].includes(screen) ? current?.id : undefined}
            site={state.site} onNavigate={setScreen}
            devDocs={{docs: devDocs, current: devDocName, toc: devDocToc, onSelect: setDevDocName}}/>
        </div>
      </main>

      {preview && <PreviewModal preview={preview} onClose={() => setPreview(null)}/>}
      {editing && currentRow && (
        <EditModal
          edits={edits}
          busy={busy}
          error={[...Object.values(editErrors), error].filter(Boolean).join(" ") || undefined}
          onChange={changeEdit}
          onClose={closeEdits}
          onSubmit={() => void correct()}
        />
      )}
    </div>
  );
}
