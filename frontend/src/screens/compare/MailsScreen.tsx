/**
 * [파일 역할] '메일 · 문서 선택' 3단 화면.
 * 1단: 기업(PDF 메일) 검색·선택, 2단: 세금계산서 PDF와 계약서 연결 후 다운로드·비교 실행,
 * 3단: 비교 결과·원문(ResultView를 그대로 받아 표시). 단 사이 경계선으로 너비를 조정한다.
 * 검색어·선택·단 너비 상태는 App이 가지고 있어 다른 화면에 다녀와도 유지된다.
 */
import type {CSSProperties, ReactNode} from 'react';
import {ArrowRight, CheckCircle2, Download, FileCheck2, Inbox, Search} from 'lucide-react';
import {stamp} from '../../api';
import type {ColumnResize} from '../../hooks/useColumnResize';
import type {Selection} from '../../hooks/useSelection';
import type {Mail, State} from '../../types';

type Props = {
  state: State;
  loading: boolean;
  busy: boolean;
  q: string;
  from: string;
  to: string;
  onQ: (v: string) => void;
  onFrom: (v: string) => void;
  onTo: (v: string) => void;
  selection: Selection;
  columns: ColumnResize;
  onFocusMail: (m: Mail) => void;
  onRequest: (path: string, body: unknown) => void;
  resultView: ReactNode;
};

/**
 * [기능명세] MailsScreen
 * 목적: 기업 선택 → 문서 연결 → 비교 결과 확인의 3단 작업 화면
 * 입력: state(메일·계약·동기화 시각), loading(최초 조회 중), busy(작업 중이면 조작 비활성),
 *   q/from/to와 변경 콜백(검색어·수신일 범위), selection(선택 훅), columns(단 너비 훅),
 *   onFocusMail(기업 카드 클릭: 선택 토글과 관련 결과 표시), onRequest(작업 API 요청),
 *   resultView(3단에 넣을 결과 화면)
 * 출력: 3단 화면 JSX
 * 처리/실패: 검색은 보낸 사람+제목(대소문자 무시)과 수신일(YYYY-MM-DD) 범위로 거른다.
 *   PDF 없는 메일은 목록에서 제외하고 개수만 표시한다.
 *   모든 연결에 계약이 있으면 '다운로드' 가능, 양쪽 PDF가 실제 저장돼 있어야 '비교 실행' 가능
 * 부수효과: 콜백을 통해 선택·검색·너비 상태 변경과 download/compare 작업 요청
 */
export function MailsScreen(props: Props) {
  const {state, loading, busy, q, from, to, onQ, onFrom, onTo, selection, columns, onFocusMail, onRequest, resultView} = props;
  const {selected, pairs} = selection;
  const {widths} = columns;

  const filtered = state.mails.filter(m =>
    (m.sender + ' ' + m.subject).toLowerCase().includes(q.toLowerCase())
    && (!from || m.received.slice(0, 10) >= from)
    && (!to || m.received.slice(0, 10) <= to));
  const allFiltered = filtered.filter(m => m.pdfs.length);
  const pdfCount = state.mails.filter(m => m.pdfs.length).length;
  const selectedMails = state.mails.filter(m => !!selected[m.id]);
  const connected = pairs.length > 0 && pairs.every(p => p.contract_id);
  /** 모든 연결의 세금계산서 PDF와 계약서 PDF가 실제 파일로 저장돼 있으면 비교 준비 완료. */
  const ready = connected && pairs.every(p => {
    const m = state.mails.find(x => x.id === p.mail_id);
    const c = state.contracts.find(x => x.id === p.contract_id);
    return m?.documents[p.invoice_url]?.available && c?.document?.available;
  });
  const gridStyle = {
    '--first': widths[0] + 'fr',
    '--second': widths[1] + 'fr',
    '--third': (100 - widths[0] - widths[1]) + 'fr',
  } as CSSProperties;

  return (
    <>
      <div className="workspace-info">
        <span>PDF 메일 <b>{pdfCount}건</b> · 계약 <b>{state.contracts.length}건</b></span>
        <span>최근 동기화 {stamp(state.synced)}</span>
        <button className="text-btn" onClick={columns.reset}>단 너비 초기화</button>
      </div>
      <div className="compare-workspace" ref={columns.workspaceRef} style={gridStyle}>
        <section className="panel company-panel">
          <div className="panel-heading">
            <div>
              <h2><b className="stage">1</b>비교할 기업 <span>{allFiltered.length}</span></h2>
              <p>기업을 누르면 PDF와 추천 계약이 선택됩니다.</p>
            </div>
          </div>
          <div className="filters">
            <div className="search">
              <Search size={16}/>
              <input aria-label="업체 또는 메일 제목 검색" placeholder="기업명 또는 메일 검색" value={q} onChange={e => onQ(e.target.value)}/>
            </div>
            <label>수신일 <input aria-label="수신일 시작" type="date" value={from} onChange={e => onFrom(e.target.value)}/><input aria-label="수신일 종료" type="date" value={to} onChange={e => onTo(e.target.value)}/></label>
            {(q || from || to) && (
              <button
                className="text-btn"
                onClick={() => {
                  onQ('');
                  onFrom('');
                  onTo('');
                }}
              >
                검색 초기화
              </button>
            )}
          </div>
          <div className="list-actions">
            <label><input type="checkbox" aria-label="표시된 PDF 메일 전체 선택" disabled={!allFiltered.length || busy} checked={allFiltered.length > 0 && allFiltered.every(m => !!selected[m.id])} onChange={() => selection.setAll(allFiltered)}/> 전체 선택</label>
            <button className="text-btn" disabled={busy} onClick={selection.clear}>선택 해제</button>
          </div>
          <div className="company-list">
            {allFiltered.map(m => {
              const c = state.contracts.find(c => c.id === m.candidates[0]);
              const saved = m.pdfs.some(a => m.documents[a.url]?.available);
              return (
                <button
                  className={'company-card ' + (selected[m.id] ? 'selected' : '')}
                  key={m.id}
                  disabled={busy}
                  aria-pressed={!!selected[m.id]}
                  onClick={() => onFocusMail(m)}
                >
                  <span className="company-title">
                    <strong>{m.sender}</strong>
                    {selected[m.id] ? <CheckCircle2 size={18}/> : <span className="select-circle"/>}
                  </span>
                  <span className="company-subject">{m.subject}</span>
                  <span className="company-meta">{m.received.slice(0, 10)} · PDF {m.pdfs.length}개 · {saved ? '저장됨' : '저장 필요'}</span>
                  <span className="contract-hint">
                    {m.candidates.length === 1
                      ? (c ? '추천 계약 · ' + c.title : '추천 계약 정보를 찾을 수 없음 · 직접 선택')
                      : m.candidates.length > 1
                        ? '계약 후보 여러 건 · 직접 선택'
                        : '연결할 계약 직접 선택'}
                  </span>
                </button>
              );
            })}
          </div>
          {!allFiltered.length && (
            <div className="empty">
              <Inbox size={28}/>
              <h3>{loading ? '목록 불러오는 중' : state.synced ? '검색 결과 없음' : '목록을 가져와 주세요'}</h3>
              <p>목록 새로고침으로 PDF 메일을 불러옵니다.</p>
            </div>
          )}
          <div className="panel-footer">PDF 없는 메일 {state.mails.length - pdfCount}건 제외</div>
        </section>
        <div className="column-divider" {...columns.dividerProps(0)}><span/></div>
        <section className="panel connections">
          <div className="panel-heading">
            <div>
              <h2><b className="stage">2</b>문서 연결 · 비교 <span>{pairs.length}</span></h2>
              <p>연결된 계약을 확인한 뒤 비교하세요.</p>
            </div>
          </div>
          {selectedMails.length
            ? selectedMails.map(m => {
              const pair = selected[m.id];
              const c = state.contracts.find(c => c.id === pair.contract_id);
              return (
                <div className="connection" key={m.id}>
                  <div>
                    <strong>{m.sender}</strong>
                    <small>{m.subject}</small>
                    <label className="field-label">
                      세금계산서 PDF
                      <select
                        aria-label={m.sender + ' 첨부 PDF 선택'}
                        value={pair.invoice_url}
                        disabled={busy}
                        onChange={e => selection.updatePair(m.id, {invoice_url: e.target.value})}
                      >
                        {m.pdfs.map(a => <option key={a.url} value={a.url}>{a.name}</option>)}
                      </select>
                    </label>
                  </div>
                  <ArrowRight size={17}/>
                  <div>
                    <label className="field-label">
                      비교할 계약서
                      <select
                        aria-label={m.sender + ' 연결 계약'}
                        value={pair.contract_id}
                        disabled={busy}
                        onChange={e => selection.updatePair(m.id, {contract_id: e.target.value})}
                      >
                        <option value="">계약서를 선택하세요</option>
                        {['지출', '수입'].map(kind => (
                          <optgroup key={kind} label={kind + ' 계약'}>
                            {state.contracts
                              .filter(c => c.kind === kind && c.file)
                              .map(c => <option key={c.id} value={c.id}>{c.partner} · {c.title} · {c.id}</option>)}
                          </optgroup>
                        ))}
                      </select>
                    </label>
                    <small>
                      {c
                        ? `${c.period} · ${c.amount_text}`
                        : m.candidates.length > 1
                          ? '후보가 여러 건입니다. 직접 선택해 주세요.'
                          : '연결할 계약을 선택해 주세요.'}
                    </small>
                  </div>
                </div>
              );
            })
            : (
              <div className="empty">
                <FileCheck2 size={28}/>
                <h3>기업을 선택해 주세요</h3>
                <p>왼쪽 목록에서 한 건 또는 여러 건을 선택할 수 있습니다.</p>
              </div>
            )}
          <div className="action-bar">
            <span><b>{pairs.length}건</b> 선택됨 {ready ? '· 비교 준비 완료' : connected ? '· PDF를 먼저 저장해 주세요' : '· 기업과 계약을 선택해 주세요'}</span>
            <div>
              <button className="secondary" disabled={!connected || busy} onClick={() => onRequest('download', {pairs})}>
                <Download size={16}/>선택 문서 다운로드
              </button>
              <button className="primary" disabled={!ready || busy} onClick={() => onRequest('compare', {pairs})}>
                <FileCheck2 size={16}/>비교 실행
              </button>
            </div>
          </div>
        </section>
        <div className="column-divider" {...columns.dividerProps(1)}><span/></div>
        <section className="workspace-results">
          <div className="panel-heading">
            <div>
              <h2><b className="stage">3</b>비교 결과 · 원문</h2>
              <p>항목별 차이와 PDF 근거를 확인하세요.</p>
            </div>
          </div>
          {resultView}
        </section>
      </div>
      <p className="workspace-help">단 사이의 경계선을 드래그하면 좌우 너비를 조정할 수 있습니다. 화면이 좁으면 세로로 배치됩니다.</p>
    </>
  );
}
