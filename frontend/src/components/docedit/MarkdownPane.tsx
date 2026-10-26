/**
 * [파일 역할] 3단 문서 편집 화면의 좌측 단: 마크다운 원문을 고정폭 textarea 로 편집한다.
 * 처리 흐름: 부모(DocEditor)가 준 value 를 그대로 보여 주고, 입력·커서 이동을 부모에 알린다.
 *   목차 클릭 시 부모가 ref 의 scrollToLine 을 불러 해당 줄이 보이도록 스크롤한다.
 * 줄 높이를 CSS 에서 px 로 고정하고 줄바꿈을 끄므로(wrap=off) 줄 번호 × 줄 높이로 위치를 정확히 계산한다.
 */
import {forwardRef, useImperativeHandle, useRef} from 'react';

/** [타입 명세] MarkdownPaneHandle — 부모가 쓰는 명령형 핸들. scrollToLine(line): 0부터 시작하는 줄이 보이게 스크롤. */
export type MarkdownPaneHandle = {scrollToLine: (line: number) => void};

/** [타입 명세] MarkdownPaneProps — value 원문, onChange 입력 알림, onCaretLine 커서가 있는 줄 알림, disabled 읽기 전용, testId 단 루트의 data-testid, role 접근성 역할(탭 모드에서 tabpanel). */
type MarkdownPaneProps = {
  value: string;
  onChange: (md: string) => void;
  onCaretLine: (line: number) => void;
  disabled?: boolean;
  testId: string;
  role: 'region' | 'tabpanel';
  hidden?: boolean;
};

/**
 * [기능명세] MarkdownPane
 * 목적: 마크다운 원문 편집 영역(좌측 단)을 그린다.
 * 입력: MarkdownPaneProps. 출력: div[role][aria-label="마크다운 편집"] > textarea[aria-label="마크다운 원문"] JSX.
 * 처리 규칙: 입력 시 onChange(새 값). 클릭·키 입력·선택 변경 시 커서 앞의 줄바꿈 수로 줄 번호를 계산해 onCaretLine 호출.
 *   disabled 면 readOnly(포커스·선택은 가능). hidden 이면 탭 모드에서 숨김(마운트는 유지해 값·스크롤 보존).
 * 예외: 없음. 부수효과: scrollToLine 호출 시 textarea 의 scrollTop·선택 범위 변경(포커스는 옮기지 않음).
 */
const MarkdownPane = forwardRef<MarkdownPaneHandle, MarkdownPaneProps>(function MarkdownPane(
  {value, onChange, onCaretLine, disabled, testId, role, hidden}, ref) {
  const area = useRef<HTMLTextAreaElement>(null);

  /**
   * [기능명세] reportCaret
   * 목적: 현재 커서가 몇 번째(0부터) 줄에 있는지 부모에 알린다. 입력: 없음(textarea 상태 사용). 출력: 없음.
   * 처리: selectionStart 앞 문자열의 \n 개수. 예외: textarea 가 없으면 무시. 부수효과: onCaretLine 호출.
   */
  const reportCaret = () => {
    const el = area.current;
    if (!el) return;
    const before = el.value.slice(0, el.selectionStart);
    onCaretLine(before.split('\n').length - 1);
  };

  useImperativeHandle(ref, () => ({
    /**
     * [기능명세] scrollToLine
     * 목적: 지정 줄이 textarea 위쪽 근처에 보이도록 스크롤하고 커서를 그 줄 처음에 둔다.
     * 입력: line(0부터). 출력: 없음. 처리: 줄 높이(computed line-height, 실패 시 20px) × 줄 번호 - 여백 8px 를 scrollTop 으로.
     *   줄 수보다 큰 값은 마지막 줄로 보정. 예외: textarea 가 숨김(display:none)이면 스크롤이 무시된다.
     * 부수효과: scrollTop·selection 변경(포커스 이동 없음).
     */
    scrollToLine(line: number) {
      const el = area.current;
      if (!el) return;
      const lines = el.value.split('\n');
      const target = Math.max(0, Math.min(line, lines.length - 1));
      const lh = parseFloat(getComputedStyle(el).lineHeight) || 20;
      el.scrollTop = Math.max(0, target * lh - 8);
      const offset = lines.slice(0, target).reduce((n, l) => n + l.length + 1, 0);
      el.setSelectionRange(offset, offset);
    },
  }), []);

  return (
    <div className="doc-pane doc-pane-md" role={role} aria-label="마크다운 편집" data-testid={testId} hidden={hidden}>
      <textarea ref={area} className="doc-md-textarea" aria-label="마크다운 원문" spellCheck={false} wrap="off"
        value={value} readOnly={disabled}
        onChange={e => { onChange(e.target.value); reportCaret(); }}
        onClick={reportCaret} onKeyUp={reportCaret} onSelect={reportCaret} />
    </div>
  );
});

export default MarkdownPane;
