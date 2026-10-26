/**
 * [파일 역할] 3단 문서 편집 화면의 가운데 단: TipTap 기반 워드형 편집기(흰 종이 바탕).
 * 처리 흐름: 마크다운 문자열을 TipTap 문서로 읽고(Markdown 확장, contentType markdown), 편집될 때마다
 *   getMarkdown() 으로 다시 직렬화해 부모에 올린다(150ms 디바운스).
 * 되먹임 방지: lastMd ref 에 "편집기와 마지막으로 주고받은 마크다운"을 보관한다. 부모가 준 value 가 lastMd 와 같으면
 *   setContent 를 하지 않아 커서가 튀지 않고, 다르면(좌 편집기 입력·외부 변경) emitUpdate:false 로 내용만 교체한다.
 * 제한: 제목 1~3단계, 목록, 굵게·기울임, 표(크기 조절 끔). 링크·밑줄은 끈다.
 */
import {forwardRef, useEffect, useImperativeHandle, useRef} from 'react';
import {EditorContent, useEditor} from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import {Markdown} from '@tiptap/markdown';
import {Table, TableCell, TableHeader, TableRow} from '@tiptap/extension-table';

/** [타입 명세] WysiwygPaneHandle — scrollToHeading(index): #~### 제목 중 n번째(0부터)가 보이도록 편집기 안에서 스크롤. */
export type WysiwygPaneHandle = {scrollToHeading: (index: number) => void};

/** [타입 명세] WysiwygPaneProps — value 마크다운, onChange 편집 결과(디바운스 후), disabled 읽기 전용, testId·role·hidden 루트 속성. */
type WysiwygPaneProps = {
  value: string;
  onChange: (md: string) => void;
  disabled?: boolean;
  testId: string;
  role: 'region' | 'tabpanel';
  hidden?: boolean;
};

/** [상수 명세] DEBOUNCE_MS — 중 편집 → 좌 반영 사이의 지연(입력 중 과도한 직렬화 방지). */
const DEBOUNCE_MS = 150;

/**
 * [기능명세] WysiwygPane
 * 목적: 마크다운을 워드 문서처럼 편집하는 TipTap 영역을 그린다.
 * 입력: WysiwygPaneProps. 출력: div[aria-label="문서 편집"] > 종이 div > EditorContent JSX.
 * 처리 규칙:
 *   - 편집 영역 DOM 은 tabindex=0·role=textbox·aria-label="문서 본문"(공용 Modal 의 Tab 순환 대상).
 *   - 편집(onUpdate) → 150ms 뒤 getMarkdown() → lastMd 갱신 → onChange. 대기 중 타이머는 새 편집 때 재설정, 언마운트 때 즉시 비움.
 *   - value 변경 → lastMd 와 같으면 무시, 다르면 대기 타이머를 취소하고 setContent(value,{contentType:'markdown', emitUpdate:false}).
 *   - disabled 변경 → setEditable(!disabled).
 * 예외: 마크다운 해석 실패는 TipTap 이 문단으로 처리한다(예외 없음). 직렬화 예외는 잡아 무시하고 이전 값을 유지한다.
 * 부수효과: 편집기 인스턴스 생성·파기, 타이머, DOM 스크롤(scrollToHeading).
 */
const WysiwygPane = forwardRef<WysiwygPaneHandle, WysiwygPaneProps>(function WysiwygPane(
  {value, onChange, disabled, testId, role, hidden}, ref) {
  /** 편집기와 마지막으로 주고받은 마크다운(되먹임 판단 기준). */
  const lastMd = useRef(value);
  const timer = useRef<number | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  const editor = useEditor({
    extensions: [
      StarterKit.configure({heading: {levels: [1, 2, 3, 4, 5, 6]}, link: false, underline: false}),
      Table.configure({resizable: false}), TableRow, TableHeader, TableCell,
      Markdown,
    ],
    content: value,
    contentType: 'markdown',
    editable: !disabled,
    editorProps: {
      attributes: {role: 'textbox', 'aria-label': '문서 본문', 'aria-multiline': 'true', tabindex: '0', class: 'doc-prose'},
    },
    onUpdate: ({editor: ed}) => {
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => {
        timer.current = null;
        try {
          const md = ed.getMarkdown();
          lastMd.current = md;
          onChangeRef.current(md);
        } catch { /* 직렬화 실패 시 이전 값을 유지한다 */ }
      }, DEBOUNCE_MS);
    },
  }, []);

  /** [효과 명세] 외부 value 반영: 편집기 내용과 다를 때만 교체(emitUpdate 끔). 대기 중인 편집 알림은 취소한다. */
  useEffect(() => {
    if (!editor || value === lastMd.current) return;
    if (timer.current !== null) { window.clearTimeout(timer.current); timer.current = null; }
    lastMd.current = value;
    editor.commands.setContent(value, {contentType: 'markdown', emitUpdate: false});
  }, [editor, value]);

  /** [효과 명세] 읽기 전용 전환. */
  useEffect(() => { editor?.setEditable(!disabled); }, [editor, disabled]);

  /** [효과 명세] 언마운트 시 대기 타이머 정리. */
  useEffect(() => () => { if (timer.current !== null) window.clearTimeout(timer.current); }, []);

  useImperativeHandle(ref, () => ({
    /**
     * [기능명세] scrollToHeading
     * 목적: 문서 안의 n번째 h1~h3 요소가 보이게 스크롤한다. 입력: index(0부터). 출력: 없음.
     * 예외: 편집기가 없거나 해당 순번이 없으면 무시. 부수효과: 가장 가까운 스크롤 영역의 scrollTop 변경.
     */
    scrollToHeading(index: number) {
      const heads = editor?.view.dom.querySelectorAll<HTMLElement>('h1,h2,h3');
      heads?.[index]?.scrollIntoView({block: 'start', behavior: 'auto'});
    },
  }), [editor]);

  return (
    <div className="doc-pane doc-pane-wysiwyg" role={role} aria-label="문서 편집" data-testid={testId} hidden={hidden}>
      <div className="doc-paper">
        <EditorContent editor={editor} />
      </div>
    </div>
  );
});

export default WysiwygPane;
