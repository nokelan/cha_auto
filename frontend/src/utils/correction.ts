/**
 * [파일 역할] 보정 폼 입력 문자열을 서버 전송값으로 바꾸는 순수 함수 모음(화면 상태 없음).
 * 서버(saebom/overrides.py)가 숫자 필드(supply·vat·total·percent·installment)를 모두 0 이상 정수로 검사하므로
 * 금액뿐 아니라 비율·차수도 같은 정수 해석(parseNonNegativeAmount)을 쓴다.
 */
import {parseNonNegativeAmount} from './amount';

/**
 * [기능명세] parseCorrectionValue
 * 목적: 보정 폼의 한 필드 입력을 전송값으로 변환한다.
 * 입력: key(필드 키), text(입력 문자열), numericKeys(숫자로 보내는 필드 키 목록)
 * 출력: {ok:true, value}(숫자 필드는 정수, 그 외는 입력 그대로) 또는 {ok:false, error}(한글 오류 문구)
 * 처리/실패: 숫자 필드는 쉼표·공백을 지운 0 이상 정수만 허용한다("1,000,000" → 1000000, "  5 " → 5).
 *   빈 값·문자·소수·음수·안전 범위 초과는 ok:false. 숫자 아닌 필드는 변환 없이 통과한다.
 * 부수효과: 없음.
 */
export function parseCorrectionValue(
  key: string,
  text: string,
  numericKeys: readonly string[],
): {ok: true; value: number | string} | {ok: false; error: string} {
  if (!numericKeys.includes(key)) return {ok: true, value: text};
  const value = parseNonNegativeAmount(text);
  return value === null ? {ok: false, error: '0 이상의 정수만 입력할 수 있습니다. (쉼표 허용)'} : {ok: true, value};
}
