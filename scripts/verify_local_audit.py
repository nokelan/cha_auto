# [파일 기능명세] '로컬 세금계산서 대조' 메뉴의 실제 사이트 통합 검증.
# 입력: 빌드된 frontend/dist, 설치된 Playwright Chromium, 그룹웨어 사이트(https://sbgw.vercel.app/) 접속,
#   샘플 폴더 로컬세금계산서_샘플/(그룹웨어 메일 첨부 PDF 13·PNG 13)과 tests/fixtures의 가온데이터 세금계산서(웹에 계약 없음).
# 출력: tmp/local-audit-review/<시각>/의 checks.json·화면 캡처·server.log. 사용자 DB·문서와 실행 중 앱은 변경하지 않는다.
# 처리: 빈 격리 데이터로 테스트 서버 실행 → 로그인 → 샘플 사본 폴더 지정(PUT, 폴더 선택창은 자동화 불가) → 대조 전 목록 확인
#   → '웹 계약서와 대조' 클릭 → 작업 완료 대기 → 사이트 정답표(data/cases.json answer_key)와 판정 비교 → 상세·원문 뷰어 → 390px 넘침 검사.
# 실패: 단언·브라우저 오류를 전파하며 finally에서 테스트 서버와 로그를 정리한다.
# 주의: 정답표의 '불일치'는 세금계산서·계약서·지출결의서 3자 기준이다. 이 기능은 세금계산서↔계약서만 보므로
#   N09(결의서만 틀림)는 '일치'가 기대값이다. 사이트 데이터가 바뀌면 EXPECTED를 갱신한다(2026-10-21 기준).
from pathlib import Path
from datetime import datetime
import json
import shutil
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
from playwright.sync_api import sync_playwright, expect

from verify_contracts import start_server, wait_job

SAMPLE = ROOT/'로컬세금계산서_샘플'
NO_CONTRACT = ROOT/'tests/fixtures/세금계산서_가온데이터_2026-09.pdf'
CASES_URL = 'https://sbgw.vercel.app/data/cases.json'


# [기능명세] expected_verdicts
# 목적: 사이트 정답표에서 세금계산서↔계약서 기준 기대 판정 만들기
# 입력: ()
# 출력: {세금계산서 PDF 파일명: {'status', 'contract_id', 'case'}}
# 처리: answer_key를 읽어 거래처 이름을 파일명 규칙(세금계산서_{상호}_2026-09.pdf)으로 바꾼다.
#   계약·세금계산서 합계가 같고 세금계산서 산술(공급가액×10%=세액)이 맞으면 '일치', 아니면 '불일치'.
# 예외/실패: 네트워크 오류 전파
# 부수효과: 사이트 접속(읽기)
def expected_verdicts():
    key = json.loads(urllib.request.urlopen(CASES_URL, timeout=30).read().decode('utf-8'))['answer_key']
    out = {}
    for k in key:
        name = k['partner'].replace('(주)', '')
        ok = k['contract_total'] == k['invoice_total'] and k['invoice_vat'] == round(k['invoice_supply'] * 0.1)
        out[f'세금계산서_{name}_2026-09.pdf'] = {'status': '일치' if ok else '불일치', 'contract_id': k['contract_id'], 'case': k['case']}
    return out


# [기능명세] main
# 목적: 로컬 세금계산서 대조의 목록·대조·판정·화면을 실제 사이트로 검증
# 입력: ()
# 출력: None; checks.json과 PNG 저장, 표준 출력에 검사 결과 JSON
# 처리: 샘플 사본 준비 → 서버 시작·로그인 → 메뉴 이동 → 폴더 지정 → 대조 전 목록 27건 → 대조 실행 → 판정 단언 → 상세·원문 → 반응형
# 예외/실패: 단언 실패·JS 오류는 예외로 중단, finally에서 브라우저와 서버 종료
# 부수효과: tmp/local-audit-review 아래 파일 생성, 사이트 네트워크 접속
def main():
    out = ROOT/'tmp/local-audit-review'/datetime.now().strftime('%Y%m%d-%H%M%S')
    out.mkdir(parents=True)
    folder = out/'invoices'
    shutil.copytree(SAMPLE, folder)
    shutil.copy2(NO_CONTRACT, folder/NO_CONTRACT.name)
    expected = expected_verdicts()
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
                page.get_by_role('button', name='로컬 세금계산서 대조', exact=True).click()
                expect(page.get_by_test_id('local-run')).to_be_disabled()
                checks.append({'runDisabledWithoutFolder': True})

                state = page.evaluate("async(f)=>{const r=await fetch('/api/local-audit/folder',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({folder:f})});return [r.status, await r.json()]}", str(folder))
                assert state[0] == 200, state
                files = state[1]['files']
                assert len(files) == 27, len(files)
                assert all(f['partner'] for f in files), [f['file'] for f in files if not f['partner']]
                checks.append({'scanned': len(files), 'pngFromFilename': sum(f['partner_source'] == 'filename' for f in files)})

                bad = page.evaluate("async()=>(await fetch('/api/local-audit/folder',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({folder:'상대경로'})})).status")
                assert bad == 400, bad
                checks.append({'relativeFolderRejected': bad})

                page.reload()
                page.get_by_role('button', name='로컬 세금계산서 대조', exact=True).click()
                expect(page.get_by_test_id('local-folder')).to_contain_text('invoices')
                expect(page.get_by_test_id('local-row')).to_have_count(27)
                page.get_by_test_id('local-run').click()
                time.sleep(.5)
                job = wait_job(page, timeout=300)
                assert job['status'] == 'done', job
                checks.append({'job': job['message']})

                result = page.evaluate("async()=>(await(await fetch('/api/local-audit')).json()).last")
                rows = {r['file']: r for r in result['rows']}
                assert len(rows) == 27, len(rows)
                verdicts = {}
                for name, exp in expected.items():
                    r = rows[name]
                    verdicts[exp['case']] = [name, r['status'], (r['contract'] or {}).get('id')]
                    assert r['status'] == exp['status'], (name, r['status'], exp, r['note'])
                    assert (r['contract'] or {}).get('id') == exp['contract_id'], (name, r['contract'])
                checks.append({'answerKey': verdicts})

                miss = rows[NO_CONTRACT.name]
                assert miss['status'] == '계약서 없음' and miss['contract'] is None, miss
                checks.append({'noContract': miss['status']})

                pngs = [r for r in rows.values() if r['type'] == 'png']
                assert all(r['status'] == '확인 필요' and r['contract'] for r in pngs), [(r['file'], r['status']) for r in pngs]
                checks.append({'pngNeedsReview': len(pngs)})

                others = {n: [r['status'], (r['contract'] or {}).get('id'), r['note']] for n, r in rows.items()
                          if r['type'] == 'pdf' and n not in expected and n != NO_CONTRACT.name}
                checks.append({'seedPdfs(정답표 없음, 기록만)': others, 'counts': result['counts']})

                imported = page.evaluate("async()=>(await(await fetch('/api/contracts')).json()).map(c=>c.id)")
                assert set(e['contract_id'] for e in expected.values()) <= set(imported), imported
                checks.append({'contractsSharedWithList': len(imported)})

                expect(page.get_by_test_id('local-row')).to_have_count(27)
                page.get_by_test_id('local-row').filter(has_text='단비클라우드').filter(has_text='PDF').first.click()
                detail = page.get_by_test_id('local-detail')
                expect(detail).to_contain_text('불일치')
                expect(detail.locator('.pdf canvas')).to_be_visible(timeout=20000)
                page.screenshot(path=str(out/'local-desktop.png'), full_page=True)
                checks.append({'detailAndPdf': True})

                page.set_viewport_size({'width': 390, 'height': 844})
                page.wait_for_timeout(300)
                overflow = page.evaluate("()=>document.documentElement.scrollWidth-document.documentElement.clientWidth")
                assert overflow <= 1, overflow
                page.screenshot(path=str(out/'local-mobile.png'), full_page=True)
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
