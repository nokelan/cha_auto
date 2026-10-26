/**
 * [파일 역할] 현재 비교 행의 계산서 추출값을 사용자가 보정하는 입력 모달.
 * 보정값은 서버에서 새 비교 이력으로 저장되며 원본 PDF는 바뀌지 않는다.
 * 창 틀(포털·dialog·Esc·포커스 트랩·스크롤 잠금·포커스 복귀)은 공용 Modal이 담당한다.
 */
import {X} from 'lucide-react';
import {EDIT_FIELDS} from '../api';
import {Modal} from './Modal';

type Props = {
  edits: Record<string, string>;
  busy: boolean;
  onChange: (key: string, value: string) => void;
  onClose: () => void;
  onSubmit: () => void;
  /** 보정 요청 실패 문구(모달이 상단 오류 배너를 가리므로 모달 안에도 표시). 없으면 표시하지 않음. */
  error?: string;
};

/**
 * [기능명세] EditModal
 * 목적: 계산서 추출값 보정 폼
 * 입력: edits(필드별 입력 문자열), busy(작업 중이면 재비교 버튼 비활성),
 *   onChange(필드 입력 변경), onClose(취소·닫기), onSubmit(보정값으로 재비교), error(선택: 요청 실패 문구)
 * 출력: EDIT_FIELDS 순서의 입력 필드와 취소/재비교 버튼을 가진 공용 Modal(role=dialog, 포털) JSX
 * 처리/실패: 값이 없는 필드는 빈 입력으로 표시. 변경 감지·숫자 변환·요청은 onSubmit 쪽이 담당.
 *   error가 있으면 입력 아래에 role=alert 오류를 보여 준다(입력값은 유지됨)
 *   Esc는 취소와 같다(배경 클릭으로는 닫지 않음). 열면 대화상자에 포커스가 가고 닫으면 연 버튼으로 돌아간다(Modal)
 * 부수효과: 없음(콜백 호출만)
 */
export function EditModal({edits, busy, onChange, onClose, onSubmit, error}: Props) {
  return (
    <Modal labelledBy="edit-title" className="edit-modal" onClose={onClose}>
        <header>
          <div>
            <h2 id="edit-title">계산서 추출값 보정</h2>
            <p>수정값은 새 비교 이력으로 저장되며 원본 PDF는 변경되지 않습니다.</p>
          </div>
          <button className="icon-btn" aria-label="보정 닫기" onClick={onClose}><X size={20}/></button>
        </header>
        <div className="edit-fields">
          {Object.entries(EDIT_FIELDS).map(([k, label]) => (
            <label key={k}>
              {label}
              <input value={edits[k] || ''} onChange={e => onChange(k, e.target.value)}/>
            </label>
          ))}
        </div>
        {error && <div role="alert" className="alert error" data-testid="edit-error">{error}</div>}
        <div className="modal-actions">
          <button className="secondary" onClick={onClose}>취소</button>
          <button className="primary" disabled={busy} onClick={onSubmit}>보정값으로 재비교</button>
        </div>
    </Modal>
  );
}
