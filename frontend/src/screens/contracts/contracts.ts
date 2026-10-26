/** [파일 역할] 계약 화면 구분 상수와 자료형. */
/** [상수 명세] KINDS — 가져오기 구분 select와 목록 구분 탭의 선택지. 서버 import API의 kind 값과 같다. */
export const KINDS = ['전체', '수입', '지출'] as const;
export type Kind = typeof KINDS[number];

/** [상수 명세] COMPARES — 목록의 문서비교 상태 필터 선택지. '미비교'는 compare가 null인 계약이다. */
export const COMPARES = ['전체', '미비교', '일치', '불일치', '확인 필요', '처리 실패'] as const;
export type CompareFilter = typeof COMPARES[number];

