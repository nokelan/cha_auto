# [파일 기능명세] '거래명세서 생성' 기능의 화면 통합 검증(실제 그룹웨어 사이트에 접속하지 않음).
# 입력: 빌드된 frontend/dist, 설치된 Playwright Chromium, tests/fixtures의 계약서 PDF 2건
#   (C-2026-002 세움바이오 = 수입, C-2026-011 세움네트웍스 = 지출).
# 출력: tmp/statement-review/<시각>/의 checks.json·화면 캡처(PNG)·내려받은 xlsx·server.log.
#   실패한 검사가 하나라도 있으면 종료코드 1, 모두 통과하면 0.
# 처리: 격리 데이터 폴더 준비(Store에 PDF 사본을 문서로 등록 + 계약서 목록 행 등록) → 테스트 서버 실행 → 로그인
#   → 계약서 목록 → C-2026-002 선택 → '거래명세서 생성' → 확인 창 기본값 검사 → 생성 → 결과 파일명·총계 확인
#   → 내려받기(xlsx 열어 값·수식 확인) → C-2026-011 지출결의서 버튼·확인 창 확인(상신하지 않음) → 390px 폭에서 확인 창 캡처.
# 격리: 사용자 DB(LOCALAPPDATA)와 fixture 원본은 건드리지 않는다. PDF는 출력 폴더로 복사해서 등록한다.
# 셀렉터: 프런트 DOM 대신 접근성 이름(버튼 텍스트, role=dialog, 입력 label)으로 찾는다. 화면 문구가 바뀌면 이 파일을 함께 고친다.
# 실패: 검사 실패는 기록하고 다음 검사를 계속한다. 브라우저·서버 오류는 해당 단계 실패로 기록하며 finally에서 서버와 로그를 정리한다.
from pathlib import Path
from datetime import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright, expect

from saebom.compare import extract
from saebom.files import KIND_FOLDERS, safe_name
from saebom.store import Store

FIXTURES = ROOT / 'tests' / 'fixtures'
FILE_BASE = 'https://sbgw.vercel.app/files/'
# 검증 대상 계약 행. 형식은 site.fetch_contracts의 계약 행과 같다: {id, kind, partner, title, period, amount_text, file{name,url}}.
CONTRACTS = [
    {'id': 'C-2026-002', 'kind': '수입', 'partner': '세움바이오(주)', 'title': '웹방화벽 서비스 유지보수 계약서',
     'period': '2026-01-01 ~ 2026-12-31', 'amount_text': '190,000원', 'pdf': '계약서_C-2026-002_세움바이오_웹방화벽.pdf'},
    {'id': 'C-2026-011', 'kind': '지출', 'partner': '세움네트웍스', 'title': '네트워크 장비 임대 및 유지보수 계약서',
     'period': '2026-01-01 ~ 2027-12-31', 'amount_text': '3,150,000원', 'pdf': '계약서_C-2026-011_세움네트웍스_네트워크유지보수.pdf'},
]
# C-2026-002의 기대 초안·결과값(계획서 검증 4번 기준: 월 190,000원 × 12개월, 부가세 별도).
EXPECT = {
    'customer': '세움바이오(주)', 'issue_date': '2025-12-10', 'from_month': '2026-01', 'to_month': '2026-12',
    'item_name': '웹방화벽 서비스 유지보수', 'item_spec': '인재 채용 홈페이지', 'monthly_amount': '190000',
    'supply': '2,280,000', 'vat': '228,000', 'total': '2,508,000', 'rows': 12,
    'file': '거래명세서_C-2026-002_세움바이오(주).xlsx',
}


# [기능명세] Checks
# 목적: 검사 결과를 모아 두고 마지막에 실패 여부를 판정
# 입력: 없음(생성 시 빈 목록)
# 출력: items(검사 사전 목록), failed(실패 수) 속성
# 처리: add(name, ok, detail)로 {name, ok, detail}을 추가하고 콘솔에 한 줄 출력. step(name, fn)은 fn 실행 중 예외를 실패로 기록
# 예외/실패: 자체 예외 없음. step은 예외를 삼키고 traceback 마지막 부분을 detail에 남긴다
# 부수효과: 표준 출력
class Checks:
    def __init__(self):
        self.items = []

    # [기능명세] Checks.add
    # 목적: 검사 한 건 기록
    # 입력: (name: 검사 이름, ok: 통과 여부, detail: 실제값 등 참고 정보)
    # 출력: ok(bool) — 호출자가 이어서 분기할 수 있게 그대로 돌려준다
    # 처리: 사전 추가 후 'PASS/FAIL 이름 detail' 출력
    # 예외/실패: 없음
    # 부수효과: items 추가, 표준 출력
    def add(self, name, ok, detail=None):
        ok = bool(ok)
        self.items.append({'name': name, 'ok': ok, 'detail': detail})
        print(('PASS ' if ok else 'FAIL ') + name + ('' if detail is None else f' :: {detail}'), flush=True)
        return ok

    # [기능명세] Checks.step
    # 목적: 화면 단계 하나를 실행하고 예외를 실패 검사로 바꿔 다음 단계가 계속되게 함
    # 입력: (name: 단계 이름, fn: 인자 없는 함수)
    # 출력: fn의 반환값, 예외가 나면 None
    # 처리: fn 실행 → 예외 시 '단계: name' 실패 기록(예외 문자열과 traceback 끝 1200자)
    # 예외/실패: 예외를 다시 던지지 않는다
    # 부수효과: 실패 시 items 추가
    def step(self, name, fn):
        try:
            return fn()
        except Exception as e:
            self.add('단계: ' + name, False, f'{type(e).__name__}: {e}\n{traceback.format_exc()[-1200:]}')
            return None

    @property
    def failed(self):
        return sum(1 for c in self.items if not c['ok'])


# [기능명세] seed_data
# 목적: 격리 데이터 폴더에 fixture 계약서 2건을 '계약서 목록'으로 가져온 상태처럼 만든다
# 입력: (data: 앱 데이터 폴더 Path, pdf_root: 원본 PDF 저장 위치 Path)
# 출력: None
# 처리: Store(root=data) 열기 → set_document_root(pdf_root)(등록 문서가 없으므로 폴더만 준비)
#   → 계약마다 fixture PDF를 pdf_root/계약서/{해시12}_{safe_name}으로 복사 → compare.extract(kind="contract")로 판독
#   → save_document(url, name, sha256, extraction, path, kind="contract") → save_contract_import(계약 행) → Store 닫기
# 예외/실패: fixture 없음·판독 오류(extraction.error)는 RuntimeError; DB·파일 오류 전파
# 부수효과: data/saebom.sqlite3 생성, pdf_root 아래 폴더·PDF 사본 생성. fixture 원본은 읽기만 한다
def seed_data(data, pdf_root):
    store = Store(root=data)
    try:
        store.set_document_root(str(pdf_root))
        folder = pdf_root / KIND_FOLDERS['contract']
        folder.mkdir(parents=True, exist_ok=True)
        for c in CONTRACTS:
            source = FIXTURES / c['pdf']
            if not source.is_file():
                raise RuntimeError(f'fixture PDF가 없습니다: {source}')
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            target = folder / (digest[:12] + '_' + safe_name(c['pdf']))
            shutil.copy2(source, target)
            extraction = extract(target, 'contract')
            if extraction.get('error'):
                raise RuntimeError(f"{c['id']} 판독 실패: {extraction['error']}")
            url = FILE_BASE + c['pdf']
            store.save_document(url, c['pdf'], digest, extraction, target, kind='contract')
            row = {k: c[k] for k in ('id', 'kind', 'partner', 'title', 'period', 'amount_text')}
            row['file'] = {'name': c['pdf'], 'url': url}
            store.save_contract_import(row)
    finally:
        store.close()


# [기능명세] start_server
# 목적: 격리 데이터 폴더로 앱 서버를 띄우고 접속 정보를 얻음(verify_contracts.py와 같은 방식)
# 입력: (data: 데이터 폴더 Path, log: 서버 출력 파일 객체)
# 출력: (subprocess.Popen, base URL, token)
# 처리: SAEBOM_DATA_DIR·SAEBOM_NO_OPEN=1로 launcher.py 또는 SAEBOM_VERIFY_EXE 환경변수의 배포본 실행 → instance.json과 /health가 준비될 때까지 최대 15초 대기
# 예외/실패: 시간 안에 준비되지 않으면 서버를 종료하고 RuntimeError
# 부수효과: 테스트 서버 프로세스 생성, data 폴더에 instance.json·app.log 생성
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


# [기능명세] digits
# 목적: 화면 입력값의 숫자만 남겨 금액 비교에 쓴다
# 입력: (text: 문자열 또는 None)
# 출력: 숫자 문자만 이은 문자열('190,000' → '190000')
# 처리: 정규식으로 숫자 아닌 문자 제거
# 예외/실패: 없음
# 부수효과: 없음
def digits(text):
    return re.sub(r'\D', '', text or '')


# [기능명세] open_contract
# 목적: 계약서 목록에서 관리번호로 계약을 선택하고 상세가 열릴 때까지 대기
# 입력: (page: 로그인된 Page, contract_id: 관리번호)
# 출력: 상세 영역 Locator(role=region, 이름 '계약 상세')
# 처리: 이름에 관리번호가 들어간 첫 버튼(목록 행) 클릭 → 상세 영역에 관리번호 표시 대기
# 예외/실패: 요소 미발견·시간 초과 시 Playwright 예외
# 부수효과: 화면 선택 상태 변경
def open_contract(page, contract_id):
    page.get_by_role('button', name=re.compile(re.escape(contract_id))).first.click()
    detail = page.get_by_role('region', name='계약 상세')
    expect(detail).to_contain_text(contract_id, timeout=10000)
    return detail


# [기능명세] statement_button
# 목적: 계약 상세의 '거래명세서 생성' 버튼 찾기(확인 창 안의 같은 이름 버튼과 구분)
# 입력: (page)
# 출력: Locator
# 처리: role=region '계약 상세' 안에서 이름이 정확히 '거래명세서 생성'인 버튼(확인 창은 body 포털이라 영역 밖)
# 예외/실패: 없음(Locator는 지연 평가)
# 부수효과: 없음
def statement_button(page):
    return page.get_by_role('region', name='계약 상세').get_by_role('button', name='거래명세서 생성', exact=True)


# [기능명세] check_defaults
# 목적: 확인 창의 기본값이 C-2026-002 계약서 값과 같은지 검사
# 입력: (dialog: role=dialog Locator, checks: Checks)
# 출력: None
# 처리: 3단 편집 화면의 마크다운 원문(textarea)에서 수신·작성 일자·청구 시작/끝 월 라벨과 품목 표 첫 행을 읽어 EXPECT와 비교,
#   미리보기 영역의 줄 수(12)·예상 총계 문자열 포함 여부 확인
# 예외/실패: 입력 미발견은 Playwright 예외(호출한 step이 실패로 기록)
# 부수효과: checks 추가
def check_defaults(dialog, checks):
    # 3단 편집 화면: 좌측 마크다운 원문(textarea)에서 라벨 목록과 품목 표를 읽는다.
    md = dialog.get_by_label('마크다운 원문').input_value()

    def label(name):
        m = re.search(r'^- ' + re.escape(name) + r':[ \t]*(.*)$', md, re.M)
        return m.group(1).strip() if m else None

    rows = [[c.strip() for c in line.strip().strip('|').split('|')] for line in md.splitlines() if line.startswith('|')]
    data_rows = rows[2:]  # 머리글·구분선 다음이 품목 행
    first = data_rows[0] if data_rows else ['', '', '']
    values = {
        'customer': label('수신'),
        'issue_date': label('작성 일자'),
        'from_month': label('청구 시작 월'),
        'to_month': label('청구 끝 월'),
        'item_name': first[0],
        'item_spec': first[1],
        'monthly_amount': digits(first[2]),
    }
    for key, value in values.items():
        checks.add(f'기본값 {key}', value == EXPECT[key], {'actual': value, 'expected': EXPECT[key]})
    text = dialog.inner_text()
    checks.add('기본값 품목 1개', len(data_rows) == 1, len(data_rows))
    checks.add('미리보기 12줄', re.search(r'=\s*12\s*줄', text) is not None, text[-400:])
    checks.add('미리보기 예상 총계', all(EXPECT[k] in text for k in ('supply', 'vat', 'total')),
               [EXPECT[k] for k in ('supply', 'vat', 'total')])


# [기능명세] check_xlsx
# 목적: 내려받은 거래명세서 엑셀의 값·수식을 간단히 확인
# 입력: (path: xlsx Path, checks: Checks)
# 출력: None
# 처리: openpyxl로 열기 → 13~24행 B열 품목·D열 월금액 12줄, 25행 이후 빈 줄, F13·F25 수식 유지, fullCalcOnLoad 확인
# 예외/실패: 파일 손상 등은 예외(호출한 step이 실패로 기록)
# 부수효과: checks 추가, 파일 읽기
def check_xlsx(path, checks):
    import openpyxl
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    names = [ws[f'B{r}'].value for r in range(13, 25)]
    amounts = [ws[f'D{r}'].value for r in range(13, 25)]
    checks.add('엑셀 12줄 품목', names == [EXPECT['item_name']] * 12, names)
    checks.add('엑셀 12줄 월금액', amounts == [int(EXPECT['monthly_amount'])] * 12, amounts)
    checks.add('엑셀 F·H 수식 유지', str(ws['F13'].value).startswith('=') and str(ws['H24'].value).startswith('='),
               [ws['F13'].value, ws['H24'].value])
    checks.add('엑셀 25행 합계 수식 유지', ws['F25'].value == '=SUM(F13:F24)', ws['F25'].value)
    calc = getattr(wb, 'calculation', None)
    checks.add('엑셀 fullCalcOnLoad', bool(calc and calc.fullCalcOnLoad), getattr(calc, 'fullCalcOnLoad', None))


# [기능명세] check_modal_keys
# 목적: 공용 Modal(components/Modal.tsx)의 키보드·접근성 규칙을 한 모달에서 검사한다.
# 입력: (page: 로그인된 Page, checks: Checks, label: 검사 이름 머리말, opener: 모달을 여는 버튼 Locator)
# 출력: None
# 처리: opener 포커스·클릭 → role=dialog 1개 확인 → aria-modal·aria-labelledby가 실제 제목을 가리키는지,
#   body 스크롤 잠금(overflow=hidden), 배경 클릭으로 닫히지 않음, Tab 12회·Shift+Tab 12회 동안 포커스가 창 밖으로 나가지 않음,
#   Esc로 닫힘, 닫은 뒤 스크롤 잠금 해제(overflow 비움), 연 버튼으로 포커스 복귀를 차례로 검사한다.
# 예외/실패: 요소 미발견·시간 초과는 Playwright 예외(호출한 step이 실패로 기록). 부수효과: checks 추가, 모달 열기·닫기
def check_modal_keys(page, checks, label, opener):
    opener.focus()
    opener.click()
    dialog = page.get_by_role('dialog')
    expect(dialog).to_have_count(1, timeout=10000)
    labelled = dialog.get_attribute('aria-labelledby')
    checks.add(label + ' dialog 속성', dialog.get_attribute('aria-modal') == 'true' and bool(labelled)
               and page.locator('#' + (labelled or 'none')).count() == 1, labelled)
    checks.add(label + ' 스크롤 잠금', page.evaluate('document.body.style.overflow') == 'hidden')
    page.mouse.click(2, 2)
    checks.add(label + ' 배경 클릭으로 안 닫힘', dialog.count() == 1)
    inside = "()=>document.querySelector('[role=dialog]').contains(document.activeElement)"
    trapped = True
    for key in ['Tab'] * 12 + ['Shift+Tab'] * 12:
        page.keyboard.press(key)
        trapped = trapped and page.evaluate(inside)
    checks.add(label + ' 포커스 트랩', trapped)
    page.keyboard.press('Escape')
    expect(dialog).to_have_count(0)
    checks.add(label + ' Esc로 닫힘', True)
    checks.add(label + ' 스크롤 잠금 해제', page.evaluate('document.body.style.overflow') == '')
    checks.add(label + ' 포커스 복귀', opener.evaluate('el => el === document.activeElement'))


# [기능명세] main
# 목적: 거래명세서 생성 화면 흐름 전체를 격리 환경에서 검증하고 결과를 저장
# 입력: ()
# 출력: 종료코드(실패 검사가 있으면 1, 없으면 0). checks.json·PNG·xlsx를 출력 폴더에 저장하고 요약 JSON을 표준 출력
# 처리: 출력 폴더 생성 → seed_data → start_server → Chromium(1440×960) 로그인 → 계약서 목록
#   → 002: 버튼 활성 → 확인 창 기본값 → 생성 → 결과(파일명·총계) → 저장 폴더에 파일 존재 → 내려받기·xlsx 검사
#   → API 보조 검사(002 초안 eligible, 011 eligible=false·POST 400, 다운로드 경로 조작 404)
#   → 011: 거래명세서 버튼 없음·지출결의서 확인 창 열기(상신 없음) → 390×844: 002 확인 창 열기·가로 넘침 검사·캡처 → JS 오류 0건
# 예외/실패: 단계별 예외는 실패 검사로 기록하고 계속 진행. 시드·서버 시작 실패는 즉시 실패로 끝낸다
# 부수효과: tmp/statement-review 아래 파일 생성, 테스트 서버 실행·종료. 실제 사이트·사용자 DB에는 접속·변경하지 않는다
def main():
    out = ROOT/'tmp/statement-review'/datetime.now().strftime('%Y%m%d-%H%M%S')
    out.mkdir(parents=True)
    data = out/'data'
    pdf_root = out/'pdf-root'
    checks = Checks()
    errors = []
    server = None
    log = (out/'server.log').open('w', encoding='utf-8')
    try:
        if checks.step('격리 데이터 준비', lambda: seed_data(data, pdf_root) or True) is None:
            return finish(out, checks)
        started = checks.step('테스트 서버 시작', lambda: start_server(data, log))
        if not started:
            return finish(out, checks)
        server, base, token = started
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 960}, accept_downloads=True)
                # pageerror 콜백 명세: 입력은 브라우저 예외, 출력 None. errors에 누적해 마지막에 0건을 검사한다.
                page.on('pageerror', lambda error: errors.append(str(error)))

                # 단계 1: 로그인 → 계약서 목록
                def login():
                    page.goto(base+'/?token='+token)
                    page.get_by_label('비밀번호', exact=True).fill('0000')
                    page.get_by_role('button', name='시작하기', exact=True).click()
                    page.get_by_role('button', name='계약서 목록', exact=True).click()
                    expect(page.get_by_role('button', name=re.compile('C-2026-002')).first).to_be_visible(timeout=10000)
                    return True
                if not checks.step('로그인·계약서 목록', login):
                    return finish(out, checks)
                checks.add('목록에 시드 계약 2건', page.get_by_role('button', name=re.compile('C-2026-011')).count() > 0)

                # 단계 2: C-2026-002 확인 창 기본값
                def open_002():
                    open_contract(page, 'C-2026-002')
                    button = statement_button(page)
                    checks.add('002 버튼 활성', button.is_enabled())
                    button.click()
                    dialog = page.get_by_role('dialog')
                    expect(dialog).to_be_visible(timeout=10000)
                    page.screenshot(path=str(out/'statement-modal-desktop.png'), full_page=True)
                    check_defaults(dialog, checks)
                    return dialog
                dialog = checks.step('002 확인 창 열기·기본값', open_002)

                # 단계 3: 생성 → 결과 화면
                result_file = None
                if dialog is not None:
                    def generate():
                        # exact: 닫기 버튼 이름('거래명세서 생성 닫기')과 구분
                        dialog.get_by_role('button', name='거래명세서 생성', exact=True).click()
                        expect(dialog.get_by_role('link', name='내려받기')).to_be_visible(timeout=20000)
                        page.screenshot(path=str(out/'statement-result-desktop.png'), full_page=True)
                        text = dialog.inner_text()
                        name = next((line.strip() for line in text.splitlines() if line.strip().endswith('.xlsx')), None)
                        checks.add('결과 파일명', name == EXPECT['file'], {'actual': name, 'expected': EXPECT['file']})
                        for key in ('supply', 'vat', 'total'):
                            checks.add(f'결과 총계 {key}', EXPECT[key] in text, EXPECT[key])
                        checks.add('결과 12줄', re.search(r'12\s*줄', text) is not None)
                        saved = pdf_root/'거래명세서'/EXPECT['file']
                        checks.add('저장 폴더에 파일 생성', saved.is_file(), str(saved))
                        return name
                    result_file = checks.step('002 거래명세서 생성', generate)

                # 단계 4: 내려받기 링크로 xlsx 받기
                if result_file:
                    def download():
                        with page.expect_download(timeout=20000) as info:
                            dialog.get_by_role('link', name='내려받기').click()
                        dl = info.value
                        target = out/(dl.suggested_filename or 'statement.xlsx')
                        dl.save_as(target)
                        head = target.read_bytes()[:2]
                        checks.add('내려받기 성공(xlsx ZIP 서명)', head == b'PK', {'file': target.name, 'size': target.stat().st_size})
                        checks.add('내려받기 파일명', dl.suggested_filename == EXPECT['file'], dl.suggested_filename)
                        check_xlsx(target, checks)
                        return True
                    checks.step('내려받기', download)

                    def close_dialog():
                        dialog.get_by_role('button', name='닫기', exact=True).click()
                        expect(page.get_by_role('dialog')).to_have_count(0)
                        return True
                    checks.step('확인 창 닫기', close_dialog)

                # 단계 5: API 보조 검사(화면과 같은 세션 쿠키 사용)
                def api_checks():
                    d = page.request.get(base+'/api/contracts/C-2026-002/statement')
                    body = d.json() if d.ok else {}
                    checks.add('API 002 초안 eligible', d.ok and body.get('eligible') is True, {'status': d.status})
                    e = page.request.get(base+'/api/contracts/C-2026-011/statement')
                    ebody = e.json() if e.ok else {}
                    checks.add('API 011 eligible=false', e.ok and ebody.get('eligible') is False, {'status': e.status, 'reason': ebody.get('reason')})
                    p = page.request.post(base+'/api/contracts/C-2026-011/statement', headers={'Origin': base}, data={
                        'customer': '세움네트웍스', 'issue_date': '2026-01-01', 'from_month': '2026-01', 'to_month': '2026-01',
                        'items': [{'name': '시험', 'spec': '', 'monthly_amount': 1000}]})
                    checks.add('API 011 생성 400', p.status == 400, p.status)
                    n = page.request.get(base+'/api/contracts/C-2026-999/statement')
                    checks.add('API 없는 계약 404', n.status == 404, n.status)
                    bad = page.request.get(base+'/api/statements/..%2F..%2Fdata%2Fsaebom.sqlite3')
                    checks.add('API 다운로드 경로 조작 404', bad.status == 404, bad.status)
                    return True
                checks.step('API 보조 검사', api_checks)

                # 단계 6: 지출 계약은 지출결의서 확인 창을 제공하며 거래명세서 생성은 API에서도 거절한다.
                # [기능명세] expense
                # 목적: 지출 계약의 작업 버튼 전환과 확인 창을 실제 상신 없이 검사한다.
                # 입력: 없음(바깥 page·checks 사용). 출력: True.
                # 처리: 상세에서 거래명세서 버튼 부재·지출결의서 버튼 활성 확인 → 확인 창 열기·닫기.
                # 예외/실패: UI 조건 불일치는 검사 실패 또는 Playwright 예외. 부수효과: 초안 HTTP 조회·PNG 저장만 수행한다.
                def expense():
                    open_contract(page, 'C-2026-011')
                    detail = page.get_by_role('region', name='계약 상세')
                    checks.add('011 거래명세서 버튼 없음', detail.get_by_role('button', name='거래명세서 생성', exact=True).count() == 0)
                    button = detail.get_by_test_id('expense-open')
                    expect(button).to_be_visible(timeout=10000)
                    checks.add('011 지출결의서 버튼 활성', button.is_enabled())
                    checks.add('011 상태 기본값 없음', detail.get_by_test_id('contract-status').inner_text() == '없음')
                    button.click()
                    modal = page.get_by_test_id('expense-modal')
                    expect(modal).to_be_visible(timeout=10000)
                    checks.add('011 지출결의서 확인 창', 'C-2026-011' in modal.inner_text())
                    page.screenshot(path=str(out/'expense-draft-desktop.png'), full_page=True)
                    page.keyboard.press('Escape')
                    expect(modal).to_have_count(0)
                    return True
                checks.step('011 지출결의서 작업 버튼·확인 창', expense)

                # 단계 6-2: 서버가 approval.site_draft=true를 주는 경우의 경고 표시(R1-6). 응답을 가로채 주입하므로 실제 상신·사이트 접속 없음.
                # [기능명세] site_draft_warning
                # 목적: 계약 목록·초안 응답에 site_draft가 실리면 상태 배지 옆 경고, 상세 알림, 확인 창 경고가 보이고 '없음' 의미는 유지되는지 검사.
                # 입력: 없음(바깥 page·checks). 출력: True.
                # 처리: /api/contracts 와 /api/contracts/C-2026-011/expense 응답의 approval을 site_draft 포함 값으로 바꿔 돌려주고, 목록 화면으로 다시 진입해 검사.
                # 예외/실패: 조건 불일치는 검사 실패. 부수효과: 라우트 핸들러 등록(끝에서 해제), 화면 이동.
                def site_draft_warning():
                    warn = '그룹웨어에 기안이 이미 만들어졌을 수 있습니다'
                    fake = {'month': '2026-10', 'doc_id': '', 'doc_no': '', 'doc_url': '', 'title': '', 'supply': 0, 'vat': 0, 'total': 0,
                            'document_total': None, 'review': [], 'warnings': [], 'submitted_at': '', 'site_draft': True, 'error': '시험용 오류'}

                    def patch_list(route):
                        response = route.fetch()
                        data = response.json()
                        for item in data:
                            if item.get('id') == 'C-2026-011':
                                item['approval'] = fake
                        route.fulfill(response=response, json=data)

                    def patch_draft(route):
                        response = route.fetch()
                        data = response.json()
                        data['approval'] = fake
                        route.fulfill(response=response, json=data)

                    page.route(re.compile(r'/api/contracts$'), patch_list)
                    page.route(re.compile(r'/api/contracts/C-2026-011/expense$'), patch_draft)
                    try:
                        page.get_by_role('button', name='작업 이력', exact=True).click()
                        page.get_by_role('button', name='계약서 목록', exact=True).click()
                        detail = open_contract(page, 'C-2026-011')
                        expect(detail.get_by_test_id('detail-site-draft')).to_be_visible(timeout=10000)
                        checks.add('site_draft 상세 경고 문구', warn in detail.get_by_test_id('detail-site-draft').inner_text())
                        checks.add('site_draft 상태 배지 경고', detail.get_by_test_id('contract-site-draft').count() == 1)
                        checks.add('site_draft여도 상태는 없음', detail.get_by_test_id('contract-status').inner_text() == '없음')
                        detail.get_by_test_id('expense-open').click()
                        modal = page.get_by_test_id('expense-modal')
                        expect(modal).to_be_visible(timeout=10000)
                        checks.add('site_draft 확인 창 경고', warn in modal.get_by_test_id('expense-site-draft').inner_text())
                        page.keyboard.press('Escape')
                        expect(modal).to_have_count(0)
                    finally:
                        page.unroute(re.compile(r'/api/contracts$'), patch_list)
                        page.unroute(re.compile(r'/api/contracts/C-2026-011/expense$'), patch_draft)
                    return True
                checks.step('site_draft 경고 표시', site_draft_warning)

                # 단계 6-3: 공용 Modal 키보드 규칙(R2-8). 거래명세서·지출결의서 확인 창을 각각 연다(상신·생성 없음).
                # [기능명세] modal_keys
                # 목적: check_modal_keys를 두 모달에 적용한다. 입력/출력: 없음 / True.
                # 처리: 002 계약 → 거래명세서 버튼, 011 계약 → 지출결의서 버튼 순서로 검사한다.
                # 예외/실패: 조건 불일치는 검사 실패. 부수효과: 모달 열기·닫기, 계약 선택 변경.
                def modal_keys():
                    open_contract(page, 'C-2026-002')
                    check_modal_keys(page, checks, '거래명세서 창', statement_button(page))
                    detail = open_contract(page, 'C-2026-011')
                    check_modal_keys(page, checks, '지출결의서 창', detail.get_by_test_id('expense-open'))
                    return True
                checks.step('모달 키보드 규칙', modal_keys)

                # 단계 7: 390px 폭에서 확인 창
                def mobile():
                    page.set_viewport_size({'width': 390, 'height': 844})
                    page.wait_for_timeout(300)
                    open_contract(page, 'C-2026-002')
                    button = statement_button(page)
                    button.scroll_into_view_if_needed()
                    button.click()
                    dialog = page.get_by_role('dialog')
                    expect(dialog).to_be_visible(timeout=10000)
                    page.wait_for_timeout(300)
                    overflow = page.evaluate("()=>document.documentElement.scrollWidth-document.documentElement.clientWidth")
                    checks.add('390px 페이지 가로 넘침 없음', overflow <= 1, overflow)
                    box = dialog.bounding_box()
                    checks.add('390px 확인 창이 화면 폭 안', box is not None and box['x'] >= -1 and box['x'] + box['width'] <= 391, box)
                    page.screenshot(path=str(out/'statement-modal-390.png'))
                    page.screenshot(path=str(out/'statement-modal-390-full.png'), full_page=True)
                    return True
                checks.step('390px 확인 창', mobile)

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
# 목적: 검사 결과를 저장하고 종료코드를 정함
# 입력: (out: 출력 폴더 Path, checks: Checks)
# 출력: 0(모두 통과) 또는 1(실패 있음 또는 검사 0건)
# 처리: checks.json 저장 → 요약(통과·실패 수, 실패 이름, 출력 폴더) 표준 출력
# 예외/실패: 파일 쓰기 오류 전파
# 부수효과: checks.json 생성, 표준 출력
def finish(out, checks):
    (out/'checks.json').write_text(json.dumps(checks.items, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    summary = {'passed': len(checks.items) - checks.failed, 'failed': checks.failed,
               'failures': [c['name'] for c in checks.items if not c['ok']], 'artifacts': str(out)}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if checks.failed or not checks.items else 0


if __name__ == '__main__':
    # Windows 콘솔(cp949)에서 출력할 수 없는 문자가 있어도 검증이 중단되지 않게 한다.
    sys.stdout.reconfigure(errors='replace')
    sys.exit(main())
