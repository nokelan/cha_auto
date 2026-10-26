# [파일 기능명세] 인증 복귀(401)와 서버 연결 실패 문구의 화면 검증(실제 사이트에 접속하지 않음).
# 입력: 빌드된 frontend/dist, 설치된 Playwright Chromium. 데이터 폴더는 tmp/auth-recovery-review/<시각>/data에 새로 만든다(사용자 DB 미사용).
# 출력: 같은 폴더의 checks.json·server.log. 실패한 검사가 하나라도 있으면 종료코드 1, 모두 통과하면 0.
# 처리: 격리 서버 실행 → 로그인(0000) → '목록 새로고침'(POST /api/sync)을 Playwright 라우트로 가로채
#   (1) 401 응답 → 'saebom:unauthorized' 이벤트로 비밀번호 화면이 다시 보이고 만료 안내가 나오는지,
#       다시 로그인하면 메인 화면이 돌아오고 오류 안내가 사라지는지
#   (2) 연결 실패(abort) → App 상단 오류 알림에 "서버에 연결할 수 없습니다…" 한글 문구가 보이고 닫기 버튼으로 닫히는지
#   (3) 새 페이지에서 auth/status 연결 실패 → 비밀번호 화면 아래에 같은 한글 문구가 보이는지
#   (4) 로그인 화면의 auth/* 401(틀린 비밀번호)은 만료 문구가 아니라 서버 안내를 그대로 보이는지
#   를 확인한다. 가로챈 요청은 서버로 가지 않으므로 실제 동기화·사이트 접속이 일어나지 않는다.
# 셀렉터: 접근성 이름(버튼 텍스트, label, role=alert)을 쓴다. 화면 문구가 바뀌면 이 파일을 함께 고친다.
# 실패: 검사 실패는 기록하고 계속한다. finally에서 서버·로그를 정리한다.
from pathlib import Path
from datetime import datetime
import json
import os
import subprocess
import sys
import time
import traceback
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
from playwright.sync_api import sync_playwright, expect

# 화면이 보여야 하는 문구(frontend/src/api.ts, AccessGate.tsx와 같아야 한다).
EXPIRED = '로그인이 만료되었습니다. 비밀번호를 다시 입력해 주세요.'
UNREACHABLE = '서버에 연결할 수 없습니다. 프로그램이 실행 중인지 확인해 주세요.'


# [기능명세] Checks
# 목적: 검사 결과를 모으고 마지막에 실패 수를 센다
# 입력/출력: add(name, ok, detail) → ok, step(name, fn) → fn 반환값(예외 시 None), failed 속성
# 처리: add는 'PASS/FAIL 이름'을 출력, step은 예외를 삼키고 실패 검사로 기록
# 예외/실패: 자체 예외 없음. 부수효과: 표준 출력
class Checks:
    def __init__(self):
        self.items = []

    def add(self, name, ok, detail=None):
        ok = bool(ok)
        self.items.append({'name': name, 'ok': ok, 'detail': detail})
        print(('PASS ' if ok else 'FAIL ') + name + ('' if detail is None else f' :: {detail}'), flush=True)
        return ok

    def step(self, name, fn):
        try:
            return fn()
        except Exception as e:
            self.add('단계: ' + name, False, f'{type(e).__name__}: {e}\n{traceback.format_exc()[-1200:]}')
            return None

    @property
    def failed(self):
        return sum(1 for c in self.items if not c['ok'])


# [기능명세] start_server
# 목적: 새 데이터 폴더로 앱 서버를 띄우고 접속 정보를 얻는다
# 입력: (data: 데이터 폴더 Path, log: 서버 출력 파일 객체)
# 출력: (Popen, base URL, token)
# 처리: SAEBOM_DATA_DIR·SAEBOM_NO_OPEN=1로 launcher.py 또는 SAEBOM_VERIFY_EXE 배포본 실행 → instance.json과 /health가 준비될 때까지 최대 15초 대기
# 예외/실패: 시간 안에 준비되지 않으면 서버를 종료하고 RuntimeError. 부수효과: 서버 프로세스 생성
def start_server(data, log):
    data.mkdir(parents=True, exist_ok=True)
    executable = os.environ.get('SAEBOM_VERIFY_EXE')
    command = [str(Path(executable).resolve())] if executable else [sys.executable, 'launcher.py']
    server = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=log,
                              env={**os.environ, 'SAEBOM_DATA_DIR': str(data), 'SAEBOM_NO_OPEN': '1'})
    for _ in range(150):
        try:
            info = json.loads((data/'instance.json').read_text())
            base = f"http://127.0.0.1:{info['port']}"
            urllib.request.urlopen(base+'/health', timeout=1).close()
            return server, base, info['token']
        except Exception:
            time.sleep(.1)
    server.terminate()
    raise RuntimeError('독립 테스트 서버 시작 실패')


# [기능명세] login
# 목적: 비밀번호 화면에서 0000으로 로그인하고 메인 화면(사이드바)이 보일 때까지 기다린다
# 입력: (page: Page, password: 입력할 비밀번호)
# 출력: None. 예외/실패: 메인 화면이 10초 안에 안 보이면 Playwright 예외. 부수효과: 입력·클릭
def login(page, password='0000'):
    page.get_by_label('비밀번호', exact=True).fill(password)
    page.get_by_role('button', name='시작하기', exact=True).click()
    expect(page.get_by_role('button', name='프로그램 종료', exact=True)).to_be_visible(timeout=10000)


# [기능명세] main
# 목적: 인증 복귀·연결 실패 문구 검증 전체 실행
# 입력: 없음. 출력: 종료코드(실패 있으면 1)
# 처리: 위 파일 머리말의 단계 (1)~(4)를 순서대로 실행하고 마지막에 JavaScript 오류 0건을 확인한다
# 예외/실패: 단계별 예외는 실패 검사로 기록. 부수효과: tmp/auth-recovery-review 아래 파일 생성, 테스트 서버 실행·종료
def main():
    out = ROOT/'tmp/auth-recovery-review'/datetime.now().strftime('%Y%m%d-%H%M%S')
    out.mkdir(parents=True)
    checks = Checks()
    errors = []
    server = None
    log = (out/'server.log').open('w', encoding='utf-8')
    try:
        started = checks.step('테스트 서버 시작', lambda: start_server(out/'data', log))
        if not started:
            return finish(out, checks)
        server, base, token = started
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 900})
                page.on('pageerror', lambda error: errors.append(str(error)))
                refresh = page.get_by_role('button', name='목록 새로고침', exact=True)

                def first_login():
                    page.goto(base+'/?token='+token)
                    login(page)
                    expect(refresh).to_be_visible(timeout=10000)
                    return True
                if not checks.step('로그인', first_login):
                    return finish(out, checks)

                # (1) 401 복귀: 작업 요청이 401을 받으면 비밀번호 화면으로 돌아가야 한다.
                def unauthorized():
                    handler = lambda route: route.fulfill(status=401, json={'detail': '인증이 필요합니다.'})
                    page.route('**/api/sync', handler)
                    try:
                        refresh.click()
                        expect(page.get_by_label('비밀번호', exact=True)).to_be_visible(timeout=10000)
                        checks.add('401 → 비밀번호 화면 재표시', True)
                        checks.add('401 → 만료 안내 문구', EXPIRED in page.locator('body').inner_text())
                        checks.add('401 → 메인 화면 사라짐', page.get_by_role('button', name='프로그램 종료', exact=True).count() == 0)
                        page.screenshot(path=str(out/'401-login-screen.png'))
                    finally:
                        page.unroute('**/api/sync', handler)
                    login(page)
                    expect(refresh).to_be_visible(timeout=10000)
                    checks.add('401 후 재로그인 → 메인 화면 복귀', True)
                    checks.add('재로그인 후 만료 문구 없음', EXPIRED not in page.locator('body').inner_text())
                    return True
                checks.step('401 복귀', unauthorized)

                # (2) 연결 실패: 서버가 꺼진 것과 같은 TypeError를 fetch에 일으키면 한글 안내가 나와야 한다.
                def unreachable():
                    handler = lambda route: route.abort('failed')
                    page.route('**/api/sync', handler)
                    try:
                        refresh.click()
                        alert = page.get_by_role('alert').filter(has_text=UNREACHABLE)
                        expect(alert).to_be_visible(timeout=10000)
                        checks.add('연결 실패 → 한글 안내 알림', True)
                        checks.add('연결 실패 → 영문 Failed to fetch 미노출', 'Failed to fetch' not in page.locator('body').inner_text())
                        page.screenshot(path=str(out/'unreachable-alert.png'))
                        alert.get_by_role('button', name='오류 닫기').click()
                        expect(alert).to_have_count(0)
                        checks.add('연결 실패 알림 닫기', True)
                    finally:
                        page.unroute('**/api/sync', handler)
                    return True
                checks.step('연결 실패 문구', unreachable)

                # (3) 시작 화면에서 auth/status 연결 실패: 새 컨텍스트에서 확인한다(쿠키 없이도 같은 문구).
                def gate_unreachable():
                    other = browser.new_page(viewport={'width': 1440, 'height': 900})
                    try:
                        other.route('**/api/auth/status', lambda route: route.abort('failed'))
                        other.goto(base+'/?token='+token)
                        expect(other.get_by_text(UNREACHABLE)).to_be_visible(timeout=10000)
                        checks.add('시작 화면 연결 실패 안내', True)
                    finally:
                        other.close()
                    return True
                checks.step('시작 화면 연결 실패', gate_unreachable)

                # (4) 로그인 화면의 틀린 비밀번호(auth/login 401)는 만료 문구가 아니라 서버 안내를 보인다.
                def wrong_password():
                    other = browser.new_page(viewport={'width': 1440, 'height': 900})
                    try:
                        other.goto(base+'/?token='+token)
                        other.get_by_label('비밀번호', exact=True).fill('9999')
                        other.get_by_role('button', name='시작하기', exact=True).click()
                        alert = other.get_by_role('alert')
                        expect(alert).to_be_visible(timeout=10000)
                        text = alert.inner_text()
                        checks.add('틀린 비밀번호는 서버 안내 표시', '올바르지' in text and EXPIRED not in text, text)
                    finally:
                        other.close()
                    return True
                checks.step('틀린 비밀번호 안내', wrong_password)

                checks.add('JavaScript 오류 0건', not errors, errors)
            finally:
                browser.close()
    finally:
        if server:
            server.terminate()
            server.wait(timeout=20)
        log.close()
    return finish(out, checks)


# [기능명세] finish
# 목적: 검사 결과를 저장하고 종료코드를 정한다
# 입력: (out: 출력 폴더, checks: Checks). 출력: 0(모두 통과) 또는 1(실패 또는 검사 0건)
# 처리: checks.json 저장 후 요약 JSON 출력. 예외/실패: 파일 쓰기 오류 전파. 부수효과: 파일 생성, 표준 출력
def finish(out, checks):
    (out/'checks.json').write_text(json.dumps(checks.items, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    summary = {'passed': len(checks.items) - checks.failed, 'failed': checks.failed,
               'failures': [c['name'] for c in checks.items if not c['ok']], 'artifacts': str(out)}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if checks.failed or not checks.items else 0


if __name__ == '__main__':
    sys.stdout.reconfigure(errors='replace')
    sys.exit(main())
