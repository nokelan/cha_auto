/**
 * [파일 역할] '로컬 세금계산서 대조' 화면의 왼쪽 목록 패널(LocalAuditScreen에서 분리).
 * 제목·검색·판정 탭과 상태별 빈 화면(불러오는 중/폴더 없음/파일 없음/조건 불일치), 세금계산서 표를 그린다.
 * 상태(검색어·탭·선택)는 컨테이너가 갖고 이 컴포넌트는 props로만 표시·콜백한다.
 * 검증용 data-testid: local-row.
 */
import {FileText, FolderSearch, Search} from 'lucide-react';
import {display} from '../../api';
import {Badge} from '../../components/Badge';
import {fieldValue, supplyDiff, TABS, type Tab, type ViewRow} from './localRows';

/**
 * [기능명세] LocalTable
 * 목적: 로컬 세금계산서 목록 패널(검색·탭·표) 표시
 * 입력: loaded(첫 조회 완료 여부), folder(저장된 폴더 또는 null), rows(전체 행), filtered(검색·탭을 적용한 행),
 *   q·onQ(검색어와 변경 콜백), tab·onTab(판정 탭과 변경 콜백), selectedFile·onSelect(선택 파일명과 선택 콜백)
 * 출력: section.panel.local-list JSX
 * 처리/실패: 조회 전 → 폴더 없음 → 파일 없음 → 조건에 맞는 행 없음 → 표 순으로 안내를 고른다.
 *   행 클릭과 파일명 버튼 클릭은 같은 선택을 수행하며 버튼 클릭은 행 클릭과 중복되지 않게 전파를 막는다.
 *   '차이' 열은 supplyDiff 결과(양수면 +)이며 0이 아닌 값은 local-diff로 강조한다
 * 부수효과: 없음(콜백 호출만)
 */
export function LocalTable({loaded, folder, rows, filtered, q, onQ, tab, onTab, selectedFile, onSelect}: {
  loaded: boolean;
  folder: string | null;
  rows: ViewRow[];
  filtered: ViewRow[];
  q: string;
  onQ: (value: string) => void;
  tab: Tab;
  onTab: (tab: Tab) => void;
  selectedFile: string;
  onSelect: (file: string) => void;
}) {
  return (
        <section className="panel local-list">
          <div className="panel-heading">
            <div>
              <h2><FileText size={16}/>세금계산서 <span>{filtered.length}</span></h2>
              <p>전체 {rows.length}건 · 행을 누르면 항목별 판정과 계약서 원문을 봅니다.</p>
            </div>
          </div>
          <div className="filters">
            <div className="search">
              <Search size={16}/>
              <input aria-label="세금계산서 검색" placeholder="파일명·상호·관리번호 검색" value={q} onChange={e => onQ(e.target.value)}/>
            </div>
            <div className="contracts-tabs" role="group" aria-label="판정 보기">
              {TABS.map(t => (
                <button key={t} className={tab === t ? 'active' : ''} aria-pressed={tab === t} onClick={() => onTab(t)}>{t}</button>
              ))}
            </div>
          </div>
          {!loaded
            ? <div className="empty"><p>로컬 세금계산서 목록을 불러오는 중입니다.</p></div>
            : !folder
              ? (
                <div className="empty">
                  <span className="empty-icon"><FolderSearch size={30}/></span>
                  <h3>세금계산서 폴더를 선택하세요</h3>
                  <p>위 [폴더 선택]으로 세금계산서 PDF·PNG가 있는 폴더를 고르면 목록이 나타납니다.</p>
                </div>
              )
              : !rows.length
                ? <div className="empty"><h3>폴더에 세금계산서가 없습니다</h3><p>폴더 바로 아래에 PDF 또는 PNG 파일이 있는지 확인하세요.</p></div>
                : !filtered.length
                  ? <div className="empty"><h3>조건에 맞는 세금계산서가 없습니다</h3><p>검색어나 판정 탭을 바꿔 보세요.</p></div>
                  : (
                    <div className="table-wrap local-table-wrap">
                      <table className="local-table">
                        <thead>
                          <tr>
                            <th>파일명</th>
                            <th>상호</th>
                            <th>청구월</th>
                            <th className="num">공급가액</th>
                            <th className="num">세액</th>
                            <th className="num">합계</th>
                            <th>관련 계약</th>
                            <th>계약 금액</th>
                            <th className="num">차이</th>
                            <th>판정</th>
                          </tr>
                        </thead>
                        <tbody>
                          {filtered.map(r => {
                            const diff = supplyDiff(r);
                            const isSel = r.file === selectedFile;
                            return (
                              <tr
                                key={r.file}
                                data-testid="local-row"
                                className={isSel ? 'selected' : ''}
                                onClick={() => onSelect(r.file)}
                              >
                                <td>
                                  <button
                                    className="local-file"
                                    aria-pressed={isSel}
                                    onClick={e => {
                                      // 행 클릭과 중복 처리하지 않도록 전파를 막고 같은 선택을 수행한다.
                                      e.stopPropagation();
                                      onSelect(r.file);
                                    }}
                                  >
                                    <span className="file-tag">{r.type === 'png' ? 'PNG' : 'PDF'}</span>
                                    <span className="local-file-name">{r.file}</span>
                                  </button>
                                </td>
                                <td className="local-partner">
                                  <span className={r.partner ? '' : 'muted'}>{display(r.partner)}</span>
                                  {r.partner_source === 'filename' && <small className="local-source">파일명에서</small>}
                                </td>
                                <td className="nowrap">{display(fieldValue(r, 'month'))}</td>
                                <td className="num">{display(fieldValue(r, 'supply'))}</td>
                                <td className="num">{display(fieldValue(r, 'vat'))}</td>
                                <td className="num">{display(fieldValue(r, 'total'))}</td>
                                <td>
                                  {r.contract
                                    ? (
                                      <span className="local-contract">
                                        <span>
                                          <b>{r.contract.id}</b>
                                          <span className={'badge ' + (r.contract.kind === '수입' ? 'green' : 'amber')}>{r.contract.kind}</span>
                                        </span>
                                        <small>{r.contract.title}</small>
                                      </span>
                                    )
                                    : <span className="muted">{r.audited ? '없음' : '대조 전'}</span>}
                                </td>
                                <td>
                                  {r.contract || r.expected
                                    ? (
                                      <span className="local-contract">
                                        <span>{r.contract?.amount_text || '미확인'}</span>
                                        <small>기대 공급가액 {display(r.expected?.supply)}</small>
                                      </span>
                                    )
                                    : <span className="muted">—</span>}
                                </td>
                                <td className={'num' + (diff ? ' local-diff' : '')}>
                                  {diff === null ? <span className="muted">—</span> : (diff > 0 ? '+' : '') + diff.toLocaleString('ko-KR')}
                                </td>
                                <td><Badge status={r.status}/></td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
        </section>
  );
}
