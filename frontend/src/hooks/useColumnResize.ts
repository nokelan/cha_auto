/**
 * [파일 역할] 3단 비교 화면(기업 목록 · 문서 연결 · 비교 결과)의 단 너비 상태와 경계선 조작 훅.
 * 너비는 퍼센트 단위 [첫째 단, 둘째 단]이며 셋째 단은 나머지다. 화면 상태일 뿐 저장하지 않는다.
 */
import {useRef, useState, type HTMLAttributes, type KeyboardEvent, type PointerEvent} from 'react';

/** [상수 명세] DEFAULT_WIDTHS — 초기·'단 너비 초기화' 시 첫째/둘째 단 비율(%). */
export const DEFAULT_WIDTHS = [27, 32];

/**
 * [기능명세] useColumnResize
 * 목적: 단 너비 상태와 경계선(separator) 키보드·포인터 조작 제공
 * 입력: 없음
 * 출력: {widths, workspaceRef(3단 컨테이너 ref, 드래그 비율 계산용), resize, reset, dividerProps}
 * 처리/실패: 최소 너비(첫째 20%, 둘째 22%, 셋째 27%)를 지키도록 값을 제한한다
 * 부수효과: widths 상태 변경, 드래그 중 포인터 캡처. DB·localStorage에 저장하지 않음
 */
export function useColumnResize() {
  const [widths, setWidths] = useState<number[]>(DEFAULT_WIDTHS);
  const workspaceRef = useRef<HTMLDivElement>(null);
  /** 드래그 시작 시점의 경계 번호·포인터 x·너비. 이동량은 이 기준값에서 계산한다. */
  const drag = useRef<{index: number; x: number; widths: number[]} | null>(null);

  /**
   * [기능명세] resize
   * 목적: 3단 화면 비율 변경
   * 입력: index: 경계 0(1·2단 사이)/1(2·3단 사이), delta: 퍼센트 변화량, base: 기준 비율(기본 현재값)
   * 출력: void
   * 처리/실패: 경계 0은 1·2단이 서로 주고받으며(1단≥20, 2단≥22),
   *   경계 1은 2단만 늘이고 줄인다(2단≥22, 3단≥27)
   * 부수효과: widths 상태 변경
   */
  const resize = (index: number, delta: number, base = widths) => {
    const next = [...base];
    if (index === 0) {
      const d = Math.max(20 - base[0], Math.min(base[1] - 22, delta));
      next[0] += d;
      next[1] -= d;
    } else {
      next[1] = Math.max(22, Math.min(100 - base[0] - 27, base[1] + delta));
    }
    setWidths(next);
  };

  /** [기능명세] reset — 단 너비를 DEFAULT_WIDTHS로 되돌린다. 부수효과: widths 변경. */
  const reset = () => setWidths(DEFAULT_WIDTHS);

  /**
   * [기능명세] dividerProps
   * 목적: 키보드·포인터로 조절 가능한 경계선 div에 펼쳐 넣을 속성 생성
   * 입력: index: 경계 번호(0: '기업 목록 너비 조정', 1: '비교 영역 너비 조정')
   * 출력: role=separator·aria 값·이벤트 처리기를 담은 HTMLAttributes
   * 처리/실패: 좌우 방향키는 2%씩, 포인터 드래그는 3단 컨테이너 전체 폭 대비 비율로 조정.
   *   포인터를 놓거나 취소하면 드래그 참조를 비운다
   * 부수효과: 포인터 캡처·drag 참조·widths 변경
   */
  const dividerProps = (index: number): HTMLAttributes<HTMLDivElement> => ({
    role: 'separator',
    tabIndex: 0,
    'aria-label': index === 0 ? '기업 목록 너비 조정' : '비교 영역 너비 조정',
    'aria-orientation': 'vertical',
    'aria-valuemin': index === 0 ? 20 : 22,
    'aria-valuemax': index === 0 ? widths[0] + widths[1] - 22 : 100 - widths[0] - 27,
    'aria-valuenow': Math.round(widths[index]),
    onKeyDown: (e: KeyboardEvent<HTMLDivElement>) => {
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        e.preventDefault();
        resize(index, e.key === 'ArrowLeft' ? -2 : 2);
      }
    },
    onPointerDown: (e: PointerEvent<HTMLDivElement>) => {
      e.currentTarget.setPointerCapture(e.pointerId);
      drag.current = {index, x: e.clientX, widths: [...widths]};
    },
    onPointerMove: (e: PointerEvent<HTMLDivElement>) => {
      if (drag.current && workspaceRef.current) {
        resize(index, (e.clientX - drag.current.x) / workspaceRef.current.clientWidth * 100, drag.current.widths);
      }
    },
    onPointerUp: () => {
      drag.current = null;
    },
    onPointerCancel: () => {
      drag.current = null;
    },
  });

  return {widths, workspaceRef, resize, reset, dividerProps};
}

/** [자료형 명세] ColumnResize — useColumnResize 반환값(화면 컴포넌트 props용). */
export type ColumnResize = ReturnType<typeof useColumnResize>;
