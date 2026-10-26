# [파일 기능명세] API 입력의 구조·크기·형식을 검증하는 공용 요청 모델. 앱과 라우트의 순환 import를 피한다.
from typing import Any, Literal
from pydantic import BaseModel, Field, StrictInt
from . import config



# [자료형/클래스 명세] Pair: 비교 연결 입력. 메일 ID·계약 ID·계산서 URL을 문자열로 받는다.
class Pair(BaseModel):
    mail_id: str
    contract_id: str
    invoice_url: str



# [자료형/클래스 명세] Work: 주요 작업 입력. Pair 목록을 1~config.MAX_PAIRS(500)건으로 제한한다.
class Work(BaseModel):
    pairs: list[Pair] = Field(min_length=1, max_length=config.MAX_PAIRS)



# [자료형/클래스 명세] Correct: 수동 보정 입력. 문서 ID별 필드 변경 사전을 받으며 세부 허용값은 엔드포인트에서 검증한다.
class Correct(BaseModel):
    overrides: dict[str, dict[str, Any]]



# [자료형/클래스 명세] Settings: 설정 입력. PDF 루트 경로 문자열 길이는 1~1000자이며 경로 유효성은 Store에서 검사한다.
class Settings(BaseModel):
    document_root: str = Field(min_length=1, max_length=1000)



# [자료형/클래스 명세] ImportContracts: 계약서 가져오기 입력. kind는 사이트 구분 필터("전체"|"수입"|"지출", 기본 전체),
# limit은 최근 N개(1~config.MAX_PAIRS, None이면 전체), only_new는 아직 가져오지 않은 계약만 고를지 여부다. 범위·값 위반은 422.
class ImportContracts(BaseModel):
    kind: Literal["전체", "수입", "지출"] = "전체"
    limit: int | None = Field(None, ge=1, le=config.MAX_PAIRS)
    only_new: bool = False



# [자료형/클래스 명세] StatementItem: 거래명세서 품목 한 줄 입력. 품목·규격은 200자 이내 문자열, 월금액은 정수다.
# 빈 값·0 이하 금액 같은 업무 검사는 statement.validate가 한글 안내(400)로 처리하고, 형식 오류만 422로 거절한다.
class StatementItem(BaseModel):
    name: str = Field(max_length=200)
    spec: str = Field(max_length=200)
    monthly_amount: int



# [자료형/클래스 명세] StatementRequest: 거래명세서 생성 입력. 수신(거래처)·작성 일자(YYYY-MM-DD)·청구 시작/끝 월(YYYY-MM)·품목 목록.
# 날짜·월 형식과 줄 수(12줄) 검사는 statement.build가 한글 안내(400)로 처리한다. items는 요청 크기 보호용으로 100개까지만 받는다.
class StatementRequest(BaseModel):
    customer: str = Field(max_length=200)
    issue_date: str = Field(max_length=20)
    from_month: str = Field(max_length=20)
    to_month: str = Field(max_length=20)
    items: list[StatementItem] = Field(max_length=100)



# [자료형/클래스 명세] LocalFolder: 로컬 세금계산서 폴더 입력. 경로 문자열 길이는 1~1000자이며 절대경로·UNC·존재 검사는 local_audit.check_folder가 한다.
class LocalFolder(BaseModel):
    folder: str = Field(min_length=1, max_length=1000)



# [자료형/클래스 명세] Login: 로그인 입력. 비밀번호 문자열 길이는 1~128자이며 정답 비교는 login에서 수행한다.
class Login(BaseModel):
    password: str = Field(min_length=1, max_length=128)


# [자료형/클래스 명세] ExpenseRequest: 지출결의서 상신값. 제목·월·정수 금액·첨부 이름·특이사항을 받는다.
# 월 형식·검산·업무 범위는 expense.validate가 400으로, 구조·크기 오류는 모델이 422로 처리한다.
class ExpenseRequest(BaseModel):
    title: str = Field(max_length=500)
    month: str = Field(max_length=20)
    supply: StrictInt
    vat: StrictInt
    total: StrictInt
    attachments: list[str] = Field(default_factory=list, max_length=100)
    note: str = Field(default="", max_length=2000)

