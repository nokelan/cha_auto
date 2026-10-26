/** [파일 역할] 계약 검색·구분·목록 표시. 서버 요청 없이 콜백으로 입력을 전달한다. */
import {FileText, Search} from 'lucide-react';
import {stamp} from '../../api';
import type {ImportedContract} from '../../types';
import {COMPARES, KINDS, type CompareFilter, type Kind} from './contracts';
import {CompareBadge, ContractActions, ContractStatus} from './ContractActions';
/**
 * [기능명세] ContractList
 * 목적: 검색·구분·선택 가능한 계약 목록 표시.
 * 입력: 전체/필터 목록, 조회 여부, 검색/탭/문서비교 필터/선택 상태, 작업 상태와 선택/초안 열기/비교 결과 열기 콜백.
 * 출력: 목록 JSX(행마다 품의 상태와 문서비교 판정 배지). 비어 있거나 조회 중이면 기존 안내를 보인다.
 * 처리/예외: 입력값을 표시하며 네트워크 요청이나 자료 변경은 하지 않는다.
 * 부수효과: 사용자 입력 시 상위 상태 변경 콜백을 호출한다.
 */
export function ContractList({items, filtered, loaded, q, tab, compareFilter, selectedId, busy, loadingId, onQ, onTab, onCompareFilter, onSelect, onOpen, onOpenResult}: {
  items: ImportedContract[]; filtered: ImportedContract[]; loaded: boolean; q: string; tab: Kind; compareFilter: CompareFilter;
  selectedId: string; onQ: (v: string) => void; onTab: (v: Kind) => void; onCompareFilter: (v: CompareFilter) => void; onSelect: (id: string) => void;
  busy: boolean; loadingId: string; onOpen: (contract: ImportedContract) => void; onOpenResult?: (resultId: string, mailId: string) => void;
}) {
  return (
        <section className="panel contracts-list">
          <div className="panel-heading">
            <div>
              <h2><FileText size={16}/>가져온 계약 <span>{filtered.length}</span></h2>
              <p>전체 {items.length}건 · 관리번호 큰 순</p>
            </div>
          </div>
          <div className="filters">
            <div className="search">
              <Search size={16}/>
              <input aria-label="계약 검색" placeholder="거래처·계약명·관리번호 검색" value={q} onChange={e => onQ(e.target.value)}/>
            </div>
            <div className="contracts-tabs" role="group" aria-label="계약 구분 보기">
              {KINDS.map(k => (
                <button key={k} className={tab === k ? 'active' : ''} aria-pressed={tab === k} onClick={() => onTab(k)}>{k}</button>
              ))}
            </div>
            <select aria-label="문서비교 상태 보기" value={compareFilter} onChange={e => onCompareFilter(e.target.value as CompareFilter)}>
              {COMPARES.map(c => <option key={c} value={c}>{c === '전체' ? '문서비교: 전체' : '문서비교: ' + c}</option>)}
            </select>
          </div>
          {!loaded
            ? <div className="empty"><p>계약서 목록을 불러오는 중입니다.</p></div>
            : !items.length
              ? (
                <div className="empty">
                  <span className="empty-icon"><FileText size={30}/></span>
                  <h3>아직 가져온 계약서가 없습니다</h3>
                  <p>위 조건을 정해 계약서 가져오기를 누르세요.</p>
                </div>
              )
              : !filtered.length
                ? <div className="empty"><h3>조건에 맞는 계약이 없습니다</h3><p>검색어나 구분 탭을 바꿔 보세요.</p></div>
                : (
                  <div className="contracts-rows">
                    {filtered.map(c => (
                      <div
                        key={c.id}
                        role="button"
                        tabIndex={0}
                        className={'contracts-row' + (c.id === selectedId ? ' selected' : '')}
                        aria-pressed={c.id === selectedId}
                        onClick={() => onSelect(c.id)}
                        onKeyDown={event => {
                          // [기능명세] 행 키보드 선택: 행 자체의 Enter/Space만 선택하며 내부 작업 버튼 키 입력은 그대로 둔다.
                          // 입력 키 이벤트, 출력 없음. Space 기본 스크롤을 막고 선택 콜백을 호출한다.
                          if (event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) {
                            event.preventDefault();
                            onSelect(c.id);
                          }
                        }}
                      >
                        <span className="contracts-row-top">
                          <b>{c.id}</b>
                          <span className={'badge ' + (c.kind === '수입' ? 'green' : 'amber')}>{c.kind}</span>
                          <ContractStatus contract={c}/>
                          <CompareBadge contract={c} onOpenResult={onOpenResult}/>
                          <span className={'contracts-pdf ' + (c.document?.available ? 'ok' : 'missing')}>
                            {c.document?.available ? '저장됨' : '파일 없음'}
                          </span>
                        </span>
                        <strong>{c.partner}</strong>
                        <span className="contracts-title">{c.title}</span>
                        <small>{c.period} · {c.amount_text}</small>
                        <small>가져온 시각 {stamp(c.imported)}</small>
                        <ContractActions contract={c} busy={busy} loading={loadingId === c.id} compact onOpen={onOpen}/>
                      </div>
                    ))}
                  </div>
                )}
        </section>
  );
}
