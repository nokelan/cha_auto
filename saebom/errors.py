# [파일 기능명세]
# 앱 전용 예외 계층. 업무 규칙 위반(사용자에게 문구를 그대로 보여 줄 오류)과 '없는 계약' 같은 조회 실패를 구분해
# HTTP 변환 규칙(api.py)이 내부 버그(KeyError 등)를 업무 오류로 오인하지 않게 한다.
# 처리 흐름: 서비스·규칙 모듈이 아래 예외를 던짐 → api.py의 예외 처리기와 routes/*가 종류별로 400·404로 변환한다.
# 유지보수: 예외를 추가하거나 의미를 바꾸면 api.py의 변환 규칙과 개발문서(인터페이스 정의서의 오류 코드 절)를 함께 갱신한다.


# [기능명세] BusinessError
# 목적: 사용자가 고칠 수 있는 업무 규칙 위반(입력 오류, 작업 충돌, 지원하지 않는 상태)을 나타냄
# 입력: (message: 화면에 그대로 보여 줄 한글 문구)
# 출력: 예외 객체. ValueError를 상속하므로 기존 `except ValueError`와 api.py의 400 변환과 호환된다
# 처리: 없음(마커 클래스)
# 예외/실패: 없음
# 부수효과: 없음
class BusinessError(ValueError):
    pass


# [기능명세] ContractNotFound
# 목적: 가져온 계약 목록에 없는 관리번호 조회 실패를 나타냄(HTTP 404로 변환)
# 입력: (contract_id: 관리번호)
# 출력: 예외 객체. LookupError를 상속해 기존 `except LookupError`와 호환되지만, routes/*는 이 클래스만 404로 바꿔야 한다
#       (내부 KeyError·IndexError가 404로 가려지는 문제를 막기 위함)
# 처리: 없음(마커 클래스)
# 예외/실패: 없음
# 부수효과: 없음
class ContractNotFound(LookupError):
    pass


# [기능명세] SubmitUncertain
# 목적: 지출결의서 '상신' 버튼을 누른 뒤 오류가 나서, 그룹웨어에 기안이 이미 만들어졌는지 확실하지 않은 상태를 나타냄
# 입력: (message: 원인 문구)
# 출력: 예외 객체. BusinessError를 상속한다
# 처리: 없음(마커 클래스). Service.run_expense가 잡아 contract_status 데이터에 site_draft=True를 남기고 다시 던진다
# 예외/실패: 없음
# 부수효과: 없음
class SubmitUncertain(BusinessError):
    pass
