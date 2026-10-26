/**
 * [파일 역할] 화면 입력 문자열을 원(KRW) 단위 정수로 해석하는 공용 함수 모음.
 * 거래명세서 월금액(양의 정수)과 지출결의서 공급가액·부가세·합계(0 이상 정수)가 서로 다른 규칙을 쓰므로
 * 두 함수로 나누어 두며, 차이는 "0을 허용하는가" 한 가지뿐이다(나머지 규칙은 같다).
 * 입력 검사는 화면 편의용이며 서버가 다시 검증한다.
 */

/**
 * [기능명세] parseNonNegativeAmount
 * 목적: 원 금액 입력을 안전한 0 이상 정수로 해석한다(지출결의서 금액 입력용, 부가세 0원 허용).
 * 입력: text — 사용자가 입력한 문자열(쉼표·공백 허용).
 * 출력: 0 이상 안전 정수 또는 null.
 * 처리/실패: 쉼표·공백을 지운 뒤 숫자만 남아 있고 Number.isSafeInteger이면 정수, 그 밖(빈 값·음수·소수·문자·안전 범위 초과)은 null.
 * 부수효과: 없음.
 */
export function parseNonNegativeAmount(text: string): number | null {
  const value = text.replace(/[,\s]/g, '');
  if (!/^\d+$/.test(value)) return null;
  const number = Number(value);
  return Number.isSafeInteger(number) ? number : null;
}

/**
 * [기능명세] parsePositiveAmount
 * 목적: 원 금액 입력을 안전한 양의 정수로 해석한다(거래명세서 월금액 입력용, 0원 불가).
 * 입력: text — 사용자가 입력한 문자열(쉼표·공백 허용).
 * 출력: 1 이상 안전 정수 또는 null.
 * 처리/실패: parseNonNegativeAmount 결과가 0이거나 null이면 null.
 * 부수효과: 없음.
 */
export function parsePositiveAmount(text: string): number | null {
  const number = parseNonNegativeAmount(text);
  return number !== null && number > 0 ? number : null;
}
