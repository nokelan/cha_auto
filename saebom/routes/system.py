# [파일 기능명세] 앱 상태·저장 설정·전용 브라우저·원문 PDF·종료·활성화 경로를 등록한다.
from contextlib import ExitStack
from fastapi import HTTPException, Query
from fastapi.responses import FileResponse
from .. import config
from ..api_models import Settings

BUSY_SETTINGS = "진행 중인 작업이 끝난 뒤 저장 위치를 변경해 주세요."

# [기능명세] register
# 목적: 이 모듈이 맡는 HTTP 경로를 앱에 등록한다. 경로: GET /api/state, PUT /api/settings, POST /api/settings/pick-folder, POST /api/browser, GET /api/documents/{id}, POST /api/shutdown·/api/activate.
# 입력: app(FastAPI), service(Service), store(Store)와 키워드 전용 공용 인자 ask_folder·strip_pages·shutdown·activate.
#       네 모듈이 같은 시그니처를 받도록 일부러 통일했다(api.create_app이 반복문으로 같은 인자를 넘김). 이 모듈에서는 ask_folder(저장 폴더 선택창)·shutdown·activate 콜백을 쓰고 strip_pages는 쓰지 않는다.
# 출력: 없음. 처리: 기존 요청과 응답을 유지해 핸들러를 클로저로 등록한다.
# 예외/실패: 각 핸들러 명세를 따른다. 부수효과: 앱 라우팅 표 변경.
def register(app, service, store, *, ask_folder=None, strip_pages=None, shutdown=None, activate=None):

    # [기능명세] register.state
    # 목적: 화면 초기·주기 조회용 상태 반환
    # 입력: ()
    # 출력: 목록/작업/저장 경로/사이트 사전
    # 처리: Service.jobs_snapshot(최신순 작업 사본)과 Service.catalog 결과 합치기, 사이트 주소는 config.SITE_URL
    # 예외/실패: 잠금·실행 인증 선행; 저장 조회 오류 전파
    # 부수효과: DB·파일 존재 여부 읽기
    @app.get("/api/state")
    def state():
        return {**service.catalog(), "jobs": service.jobs_snapshot(), "data_dir": str(store.root), "document_root": str(store.document_root()), "site": config.SITE_URL}


    # [기능명세] register.settings
    # 목적: 저장 위치 변경 요청 처리
    # 입력: (body: Settings)
    # 출력: document_root 사전
    # 처리: Service.exclusive("저장 위치 변경") 진입(실행 중 작업 거절, 블록 동안 새 작업 접수는 기다리지 않고 즉시 400으로 거절. 서비스 잠금은 쥐지 않지만 Store가 이동 내내 store.lock을 쥐므로 /api/state 응답은 이동이 끝날 때까지 지연될 수 있음)→Store.set_document_root
    # 예외/실패: exclusive 진입 실패(진행 작업·종료 중)는 BUSY_SETTINGS 문구의 ValueError; 이동 중 OSError는 안내 가능한 ValueError로 변환; Store의 ValueError는 그대로 전달
    # 부수효과: 등록 PDF 이동과 DB 설정·경로 변경; 세부 원자성은 Store 명세 참조
    @app.put("/api/settings")
    def settings(body: Settings):
        with ExitStack() as stack:
            try:
                stack.enter_context(service.exclusive("저장 위치 변경"))
            except ValueError as e:
                raise ValueError(BUSY_SETTINGS) from e
            try:
                return {"document_root": store.set_document_root(body.document_root)}
            except OSError as e:
                raise ValueError(f"저장 위치를 바꾸지 못했습니다. 기존 설정과 원본 파일은 유지됩니다. 새 폴더의 쓰기 권한과 여유 공간을 확인해 주세요. ({type(e).__name__})")


    # [기능명세] register.pick_folder
    # 목적: 원본 PDF 저장 폴더용 Windows 기본 폴더 선택창 제공
    # 입력: ()
    # 출력: folder 문자열 또는 None 사전
    # 처리: ask_folder("원본 PDF 저장 폴더 선택", 현재 저장 위치의 상위 폴더) 호출
    # 예외/실패: 취소는 None; Tk·대화상자 오류 전파
    # 부수효과: 네이티브 대화상자 표시; 선택만으로 설정을 적용하지 않음
    @app.post("/api/settings/pick-folder")
    def pick_folder():
        return {"folder": ask_folder("원본 PDF 저장 폴더 선택", str(store.document_root().parent))}


    # [기능명세] register.browser
    # 목적: 로그인용 사이트 브라우저 열기 작업 접수
    # 입력: ()
    # 출력: 작업 ID 사전
    # 처리: Service.submit으로 open_browser 예약
    # 예외/실패: 진행 중·종료 중이면 ValueError
    # 부수효과: 사이트 브라우저 탐색 예약
    @app.post("/api/browser")
    def browser():
        return service.submit("전용 브라우저", service.open_browser)


    # [기능명세] register.document
    # 목적: 현재 경로의 원본 PDF 제공
    # 입력: (id: str, download: 쿼리 문자열 — "1"이면 내려받기, 없거나 다른 값이면 화면 열기)
    # 출력: application/pdf FileResponse. 기본은 Content-Disposition inline, ?download=1이면 attachment(한글 파일명은 RFC 5987 filename*=utf-8''… 로 인코딩됨)
    # 처리: Service.document_file(문서 ID→(경로, 표시 이름), 레코드·파일 부재면 None)→파일 응답
    # 예외/실패: 레코드 또는 파일 부재 HTTP 404
    # 부수효과: PDF 파일 읽기; 임의 사용자 경로를 입력받지 않음
    @app.get("/api/documents/{id}")
    def document(id: str, download: str | None = Query(None)):
        found = service.document_file(id)
        if not found:
            raise HTTPException(404, "저장한 PDF를 찾을 수 없습니다. 다시 다운로드해 주세요.")
        path, name = found
        return FileResponse(path, media_type="application/pdf", filename=name, content_disposition_type="attachment" if download == "1" else "inline")


    # [기능명세] register.stop
    # 목적: 로컬 프로그램 정상 종료 요청
    # 입력: ()
    # 출력: ok 불리언 사전
    # 처리: shutdown 콜백이 있으면 호출
    # 예외/실패: 실행·잠금 인증 선행; 콜백 오류 전파
    # 부수효과: 서버 종료 플래그 변경 요청
    @app.post("/api/shutdown")
    def stop():
        if shutdown:
            shutdown()
        return {"ok": True}


    # [기능명세] register.focus_window
    # 목적: 기존 앱 창 활성화 요청
    # 입력: ()
    # 출력: ok 불리언 사전
    # 처리: activate 콜백이 있으면 호출
    # 예외/실패: 실행 세션은 필요하지만 잠금 해제 전에도 허용
    # 부수효과: 앱 활성화 이벤트 설정; 비밀번호 잠금을 해제하지 않음
    @app.post("/api/activate")
    def focus_window():
        if activate:
            activate()
        return {"ok": True}

