# [파일 기능명세]
# 실행 진입점. Windows Mutex로 중복 실행을 막고 로컬 서버와 Chromium 앱 창의 수명을 관리한다. 입력은 환경변수·기존 instance.json이며, 종료 시 서버·브라우저·실행 정보를 정리한다.
# 처리 흐름: main → Store·로그 준비 → _acquire_mutex(중복이면 _existing_instance로 기존 창 활성화 후 종료)
#           → _start_server(포트·토큰·Uvicorn 준비, instance.json 기록) → _run_window를 데몬 스레드로 실행 → server.run → 정리.
# 유지보수: 함수·데이터 계약이 바뀌면 해당 기능명세와 실제 회귀 검사를 함께 갱신한다.

"""EXE entry point. Single instance, loopback server, browser launch, clean shutdown."""
import ctypes
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import time
import urllib.request

import uvicorn

from saebom.api import create_app
from saebom.store import Store

# CreateMutexW 뒤 GetLastError가 이 값이면 같은 이름의 Mutex가 이미 있다(ERROR_ALREADY_EXISTS).
ERROR_ALREADY_EXISTS = 183


# [기능명세] _acquire_mutex
# 목적: 데이터 폴더별 Windows 단일 실행 Mutex 생성
# 입력: (store: Store)
# 출력: (mutex 핸들|None, already: 이미 실행 중인지)
# 처리: Windows가 아니면 (None, False). 앱 루트 경로 SHA-256 앞 16자로 'Local\SaebomCompare-…' Mutex 생성 → 183이면 already=True
# 예외/실패: Win32 호출 실패는 핸들 None으로 나타날 수 있음
# 부수효과: 프로세스 Mutex 핸들 생성(종료 시 main이 닫음)
def _acquire_mutex(store):
    if os.name != "nt":
        return None, False
    kernel = ctypes.windll.kernel32
    kernel.CreateMutexW.restype = ctypes.c_void_p
    mutex = kernel.CreateMutexW(None, False, "Local\\SaebomCompare-" + hashlib.sha256(str(store.root).encode()).hexdigest()[:16])
    return mutex, kernel.GetLastError() == ERROR_ALREADY_EXISTS


# [기능명세] _existing_instance
# 목적: 이미 실행 중인 앱 창을 앞으로 가져오기 요청
# 입력: (store: Store, instance: instance.json 경로)
# 출력: None
# 처리: 최대 40회(0.25초 간격) instance.json 읽기 → /health 200 확인 → 세션 쿠키로 /api/activate POST 후 반환
# 예외/실패: 파일 없음·접속 실패는 재시도; 40회 실패해도 조용히 반환
# 부수효과: 로컬 서버로 HTTP 요청; 반환 전 store 연결 닫기
def _existing_instance(store, instance):
    for _ in range(40):
        try:
            info = json.loads(instance.read_text())
            if urllib.request.urlopen(f"http://127.0.0.1:{info['port']}/health", timeout=1).status == 200:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{info['port']}/api/activate", data=b"{}",
                    headers={"Cookie": "saebom_session=" + info["token"], "Content-Type": "application/json"})
                urllib.request.urlopen(request, timeout=2).close()
                store.close()
                return
        except Exception:
            time.sleep(.25)
    store.close()


# [기능명세] _start_server
# 목적: 루프백 포트·실행 토큰·Uvicorn 서버 준비
# 입력: (store: Store, static: 프런트 빌드 폴더, instance: instance.json 경로, activate: 활성화 이벤트)
# 출력: (server: uvicorn.Server, sock: 바인딩된 소켓, port: int, token: str)
# 처리: 127.0.0.1 임의 포트 바인딩 → 토큰 생성 → create_app(shutdown 콜백·activate.set 연결) → Server 생성 → instance.json에 포트·토큰 기록
# 예외/실패: 소켓·파일 쓰기 오류 전파
# 부수효과: 로컬 포트 점유·instance.json 생성; 서버 실행(run)은 호출자가 담당
def _start_server(store, static, instance, activate):
    token = secrets.token_urlsafe(32)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = None

    # [기능명세] _start_server.shutdown
    # 목적: 서버의 정상 종료 요청
    # 입력: ()
    # 출력: None
    # 처리: 공유 Uvicorn 서버의 should_exit를 True로 설정
    # 예외/실패: server가 만들어진 뒤 콜백으로 호출하는 것이 전제
    # 부수효과: 서버 종료 플래그 변경; 파일을 즉시 삭제하지 않음
    def shutdown():
        server.should_exit = True

    app = create_app(store, static, token, shutdown, activate.set)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, access_log=False))
    instance.write_text(json.dumps({"port": port, "token": token}), encoding="utf-8")
    return server, sock, port, token


# [기능명세] _run_window
# 목적: 서버 준비 후 앱 창을 열고 창 닫힘 감시
# 입력: (server, store, root: 실행 루트(번들 browser 위치), port, token, activate: 활성화 이벤트, window_done: 완료 이벤트, launch_error: 오류 수집 리스트)
# 출력: None; 별도 데몬 스레드에서 실행
# 처리: 최대 200회(0.1초) 준비 확인 → SAEBOM_NO_OPEN=1이 아니면 Chromium 앱 모드 실행 → 활성화 이벤트 처리 → 닫힘 시 서버 종료 요청
# 예외/실패: 브라우저 예외를 launch_error에 기록; 정상 종료와 구분
# 부수효과: Playwright·앱 프로필 사용, 창 종료 시 컨텍스트 정리·server.should_exit 설정 및 완료 이벤트 설정
def _run_window(server, store, root, port, token, activate, window_done, launch_error):
    for _ in range(200):
        if server.started:
            if os.environ.get("SAEBOM_NO_OPEN") != "1":
                try:
                    from playwright.sync_api import sync_playwright
                    bundle = root / "browser"
                    if bundle.exists():
                        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundle)
                    with sync_playwright() as pw:
                        context = pw.chromium.launch_persistent_context(
                            str(store.root / "app-profile"), headless=False, no_viewport=True,
                            args=[f"--app=http://127.0.0.1:{port}/?token={token}", "--window-size=1440,960"],
                            ignore_default_args=["--enable-automation", "about:blank"])
                        try:
                            page = context.pages[0] if context.pages else context.wait_for_event("page")
                            while not server.should_exit and not page.is_closed():
                                try:
                                    if activate.is_set():
                                        activate.clear()
                                        page.bring_to_front()
                                    page.wait_for_timeout(200)
                                except Exception:
                                    if not page.is_closed():
                                        raise
                        finally:
                            context.close()
                except Exception as e:
                    launch_error.append(e)
                finally:
                    server.should_exit = True
                    window_done.set()
            else:
                window_done.set()
            return
        time.sleep(.1)


# [기능명세] main
# 목적: 로컬 앱 전체 실행과 자원 수명 제어
# 입력: ()
# 출력: None; 중복 실행은 기존 창 활성화 후 반환
# 처리: Store·로그 준비 → Mutex 확인(중복이면 _existing_instance) → _start_server → _run_window 데몬 스레드 → server.run → 정리
#       정리 순서: should_exit → 창 종료 최대 10초 대기 → instance.json 삭제 → 소켓 닫기 → Mutex 핸들 닫기
# 예외/실패: 앱 창 생성 실패는 RuntimeError; 외부 진입점에서 로그·오류창 처리
# 부수효과: 로컬 포트·instance.json·브라우저 프로필·로그 생성, 종료 시 실행 정보 삭제
def main():
    store = Store()
    logging.basicConfig(filename=store.root / "app.log", level=logging.INFO, encoding="utf-8", format="%(asctime)s %(levelname)s %(message)s")
    instance = store.root / "instance.json"
    mutex, already = _acquire_mutex(store)
    if already:
        _existing_instance(store, instance)
        return
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    static = root / "frontend" / "dist"
    activate = threading.Event()
    window_done = threading.Event()
    launch_error = []
    server, sock, port, token = _start_server(store, static, instance, activate)
    threading.Thread(target=_run_window, args=(server, store, root, port, token, activate, window_done, launch_error), daemon=True).start()
    try:
        server.run(sockets=[sock])
    finally:
        server.should_exit = True
        window_done.wait(timeout=10)
        instance.unlink(missing_ok=True)
        sock.close()
        if mutex:
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(mutex))
    if launch_error:
        raise RuntimeError("앱 창을 열지 못했습니다. " + str(launch_error[0]))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.exception("실행 실패")
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(None, f"실행하지 못했습니다.\n{e}\n\n%LOCALAPPDATA%\\SaebomCompare\\app.log를 확인해 주세요.", "새봄 문서비교", 16)
        else:
            raise
