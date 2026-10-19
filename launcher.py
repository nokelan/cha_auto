# [파일 기능명세]
# 실행 진입점. Windows Mutex로 중복 실행을 막고 로컬 서버와 Chromium 앱 창의 수명을 관리한다. 입력은 환경변수·기존 instance.json이며, 종료 시 서버·브라우저·실행 정보를 정리한다.
# 유지보수: 함수·데이터 계약이 바뀌면 해당 기능명세와 실제 회귀 검사를 함께 갱신한다.

"""EXE entry point. Single instance, loopback server, browser launch, clean shutdown."""
import ctypes
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


# [기능명세] main
# 목적: 로컬 앱 전체 실행과 자원 수명 제어
# 입력: ()
# 출력: None; 중복 실행은 기존 창 활성화 후 반환
# 처리: Store·로그·Mutex 준비→서버 기동→앱 창 감시→정리
# 예외/실패: 앱 창 생성 실패는 RuntimeError; 외부 진입점에서 로그·오류창 처리
# 부수효과: 로컬 포트·instance.json·브라우저 프로필·로그 생성, 종료 시 실행 정보 삭제
def main():
    store = Store()
    logging.basicConfig(filename=store.root / "app.log", level=logging.INFO, encoding="utf-8", format="%(asctime)s %(levelname)s %(message)s")
    instance = store.root / "instance.json"
    mutex = None
    if os.name == "nt":
        kernel = ctypes.windll.kernel32
        kernel.CreateMutexW.restype = ctypes.c_void_p
        mutex = kernel.CreateMutexW(None, False, "Local\\SaebomCompare-" + __import__("hashlib").sha256(str(store.root).encode()).hexdigest()[:16])
        if kernel.GetLastError() == 183:
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
            return
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    static = root / "frontend" / "dist"
    token = secrets.token_urlsafe(32)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = None
    launch_error = []
    activate = threading.Event()
    window_done = threading.Event()

    # [기능명세] main.shutdown
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

    # [기능명세] main.ready
    # 목적: 서버 준비 후 앱 창을 열고 창 닫힘 감시
    # 입력: ()
    # 출력: None; 별도 데몬 스레드에서 실행
    # 처리: 최대 200회 준비 확인→Chromium 앱 모드→활성화 이벤트 처리→닫힘 시 shutdown
    # 예외/실패: 브라우저 예외를 launch_error에 기록; 정상 종료와 구분
    # 부수효과: Playwright·앱 프로필 사용, 창 종료 시 컨텍스트 정리 및 완료 이벤트 설정
    def ready():
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
                        shutdown()
                        window_done.set()
                else:
                    window_done.set()
                return
            time.sleep(.1)
    threading.Thread(target=ready, daemon=True).start()
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
