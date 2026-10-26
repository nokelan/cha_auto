/**
 * [파일 역할] 앱의 모든 확인·입력·원문 창이 공유하는 모달 틀.
 * 공통 규칙: document.body 포털 / role=dialog·aria-modal·aria-labelledby / Esc로 닫기(닫기 불가 상태에서는 무시) /
 *   Tab 포커스 트랩 / 열려 있는 동안 본문 스크롤 잠금(닫으면 원래 값 복원) / 닫을 때 연 요소로 포커스 복귀 /
 *   배경 클릭으로는 닫지 않음(입력 중인 값을 잃지 않도록).
 * 모양은 style.css에서 불러오는 modal-base.css의 .modal-backdrop·.modal 클래스를 쓴다. 모달이 겹쳐 열리면 맨 위 모달만 키보드를 처리한다.
 */
import {useEffect, useRef, type ReactNode, type RefObject} from 'react';
import {createPortal} from 'react-dom';
import './modal.css';

/** [상수 명세] FOCUSABLE — 포커스 트랩이 순환 대상으로 삼는 요소 선택자(비활성·tabindex=-1 제외). */
const FOCUSABLE = 'button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),a[href],[tabindex]:not([tabindex="-1"])';

/** [상태 명세] openModals — 열려 있는 모달의 식별자 스택. 마지막 항목만 Esc·Tab을 처리한다. */
const openModals: symbol[] = [];

/**
 * [기능명세] Modal
 * 목적: 포털·접근성 속성·키보드·스크롤·포커스 규칙을 갖춘 공용 모달 틀을 그린다.
 * 입력: labelledBy(제목 요소 id, 필수), onClose(Esc 닫기 요청. 부모가 상태를 바꿔 언마운트한다),
 *   closable(false면 Esc를 무시. 요청 진행 중 등. 기본 true), className(section에 덧붙일 클래스),
 *   testId(data-testid), initialFocus(열 때 포커스할 요소 ref. 없으면 대화상자 자체),
 *   returnFocus(닫을 때 포커스를 돌려줄 요소 ref. 모달을 열기 전에 버튼이 잠시 비활성화돼 포커스를 잃는 경우에 쓴다. 없으면 열릴 때의 포커스 요소),
 *   dialogRef(부모가 대화상자 DOM이 필요할 때 넘기는 ref), children(header·본문·버튼줄).
 * 출력: document.body 포털의 backdrop > section.modal[role=dialog] JSX.
 * 처리/실패:
 *   - 열릴 때 직전 포커스 요소와 body overflow를 보관하고 body를 overflow:hidden으로 잠근 뒤 포커스를 옮긴다.
 *   - Escape: 맨 위 모달이고 closable이 true일 때만 onClose 호출.
 *   - Tab/Shift+Tab: 대화상자 안의 보이는 포커스 가능 요소 사이를 순환한다. 없으면 대화상자 자체에 머문다.
 *     포커스가 대화상자 밖이거나 대화상자 자체에 있으면 첫/마지막 요소로 들어온다.
 *   - 배경(backdrop) 클릭은 처리하지 않는다.
 *   - 닫히면(언마운트) 스크롤 잠금을 보관한 값으로 되돌리고, returnFocus 요소(없으면 연 요소)가 아직 문서에 있으면 포커스를 돌려준다.
 * 부수효과: document keydown 리스너, body 스타일·포커스 변경(정리 시 복원), 모달 스택 갱신.
 */
export function Modal({labelledBy, onClose, closable = true, className = '', testId, initialFocus, returnFocus, dialogRef, children}: {
  labelledBy: string;
  onClose: () => void;
  closable?: boolean;
  className?: string;
  testId?: string;
  initialFocus?: RefObject<HTMLElement | null>;
  returnFocus?: RefObject<HTMLElement | null>;
  dialogRef?: RefObject<HTMLElement | null>;
  children: ReactNode;
}) {
  const ownRef = useRef<HTMLElement>(null);
  const dialog = dialogRef ?? ownRef;
  /** 최신 onClose·closable(키보드 리스너를 다시 등록하지 않으려고 ref로 보관). */
  const latest = useRef({onClose, closable});
  latest.current = {onClose, closable};
  /** 처음 포커스 대상 ref(마운트 시점 값만 사용). */
  const focusTarget = useRef(initialFocus);
  /** 닫을 때 포커스를 돌려줄 요소 ref(마운트 시점 값만 사용). */
  const returnTarget = useRef(returnFocus);

  /**
   * [효과 명세] 열기·닫기 수명
   * 처리: 마운트 때 직전 포커스·body overflow를 보관하고 스크롤을 잠근 뒤 처음 포커스를 옮기며 keydown 리스너를 등록한다.
   * 부수효과/정리: 정리 때 리스너·스택 항목을 제거하고 overflow를 복원하며 연 요소로 포커스를 돌려준다
   *   (연 요소가 사라졌으면 복귀하지 않음).
   */
  useEffect(() => {
    const id = Symbol('modal');
    openModals.push(id);
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    (focusTarget.current?.current ?? dialog.current)?.focus();

    /** [기능명세] onKey: keydown을 받아 맨 위 모달에서만 Esc 닫기와 Tab 순환을 처리한다. 출력 없음, 서버 요청 없음. */
    const onKey = (event: KeyboardEvent) => {
      if (openModals[openModals.length - 1] !== id) return;
      if (event.key === 'Escape') {
        if (latest.current.closable) latest.current.onClose();
        return;
      }
      if (event.key !== 'Tab') return;
      const root = dialog.current;
      if (!root) return;
      const nodes = Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(el => el.getClientRects().length > 0);
      if (!nodes.length) {
        event.preventDefault();
        root.focus();
        return;
      }
      const firstNode = nodes[0], lastNode = nodes[nodes.length - 1];
      const active = document.activeElement;
      if (!root.contains(active) || active === root) {
        event.preventDefault();
        (event.shiftKey ? lastNode : firstNode).focus();
      } else if (event.shiftKey && active === firstNode) {
        event.preventDefault();
        lastNode.focus();
      } else if (!event.shiftKey && active === lastNode) {
        event.preventDefault();
        firstNode.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      const at = openModals.indexOf(id);
      if (at >= 0) openModals.splice(at, 1);
      document.body.style.overflow = overflow;
      const back = returnTarget.current?.current;
      if (back?.isConnected) back.focus();
      else if (previous?.isConnected) previous.focus();
    };
  }, []);

  return createPortal(
    <div className="modal-backdrop">
      <section ref={dialog} tabIndex={-1} className={('modal ' + className).trim()} role="dialog" aria-modal="true"
        aria-labelledby={labelledBy} data-testid={testId}>
        {children}
      </section>
    </div>,
    document.body,
  );
}
