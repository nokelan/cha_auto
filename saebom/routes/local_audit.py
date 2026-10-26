# [파일 기능명세] 로컬 세금계산서 대조 상태·폴더 설정·작업 경로를 등록한다. 인증은 api.create_app이 적용한다.
from ..api_models import LocalFolder
from ..service import LOCAL_FOLDER_KEY


# [기능명세] register
# 목적: 이 모듈이 맡는 HTTP 경로를 앱에 등록한다. 경로: GET /api/local-audit, PUT /api/local-audit/folder, POST /api/local-audit/pick-folder, POST /api/local-audit/run.
# 입력: app(FastAPI), service(Service), store(Store)와 키워드 전용 공용 인자 ask_folder·strip_pages·shutdown·activate.
#       네 모듈이 같은 시그니처를 받도록 일부러 통일했다(api.create_app이 반복문으로 같은 인자를 넘김). 이 모듈에서는 ask_folder만 쓰고(폴더 선택창) 나머지 콜백은 쓰지 않는다.
# 출력: 없음. 처리: 기존 요청과 응답을 유지해 핸들러를 클로저로 등록한다.
# 예외/실패: 각 핸들러 명세를 따른다. 부수효과: 앱 라우팅 표 변경.
def register(app, service, store, *, ask_folder=None, strip_pages=None, shutdown=None, activate=None):

    # [기능명세] register.local_audit_state
    # 목적: '로컬 세금계산서 대조' 화면 상태 조회
    # 입력: ()
    # 출력: {folder|null, folder_error|null, files:[{file, path, type, size, partner, partner_source, invoice:{fields, error}}],
    #        warnings:[str], last: {folder, ran_at, contracts_total, counts, warnings, rows}|null}
    # 처리: Service.local_audit_state 호출(폴더 파일 판독은 (경로, 수정 시각, 크기) 캐시로 재사용)
    # 예외/실패: 실행·잠금 인증 선행; 폴더 문제는 folder_error로 200 응답; DB 오류 전파
    # 부수효과: 로컬 폴더·PDF 읽기, DB 읽기
    @app.get("/api/local-audit")
    def local_audit_state():
        return service.local_audit_state()


    # [기능명세] register.set_local_folder
    # 목적: 로컬 세금계산서 폴더 저장
    # 입력: (body: LocalFolder — folder 1~1000자)
    # 출력: local_audit_state와 같은 상태 사전
    # 처리: Service.set_local_folder(폴더 검사 → meta.local_invoice_folder 저장 → 상태 반환)
    # 예외/실패: 빈 문자열·누락은 422; 상대경로·UNC·없는 폴더는 ValueError→400(한글 detail); 실행·잠금 인증 선행
    # 부수효과: meta 갱신, 폴더·PDF 읽기
    @app.put("/api/local-audit/folder")
    def set_local_folder(body: LocalFolder):
        return service.set_local_folder(body.folder)


    # [기능명세] register.pick_local_folder
    # 목적: 세금계산서 폴더를 고르는 Windows 기본 폴더 선택창 제공
    # 입력: ()
    # 출력: {folder: 선택한 폴더 문자열|null}
    # 처리: 시작 폴더 = 저장된 meta.local_invoice_folder, 없으면 store.document_root() → ask_folder("세금계산서 폴더 선택", 시작 폴더)
    # 예외/실패: 취소는 null; Tk·대화상자 오류 전파; 실행·잠금 인증 선행
    # 부수효과: 네이티브 대화상자 표시; 선택만 하고 저장하지 않음(화면이 PUT /api/local-audit/folder를 호출)
    @app.post("/api/local-audit/pick-folder")
    def pick_local_folder():
        start = store.meta_get(LOCAL_FOLDER_KEY) or str(store.document_root())
        return {"folder": ask_folder("세금계산서 폴더 선택", start)}


    # [기능명세] register.run_local_audit
    # 목적: 로컬 세금계산서 대조 작업 접수
    # 입력: ()
    # 출력: {"id": 작업 ID}
    # 처리: Service.submit("로컬 세금계산서 대조", Service.run_local_audit)
    # 예외/실패: 진행 중·종료 중이면 ValueError→400; 폴더 미설정 등은 작업 실패 메시지로 남음; 실행·잠금 인증 선행
    # 부수효과: 백그라운드 사이트 수집·계약서 PDF 저장·meta.local_audit 갱신 작업 예약
    @app.post("/api/local-audit/run")
    def run_local_audit():
        return service.submit("로컬 세금계산서 대조", service.run_local_audit)

