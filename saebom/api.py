# [파일 기능명세]
# HTTP 경계. 요청 모델 검증, 로컬 실행 세션·비밀번호 잠금 검사, 작업 접수와 PDF·CSV 응답을 제공한다. 업무 로직은 Service, 저장·이동은 Store에 위임한다.
# 유지보수: 함수·데이터 계약이 바뀌면 해당 기능명세와 실제 회귀 검사를 함께 갱신한다.

import csv
import io
import secrets
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .service import Service
from .store import Store


# [자료형/클래스 명세] Pair: 비교 연결 입력. 메일 ID·계약 ID·계산서 URL을 문자열로 받는다.
class Pair(BaseModel):
    mail_id: str
    contract_id: str
    invoice_url: str


# [자료형/클래스 명세] Work: 주요 작업 입력. Pair 목록을 1~500건으로 제한한다.
class Work(BaseModel):
    pairs: list[Pair] = Field(min_length=1, max_length=500)


# [자료형/클래스 명세] Correct: 수동 보정 입력. 문서 ID별 필드 변경 사전을 받으며 세부 허용값은 엔드포인트에서 검증한다.
class Correct(BaseModel):
    overrides: dict[str, dict[str, Any]]


# [자료형/클래스 명세] Settings: 설정 입력. PDF 루트 경로 문자열 길이는 1~1000자이며 경로 유효성은 Store에서 검사한다.
class Settings(BaseModel):
    document_root: str = Field(min_length=1, max_length=1000)


# [자료형/클래스 명세] Login: 로그인 입력. 비밀번호 문자열 길이는 1~128자이며 정답 비교는 login에서 수행한다.
class Login(BaseModel):
    password: str = Field(min_length=1, max_length=128)


# [기능명세] create_app
# 목적: 로컬 HTTP 앱과 경로·접근 정책 구성
# 입력: (store: Store, static: Path, token=None, shutdown=None, activate=None)
# 출력: FastAPI 인스턴스
# 처리: Service·실행 세션·잠금 토큰 생성→미들웨어·엔드포인트·정적 파일 등록
# 예외/실패: Store·정적 파일 준비 오류 전파
# 부수효과: Service 작업 실행기 생성; 서버 포트 바인딩은 launcher 담당
def create_app(store: Store, static: Path, token=None, shutdown=None, activate=None):
    service = Service(store)
    token = token or secrets.token_urlsafe(32)
    unlocked_token = secrets.token_urlsafe(32)

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
    app.state.service = service
    app.state.token = token

    # [기능명세] create_app.protect
    # 목적: 로컬 실행 세션과 비밀번호 잠금 검사
    # 입력: (request: Request, call_next)
    # 출력: HTTP 응답 또는 다음 핸들러 응답
    # 처리: Host/Origin→health→최초 토큰 쿠키→실행 쿠키→보호 API 잠금→보안 헤더
    # 예외/실패: 호스트·출처 403, 실행·잠금 미인증 401; 허용 경로 외 API 접근 차단
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
        if request.url.path == "/" and secrets.compare_digest(request.query_params.get("token", ""), token):
            response = RedirectResponse("/", status_code=303)
            response.set_cookie("saebom_session", token, httponly=True, samesite="strict")
            response.headers["Referrer-Policy"] = "no-referrer"
            return response
        if not secrets.compare_digest(request.cookies.get("saebom_session", ""), token):
            return JSONResponse({"detail": "EXE를 실행해 앱 화면을 다시 열어 주세요."}, status_code=401)
        public_api = {"/api/auth/status", "/api/auth/login", "/api/activate"}
        if request.url.path.startswith("/api/") and request.url.path not in public_api:
            if not secrets.compare_digest(request.cookies.get("saebom_unlocked", ""), unlocked_token):
                return JSONResponse({"detail": "비밀번호를 입력해 프로그램을 잠금 해제해 주세요."}, status_code=401)
        response = await call_next(request)
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; worker-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    # [기능명세] create_app.bad_input
    # 목적: 업무 ValueError를 화면용 응답으로 변환
    # 입력: (request, exc)
    # 출력: detail을 담은 HTTP 400 JSON
    # 처리: 예외 메시지를 문자열로 전달
    # 예외/실패: 다른 예외 종류는 이 핸들러의 대상이 아님
    # 부수효과: 없음
    @app.exception_handler(ValueError)
    async def bad_input(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    # [기능명세] create_app.auth_status
    # 목적: 현재 실행의 비밀번호 인증 여부 조회
    # 입력: (request: Request)
    # 출력: authenticated 불리언 사전
    # 처리: 요청 잠금 해제 쿠키와 실행별 토큰을 상수시간 비교
    # 예외/실패: 실행 쿠키 검사는 미들웨어 담당
    # 부수효과: 쿠키 읽기; 비밀번호를 반환하지 않음
    @app.get("/api/auth/status")
    def auth_status(request: Request):
        return {"authenticated": secrets.compare_digest(request.cookies.get("saebom_unlocked", ""), unlocked_token)}

    # [기능명세] create_app.login
    # 목적: 시작 비밀번호 검증과 잠금 해제
    # 입력: (body: Login)
    # 출력: 성공 JSON 응답 및 HttpOnly 쿠키
    # 처리: UTF-8 비밀번호와 설정된 고정 값을 compare_digest로 비교
    # 예외/실패: 틀린 비밀번호는 HTTP 401; 길이 검증은 Login 모델 담당
    # 부수효과: 성공 시 실행별 잠금 해제 쿠키 발급; 파일·DB에 입력값을 저장하지 않음
    @app.post("/api/auth/login")
    def login(body: Login):
        if not secrets.compare_digest(body.password.encode("utf-8"), b"0000"):
            raise HTTPException(status_code=401, detail="비밀번호가 올바르지 않습니다.")
        response = JSONResponse({"authenticated": True})
        response.set_cookie("saebom_unlocked", unlocked_token, httponly=True, samesite="strict")
        return response

    # [기능명세] create_app.state
    # 목적: 화면 초기·주기 조회용 상태 반환
    # 입력: ()
    # 출력: 목록/작업/저장 경로/사이트 사전
    # 처리: 작업 잠금 조회와 Service.catalog 결과 합치기
    # 예외/실패: 잠금·실행 인증 선행; 저장 조회 오류 전파
    # 부수효과: DB·파일 존재 여부 읽기
    @app.get("/api/state")
    def state():
        with service.lock:
            jobs = list(service.jobs.values())[::-1]
        return {**service.catalog(), "jobs": jobs, "data_dir": str(store.root), "document_root": str(store.document_root()), "site": "https://sbgw.vercel.app/"}

    # [기능명세] create_app.settings
    # 목적: 저장 위치 변경 요청 처리
    # 입력: (body: Settings)
    # 출력: document_root 사전
    # 처리: 서비스 잠금→실행 작업 검사→Store.set_document_root
    # 예외/실패: 진행 작업은 ValueError; OSError를 안내 가능한 ValueError로 변환
    # 부수효과: 등록 PDF 이동과 DB 설정·경로 변경; 세부 원자성은 Store 명세 참조
    @app.put("/api/settings")
    def settings(body: Settings):
        with service.lock:
            if any(j["status"] == "running" for j in service.jobs.values()):
                raise ValueError("진행 중인 작업이 끝난 뒤 저장 위치를 변경해 주세요.")
            try:
                return {"document_root": store.set_document_root(body.document_root)}
            except OSError as e:
                raise ValueError(f"저장 위치를 바꾸지 못했습니다. 기존 설정과 원본 파일은 유지됩니다. 새 폴더의 쓰기 권한과 여유 공간을 확인해 주세요. ({type(e).__name__})")

    # [기능명세] create_app.pick_folder
    # 목적: Windows 기본 폴더 선택창 제공
    # 입력: ()
    # 출력: folder 문자열 또는 None 사전
    # 처리: 숨긴 Tk 창 생성→최상단 폴더 대화상자→finally에서 창 파괴
    # 예외/실패: 취소는 None; Tk·대화상자 오류 전파
    # 부수효과: 네이티브 대화상자 표시; 선택만으로 설정을 적용하지 않음
    @app.post("/api/settings/pick-folder")
    def pick_folder():
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            folder = filedialog.askdirectory(title="원본 PDF 저장 폴더 선택", initialdir=str(store.document_root().parent), parent=root)
            return {"folder": folder or None}
        finally:
            root.destroy()

    # [기능명세] create_app.sync
    # 목적: 목록 동기화 작업 접수
    # 입력: ()
    # 출력: 작업 ID 사전
    # 처리: Service.submit으로 sync 예약
    # 예외/실패: 진행 중·종료 중이면 ValueError
    # 부수효과: 백그라운드 사이트 수집 예약
    @app.post("/api/sync")
    def sync():
        return service.submit("목록 동기화", service.sync)

    # [기능명세] create_app.browser
    # 목적: 로그인용 사이트 브라우저 열기 작업 접수
    # 입력: ()
    # 출력: 작업 ID 사전
    # 처리: Service.submit으로 open_browser 예약
    # 예외/실패: 진행 중·종료 중이면 ValueError
    # 부수효과: 사이트 브라우저 탐색 예약
    @app.post("/api/browser")
    def browser():
        return service.submit("전용 브라우저", service.open_browser)

    # [기능명세] create_app.download
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

    # [기능명세] create_app.compare
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

    # [기능명세] create_app.results
    # 목적: 저장 이력 조회
    # 입력: ()
    # 출력: 결과 사전 목록
    # 처리: Store.results 호출
    # 예외/실패: 실행·잠금 인증 선행
    # 부수효과: DB 읽기
    @app.get("/api/results")
    def results():
        return store.results()

    # [기능명세] create_app.correct
    # 목적: 추출값 수동 보정 재비교 접수
    # 입력: (id: str, body: Correct)
    # 출력: 새 작업 ID 사전
    # 처리: 기존 결과 검색→문서·필드·범위·월 검사→보정 병합→부모 결과를 참조해 재비교
    # 예외/실패: 결과 부재 404, 허용하지 않은 보정 ValueError
    # 부수효과: 새 결과 생성 작업 예약; 원본 PDF·이전 결과는 변경하지 않음
    @app.post("/api/results/{id}/correct")
    def correct(id: str, body: Correct):
        result = next((r for r in store.results() if r["id"] == id), None)
        if not result:
            raise HTTPException(404, "결과를 찾을 수 없습니다.")
        valid_ids = {r["invoice"]["id"] for r in result["rows"]}
        fields = {"supply", "vat", "total", "month", "biz", "percent", "installment", "partner"}
        for docid, changes in body.overrides.items():
            if docid not in valid_ids or not changes.keys() <= fields:
                raise ValueError("수정할 문서 또는 항목이 잘못되었습니다.")
            for key, v in changes.items():
                if key in {"supply", "vat", "total", "percent", "installment"}:
                    if type(v) is not int or v < 0 or v > (100 if key == "percent" else 10**12):
                        raise ValueError("금액·차수·비율은 범위 안의 정수로 입력해 주세요.")
                elif not isinstance(v, str) or len(v) > 200:
                    raise ValueError("수정값을 200자 이내 문자열로 입력해 주세요.")
                elif key == "month":
                    try:
                        date.fromisoformat(v + "-01")
                    except ValueError:
                        raise ValueError("청구 월은 YYYY-MM 형식으로 입력해 주세요.")
        merged = {k: dict(v) for k, v in result.get("overrides", {}).items()}
        for k, v in body.overrides.items():
            merged.setdefault(k, {}).update(v)
        return service.submit("보정 후 재비교", service.run_compare, result["pairs"], merged, id)

    # [기능명세] create_app.document
    # 목적: 현재 경로의 원본 PDF 제공
    # 입력: (id: str)
    # 출력: inline application/pdf FileResponse
    # 처리: 문서 ID 조회→최신 경로 존재 확인→파일 응답
    # 예외/실패: 레코드 또는 파일 부재 HTTP 404
    # 부수효과: PDF 파일 읽기; 임의 사용자 경로를 입력받지 않음
    @app.get("/api/documents/{id}")
    def document(id: str):
        doc = store.document(id=id)
        if not doc or not store.path(doc).exists():
            raise HTTPException(404, "저장한 PDF를 찾을 수 없습니다. 다시 다운로드해 주세요.")
        return FileResponse(store.path(doc), media_type="application/pdf", filename=doc["name"], content_disposition_type="inline")

    # [기능명세] create_app.csv_result
    # 목적: 비교 결과를 CSV로 변환
    # 입력: (id: str)
    # 출력: UTF-8 BOM이 포함된 다운로드 Response
    # 처리: 결과 조회→항목별 행과 근거 작성→셀 수식 접두어 방어
    # 예외/실패: 결과 부재 HTTP 404
    # 부수효과: 메모리 CSV 생성; 서버 파일로 저장하지 않음
    @app.get("/api/results/{id}/csv")
    def csv_result(id: str):
        result = next((r for r in store.results() if r["id"] == id), None)
        if not result:
            raise HTTPException(404, "결과가 없습니다.")
        out = io.StringIO()
        writer = csv.writer(out)

        # [기능명세] create_app.csv_result.safe
        # 목적: CSV 셀 수식 해석 방지 문자열 변환
        # 입력: (v)
        # 출력: 안전한 셀 문자열
        # 처리: None을 빈 값으로, 그 외 문자열화 후 위험 접두 문자 앞에 작은따옴표 추가
        # 예외/실패: 의도된 문자열 변환이 전제
        # 부수효과: 없음
        def safe(v):
            s = "" if v is None else str(v)
            return "'" + s if s.startswith(("=", "+", "-", "@", "\t", "\r")) else s

        writer.writerow(["업체", "메일", "계약번호", "전체판정", "항목", "계산서", "계약·기준", "차이(계산서-기준)", "항목판정", "설명", "계산서 근거", "계약 근거"])
        for row in result["rows"]:
            for c in row["checks"] or [{"label": "문서 처리", "status": row["status"], "note": row["error"]}]:
                writer.writerow([safe(x) for x in (row["partner"], row["subject"], row["contract_id"], row["status"], c["label"], c.get("actual"), c.get("expected"), c.get("difference"), c["status"], c.get("note"), (c.get("invoice_source") or {}).get("quote"), (c.get("contract_source") or {}).get("quote"))])
        return Response("\ufeff" + out.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="saebom-{id[:8]}.csv"'})

    # [기능명세] create_app.stop
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

    # [기능명세] create_app.focus_window
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

    app.mount("/", StaticFiles(directory=static, html=True), name="ui")
    return app
