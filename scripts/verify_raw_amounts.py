# [파일 기능명세] 금액 원 추출 표시와 원문 드래그의 Google Chrome 통합 검증.
# 입력: tests/fixtures의 가상 기업 PDF, 빌드된 frontend/dist 또는 SAEBOM_VERIFY_EXE의 배포본, 설치된 Google Chrome.
# 출력: tmp/raw-amount-review의 결과 JSON·스크린샷. 사용자 DB·문서와 실행 중 앱은 변경하지 않는다.
# 처리: 독립 DB/원본 준비→테스트 서버→Chrome 로그인→원 추출·보정·누락·포함세액→원문 드래그→반응형.
# 실패: 단언·브라우저 오류를 전파하며 finally에서 테스트 서버와 로그를 정리한다.
from pathlib import Path
from datetime import datetime
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright, expect
from ui_helpers import workspace_bottom
from saebom.compare import extract
from saebom.service import Service
from saebom.store import Store


# [기능명세] seed_data
# 입력: 독립 테스트 데이터 루트. 출력: 생성한 세 문서 쌍과 최초 결과의 정보.
# 처리: 세 업체 fixture 복사·추출 후 누락 필드 사례 한 건 구성, 실제 Service로 비교 결과 생성.
# 실패/부수효과: 판독·작업 실패 시 예외. 변경은 테스트 디렉터리 안의 파일·DB로 한정한다.
def seed_data(data_root):
    store = Store(data_root)
    original_root = data_root / 'originals'
    store.set_document_root(str(original_root))
    mails, contracts, cases, pairs = [], [], [], []
    for index, partner in enumerate(('가온데이터', '다솜오피스', '세움네트웍스')):
        invoice_file = next((ROOT/'tests/fixtures').glob(f'세금계산서_{partner}_2026-09.pdf'))
        contract_file = next((ROOT/'tests/fixtures').glob(f'계약서_*_{partner}_*.pdf'))
        documents = []
        for kind, file in (('invoice', invoice_file), ('contract', contract_file)):
            dest = original_root / ('세금계산서' if kind == 'invoice' else '계약서') / file.name
            shutil.copy2(file, dest)
            extracted = extract(dest, kind)
            assert not extracted['error'], extracted['error']
            if index == 2 and kind == 'invoice':
                extracted = copy.deepcopy(extracted)
                extracted['fields'].pop('vat', None)
            url = f'https://sbgw.vercel.app/qa/{index}/{kind}.pdf'
            document = store.save_document(url, file.name, hashlib.sha256(file.read_bytes()).hexdigest(), extracted, dest)
            documents.append(document)
        invoice, contract = documents
        mail_id, contract_id = f'qa-mail-{index}', f'qa-contract-{index}'
        mails.append({'id': mail_id, 'sender': partner, 'subject': f'{partner} 원 추출 금액 확인', 'received': f'2026-10-{20-index:02d} 10:00', 'attachments': [{'name': invoice['name'], 'url': invoice['source']}]})
        contracts.append({'id': contract_id, 'kind': '지출', 'partner': partner, 'title': f'{partner} 테스트 계약', 'period': '2026년', 'amount_text': 'PDF 원 추출 확인', 'file': {'name': contract['name'], 'url': contract['source']}})
        pair = {'mail_id': mail_id, 'contract_id': contract_id, 'invoice_url': invoice['source']}
        pairs.append(pair)
        cases.append({'partner': partner, 'invoice': invoice, 'contract': contract})
    store.snapshot(mails, contracts)
    service = Service(store)
    try:
        job_id = service.submit('원 추출 표시 테스트', service.run_compare, pairs)['id']
        for _ in range(200):
            if service.jobs[job_id]['status'] != 'running':
                break
            time.sleep(.02)
        assert service.jobs[job_id]['status'] == 'done', service.jobs[job_id]
    finally:
        service.close()
        store.close()
    return cases


# [기능명세] money
# 입력: 테스트 기대 금액 정수. 출력: 천 단위 쉼표와 원 단위를 포함한 문자열. 부수효과 없음.
def money(value):
    return f'{value:,}원'


# [기능명세] raw_field
# 입력: Chrome 페이지, 문서 이름, 금액 항목. 출력: 사용자에게 보이는 접근성 group Locator.
# 처리: UI의 한국어 원 추출값 이름으로 찾으며 서버 상태나 DOM을 수정하지 않는다.
def raw_field(page, source, label):
    return page.get_by_role('group', name=f'{source} {label} 원 추출값', exact=True)


# [기능명세] wait_pdf
# 입력: 원문 모달을 연 Chrome 페이지. 출력: None.
# 처리: 두 Canvas가 표시되고 로딩·오류가 사라질 때까지 단언 대기. 실패 시 Playwright 오류.
def wait_pdf(page):
    expect(page.locator('.pdf canvas')).to_have_count(2)
    expect(page.locator('.pdf .spin, .pdf .error')).to_have_count(0, timeout=20000)
    expect(page.locator('.pdf canvas').first).to_be_visible()
    expect(page.locator('.pdf canvas').last).to_be_visible()
    page.wait_for_timeout(150)


# [기능명세] check_modal_keys
# 목적: 공용 Modal(components/Modal.tsx)의 키보드·접근성 규칙을 한 모달에서 검사한다(보정 창·원문 창에 사용).
# 입력: (page: 로그인된 Page, checks: 결과 목록(list), label: 이름 머리말, opener: 모달을 여는 버튼 Locator)
# 출력: None
# 처리: opener 클릭 → role=dialog 1개와 aria-modal·aria-labelledby(실제 제목 요소) → body 스크롤 잠금 → 배경 클릭으로 안 닫힘
#   → Tab 12회·Shift+Tab 12회 동안 포커스가 창 안에 머묾 → Esc로 닫힘 → 스크롤 잠금 해제 → 연 버튼으로 포커스 복귀.
# 예외/실패: 하나라도 어긋나면 AssertionError, 요소 미발견은 Playwright 예외. 부수효과: 모달 열기·닫기, checks에 결과 추가
def check_modal_keys(page, checks, label, opener):
    opener.focus()
    opener.click()
    dialog = page.get_by_role('dialog')
    expect(dialog).to_have_count(1, timeout=10000)
    labelled = dialog.get_attribute('aria-labelledby')
    assert dialog.get_attribute('aria-modal') == 'true' and labelled and page.locator('#' + labelled).count() == 1, (label, labelled)
    assert page.evaluate('document.body.style.overflow') == 'hidden', label + ' 스크롤 잠금'
    page.mouse.click(2, 2)
    assert dialog.count() == 1, label + ' 배경 클릭으로 닫힘'
    inside = "()=>document.querySelector('[role=dialog]').contains(document.activeElement)"
    for key in ['Tab'] * 12 + ['Shift+Tab'] * 12:
        page.keyboard.press(key)
        assert page.evaluate(inside), (label, '포커스가 창 밖으로 나감', key)
    page.keyboard.press('Escape')
    expect(dialog).to_have_count(0)
    assert page.evaluate('document.body.style.overflow') == '', label + ' 스크롤 잠금 해제'
    assert opener.evaluate('el => el === document.activeElement'), label + ' 포커스 복귀'
    checks.append({'modalKeys': label, 'checked': 'dialog 속성·스크롤 잠금·배경 클릭 무시·포커스 트랩·Esc·포커스 복귀'})


# [기능명세] main
# 입력: 현재 프로젝트 소스·fixture·Chrome 실행 환경. 출력: 검증 JSON과 화면 캡처.
# 처리: 격리 서버와 새 Chrome 컨텍스트에서 UI 조작으로 원 추출·보정·누락·드래그·스크롤 검사.
# 실패/부수효과: 불일치 시 예외, finally로 서버 종료. 사용자 실행 앱·브라우저 프로필은 사용하지 않는다.
def main():
    out = ROOT/'tmp/raw-amount-review'/datetime.now().strftime('%Y%m%d-%H%M%S')
    out.mkdir(parents=True)
    data = out/'data'
    cases = seed_data(data)
    log = (out/'server.log').open('w', encoding='utf-8')
    executable = os.environ.get('SAEBOM_VERIFY_EXE')
    command = [str(Path(executable).resolve())] if executable else [sys.executable, 'launcher.py']
    server = subprocess.Popen(command, cwd=ROOT, env={**os.environ, 'SAEBOM_DATA_DIR': str(data), 'SAEBOM_NO_OPEN': '1'}, stdout=log, stderr=log)
    checks, errors = [], []
    try:
        for _ in range(150):
            try:
                info = json.loads((data/'instance.json').read_text())
                base = f"http://127.0.0.1:{info['port']}"
                urllib.request.urlopen(base+'/health', timeout=1).close()
                break
            except Exception:
                time.sleep(.1)
        else:
            raise RuntimeError('독립 테스트 서버 시작 실패')
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='chrome', headless=False)
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 960}, device_scale_factor=1)
                # pageerror 콜백: Chrome의 비동기 JS 오류 문자열을 errors에 모아 마지막에 검사한다.
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base+'/?token='+info['token'])
                page.get_by_label('비밀번호', exact=True).fill('0000')
                page.get_by_role('button', name='시작하기', exact=True).click()
                page.get_by_role('button', name='비교 결과', exact=True).click()
                panel = page.get_by_role('region', name='금액 원 추출값', exact=True)
                expect(panel).to_be_visible()
                for key, label in (('supply', '공급가액'), ('vat', '부가세'), ('total', '합계액')):
                    expect(raw_field(page, '세금계산서', label).locator(':scope > strong')).to_have_text(money(cases[0]['invoice']['extraction']['fields'][key]['value']))
                invoice_supply = raw_field(page, '세금계산서', '공급가액')
                invoice_supply.locator('summary').click()
                expect(invoice_supply.locator('pre')).to_have_text(cases[0]['invoice']['extraction']['fields']['supply']['quote'])
                expect(invoice_supply.locator('summary')).to_contain_text('1페이지')
                panel.screenshot(path=str(out/'01-original-amounts.png'))
                checks.append({'originalAmounts': '계산서 3개 금액과 원문·페이지 일치', 'invoice': {k: cases[0]['invoice']['extraction']['fields'][k]['value'] for k in ('supply', 'vat', 'total')}})

                page.locator('.result-list > button').nth(1).click()
                included = cases[1]['contract']['extraction']['fields']
                assert included['vat_mode']['value'] == 'included', included
                expect(raw_field(page, '계약서', '계약금액').locator(':scope > strong')).to_have_text(money(included['amount']['value']))
                expect(page.locator('.raw-money-conditions')).to_contain_text('부가세 포함')
                expected_supply = next(c['expected'] for c in page.evaluate("async()=>{const s=await(await fetch('/api/results')).json();const r=await(await fetch('/api/results/'+s[0].id)).json();return r.rows[1].checks}") if c['key'] == 'supply')
                assert expected_supply != included['amount']['value']
                panel.screenshot(path=str(out/'02-vat-included.png'))
                checks.append({'contractRawAmount': included['amount']['value'], 'calculatedSupply': expected_supply, 'distinct': True})

                page.locator('.result-list > button').nth(2).click()
                missing = raw_field(page, '세금계산서', '부가세')
                expect(missing.locator(':scope > strong')).to_have_text('미추출')
                expect(missing).to_contain_text('원문 근거 없음')
                checks.append({'missingAmount': '누락값을 0원으로 표시하지 않음'})

                page.locator('.result-list > button').nth(0).click()
                check_modal_keys(page, checks, '보정 창', page.get_by_role('button', name='계산서 추출값 보정', exact=True))
                first = cases[0]['invoice']['extraction']['fields']
                new_supply, new_vat = first['supply']['value']+1000, first['vat']['value']+100
                page.get_by_role('button', name='계산서 추출값 보정', exact=True).click()
                page.get_by_label('공급가액', exact=True).fill(str(new_supply))
                page.get_by_label('부가세', exact=True).fill(str(new_vat))
                page.get_by_label('합계액', exact=True).fill(str(new_supply+new_vat))
                # R1-10: 보정 요청이 실패하면 폼을 닫지 않고 입력값을 유지하며 오류만 보여 준다(서버 500 응답을 흉내냄).
                fail_route = lambda route: route.fulfill(status=500, json={'detail': '시험용 보정 실패'})
                page.route('**/correct', fail_route)
                page.get_by_role('button', name='보정값으로 재비교', exact=True).click()
                expect(page.get_by_test_id('edit-error')).to_contain_text('시험용 보정 실패', timeout=10000)
                assert page.get_by_label('공급가액', exact=True).input_value() == str(new_supply), '보정 실패 뒤 입력값이 사라짐'
                page.unroute('**/correct', fail_route)
                checks.append({'correctionFailure': '실패 시 보정 폼과 입력값 유지, 오류 표시'})
                page.get_by_role('button', name='보정값으로 재비교', exact=True).click()
                expect(page.get_by_label('공급가액', exact=True)).to_have_count(0, timeout=20000)
                original = raw_field(page, '세금계산서', '공급가액')
                expect(original.locator('.raw-money-corrected')).to_contain_text(money(new_supply), timeout=20000)
                expect(original.locator(':scope > strong')).to_have_text(money(first['supply']['value']))
                expect(original.locator('.raw-money-corrected')).to_contain_text('수동 보정')
                panel.screenshot(path=str(out/'03-corrected-and-original.png'))
                checks.append({'correction': '최초 추출값 보존·보정 비교값 별도 표시', 'original': first['supply']['value'], 'effective': new_supply})

                check_modal_keys(page, checks, '원문 창', page.get_by_role('button', name='원문 나란히 보기', exact=True))
                # R2-8: 문서 로드와 페이지 렌더 효과 분리 — 확대·화면 폭 변화에는 /api/documents/{id}를 다시 받지 않는다.
                doc_requests = []
                page.on('request', lambda request: doc_requests.append(request.url) if '/api/documents/' in request.url else None)
                page.get_by_role('button', name='원문 나란히 보기', exact=True).click()
                wait_pdf(page)
                page.wait_for_timeout(1200)  # PDF.js 범위 요청이 끝나 요청 수가 안정될 때까지 기다린다.
                requests_before = len(doc_requests)
                assert requests_before >= 2, doc_requests
                left, right = page.locator('.pdf').first, page.locator('.pdf').last
                left.locator('canvas').click(position={'x': 100, 'y': 100})
                expect(left.locator('output')).to_have_text('200%')
                wait_pdf(page)
                page.set_viewport_size({'width': 1300, 'height': 900})
                page.wait_for_timeout(500)
                wait_pdf(page)
                page.set_viewport_size({'width': 1440, 'height': 960})
                page.wait_for_timeout(500)
                wait_pdf(page)
                assert len(doc_requests) == requests_before, ('확대·폭 변화에 문서를 다시 요청함', requests_before, doc_requests)
                checks.append({'pdfNoRefetch': '확대·화면 폭 변화에 /api/documents 재요청 없음', 'requests': requests_before})
                body = left.locator('.pdf-body')
                state = body.evaluate('(e)=>{e.scrollTo(120,120);return {x:e.scrollLeft,y:e.scrollTop,maxX:e.scrollWidth-e.clientWidth,maxY:e.scrollHeight-e.clientHeight}}')
                assert state['maxX'] > 0 and state['maxY'] > 0, state
                rect = body.bounding_box()
                x, y = rect['x']+rect['width']*.6, rect['y']+rect['height']*.5
                page.mouse.move(x,y);page.mouse.down();page.mouse.move(x-100,y-70,steps=8);page.mouse.up()
                after = body.evaluate('(e)=>({x:e.scrollLeft,y:e.scrollTop})')
                assert after['x'] > state['x']+70 and after['y'] > state['y']+40, (state, after)
                expect(left.locator('output')).to_have_text('200%')
                expect(right.locator('output')).to_have_text('100%')
                assert left.locator('canvas').evaluate('(e)=>getComputedStyle(e).cursor') != 'grabbing'
                page.screenshot(path=str(out/'04-drag-document.png'))
                left.locator('canvas').click()
                expect(left.locator('output')).to_have_text('100%')
                wait_pdf(page)
                checks.append({'mousePan': 'Chrome 마우스 드래그로 좌우·상하 이동, 드래그 시 배율 유지, 짧은 클릭 확대/맞춤 유지', 'before': state, 'after': after})
                page.get_by_role('button', name='원문 보기 닫기', exact=True).click()

                for width, height in ((1440,960),(1024,768),(390,844)):
                    page.set_viewport_size({'width':width,'height':height})
                    panel.scroll_into_view_if_needed()
                    expect(panel).to_be_visible()
                    for value in panel.locator('.raw-money-field > strong').all():
                        box = value.bounding_box()
                        assert box and box['x'] >= 0 and box['x']+box['width'] <= width, box
                    metrics = page.evaluate('({scroll:document.documentElement.scrollWidth,client:document.documentElement.clientWidth})')
                    assert metrics['scroll'] <= metrics['client'], metrics
                    panel.screenshot(path=str(out/f'05-raw-amounts-{width}.png'))
                    workspace_bottom(page)
                    checks.append({'viewport':f'{width}x{height}','amountsVisible':True,'noHorizontalOverflow':True,'footerVisible':True})
                assert not errors, errors
                report={'browser':'Google Chrome','version':browser.version,'checks':checks,'javascriptErrors':errors,'artifacts':str(out)}
                (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                (out.parent/'latest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps(report,ensure_ascii=False,indent=2))
            finally:
                browser.close()
    finally:
        server.terminate()
        server.wait(timeout=15)
        log.close()


if __name__ == '__main__':
    main()
