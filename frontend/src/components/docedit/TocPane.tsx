/**
 * [파일 역할] 3단 문서 편집 화면의 우측 단: 목차(# ~ ###) 버튼 목록과 읽기 전용 안내(sideInfo) 슬롯.
 * 처리 흐름: 부모가 계산한 TocItem 목록을 level 에 따라 들여써 버튼으로 그리고, 클릭하면 onPick(item)을 부른다.
 */
import type {ReactNode} from 'react';
import type {TocItem} from './toc';

/** [타입 명세] TocPaneProps — items 목차, activeIndex 현재 위치한 제목 순번(없으면 -1), onPick 항목 클릭, sideInfo 목차 아래 안내 영역, testId·role 루트 속성. */
type TocPaneProps = {
  items: TocItem[];
  activeIndex: number;
  onPick: (item: TocItem) => void;
  sideInfo?: ReactNode;
  testId: string;
  role: 'navigation' | 'tabpanel';
  hidden?: boolean;
};

/**
 * [기능명세] TocPane
 * 목적: 목차 목록과 안내 슬롯을 그린다.
 * 입력: TocPaneProps. 출력: div[aria-label="목차"] JSX(목록 nav + sideInfo 영역).
 * 처리 규칙: 항목은 level 1~3 에 따라 클래스 toc-l1~l3 로 들여쓰고, activeIndex 항목은 aria-current="true"와 활성 스타일.
 *   항목이 없으면 "제목이 없습니다" 안내. sideInfo 가 있으면 구분선 아래 읽기 전용 영역으로 표시.
 * 예외: 없음. 부수효과: 클릭 시 onPick 호출만(스크롤은 부모가 처리).
 */
export default function TocPane({items, activeIndex, onPick, sideInfo, testId, role, hidden}: TocPaneProps) {
  return (
    <div className="doc-pane doc-pane-toc" role={role} aria-label="목차" data-testid={testId} hidden={hidden}>
      <h3 className="doc-toc-title">목차</h3>
      {items.length === 0 ? (
        <p className="doc-toc-empty">제목이 없습니다</p>
      ) : (
        <ul className="doc-toc-list">
          {items.map(item => (
            <li key={item.index}>
              <button type="button" className={`doc-toc-item toc-l${item.level}${item.index === activeIndex ? ' active' : ''}`}
                aria-current={item.index === activeIndex ? 'true' : undefined}
                title={item.text || '(제목 없음)'} onClick={() => onPick(item)}>
                {item.text || '(제목 없음)'}
              </button>
            </li>
          ))}
        </ul>
      )}
      {sideInfo ? <div className="doc-side-info" data-testid={`${testId}-side-info`}>{sideInfo}</div> : null}
    </div>
  );
}
