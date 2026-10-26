/**
 * [파일 역할] 전송 전 문서 편집 3단 화면: 좌 마크다운 원문 / 중 워드형 편집(TipTap) / 우 목차 + 안내 슬롯.
 * 단일 원천: 마크다운 문자열 하나(state md). 좌 입력과 중 편집이 모두 md 를 갱신하고 onChange 로 부모에 올린다.
 *   중 편집기는 md 가 자신이 만든 값과 다를 때만 내용을 교체한다(WysiwygPane 참고).
 * 반응형: 760px 이하(matchMedia)에서는 3열 대신 탭 3개(마크다운/문서/목차)로 한 번에 하나만 보인다.
 *   숨겨진 단도 마운트를 유지해 TipTap 상태·스크롤이 사라지지 않는다.
 * 높이는 부모(.doc-edit-modal 등)가 정하며 .doc-editor 가 height:100% 로 채운다.
 */
import {useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode} from 'react';
import MarkdownPane, {type MarkdownPaneHandle} from './MarkdownPane';
import WysiwygPane, {type WysiwygPaneHandle} from './WysiwygPane';
import TocPane from './TocPane';
import {extractToc, type TocItem} from './toc';
import './docedit.css';

/** [타입 명세] DocEditorProps — markdown 초기값(외부에서 바뀌면 반영), onChange 편집 결과 알림, sideInfo 목차 아래 읽기 전용 안내, disabled 읽기 전용, testIdPrefix data-testid 접두어(기본 doc-editor). */
export type DocEditorProps = {
  markdown: string;
  onChange: (md: string) => void;
  sideInfo?: ReactNode;
  disabled?: boolean;
  testIdPrefix?: string;
};

/** [상수 명세] NARROW_QUERY — 탭 모드로 전환하는 폭 조건(CSS 미디어쿼리와 같은 값). */
const NARROW_QUERY = '(max-width: 760px)';

/** [상수 명세] TABS — 탭 순서·식별자·이름. */
const TABS = [
  {id: 'md', label: '마크다운'},
  {id: 'doc', label: '문서'},
  {id: 'toc', label: '목차'},
] as const;
type TabId = typeof TABS[number]['id'];

/**
 * [기능명세] useNarrow
 * 목적: 화면 폭이 760px 이하인지 구독한다. 입력: 없음. 출력: boolean.
 * 처리: matchMedia 변경 이벤트로 갱신. matchMedia 가 없으면 false. 부수효과: 이벤트 리스너 등록·해제.
 */
function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => typeof window.matchMedia === 'function' && window.matchMedia(NARROW_QUERY).matches);
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const mq = window.matchMedia(NARROW_QUERY);
    const on = () => setNarrow(mq.matches);
    on();
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, []);
  return narrow;
}

/**
 * [기능명세] DocEditor
 * 목적: 마크다운 문서를 좌·중 양방향 동기화로 편집하고 목차로 이동하는 3단 화면을 그린다.
 * 입력: DocEditorProps. 출력: div.doc-editor JSX(탭 모드에서는 tablist + 한 단).
 * 처리 규칙:
 *   - md state 가 단일 원천. markdown prop 이 내부 값(mdRef)과 다를 때만 md 를 교체한다.
 *   - 좌 입력/중 편집 → md 갱신 + onChange(md). 목차는 md 에서 extractToc 로 계산(useMemo).
 *   - 목차 클릭 → 좌는 item.line, 중은 item.index 로 스크롤. 탭 모드에서는 문서 탭으로 전환한 뒤 다음 프레임에 스크롤한다.
 *   - 활성 목차 항목: 좌 편집기 커서 줄 이전의 마지막 제목.
 *   - 탭 키보드: 좌우 방향키·Home·End 로 이동(roving tabindex), 선택 즉시 표시.
 *   - disabled 면 두 편집기 모두 읽기 전용.
 * 예외: 없음(편집기 내부 예외는 각 단에서 처리). 부수효과: onChange 호출, requestAnimationFrame 스크롤.
 */
export default function DocEditor({markdown, onChange, sideInfo, disabled, testIdPrefix}: DocEditorProps) {
  const prefix = testIdPrefix ?? 'doc-editor';
  const narrow = useNarrow();
  const [md, setMd] = useState(markdown);
  const mdRef = useRef(markdown);
  const [caretLine, setCaretLine] = useState(0);
  const [tab, setTab] = useState<TabId>('doc');
  const mdPane = useRef<MarkdownPaneHandle>(null);
  const docPane = useRef<WysiwygPaneHandle>(null);
  const tabButtons = useRef<Record<string, HTMLButtonElement | null>>({});
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  /** [효과 명세] 외부 markdown prop 반영: 내부 보유 값과 다를 때만 교체한다(자기 onChange 의 되돌림은 무시). */
  useEffect(() => {
    if (markdown !== mdRef.current) { mdRef.current = markdown; setMd(markdown); }
  }, [markdown]);

  /**
   * [기능명세] update
   * 목적: 편집 결과를 단일 원천에 반영하고 부모에 알린다. 입력: next(새 마크다운). 출력: 없음.
   * 처리: 내부 값과 같으면 무시(중복 알림 방지). 부수효과: state·ref 갱신, onChange 호출.
   */
  const update = useCallback((next: string) => {
    if (next === mdRef.current) return;
    mdRef.current = next;
    setMd(next);
    onChangeRef.current(next);
  }, []);

  const toc = useMemo(() => extractToc(md), [md]);
  const activeIndex = useMemo(() => {
    let found = -1;
    for (const t of toc) if (t.line <= caretLine) found = t.index;
    return found;
  }, [toc, caretLine]);

  /**
   * [기능명세] pickToc
   * 목적: 목차 항목 위치로 좌·중 편집기를 스크롤한다. 입력: item. 출력: 없음.
   * 처리: 캐럿 줄을 항목 줄로 설정(활성 표시). 탭 모드면 문서 탭으로 전환 후 rAF 에서 스크롤, 아니면 즉시 스크롤.
   * 부수효과: 상태 갱신, 두 편집기 스크롤 위치 변경.
   */
  const pickToc = (item: TocItem) => {
    setCaretLine(item.line);
    const go = () => { mdPane.current?.scrollToLine(item.line); docPane.current?.scrollToHeading(item.index); };
    if (narrow) {
      setTab('doc');
      requestAnimationFrame(() => requestAnimationFrame(go));
    } else go();
  };

  /**
   * [기능명세] onTabKey
   * 목적: 탭 목록의 방향키 이동을 처리한다. 입력: 키보드 이벤트. 출력: 없음.
   * 처리: ←/→ 순환, Home/End 처음·끝. 그 밖의 키는 무시. 부수효과: 탭 상태 변경과 새 탭 버튼 포커스.
   */
  const onTabKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const at = TABS.findIndex(t => t.id === tab);
    let to = -1;
    if (e.key === 'ArrowRight') to = (at + 1) % TABS.length;
    else if (e.key === 'ArrowLeft') to = (at - 1 + TABS.length) % TABS.length;
    else if (e.key === 'Home') to = 0;
    else if (e.key === 'End') to = TABS.length - 1;
    if (to < 0) return;
    e.preventDefault();
    setTab(TABS[to].id);
    tabButtons.current[TABS[to].id]?.focus();
  };

  const hide = (id: TabId) => narrow && tab !== id;

  return (
    <div className="doc-editor" data-testid={prefix} data-mode={narrow ? 'tabs' : 'columns'}>
      {narrow && (
        <div className="doc-tabs" role="tablist" aria-label="편집 화면 선택" onKeyDown={onTabKey}>
          {TABS.map(t => (
            <button key={t.id} type="button" role="tab" id={`${prefix}-tab-${t.id}`} aria-selected={tab === t.id}
              aria-controls={`${prefix}-panel-${t.id}`} tabIndex={tab === t.id ? 0 : -1} data-testid={`${prefix}-tab-${t.id}`}
              className={`doc-tab${tab === t.id ? ' active' : ''}`} ref={el => { tabButtons.current[t.id] = el; }}
              onClick={() => setTab(t.id)}>{t.label}</button>
          ))}
        </div>
      )}
      <div className="doc-panes">
        <MarkdownPane ref={mdPane} value={md} onChange={update} onCaretLine={setCaretLine} disabled={disabled}
          testId={`${prefix}-md`} role={narrow ? 'tabpanel' : 'region'} hidden={hide('md')} />
        <WysiwygPane ref={docPane} value={md} onChange={update} disabled={disabled}
          testId={`${prefix}-wysiwyg`} role={narrow ? 'tabpanel' : 'region'} hidden={hide('doc')} />
        <TocPane items={toc} activeIndex={activeIndex} onPick={pickToc} sideInfo={sideInfo}
          testId={`${prefix}-toc`} role={narrow ? 'tabpanel' : 'navigation'} hidden={hide('toc')} />
      </div>
    </div>
  );
}
