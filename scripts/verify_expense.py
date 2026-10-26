# [파일 기능명세] 계약서 목록의 '지출결의서 상신' 실제 사이트 통합 검증.
# 입력: 빌드된 frontend/dist, 설치된 Playwright Chromium, 그룹웨어 사이트(https://sbgw.vercel.app/#/draft) 접속.
# 출력: tmp/expense-review/<시각>/의 checks.json·화면 캡처·server.log. 사용자 DB·문서와 실행 중 앱은 변경하지 않는다.
#   그룹웨어 기안은 격리 데이터 폴더의 전용 브라우저 프로필(localStorage)에만 남는다.
# 처리: 빈 격리 데이터로 테스트 서버 실행 → 로그인 → 지출 계약 가져오기 → 상태 기본값 '없음' 확인
#   → C-2026-031(월 2,100,000 부가세 별도)·C-2026-037(월 440,000 부가세 포함) 각각 행 버튼으로 확인 창 열기
#   → 초안 금액 단언 → 상신 → 작업 완료 대기 → 상태 '품의완료'·검토 항목 전부 일치·문서번호 단언 → 화면 캡처 → 390px 넘침 검사.
# 실패: 단언·브라우저 오류를 전파하며 finally에서 테스트 서버와 로그를 정리한다.
# 주의: 기대 금액은 2026-10-21 사이트 계약 기준이다. 청구월 기본값은 실행일 기준 직전 달이다.
from pathlib import Path
from datetime import datetime
import json
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
from playwright.sync_api import sync_playwright, expect

from verify_contracts import start_server, wait_job

CASES = [
    {'id': 'C-2026-031', 'supply': 2100000, 'vat': 210000, 'total': 2310000},
    {'id': 'C-2026-037', 'supply': 400000, 'vat': 40000, 'total': 440000},
]


# [기능명세] contracts
# 목적: 서버의 가져온 계약 목록을 관리번호 사전으로 조회
# 입력: (page: 로그인된 Page)
# 출력: {관리번호: 계약 사전(status·approval 포함)}
# 처리: GET /api/contracts
# 예외/실패: 요청 실패는 Playwright 예외
# 부수효과: 없음
def contracts(page):
    return {c['id']: c for c in page.evaluate("async()=>(await(await fetch('/api/contracts')).json())")}


# [기능명세] submit_case
# 목적: 계약 한 건의 지출결의서를 화면에서 상신하고 결과를 단언
# 입력: (page, case: {id, supply, vat, total}, out: 캡처 폴더)
# 출력: 검사 결과 사전
# 처리: 목록에서 해당 행의 expense-open 클릭 → 확인 창의 초안(GET) 금액 단언 → expense-submit의 POST 응답 확인 → 해당 작업 완료 대기
#   → 계약 상태 '품의완료'·approval 금액·검토 전부 ok 단언 → 결과 영역 표시 확인·캡처 → 창 닫기
# 예외/실패: 단언 실패·시간 초과 시 예외
# 부수효과: 그룹웨어에 기안 1건 상신(격리 브라우저 프로필), 격리 DB 상태 갱신, PNG 저장
def submit_case(page, case, out):
    draft = page.evaluate("async(id)=>(await(await fetch('/api/contracts/'+id+'/expense')).json())", case['id'])
    assert draft['eligible'], draft
    assert (draft['supply'], draft['vat'], draft['total']) == (case['supply'], case['vat'], case['total']), draft
    row = page.locator('.contracts-row', has_text=case['id']).first
    row.get_by_test_id('expense-open').click()
    modal = page.get_by_test_id('expense-modal')
    expect(modal).to_be_visible()
    expect(modal).to_contain_text(case['id'])
    page.screenshot(path=str(out/f"expense-{case['id']}-draft.png"))
    with page.expect_response(lambda response: response.request.method == 'POST'
                              and response.url.endswith('/api/contracts/' + case['id'] + '/expense')) as posted:
        modal.get_by_test_id('expense-submit').click()
    response = posted.value
    assert response.ok, (response.status, response.text())
    submitted_job = response.json()['id']
    job = wait_job(page, timeout=120)
    assert job['id'] == submitted_job, (submitted_job, job)
    assert job['status'] == 'done', job
    c = contracts(page)[case['id']]
    a = c['approval']
    assert c['status'] == '품의완료', (c['status'], a)
    assert (a['supply'], a['vat'], a['total']) == (case['supply'], case['vat'], case['total']), a
    assert a['review'] and all(r['ok'] for r in a['review']), a['review']
    assert a['doc_no'] and a['doc_url'].startswith('https://sbgw.vercel.app/'), a
    expect(page.get_by_test_id('expense-result')).to_contain_text('품의완료', timeout=10000)
    page.screenshot(path=str(out/f"expense-{case['id']}-result.png"))
    page.keyboard.press('Escape')
    expect(modal).to_have_count(0)
    return {'id': case['id'], 'job': job['message'], 'doc_no': a['doc_no'], 'month': a['month'],
            'review': [[r['label'], r['ok']] for r in a['review']], 'missing_attachments': a.get('missing_attachments')}


# [기능명세] main
# 목적: 지출결의서 상신·검토·품의완료 상태를 실제 사이트로 검증
# 입력: ()
# 출력: None; checks.json과 PNG 저장, 표준 출력에 검사 결과 JSON
# 처리: 서버 시작·로그인 → 지출 계약 가져오기 → 상태 기본값 → 두 계약 상신 → 목록 상태 배지 → 390px
# 예외/실패: 단언 실패·JS 오류는 예외로 중단, finally에서 브라우저와 서버 종료
# 부수효과: tmp/expense-review 아래 파일 생성, 사이트 네트워크 접속·기안 상신
def main():
    out = ROOT/'tmp/expense-review'/datetime.now().strftime('%Y%m%d-%H%M%S')
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
                page.get_by_label('가져올 계약 구분').select_option(label='지출')
                page.get_by_label('가져올 개수').fill('')
                page.get_by_role('button', name='계약서 가져오기', exact=True).click()
                time.sleep(.5)
                job = wait_job(page)
                assert job['status'] == 'done', job
                before = contracts(page)
                assert len(before) == 15 and all(c['status'] == '없음' and c['approval'] is None for c in before.values()), before
                checks.append({'importedExpense': len(before), 'defaultStatus': '없음'})

                rejected = page.request.post(base+'/api/contracts/C-2026-031/expense', headers={'Origin': base},
                                             data={'title': '', 'month': '2026-13', 'supply': 1, 'vat': 1,
                                                   'total': 3, 'attachments': [], 'note': ''})
                assert rejected.status == 400, rejected.status
                checks.append({'invalidRejected': rejected.status})

                for case in CASES:
                    checks.append(submit_case(page, case, out))

                after = contracts(page)
                done = sorted(k for k, c in after.items() if c['status'] == '품의완료')
                assert done == sorted(c['id'] for c in CASES), done
                assert all(c['status'] == '없음' for k, c in after.items() if k not in done)
                badges = page.get_by_test_id('contract-status').all_inner_texts()
                assert badges.count('품의완료') >= 2, badges
                checks.append({'statusAfter': done, 'badges': {b: badges.count(b) for b in set(badges)}})

                # 재조회·새로고침에도 완료 상태와 문서 연결이 유지되는지 확인한다.
                page.reload()
                page.get_by_role('button', name='계약서 목록', exact=True).click()
                expect(page.get_by_test_id('contract-status').filter(has_text='품의완료').first).to_be_visible()
                restored = contracts(page)
                assert all(restored[c['id']]['approval']['doc_no'] == after[c['id']]['approval']['doc_no'] for c in CASES)
                checks.append({'reloadPreservesApproval': True})
                page.locator('.contracts-row', has_text='C-2026-031').first.click()
                page.screenshot(path=str(out/'contracts-desktop.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.wait_for_timeout(300)
                overflow = page.evaluate("()=>document.documentElement.scrollWidth-document.documentElement.clientWidth")
                assert overflow <= 1, overflow
                page.screenshot(path=str(out/'contracts-mobile.png'), full_page=True)
                checks.append({'mobileNoOverflow': True})
                # 390px에서도 행 작업 버튼으로 확인 창을 열 수 있고 창이 화면 안에 들어와야 한다.
                page.locator('.contracts-row', has_text='C-2026-031').first.get_by_test_id('expense-open').click()
                modal = page.get_by_test_id('expense-modal')
                expect(modal).to_be_visible()
                duplicate_warning = modal.get_by_text('같은 청구월에 품의완료된 상신이 있습니다.', exact=False)
                expect(duplicate_warning).to_be_visible()
                box = modal.bounding_box()
                assert box and box['x'] >= -1 and box['x'] + box['width'] <= 391, box
                page.screenshot(path=str(out/'expense-mobile.png'))
                checks.append({'mobileExpenseModal': True})
                other_month = '2026-08' if restored['C-2026-031']['approval']['month'] != '2026-08' else '2026-09'
                modal.get_by_label('청구·사용 월', exact=True).fill(other_month)
                expect(duplicate_warning).to_have_count(0)
                checks.append({'duplicateWarningFollowsMonth': True})
                page.keyboard.press('Escape')
                assert not errors, errors
                checks.append({'javascriptErrors': errors})
            except Exception as exc:
                # 실패해도 원인과 현재 화면을 보존해 검토 불일치를 재현할 수 있게 한다.
                checks.append({'failed': str(exc), 'traceback': traceback.format_exc()})
                page.screenshot(path=str(out/'failure.png'), full_page=True)
                raise
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
