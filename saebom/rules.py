# [파일 기능명세]
# 여러 모듈이 같은 뜻으로 쓰던 작은 규칙의 공용 구현: 금액 상한, 청구 월(YYYY-MM) 형식 판단, 스프레드시트·CSV 수식 방지.
# 이전에는 routes/compare.py(보정 검증·CSV), statement.py(거래명세서), expense.py(지출결의서)에 같은 로직이 따로 있어 동작이 어긋났다
# (예: CSV는 탭·캐리지 리턴 접두도 막았지만 엑셀 셀은 막지 않음). 오류 문구는 호출하는 쪽이 정하고, 이 모듈은 판단만 한다.
# 비교 판정(compare.py)에 쓰는 규칙(norm 등)은 이 모듈에 두지 않는다.
# 유지보수: 값이나 의미가 바뀌면 이 주석과 호출하는 모듈의 기능명세, 개발문서(인터페이스 정의서)를 함께 갱신한다.

from datetime import date

# 금액 한 칸의 최대값(원). 공급가액·세액·합계·보정 금액 검증이 공통으로 쓴다.
MAX_AMOUNT = 10 ** 12

# 수식으로 해석될 수 있는 셀 접두 문자. 엑셀·CSV 모두 이 문자로 시작하는 값 앞에 작은따옴표를 붙여 문자열로 만든다.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


# [기능명세] is_month
# 목적: 청구 월 문자열이 실제 달력의 'YYYY-MM'인지 판단
# 입력: (value: 임의 값)
# 출력: bool — 문자열이고 date.fromisoformat(value + "-01")가 성공하면 True
# 처리: 문자열이 아니면 False, 그 외에는 해당 월 1일로 해석해 보고 ValueError면 False
# 예외/실패: 예외를 밖으로 내지 않음(오류 문구는 호출하는 쪽이 정함)
# 부수효과: 없음
def is_month(value):
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value + "-01")
    except ValueError:
        return False
    return True


# [기능명세] is_amount
# 목적: 금액 값이 허용 범위의 정수인지 판단
# 입력: (value: 임의 값, upper: 상한(기본 MAX_AMOUNT))
# 출력: bool — type이 정확히 int(bool 제외)이고 0 이상 upper 이하이면 True
# 처리: type(value) is int 검사 후 범위 비교
# 예외/실패: 없음
# 부수효과: 없음
def is_amount(value, upper=MAX_AMOUNT):
    return type(value) is int and 0 <= value <= upper


# [기능명세] spreadsheet_safe
# 목적: CSV·엑셀 셀이 수식으로 실행되지 않도록 문자열 앞에 작은따옴표 추가
# 입력: (value: 임의 값 — None이면 빈 문자열)
# 출력: 문자열. FORMULA_PREFIXES 중 하나로 시작하면 앞에 "'"를 붙인 값, 아니면 그대로
# 처리: None→"" , 그 외 str() 변환 후 접두 검사
# 예외/실패: 없음
# 부수효과: 없음
def spreadsheet_safe(value):
    s = "" if value is None else str(value)
    return "'" + s if s.startswith(FORMULA_PREFIXES) else s
