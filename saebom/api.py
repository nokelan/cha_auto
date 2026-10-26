# [파일 기능명세]
# HTTP 경계. 요청 모델 검증, 로컬 실행 세션·비밀번호 잠금 검사, 작업 접수와 PDF·CSV 응답을 제공한다. 업무 로직은 Service, 저장·이동은 Store에 위임한다.
# 비밀번호는 config.APP_PASSWORD와 비교하고, 연속 실패가 config.LOGIN_MAX_FAILURES회에 이르면 config.LOGIN_LOCK_SECONDS초 동안 429로 거절한다(메모리 관리, 재시작 시 초기화).
# 예외 변환: BusinessError는 400(로그 없음), 일반 ValueError는 400+로그, 응답은 {"detail": 메시지}.
# 결과 API는 목록용 요약(GET /api/results)과 pages를 비운 상세(GET /api/results/{id})로 나뉜다.
# 계약서 목록 API는 가져오기 작업 접수(POST /api/contracts/import)와 가져온 계약 조회(GET /api/contracts, pages 비움)이며 둘 다 잠금 해제가 필요하다.
# 거래명세서 API는 초안 조회(GET /api/contracts/{id}/statement), 생성(POST 같은 경로), 엑셀 내려받기(GET /api/statements/{file})이며
# 없는 계약은 404, 원문 없음·지출 계약 생성·검증 실패·작업 중은 400이다. 생성 규칙은 statement.py에 있다.
# 로컬 세금계산서 대조 API는 상태 조회(GET /api/local-audit), 폴더 저장(PUT /api/local-audit/folder), 폴더 선택창(POST /api/local-audit/pick-folder),
# 대조 작업 접수(POST /api/local-audit/run)이며 모두 잠금 해제가 필요하다. 폴더 선택창은 ask_folder 도우미를 원본 PDF 폴더 선택과 함께 쓴다.
# 지출결의서 초안·상신은 routes/contracts.py가 Service에 위임하며, 상신 뒤 불확실 오류는 contract_status.data.site_draft로 남긴다.
# 유지보수: 함수·데이터 계약이 바뀌면 해당 기능명세와 실제 회귀 검사를 함께 갱신한다.

import logging
import math
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .api_models import Login
from . import config
from .errors import BusinessError
from .views import strip_result_pages
from .service import Service
from .store import Store

log = logging.getLogger(__name__)


# [기능명세] strip_pages
# 목적: 결과 상세 응답에서 큰 페이지 전문(pages)을 뺀 사본 생성
# 입력: (result: Store.result가 반환한 결과 사전)
# 출력: rows의 invoice·contract의 extraction.pages와 effective_invoice.pages를 빈 배열로 바꾼 새 결과 사전
# 처리: views.strip_result_pages에 위임(동작 동일; 입력 사전과 저장 데이터는 변경하지 않음)
# 예외/실패: rows가 없으면 빈 목록으로 처리
# 부수효과: 없음
def strip_pages(result):
    return strip_result_pages(result)


# [기능명세] _same
# 목적: 비밀 문자열(토큰·쿠키)을 상수시간으로 비교하되 비ASCII 입력에도 예외가 나지 않게 함
# 입력: (a: str, b: str)
# 출력: 두 문자열이 UTF-8 바이트로 같으면 True
# 처리: 양쪽을 UTF-8로 인코딩해 secrets.compare_digest(bytes, bytes) 호출
# 예외/실패: 없음(str 입력 가정; 쿠키·쿼리 값은 항상 str). str끼리 비교하면 비ASCII에서 TypeError가 나는 문제를 막는다
# 부수효과: 없음
def _same(a, b):
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


# [기능명세] ask_folder
# 목적: Windows 기본 폴더 선택창을 열고 고른 폴더 반환(원본 PDF 저장 위치·세금계산서 폴더 선택 공용)
# 입력: (title: 대화상자 제목, initialdir: 시작 폴더 문자열)
# 출력: 고른 폴더 문자열 또는 None(취소)
# 처리: 숨긴 Tk 창 생성→최상단 표시→filedialog.askdirectory(title, initialdir)→finally에서 창 파괴
# 예외/실패: Tk·대화상자 오류 전파. 주의: 동기 라우트로 호출되면 FastAPI 스레드풀(비메인 스레드)에서 실행된다.
#           Tk는 메인 스레드 사용이 원칙이라 환경에 따라 불안정(교착·창 미표시·TclError)할 수 있고, 동시에 두 번 열면 서로 막을 수 있다. 동작은 바꾸지 않았다(알려진 위험).
#           테스트는 모듈 속성 api.ask_folder를 바꿔 대화상자 없이 검사한다
# 부수효과: 네이티브 대화상자 표시; 설정을 저장하지 않음
def ask_folder(title, initialdir):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return filedialog.askdirectory(title=title, initialdir=initialdir, parent=root) or None
    finally:
        root.destroy()


# [기능명세] create_app
# 목적: 로컬 HTTP 앱과 경로·접근 정책 구성
# 입력: (store: Store, static: Path, token=None, shutdown=None, activate=None)
# 출력: FastAPI 인스턴스
# 처리: Service·실행 세션·잠금 토큰·로그인 실패 상태(횟수·잠금 만료 시각, threading.Lock 보호) 생성→미들웨어·엔드포인트·정적 파일 등록
# 예외/실패: Store·정적 파일 준비 오류 전파
# 부수효과: Service 작업 실행기 생성; 서버 포트 바인딩은 launcher 담당
def create_app(store: Store, static: Path, token=None, shutdown=None, activate=None):
    service = Service(store)
    token = token or secrets.token_urlsafe(32)
    unlocked_token = secrets.token_urlsafe(32)
    # 로그인 실패 상태: 이 앱 인스턴스(실행)에서만 유지한다. 시각은 time.monotonic() 기준.
    login_lock = threading.Lock()
    login_state = {"failures": 0, "locked_until": 0.0}

    # [기능명세] create_app.lifespan
    # 목적: HTTP 앱 종료 자원 정리
    # 입력: (app)
    # 출력: 비동기 컨텍스트 매니저
    # 처리: yield로 앱 실행을 허용한 뒤 Service와 Store 종료
    # 예외/실패: 정리 함수 오류는 전파
    # 부수효과: 작업 실행기·사이트 브라우저·DB 연결 종료
    @asynccontextmanager
    async def lifespan(app):
        yield
        service.close()
        store.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.service = service  # 테스트가 작업 상태를 직접 확인할 때 쓴다(실행 토큰은 클로저 변수 token만 사용)

    # [기능명세] create_app.protect
    # 목적: 로컬 실행 세션과 비밀번호 잠금 검사
    # 입력: (request: Request, call_next)
    # 출력: HTTP 응답 또는 다음 핸들러 응답
    # 처리: Host/Origin→health→최초 토큰 쿠키→실행 쿠키→보호 API 잠금→보안 헤더
    # 예외/실패: 호스트·출처 403, 실행·잠금 미인증 401(비ASCII 토큰·쿠키도 500이 아닌 401); 허용 경로 외 API 접근 차단
    # 부수효과: 실행 세션 쿠키와 응답 헤더 설정; 서버 파일 내용 변경 없음
    @app.middleware("http")
    async def protect(request: Request, call_next):
        host = request.headers.get("host", "")
        if host.split(":")[0] != "127.0.0.1":
            return JSONResponse({"detail": "로컬 접속만 허용됩니다."}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != f"http://{host}":
            return JSONResponse({"detail": "다른 사이트의 요청은 허용되지 않습니다."}, status_code=403)
        if request.url.path == "/health":
            return JSONResponse({"ok": True, "app": "SaebomCompare"})
        if request.url.path == "/" and _same(request.query_params.get("token", ""), token):
            response = RedirectResponse("/", status_code=303)
            response.set_cookie("saebom_session", token, httponly=True, samesite="strict")
            response.headers["Referrer-Policy"] = "no-referrer"
            return response
        if not _same(request.cookies.get("saebom_session", ""), token):
            return JSONResponse({"detail": "EXE를 실행해 앱 화면을 다시 열어 주세요."}, status_code=401)
        public_api = {"/api/auth/status", "/api/auth/login", "/api/activate"}
        if request.url.path.startswith("/api/") and request.url.path not in public_api:
            if not _same(request.cookies.get("saebom_unlocked", ""), unlocked_token):
                return JSONResponse({"detail": "비밀번호를 입력해 프로그램을 잠금 해제해 주세요."}, status_code=401)
        response = await call_next(request)
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; worker-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    # [기능명세] create_app.bad_input
    # 목적: ValueError를 화면용 응답으로 변환하되 내부 버그가 400 뒤에 숨지 않게 기록
    # 입력: (request, exc)
    # 출력: {"detail": 메시지} 형태의 HTTP 400 JSON(형식·상태코드는 기존과 동일)
    # 처리: errors.BusinessError(사용자가 고칠 수 있는 업무 오류)는 로그 없이 변환. 그 밖의 ValueError는 호환을 위해 400을 유지하되 log.exception으로 기록
    # 예외/실패: ValueError 외 예외 종류는 이 핸들러의 대상이 아님
    # 부수효과: 일반 ValueError일 때만 logging.exception 기록
    @app.exception_handler(ValueError)
    async def bad_input(request, exc):
        if not isinstance(exc, BusinessError):
            log.exception("요청 처리 중 ValueError(업무 오류가 아닌 일반 ValueError): %s %s", request.method, request.url.path, exc_info=exc)
        return JSONResponse({"detail": str(exc)}, status_code=400)

    # [기능명세] create_app.auth_status
    # 목적: 현재 실행의 비밀번호 인증 여부 조회
    # 입력: (request: Request)
    # 출력: authenticated 불리언 사전
    # 처리: 요청 잠금 해제 쿠키와 실행별 토큰을 UTF-8 바이트로 상수시간 비교(_same; 비ASCII 쿠키도 False)
    # 예외/실패: 실행 쿠키 검사는 미들웨어 담당
    # 부수효과: 쿠키 읽기; 비밀번호를 반환하지 않음
    @app.get("/api/auth/status")
    def auth_status(request: Request):
        return {"authenticated": _same(request.cookies.get("saebom_unlocked", ""), unlocked_token)}

    # [기능명세] create_app.login
    # 목적: 시작 비밀번호 검증과 잠금 해제
    # 입력: (body: Login)
    # 출력: 성공 JSON 응답 및 HttpOnly 쿠키
    # 처리: login_lock 안에서 잠금 만료 시각 확인→UTF-8 비밀번호와 config.APP_PASSWORD를 compare_digest로 비교→실패면 횟수 증가, config.LOGIN_MAX_FAILURES회에 이르면 횟수를 0으로 되돌리고 config.LOGIN_LOCK_SECONDS초 잠금→성공이면 횟수 초기화
    # 예외/실패: 잠금 중이면 정답이어도 HTTP 429("비밀번호를 여러 번 틀렸습니다. N초 후 다시 시도해 주세요.", N은 남은 초 올림); 틀린 비밀번호는 HTTP 401(잠금을 거는 마지막 실패도 401); 길이 검증은 Login 모델 담당
    # 부수효과: 메모리의 실패 횟수·잠금 시각 갱신; 성공 시 실행별 잠금 해제 쿠키 발급; 파일·DB에 입력값을 저장하지 않음
    @app.post("/api/auth/login")
    def login(body: Login):
        with login_lock:
            remaining = login_state["locked_until"] - time.monotonic()
            if remaining > 0:
                raise HTTPException(status_code=429, detail=f"비밀번호를 여러 번 틀렸습니다. {max(1, math.ceil(remaining))}초 후 다시 시도해 주세요.")
            if not secrets.compare_digest(body.password.encode("utf-8"), config.APP_PASSWORD.encode("utf-8")):
                login_state["failures"] += 1
                if login_state["failures"] >= config.LOGIN_MAX_FAILURES:
                    login_state["failures"] = 0
                    login_state["locked_until"] = time.monotonic() + config.LOGIN_LOCK_SECONDS
                raise HTTPException(status_code=401, detail="비밀번호가 올바르지 않습니다.")
            login_state["failures"] = 0
        response = JSONResponse({"authenticated": True})
        response.set_cookie("saebom_unlocked", unlocked_token, httponly=True, samesite="strict")
        return response

    from .routes import compare, contracts, devdocs, local_audit, system
    # [기능명세] folder_picker 콜백: 제목과 초기 경로를 현재 api.ask_folder에 전달한다.
    # 출력은 선택 폴더 또는 None. 예외와 대화상자 표시는 ask_folder 명세를 따른다.
    folder_picker = lambda title, initialdir: ask_folder(title, initialdir)
    for routes in (compare, contracts, devdocs, local_audit, system):
        routes.register(app, service, store, ask_folder=folder_picker, strip_pages=strip_pages, shutdown=shutdown, activate=activate)

    app.mount("/", StaticFiles(directory=static, html=True), name="ui")
    return app
