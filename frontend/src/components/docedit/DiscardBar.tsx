/**
 * [파일 역할] 문서 편집 중 창을 닫으려 할 때 "변경 내용을 버릴까요?"를 창 안에서 묻는 확인 줄.
 * 브라우저 confirm 대화상자는 쓰지 않는다(공용 Modal의 포커스 트랩·자동 검증과 충돌하므로).
 * StatementModal·ExpenseModal이 편집 단계에서 변경이 있을 때만 이 줄을 보여 준다.
 */
import {useEffect, useRef} from 'react';
import {AlertTriangle} from 'lucide-react';

/**
 * [기능명세] DiscardBar
 * 목적: 저장되지 않은 편집 내용을 버리고 닫을지 사람에게 확인한다.
 * 입력: onKeep(계속 편집), onDiscard(버리고 닫기)
 * 출력: role=alert 확인 줄 JSX
 * 처리 규칙: 나타나면 "계속 편집" 버튼에 포커스를 둔다(Enter 한 번으로 실수로 버리지 않게).
 * 예외·실패 조건: 없음
 * 부수효과: 마운트 시 DOM 포커스 이동
 */
export function DiscardBar({onKeep, onDiscard}: {onKeep: () => void; onDiscard: () => void}) {
  const keep = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    keep.current?.focus();
  }, []);
  return (
    <div role="alert" className="alert amber doc-discard" data-testid="doc-discard">
      <AlertTriangle size={17}/>
      <span>편집한 내용이 사라집니다. 닫을까요?</span>
      <button className="secondary" ref={keep} onClick={onKeep}>계속 편집</button>
      <button className="secondary" onClick={onDiscard}>버리고 닫기</button>
    </div>
  );
}
