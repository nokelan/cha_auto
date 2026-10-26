/**
 * [파일 역할] catch 절에서 받은 unknown 오류를 화면 문구로 바꾸는 공용 함수.
 */

/**
 * [기능명세] errorMessage
 * 목적: `(e as Error).message` 캐스팅을 대신해 어떤 값이 던져져도 안전하게 문구를 얻는다.
 * 입력: e — catch 절의 unknown 값.
 * 출력: Error면 message, 문자열이면 그대로, 그 밖에는 String(e)로 만든 문구.
 * 처리/실패: 실패하지 않는다. api()가 던지는 한글 안내 Error를 그대로 통과시킨다.
 * 부수효과: 없음.
 */
export function errorMessage(e: unknown): string {
  if (e instanceof Error) return e.message;
  if (typeof e === 'string') return e;
  return String(e);
}
