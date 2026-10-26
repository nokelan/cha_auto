/**
 * [파일 역할] 서버 호출 공통 함수와 화면 전체가 공유하는 상수·표시 함수.
 * - api: 동일 출처 /api JSON 호출과 오류 메시지 변환
 * - stamp/display: 시각·비교값을 화면 문자열로 변환
 * - STATUS: 비교 판정 문자열(서버 compare.py가 내는 값과 같아야 함. types.ts의 Judgement와 짝)
 * - LOCAL_STATUS: 로컬 세금계산서 대조의 추가 판정('계약서 없음')과 화면 전용 '대조 전'
 * - EDIT_FIELDS: 계산서 추출값 보정 항목과 라벨
 */
import type {Judgement, LocalJudgement, State} from './types';

/** [상수 명세] STATUS — 서버가 돌려주는 판정 문자열. 화면 문구와 색상 판정에 함께 쓴다. */
export const STATUS = {MATCH: '일치', MISMATCH: '불일치', CHECK: '확인 필요', FAILED: '처리 실패'} as const satisfies Record<string, Judgement>;

/** [상수 명세] STATUS_ORDER — 결과 요약 카운트에 표시하는 판정 순서. */
export const STATUS_ORDER: Judgement[] = [STATUS.MATCH, STATUS.MISMATCH, STATUS.CHECK, STATUS.FAILED];

/**
 * [상수 명세] LOCAL_STATUS — '로컬 세금계산서 대조'에만 쓰는 추가 판정 문자열.
 * NONE은 서버(saebom/local_audit)가 웹 계약 후보가 0건일 때 내는 값이고,
 * PENDING은 아직 대조하지 않은 파일(또는 폴더가 바뀐 뒤의 파일)에 화면이 붙이는 표시용 값이다(서버는 내지 않음).
 */
export const LOCAL_STATUS = {NONE: '계약서 없음', PENDING: '대조 전'} as const;

/** [상수 명세] LOCAL_STATUS_ORDER — 로컬 대조 요약 카운트에 표시하는 판정 순서(STATUS_ORDER + 계약서 없음). */
export const LOCAL_STATUS_ORDER: LocalJudgement[] = [...STATUS_ORDER, LOCAL_STATUS.NONE];

/** [상수 명세] EMPTY_STATE — 첫 조회 전 화면이 쓰는 빈 서버 상태. */
export const EMPTY_STATE: State = {mails: [], contracts: [], jobs: [], synced: null, data_dir: '', document_root: '', site: ''};

/**
 * [상수 명세] EDIT_FIELDS
 * 보정 가능한 계산서 필드 키와 입력 라벨. 키 순서가 보정 폼의 표시 순서다.
 * 서버 correct API가 허용하는 필드와 같아야 한다.
 */
export const EDIT_FIELDS: Record<string, string> = {
  partner: '업체명',
  biz: '사업자등록번호',
  supply: '공급가액',
  vat: '부가세',
  total: '합계액',
  month: '청구 월 (YYYY-MM)',
  percent: '분할 비율 (%)',
  installment: '분할 차수',
};

/** [상수 명세] NUMERIC_EDIT_FIELDS — 보정 요청 때 Number로 바꿔 보내는 필드. */
export const NUMERIC_EDIT_FIELDS = ['supply', 'vat', 'total', 'percent', 'installment'];

/**
 * [기능명세] api
 * 목적: 로컬 API JSON 호출 공통 함수
 * 입력: path: /api/ 뒤 경로, body: 선택 JSON, method: 본문이 있을 때 사용할 HTTP 메서드(기본 POST)
 * 출력: Promise<T>; 응답 JSON
 * 처리/실패: 본문이 없으면 GET, 있으면 JSON 요청. 실패 응답의 detail 문자열을 Error 메시지로 던진다
 *   (예: 로그인 잠금 429의 "…초 후 다시 시도해 주세요."). detail이 없거나 문자열이 아니면 일반 안내 문구.
 *   fetch 자체가 실패(서버 종료 등 TypeError)하면 영문 'Failed to fetch' 대신 한글 연결 안내 문구를 던진다.
 *   auth/status·auth/login 이외 경로가 401이면 인증이 풀린 것이므로 'saebom:unauthorized' 이벤트를
 *   (재인증 전까지) 한 번만 보내고 한글 안내 오류를 던진다. auth/* 의 401은 기존대로 서버 detail(오답 안내)을 던진다.
 * 부수효과: fetch 네트워크 요청, 401 시 window 이벤트 1회 발송(unauthorizedSent 플래그).
 *   auth/login 성공 시 플래그를 해제한다. 상태 변경·오류 표시는 호출자가 담당
 */
export async function api<T>(path: string, body?: unknown, method = 'POST'): Promise<T> {
  const init: RequestInit = body === undefined
    ? {}
    : {method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)};
  let r: Response;
  try {
    r = await fetch('/api/' + path, init);
  } catch {
    throw Error('서버에 연결할 수 없습니다. 프로그램이 실행 중인지 확인해 주세요.');
  }
  if (r.status === 401 && !path.startsWith('auth/')) {
    if (!unauthorizedSent) {
      unauthorizedSent = true;
      window.dispatchEvent(new Event('saebom:unauthorized'));
    }
    throw Error('로그인이 만료되었습니다. 비밀번호를 다시 입력해 주세요.');
  }
  if (!r.ok) {
    const e = await r.json().catch(() => ({detail: '요청을 완료하지 못했습니다.'}));
    throw Error(typeof e.detail === 'string' ? e.detail : '입력값을 확인해 주세요.');
  }
  if (path === 'auth/login') unauthorizedSent = false;
  return r.json();
}

/** [상태 명세] unauthorizedSent — 401 이벤트를 연달아 보내지 않기 위한 모듈 플래그(auth/login 성공 때 해제). */
let unauthorizedSent = false;

/**
 * [기능명세] stamp
 * 목적: 동기화·결과 시각 표시
 * 입력: ISO 시각 또는 null
 * 출력: 한국어 월·일·시·분 문자열 또는 '아직 동기화하지 않음'
 * 처리/실패: Date와 ko-KR 로캘로 변환
 * 부수효과: 없음
 */
export const stamp = (s: string | null) =>
  s
    ? new Date(s).toLocaleString('ko-KR', {month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit'})
    : '아직 동기화하지 않음';

/**
 * [기능명세] display
 * 목적: 비교값 화면 표시
 * 입력: unknown 값
 * 출력: 표시 문자열
 * 처리/실패: null/undefined는 '미확인', 숫자는 천 단위 구분, 배열은 쉼표 연결, 그 외 String 변환
 * 부수효과: 없음
 */
export const display = (v: unknown): string =>
  v === null || v === undefined
    ? '미확인'
    : typeof v === 'number'
      ? v.toLocaleString('ko-KR')
      : Array.isArray(v)
        ? v.join(', ')
        : String(v);

/**
 * [기능명세] apiText
 * 목적: 로컬 API의 텍스트(마크다운) 본문 GET 호출. api<T>()가 JSON 전용이라 개발문서 열람용으로 추가했다.
 * 입력: path: /api/ 뒤 경로(이미 인코딩된 상태)
 * 출력: Promise<string> 응답 본문
 * 처리/실패: 연결 실패·401(잠금 화면 복귀 이벤트 발송)·기타 오류 처리는 api()와 같은 한글 오류 규칙을 따른다.
 * 부수효과: fetch 요청, 401 시 'saebom:unauthorized' 이벤트 1회 발송
 */
export async function apiText(path: string): Promise<string> {
  let r: Response;
  try {
    r = await fetch('/api/' + path);
  } catch {
    throw Error('서버에 연결할 수 없습니다. 프로그램이 실행 중인지 확인해 주세요.');
  }
  if (r.status === 401) {
    if (!unauthorizedSent) {
      unauthorizedSent = true;
      window.dispatchEvent(new Event('saebom:unauthorized'));
    }
    throw Error('로그인이 만료되었습니다. 비밀번호를 다시 입력해 주세요.');
  }
  if (!r.ok) {
    const e = await r.json().catch(() => ({detail: '문서를 불러오지 못했습니다.'}));
    throw Error(typeof e.detail === 'string' ? e.detail : '문서를 불러오지 못했습니다.');
  }
  return r.text();
}
