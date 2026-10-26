# [파일 기능명세] 문서비교 작업·결과·보정·CSV 경로를 등록한다. 인증은 api.create_app이 적용한다.
# 결과·문서 접근은 Service(get_result·list_results), 보정 검증·병합은 overrides.py, CSV 생성은 export.py에 위임하고 라우트는 HTTP 변환만 맡는다.
from fastapi import HTTPException
from fastapi.responses import Response
from ..api_models import Work, Correct
from ..export import result_csv
from ..overrides import merge_overrides, validate_overrides

# [기능명세] register
# 목적: 이 모듈이 맡는 HTTP 경로를 앱에 등록한다. 경로: POST /api/sync·/api/download·/api/compare, GET /api/results·/api/results/{id}·/api/results/{id}/csv, POST /api/results/{id}/correct.
# 입력: app(FastAPI), service(Service), store(Store)와 키워드 전용 공용 인자 ask_folder·strip_pages·shutdown·activate.
#       네 모듈이 같은 시그니처를 받도록 일부러 통일했다(api.create_app이 반복문으로 같은 인자를 넘김). 이 모듈에서는 ask_folder·shutdown·activate는 쓰지 않고 strip_pages로 결과 상세 응답의 pages를 비운다.
# 출력: 없음. 처리: 기존 요청과 응답을 유지해 핸들러를 클로저로 등록한다.
# 예외/실패: 각 핸들러 명세를 따른다. 부수효과: 앱 라우팅 표 변경.
def register(app, service, store, *, ask_folder=None, strip_pages=None, shutdown=None, activate=None):

    # [기능명세] register.sync
    # 목적: 목록 동기화 작업 접수
    # 입력: ()
    # 출력: 작업 ID 사전
    # 처리: Service.submit으로 sync 예약
    # 예외/실패: 진행 중·종료 중이면 ValueError
    # 부수효과: 백그라운드 사이트 수집 예약
    @app.post("/api/sync")
    def sync():
        return service.submit("목록 동기화", service.sync)


    # [기능명세] register.download
    # 목적: 선택 PDF 저장 작업 접수
    # 입력: (work: Work)
    # 출력: 작업 ID 사전
    # 처리: 요청 모델→연결 검증→download 예약
    # 예외/실패: 잘못된 연결은 ValueError, 형식 오류는 모델 검증 응답
    # 부수효과: 다운로드 예약; 완료 결과는 상태 API에서 확인
    @app.post("/api/download")
    def download(work: Work):
        pairs = [p.model_dump() for p in work.pairs]
        service.validate_pairs(pairs)
        return service.submit("문서 다운로드", service.download, pairs)


    # [기능명세] register.compare
    # 목적: 오프라인 비교 작업 접수
    # 입력: (work: Work)
    # 출력: 작업 ID 사전
    # 처리: 요청 모델→연결 검증→run_compare 예약
    # 예외/실패: 모델 오류·잘못된 연결·작업 충돌 시 실패
    # 부수효과: 로컬 비교 작업 예약
    @app.post("/api/compare")
    def compare(work: Work):
        pairs = [p.model_dump() for p in work.pairs]
        service.validate_pairs(pairs)
        return service.submit("오프라인 비교", service.run_compare, pairs)


    # [기능명세] register.results
    # 목적: 목록·이력 화면용 결과 요약 조회
    # 입력: ()
    # 출력: 최신순 [{id, created, parent|null, count, mismatch, partners, mail_ids}] 목록
    # 처리: Service.list_results(=Store.result_summaries) 호출(행 상세·페이지 전문은 포함하지 않음)
    # 예외/실패: 실행·잠금 인증 선행
    # 부수효과: DB 읽기
    @app.get("/api/results")
    def results():
        return service.list_results()


    # [기능명세] register.result_detail
    # 목적: 선택한 결과 한 건의 상세 조회
    # 입력: (id: str) — 경로 한 구간만 받으므로 /api/results/{id}/csv·/correct와 충돌하지 않음
    # 출력: {id, created, parent, rows, pairs, overrides} — 각 행의 invoice·contract extraction.pages와 effective_invoice.pages는 빈 배열
    # 처리: Service.get_result 조회→strip_pages로 응답용 사본 생성
    # 예외/실패: 결과 부재 HTTP 404; 실행·잠금 인증 선행
    # 부수효과: DB 읽기; 저장된 결과는 변경하지 않음
    @app.get("/api/results/{id}")
    def result_detail(id: str):
        result = service.get_result(id)
        if not result:
            raise HTTPException(404, "결과를 찾을 수 없습니다.")
        return strip_pages(result)


    # [기능명세] register.correct
    # 목적: 추출값 수동 보정 재비교 접수
    # 입력: (id: str, body: Correct)
    # 출력: 새 작업 ID 사전
    # 처리: Service.get_result로 기존 결과 조회→overrides.validate_overrides(문서·필드·범위·월 검사)→overrides.merge_overrides→부모 결과를 참조해 재비교(run_compare가 부모 결과로 동기화 뒤 사라진 메일·계약을 보충하므로 동기화 뒤에도 가능)
    # 예외/실패: 결과 부재 404, 허용하지 않은 보정 ValueError
    # 부수효과: 새 결과 생성 작업 예약; 원본 PDF·이전 결과는 변경하지 않음
    @app.post("/api/results/{id}/correct")
    def correct(id: str, body: Correct):
        result = service.get_result(id)
        if not result:
            raise HTTPException(404, "결과를 찾을 수 없습니다.")
        validate_overrides(result, body.overrides)
        merged = merge_overrides(result, body.overrides)
        return service.submit("보정 후 재비교", service.run_compare, result["pairs"], merged, id)


    # [기능명세] register.csv_result
    # 목적: 비교 결과를 CSV로 변환
    # 입력: (id: str)
    # 출력: UTF-8 BOM이 포함된 다운로드 Response
    # 처리: Service.get_result로 결과 조회→export.result_csv(항목별 행과 근거, 셀 수식 접두어 방어)→헤더·파일명 설정
    # 예외/실패: 결과 부재 HTTP 404
    # 부수효과: 메모리 CSV 생성; 서버 파일로 저장하지 않음
    @app.get("/api/results/{id}/csv")
    def csv_result(id: str):
        result = service.get_result(id)
        if not result:
            raise HTTPException(404, "결과가 없습니다.")
        return Response(result_csv(result), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="saebom-{id[:8]}.csv"'})

