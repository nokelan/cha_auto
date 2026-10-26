# [파일 기능명세] '계약서 목록' 메뉴의 실제 사이트 통합 검증.
# 입력: 빌드된 frontend/dist, 설치된 Playwright Chromium, 그룹웨어 사이트(https://sbgw.vercel.app/#/contracts) 접속.
# 출력: tmp/contracts-review/<시각>/의 checks.json·화면 캡처·server.log. 사용자 DB·문서와 실행 중 앱은 변경하지 않는다.
# 처리: 빈 격리 데이터로 테스트 서버 실행 → 로그인 → 계약서 목록 메뉴에서 조건별 가져오기 4회(지출 최근 3개,
#   안 가져온 것 최근 3개, 안 가져온 것 전체, 재실행 0건) → 목록·원문 뷰어·반응형 확인.
# 실패: 단언·브라우저 오류를 전파하며 finally에서 테스트 서버와 로그를 정리한다.
# 주의: 기대 관리번호는 2026-10-21 사이트 기준(지출 15건, 수입 3건, 전체 18건)이다. 사이트 목록이 바뀌면 기대값을 갱신한다.
from pathlib import Path
from datetime import datetime
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
from playwright.sync_api import sync_playwright, expect


# [기능명세] start_server
# 목적: 격리 데이터 폴더로 앱 서버를 띄우고 접속 정보를 얻음
# 입력: (data: 데이터 폴더 Path, log: 서버 출력 파일 객체), 선택 환경변수 SAEBOM_VERIFY_EXE(검사할 배포 EXE 경로)
# 출력: (subprocess.Popen, base URL, token)
# 처리: SAEBOM_DATA_DIR·SAEBOM_NO_OPEN=1로 launcher.py 또는 SAEBOM_VERIFY_EXE 실행 → instance.json과 /health가 준비될 때까지 최대 15초 대기
# 예외/실패: 시간 안에 준비되지 않으면 RuntimeError
# 부수효과: 테스트 서버 프로세스·격리 데이터 폴더 생성
def start_server(data, log):
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


# [기능명세] wait_job
# 목적: 가장 최근 작업이 끝날 때까지 대기하고 결과를 반환
# 입력: (page: 로그인된 Page, timeout: 초, 기본 120)
# 출력: 최근 작업 사전(status·message·errors 등)
# 처리: 0.5초 간격으로 /api/state의 jobs[0]을 읽어 running이 아니면 반환
# 예외/실패: 시간 초과 시 AssertionError
# 부수효과: 없음(HTTP 읽기)
def wait_job(page, timeout=120):
    for _ in range(timeout*2):
        job = page.evaluate("async()=>(await(await fetch('/api/state')).json()).jobs[0]")
        if job and job['status'] != 'running':
            return job
        time.sleep(.5)
    raise AssertionError('가져오기 작업이 끝나지 않았습니다.')


# [기능명세] imported_ids
# 목적: 서버에 기록된 가져온 계약 관리번호 목록 조회
# 입력: (page)
# 출력: 관리번호 문자열 목록(서버 정렬 순서: 관리번호 큰 순)
# 처리: GET /api/contracts
# 예외/실패: 요청 실패는 Playwright 예외
# 부수효과: 없음
def imported_ids(page):
    return page.evaluate("async()=>(await(await fetch('/api/contracts')).json()).map(c=>c.id)")


# [기능명세] run_import
# 목적: 화면의 가져오기 조건을 입력하고 버튼을 눌러 작업 완료까지 대기
# 입력: (page, kind: '전체'|'수입'|'지출', limit: 개수 문자열('' 이면 전체), only_new: 체크 여부)
# 출력: 끝난 작업 사전
# 처리: 구분 select·개수 입력·체크박스 설정 → '계약서 가져오기' 클릭 → wait_job
# 예외/실패: 요소 미발견·작업 시간 초과 시 예외
# 부수효과: 서버가 사이트에서 계약 PDF를 내려받아 격리 데이터에 저장
def run_import(page, kind, limit, only_new):
    page.get_by_label('가져올 계약 구분').select_option(label=kind)
    page.get_by_label('가져올 개수').fill(limit)
    box = page.get_by_label('아직 가져오지 않은 계약만')
    box.check() if only_new else box.uncheck()
    page.get_by_role('button', name='계약서 가져오기', exact=True).click()
    time.sleep(.5)
    return wait_job(page)


# [기능명세] main
# 목적: 계약서 목록 기능의 조건별 가져오기와 화면 표시를 실제 사이트로 검증
# 입력: ()
# 출력: None; checks.json과 PNG 저장, 표준 출력에 검사 결과 JSON
# 처리: 서버 시작 → 로그인 → 계약서 목록 메뉴 → 4가지 조건 가져오기 단언 → 상세·원문 뷰어 → 390px 가로 넘침 검사
# 예외/실패: 단언 실패·JS 오류는 예외로 중단, finally에서 브라우저와 서버 종료
# 부수효과: tmp/contracts-review 아래 파일 생성, 사이트 네트워크 접속
def main():
    out = ROOT/'tmp/contracts-review'/datetime.now().strftime('%Y%m%d-%H%M%S')
    out.mkdir(parents=True)
    data = out/'data'
    log = (out/'server.log').open('w', encoding='utf-8')
    server, base, token = start_server(data, log)
    checks, errors = [], []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 960})
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base+'/?token='+token)
                page.get_by_label('비밀번호', exact=True).fill('0000')
                page.get_by_role('button', name='시작하기', exact=True).click()
                page.get_by_role('button', name='계약서 목록', exact=True).click()
                expect(page.get_by_role('button', name='계약서 가져오기', exact=True)).to_be_visible()
                expect(page.get_by_text('아직 가져온 계약서가 없습니다')).to_be_visible()

                job = run_import(page, '지출', '3', False)
                assert job['status'] == 'done', job
                ids = imported_ids(page)
                assert ids == ['C-2026-040', 'C-2026-039', 'C-2026-038'], ids
                checks.append({'expenseRecent3': ids})

                job = run_import(page, '지출', '3', True)
                assert job['status'] == 'done', job
                ids = imported_ids(page)
                assert ids[3:] == ['C-2026-037', 'C-2026-036', 'C-2026-035'], ids
                checks.append({'expenseNewRecent3': ids[3:]})

                job = run_import(page, '전체', '', True)
                assert job['status'] == 'done', job
                ids = imported_ids(page)
                assert len(ids) == 18 and len(set(ids)) == 18, ids
                checks.append({'allNew': len(ids)})

                job = run_import(page, '전체', '', True)
                assert job['status'] == 'done' and '가져올 계약이 없습니다' in job['message'], job
                checks.append({'nothingLeft': job['message']})

                contracts = page.evaluate("async()=>(await(await fetch('/api/contracts')).json())")
                assert all(c['document'] and c['document']['available'] for c in contracts), contracts
                assert all(c['document']['extraction']['pages'] == [] for c in contracts)
                checks.append({'allPdfSaved': True, 'pagesStripped': True})

                page.get_by_text('C-2026-040').first.click()
                expect(page.locator('.pdf canvas')).to_be_visible(timeout=20000)
                expect(page.locator('.pdf .spin, .pdf .error')).to_have_count(0, timeout=20000)
                page.screenshot(path=str(out/'contracts-desktop.png'), full_page=True)
                checks.append({'pdfViewer': True})

                page.set_viewport_size({'width': 390, 'height': 844})
                page.wait_for_timeout(300)
                overflow = page.evaluate("()=>document.documentElement.scrollWidth-document.documentElement.clientWidth")
                assert overflow <= 1, overflow
                page.screenshot(path=str(out/'contracts-mobile.png'), full_page=True)
                checks.append({'mobileNoOverflow': True})
                assert not errors, errors
                checks.append({'javascriptErrors': errors})
            finally:
                browser.close()
    finally:
        server.terminate()
        server.wait(timeout=20)
        log.close()
    (out/'checks.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'checks': checks, 'artifacts': str(out)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
