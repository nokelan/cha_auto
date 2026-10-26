# [파일 기능명세]
# 수동 보정(overrides) 규칙 모듈. routes/compare.py의 correct 핸들러에 있던 입력 검증과 병합을 순수 함수로 분리했다.
# 입력 형식: {문서ID: {필드: 값}}. 허용 필드는 supply·vat·total·month·biz·percent·installment·partner.
# 처리 흐름: validate_overrides가 문서 ID·필드·값 범위를 검사(ValueError) → merge_overrides가 기존 보정과 새 보정을 합쳐 새 사전을 만든다.
# 파일·DB·네트워크를 쓰지 않으며 입력 사전을 변경하지 않는다. 오류 문구는 분리 전과 같다.
# 유지보수: 허용 필드·범위·문구가 바뀌면 이 주석, 호출하는 routes/compare.py 명세, tests/test_refactor_api.py를 함께 갱신한다.

from .rules import MAX_AMOUNT, is_amount, is_month

# 보정을 허용하는 필드 이름 집합.
ALLOWED_FIELDS = {"supply", "vat", "total", "month", "biz", "percent", "installment", "partner"}
# 정수 범위로 검사하는 필드(percent만 0~100, 나머지는 0~MAX_AMOUNT).
INT_FIELDS = {"supply", "vat", "total", "percent", "installment"}


# [기능명세] validate_overrides
# 목적: 보정 요청이 허용된 문서·필드·값 범위인지 검사
# 입력: (result: 저장된 결과 사전(rows[].invoice.id 사용), overrides: {문서ID: {필드: 값}})
# 출력: None(통과)
# 처리: 문서 ID가 결과 행의 계산서 ID이고 필드가 허용 집합 안인지 확인 → 금액·차수·비율은 정확한 int(bool 제외)이며 0~상한
#       (percent 100, 그 외 MAX_AMOUNT) → 그 외 필드는 200자 이내 문자열 → month는 실제 달력의 YYYY-MM
# 예외/실패: ValueError("수정할 문서 또는 항목이 잘못되었습니다.") / ("금액·차수·비율은 범위 안의 정수로 입력해 주세요.")
#           / ("수정값을 200자 이내 문자열로 입력해 주세요.") / ("청구 월은 YYYY-MM 형식으로 입력해 주세요.")
# 부수효과: 없음
def validate_overrides(result, overrides):
    valid_ids = {r["invoice"]["id"] for r in result["rows"]}
    for docid, changes in overrides.items():
        if docid not in valid_ids or not changes.keys() <= ALLOWED_FIELDS:
            raise ValueError("수정할 문서 또는 항목이 잘못되었습니다.")
        for key, v in changes.items():
            if key in INT_FIELDS:
                if not is_amount(v, 100 if key == "percent" else MAX_AMOUNT):
                    raise ValueError("금액·차수·비율은 범위 안의 정수로 입력해 주세요.")
            elif not isinstance(v, str) or len(v) > 200:
                raise ValueError("수정값을 200자 이내 문자열로 입력해 주세요.")
            elif key == "month" and not is_month(v):
                raise ValueError("청구 월은 YYYY-MM 형식으로 입력해 주세요.")


# [기능명세] merge_overrides
# 목적: 결과에 저장된 기존 보정에 새 보정을 덮어써 합친 사전 생성
# 입력: (result: 결과 사전(overrides 키 선택), overrides: 새 보정 {문서ID: {필드: 값}})
# 출력: 새 사전 {문서ID: {필드: 값}} — 같은 문서·필드는 새 값이 우선
# 처리: result.get("overrides")를 문서별로 복사한 뒤 새 보정을 문서별 update
# 예외/실패: 없음(검증은 validate_overrides 담당)
# 부수효과: 없음; 입력 사전은 변경하지 않음
def merge_overrides(result, overrides):
    merged = {k: dict(v) for k, v in result.get("overrides", {}).items()}
    for k, v in overrides.items():
        merged.setdefault(k, {}).update(v)
    return merged
