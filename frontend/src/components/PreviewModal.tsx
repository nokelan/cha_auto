/**
 * [파일 역할] 세금계산서(왼쪽)와 계약서(오른쪽) PDF를 나란히 띄우는 원문 보기 모달.
 * 창 틀(포털·dialog·Esc·포커스 트랩·스크롤 잠금·포커스 복귀)은 공용 Modal이 담당한다.
 */
import {X} from 'lucide-react';
import type {Preview} from '../types';
import {Modal} from './Modal';
import {Pdf} from './Pdf';

/**
 * [기능명세] PreviewModal
 * 목적: 원문 나란히 보기
 * 입력: preview(두 문서와 처음 열 페이지), onClose(닫기 요청)
 * 출력: 공용 Modal(role=dialog, 포털) JSX. 각 문서는 독립된 Pdf 뷰어(페이지·배율 상태 별도)
 * 처리/실패: 페이지가 없으면 Pdf가 1페이지로 연다. PDF 오류는 각 뷰어가 표시한다
 * 부수효과: 닫기 버튼과 Esc가 onClose를 호출한다(상태 변경은 호출자 담당. 배경 클릭으로는 닫지 않음)
 */
export function PreviewModal({preview, onClose}: {preview: Preview; onClose: () => void}) {
  return (
    <Modal labelledBy="preview-title" className="pdf-modal" onClose={onClose}>
        <header>
          <div>
            <h2 id="preview-title">원문 나란히 보기</h2>
            <p>왼쪽 세금계산서 · 오른쪽 계약서</p>
          </div>
          <button className="icon-btn" aria-label="원문 보기 닫기" onClick={onClose}><X size={22}/></button>
        </header>
        <div className="pdf-pair">
          <Pdf doc={preview.invoice} initialPage={preview.invoicePage}/>
          <Pdf doc={preview.contract} initialPage={preview.contractPage}/>
        </div>
    </Modal>
  );
}
