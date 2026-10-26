# [파일 기능명세]
# 앱 안 "개발문서" 화면을 실제 Chromium으로 검사한다. 개발문서/NN_*.md 전부가 열리는지, 문서마다 Mermaid 블록 수와
# 화면에 그려진 SVG 수가 같은지, 본문에 정화되지 않은 스크립트·인라인 이벤트가 없는지, 문서 간 링크 이동과 비활성 링크,
# CSP·JS 오류, 4개 폭에서 페이지 가로 넘침이 없는지 확인한다.
# fixture만 새 DB에 등록하며 실사이트 접속·상신·사용자 DB 변경은 하지 않는다. 읽기 전용 API 외 쓰기 요청이 있으면 실패한다.
# 출력: tmp/devdocs-review/<시각>/report.json·PNG. 실패 시 단언 예외를 전파하고 finally에서 서버·브라우저를 정리한다.
from datetime import datetime
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright, expect
import verify_raw_amounts as raw
import verify_statement as statement
from saebom.store import Store

DOCS = ROOT / '개발문서'


# [기능명세] main
# 목적: 개발문서 화면 전체 검증. 입력 없음, 출력은 report.json과 요약(JSON). 실패는 예외로 전파한다.
# 처리: 문서 파일 목록·Mermaid 블록 수 계산→격리 서버·로그인→개발문서 메뉴→문서별 열기·도형 수·정화·링크 검사
#       →문서 간 링크 클릭 이동→4개 폭 가로 넘침→콘솔·페이지 오류와 쓰기 요청 0건 확인.
# 부수효과: tmp/devdocs-review 산출물, 테스트 서버·Chromium(finally에서 종료).
def main():
    files = sorted(p for p in DOCS.glob('[0-9][0-9]_*.md'))
    expected = {p.name: len(re.findall(r'```mermaid\s*\n', p.read_text(encoding='utf-8'))) for p in files}
    out = ROOT / 'tmp/devdocs-review' / datetime.now().strftime('%Y%m%d-%H%M%S')
    out.mkdir(parents=True)
    data = out / 'data'
    raw.seed_data(data)
    statement.seed_data(data, data / 'originals')
    store = Store(data)
    store.close()
    errors, console, writes, checks = [], [], [], []
    log = (out / 'server.log').open('w', encoding='utf-8')
    server = None
    try:
        server, base, token = statement.start_server(data, log)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 960})
                page.on('pageerror', lambda e: errors.append(str(e)))
                # [콜백 명세] 콘솔 오류(CSP 위반 포함) 수집. 입력은 콘솔 메시지, 출력 없음, console 목록에 추가한다.
                page.on('console', lambda m: console.append(m.text) if m.type == 'error' else None)
                # [콜백 명세] 쓰기 요청 수집: 로그인 외 POST·PUT·DELETE가 있으면 실패 근거가 된다.
                page.on('request', lambda r: writes.append(r.url) if r.method in {'POST', 'PUT', 'DELETE'} and '/api/auth/' not in r.url else None)
                page.goto(base + '/?token=' + token)
                page.get_by_label('비밀번호', exact=True).fill('0000')
                page.get_by_role('button', name='시작하기', exact=True).click()
                expect(page.locator('.sidebar')).to_be_visible()
                page.locator('.sidebar nav').get_by_role('button', name='개발문서', exact=False).click()
                links = page.get_by_role('complementary', name='관련 링크', exact=True)
                article = page.locator('.docs-article')
                expect(article).to_be_visible()
                listed = page.request.get(base + '/api/devdocs').json()['docs']
                assert [d['name'] for d in listed] == [p.name for p in files], (listed, [p.name for p in files])
                for doc in files:
                    links.locator('button', has_text=re.compile('.')).filter(has=page.locator(f'xpath=self::*[@title="{doc.name}"]')).first.click()
                    expect(article).to_contain_text(re.sub(r'[`*_]', '', doc.read_text(encoding='utf-8').splitlines()[0].lstrip('# ').strip())[:6])
                    if expected[doc.name]:
                        expect(article.locator('.docs-mermaid svg')).to_have_count(expected[doc.name], timeout=30000)
                    assert article.locator('.docs-mermaid-error').count() == 0, doc.name
                    if expected[doc.name]:
                        article.locator('.docs-mermaid').first.screenshot(path=str(out / f'mermaid-{doc.name[:2]}.png'))
                    # 정화 확인: 스크립트·인라인 이벤트·javascript: 링크 없음
                    unsafe = article.evaluate('(e)=>({scripts:e.querySelectorAll("script").length,handlers:[...e.querySelectorAll("*")].filter(n=>[...n.attributes].some(a=>/^on/i.test(a.name))).length,js:[...e.querySelectorAll("a[href]")].filter(a=>/^javascript:/i.test(a.getAttribute("href"))).length})')
                    assert unsafe == {'scripts': 0, 'handlers': 0, 'js': 0}, (doc.name, unsafe)
                    checks.append({'doc': doc.name, 'mermaid': expected[doc.name], 'unsafe': unsafe})
                # 문서 간 링크: 00 목록의 첫 NN_*.md 링크를 눌러 이동하고, ../ 링크는 비활성이며 이동하지 않는다.
                links.locator('button[title="00_문서목록.md"]').click()
                expect(article).to_contain_text('문서 지도')
                inner = article.locator('a[data-doc]').first
                target_name = inner.get_attribute('data-doc')
                inner.click()
                expect(links.locator(f'button[title="{target_name}"]')).to_have_attribute('aria-current', 'page')
                links.locator('button[title="00_문서목록.md"]').click()
                expect(article).to_contain_text('문서 지도')
                off = article.locator('.docs-link-off')
                assert off.count() > 0 and article.locator('a[href^="../"]').count() == 0 and article.locator('a[data-doc]').count() > 0
                checks.append({'docLinkNavigation': target_name, 'disabledLinks': off.count()})
                # 반응형: 폭마다 가장 큰 문서(07 시퀀스)와 목록 문서의 가로 넘침을 본다.
                for width, height in [(1440, 960), (1100, 900), (760, 900), (390, 844)]:
                    page.set_viewport_size({'width': width, 'height': height})
                    for name in ['07_시퀀스_다이어그램.md', '04_API_명세서.md']:
                        links.locator(f'button[title="{name}"]').click()
                        expect(article.locator('h1').first).to_be_visible()
                        page.wait_for_timeout(300)
                        metrics = page.evaluate('()=>({scrollWidth:document.documentElement.scrollWidth,clientWidth:document.documentElement.clientWidth})')
                        assert metrics['scrollWidth'] <= metrics['clientWidth'] + 1, (width, name, metrics)
                        checks.append({'viewport': f'{width}x{height}', 'doc': name, **metrics})
                        page.screenshot(path=str(out / f'{width}-{name[:2]}.png'))
                assert not errors, errors
                assert not console, console
                assert not writes, writes
                report = {'documents': len(files), 'mermaidBlocks': sum(expected.values()), 'checks': checks,
                          'javascriptErrors': errors, 'consoleErrors': console, 'unexpectedWrites': writes, 'artifacts': str(out)}
                (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps({k: report[k] for k in ['documents', 'mermaidBlocks', 'javascriptErrors', 'consoleErrors', 'unexpectedWrites', 'artifacts']}, ensure_ascii=False, indent=2))
            finally:
                browser.close()
    finally:
        if server:
            server.terminate()
            server.wait(timeout=20)
        log.close()


if __name__ == '__main__':
    main()
