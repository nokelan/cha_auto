# [파일 기능명세] 가져온 계약 목록·거래명세서·지출결의서 경로를 등록한다. 인증은 api.create_app이 적용한다.
# 404는 서비스가 던지는 ContractNotFound만 변환한다. 내부 KeyError·IndexError 등은 404로 가리지 않고 전파해 500과 로그로 남긴다.
from fastapi import HTTPException
from fastapi.responses import FileResponse
from ..api_models import ImportContracts, StatementRequest, ExpenseRequest
from ..errors import ContractNotFound

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# [기능명세] register
# 목적: 이 모듈이 맡는 HTTP 경로를 앱에 등록한다. 경로: POST /api/contracts/import, GET /api/contracts, GET·POST /api/contracts/{id}/statement, GET /api/statements/{file}, GET·POST /api/contracts/{id}/expense.
# 입력: app(FastAPI), service(Service), store(Store)와 키워드 전용 공용 인자 ask_folder·strip_pages·shutdown·activate.
#       네 모듈이 같은 시그니처를 받도록 일부러 통일했다(api.create_app이 반복문으로 같은 인자를 넘김). 이 모듈에서는 공용 도우미·콜백 인자는 쓰지 않는다.
# 출력: 없음. 처리: 기존 요청과 응답을 유지해 핸들러를 클로저로 등록한다.
# 예외/실패: 각 핸들러 명세를 따른다. 부수효과: 앱 라우팅 표 변경.
def register(app, service, store, *, ask_folder=None, strip_pages=None, shutdown=None, activate=None):

    # [기능명세] expense_draft
    # 목적: 지출결의서 초안 조회. 입력: 관리번호. 출력: 적격 여부·초안·경고·마지막 상신 정보.
    # 처리: 서비스에 위임. 예외/실패: 없는 계약(ContractNotFound) 404, 원문 없음 400, 그 밖의 내부 오류는 전파(500). 부수효과: DB·파일 읽기.
    @app.get("/api/contracts/{id}/expense")
    def expense_draft(id: str):
        try:
            return service.expense_draft(id)
        except ContractNotFound:
            raise HTTPException(404, "가져온 계약을 찾을 수 없습니다.") from None

    # [기능명세] submit_expense
    # 목적: 확인 창 수정값으로 지출결의서 상신 작업 접수. 입력: 관리번호·ExpenseRequest. 출력: 작업 ID.
    # 처리: 서비스 검증 후 예약. 예외/실패: 없는 계약(ContractNotFound) 404(내부 KeyError 등은 전파), 부적격·검산·월·작업 충돌 400, 구조 오류 422.
    # 부수효과: 작업 상태 저장과 사이트 상신 예약. 실제 결과는 계약 목록 approval에서 조회한다.
    @app.post("/api/contracts/{id}/expense")
    def submit_expense(id: str, body: ExpenseRequest):
        try:
            return service.submit_expense(id, body.model_dump())
        except ContractNotFound:
            raise HTTPException(404, "가져온 계약을 찾을 수 없습니다.") from None

    # [기능명세] register.import_contracts
    # 목적: '계약서 목록' 메뉴의 계약서 가져오기 작업 접수
    # 입력: (body: ImportContracts — kind/limit/only_new)
    # 출력: {"id": 작업 ID}
    # 처리: 요청 모델 검증 → Service.submit("계약서 가져오기", import_contracts, kind, limit, only_new)
    # 예외/실패: 형식 오류(구분 이름·limit 범위)는 422; 진행 중·종료 중이면 ValueError(400); 실행·잠금 인증은 미들웨어가 선행
    # 부수효과: 백그라운드 사이트 수집·PDF 저장 작업 예약
    @app.post("/api/contracts/import")
    def import_contracts(body: ImportContracts):
        return service.submit("계약서 가져오기", service.import_contracts, body.kind, body.limit, body.only_new)


    # [기능명세] register.contracts
    # 목적: '계약서 목록' 화면용 가져온 계약 목록 조회
    # 입력: ()
    # 출력: 관리번호 큰 순 [{id, kind, partner, title, period, amount_text, file, imported, document|null}] — document.extraction.pages는 빈 배열
    # 처리: Service.contract_catalog 호출
    # 예외/실패: 실행·잠금 인증 선행; DB 오류 전파
    # 부수효과: DB·파일 존재 여부 읽기
    @app.get("/api/contracts")
    def contracts():
        return service.contract_catalog()


    # [기능명세] register.statement_draft
    # 목적: 거래명세서 확인 창 초기값 조회
    # 입력: (id: 관리번호) — /api/contracts/{id}/statement는 두 구간 경로라 /api/contracts·/api/contracts/import와 충돌하지 않음
    # 출력: {contract_id, eligible, reason, customer, customer_biz, contract_date, issue_date, period_start, period_end,
    #        from_month, to_month, items:[{name, spec, monthly_amount}], notes, missing, folder}
    # 처리: Service.statement_draft 호출(지출 계약도 eligible=false·reason으로 200)
    # 예외/실패: 가져온 계약이 없으면(ContractNotFound) HTTP 404, 내부 KeyError 등은 전파(500); 원문 PDF가 없으면 ValueError→400; 실행·잠금 인증 선행
    # 부수효과: DB 읽기·파일 존재 확인
    @app.get("/api/contracts/{id}/statement")
    def statement_draft(id: str):
        try:
            return service.statement_draft(id)
        except ContractNotFound:
            raise HTTPException(404, "가져온 계약을 찾을 수 없습니다.")


    # [기능명세] register.create_statement
    # 목적: 확인 창에서 고친 값으로 거래명세서 엑셀 생성
    # 입력: (id: 관리번호, body: StatementRequest)
    # 출력: {file: 파일명, path: 절대경로, rows: 줄 수, supply: 공급가액, vat: 세액, total: 합계, warnings: [str]}
    # 처리: 요청 모델 검증 → Service.create_statement(id, 요청 사전)
    # 예외/실패: 없는 계약(ContractNotFound) HTTP 404(내부 KeyError 등은 전파); 지출 계약·원문 없음·입력 검증 실패·12줄 초과·작업 진행 중은 ValueError→400(한글 detail); 형식 오류 422
    # 부수효과: PDF 보관 폴더/거래명세서/에 새 xlsx 파일 생성(덮어쓰기 없음)
    @app.post("/api/contracts/{id}/statement")
    def create_statement(id: str, body: StatementRequest):
        try:
            return service.create_statement(id, body.model_dump())
        except ContractNotFound:
            raise HTTPException(404, "가져온 계약을 찾을 수 없습니다.")


    # [기능명세] register.statement_file
    # 목적: 만든 거래명세서 엑셀 내려받기
    # 입력: (file: 파일명 한 구간)
    # 출력: attachment xlsx FileResponse(한글 파일명은 filename*로 인코딩)
    # 처리: 파일명 검사(/, \, '..' 없음, .xlsx로 끝남) → 거래명세서 폴더 아래 경로 계산 → resolve한 상위 폴더가 거래명세서 폴더인지·파일인지 확인
    # 예외/실패: 검사 실패·파일 없음은 HTTP 404; 실행·잠금 인증 선행
    # 부수효과: 파일 읽기; 폴더 밖 임의 경로는 열지 않음
    @app.get("/api/statements/{file}")
    def statement_file(file: str):
        missing = HTTPException(404, "거래명세서 파일을 찾을 수 없습니다.")
        if "/" in file or "\\" in file or ".." in file or not file.lower().endswith(".xlsx"):
            raise missing
        folder = service.statement_folder()
        path = folder / file
        try:
            if path.resolve().parent != folder.resolve() or not path.is_file():
                raise missing
        except OSError:
            raise missing
        return FileResponse(path, media_type=XLSX_MEDIA, filename=file)

