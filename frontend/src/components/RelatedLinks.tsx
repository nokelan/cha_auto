/** [파일 역할] 현재 업무와 관련된 화면·저장 원문·결과 링크를 모으는 오른쪽 패널.
 * 서버 작업을 실행하지 않고 화면 이동·사용자가 누른 파일/사이트 링크만 제공한다. */
import {ArrowUpRight, FileText, Link2} from 'lucide-react';
import {NAV} from '../navigation';
import type {DevDocInfo, Doc, DocToc} from '../types';

/** [상수 명세] RELATED — 화면별 관련 업무 메뉴 ID. 현재 화면 자체는 포함하지 않는다. */
const RELATED: Record<string, string[]> = {
  mails: ['results', 'contracts', 'history', 'settings'],
  results: ['mails', 'history', 'contracts'],
  contracts: ['mails', 'local', 'settings'],
  local: ['contracts', 'results', 'settings'],
  history: ['results', 'mails'],
  settings: ['mails', 'contracts', 'local'],
  docs: ['mails', 'settings'],
};

/**
 * [기능명세] RelatedLinks
 * 목적: 현재 화면과 연결된 메뉴·사용 가능한 저장 문서·결과 CSV를 오른쪽에 정리한다.
 * 입력: screen(현재 메뉴 ID), documents(현재 선택 업무의 저장 문서), resultId(현재 결과, 선택),
 *   site(설정 화면에서 표시할 서버 사이트 주소), onNavigate(내부 메뉴 변경),
 *   devDocs(개발문서 화면의 문서 목록·현재 문서·목차·문서 선택 콜백, docs 화면에서만 사용).
 * 출력: '관련 링크' 접근성 이름을 가진 aside JSX.
 * 처리/실패: 문서는 ID 중복을 제거하고 available=false는 링크로 표시하지 않는다.
 *   없는 원문·결과는 안내를 표시한다. 외부 링크는 HTTPS일 때만 표시하고 자동 접속하지 않는다.
 * 부수효과: 메뉴 버튼은 onNavigate 호출만, 링크는 사용자가 눌렀을 때 새 탭/다운로드를 연다.
 */
export function RelatedLinks({screen, documents, resultId, site, onNavigate, devDocs}: {
  screen: string;
  documents: (Doc | null | undefined)[];
  resultId?: string;
  site: string;
  onNavigate: (screen: string) => void;
  devDocs?: {docs: DevDocInfo[]; current: string; toc: DocToc[]; onSelect: (name: string) => void};
}) {
  const docs = [...new Map(documents.filter((d): d is Doc => !!d && d.available !== false).map(d => [d.id, d])).values()];
  const menus = (RELATED[screen] ?? []).map(id => NAV.find(n => n.id === id)!).filter(Boolean);
  return (
    <aside className="related-links" aria-label="관련 링크" tabIndex={0}>
      <header className="related-heading">
        <span className="related-icon"><Link2 size={19}/></span>
        <div><h2>관련 링크</h2><p>현재 업무와 연결된 곳을 모았어요.</p></div>
      </header>
      <section className="related-section" aria-labelledby="related-menu-title">
        <h3 id="related-menu-title">관련 업무</h3>
        <div className="related-list">
          {menus.map(menu => (
            <button key={menu.id} onClick={() => onNavigate(menu.id)}>
              <menu.icon size={16}/><span>{menu.label}로 이동</span><ArrowUpRight size={14}/>
            </button>
          ))}
        </div>
      </section>
      {screen === 'docs' && devDocs && <section className="related-section" aria-labelledby="related-devdocs-title">
        <h3 id="related-devdocs-title">개발문서</h3>
        {devDocs.docs.length ? <div className="related-list">{devDocs.docs.map(d => (
          <button key={d.name} className={d.name === devDocs.current ? 'docs-current' : ''} title={d.name}
            aria-current={d.name === devDocs.current ? 'page' : undefined} onClick={() => devDocs.onSelect(d.name)}>
            <FileText size={16}/><span>{d.title || d.name}</span>
          </button>
        ))}</div> : <p className="related-empty">문서 목록을 불러오면 여기에 표시됩니다.</p>}
        {devDocs.toc.length > 0 && <>
          <h3 id="related-toc-title">현재 문서 목차</h3>
          <nav className="related-toc" aria-labelledby="related-toc-title">{devDocs.toc.filter(t => t.level <= 3).map(t => (
            <button key={t.id} style={{paddingLeft: 6 + (t.level - 1) * 10}}
              onClick={() => document.getElementById(t.id)?.scrollIntoView({block: 'start'})}>{t.text}</button>
          ))}</nav>
        </>}
      </section>}
      {screen !== 'docs' && <section className="related-section" aria-labelledby="related-documents-title">
        <h3 id="related-documents-title">선택한 문서</h3>
        {docs.length ? <div className="related-list">{docs.map(doc => (
          <a key={doc.id} href={'/api/documents/' + encodeURIComponent(doc.id)} target="_blank" rel="noreferrer">
            <FileText size={16}/><span>{doc.name}</span><ArrowUpRight size={14}/>
          </a>
        ))}</div> : <p className="related-empty">목록에서 문서나 결과를 선택하면 저장된 원문 링크가 여기에 표시됩니다.</p>}
      </section>}
      {resultId && <section className="related-section" aria-labelledby="related-result-title">
        <h3 id="related-result-title">비교 결과 파일</h3>
        <div className="related-list"><a href={'/api/results/' + encodeURIComponent(resultId) + '/csv'} download>
          <FileText size={16}/><span>현재 결과 CSV 내려받기</span><ArrowUpRight size={14}/>
        </a></div>
      </section>}
      {screen === 'settings' && /^https:\/\//.test(site) && <section className="related-section" aria-labelledby="related-site-title">
        <h3 id="related-site-title">사이트</h3>
        <div className="related-list"><a href={site} target="_blank" rel="noreferrer">
          <Link2 size={16}/><span>그룹웨어 사이트 열기</span><ArrowUpRight size={14}/>
        </a></div>
        <p className="related-empty">자동 작업용 전용 브라우저는 본문의 버튼으로 여세요.</p>
      </section>}
      <p className="related-footnote">다운로드·대조·상신은 왼쪽 업무 화면의 버튼에서 실행합니다.</p>
    </aside>
  );
}
