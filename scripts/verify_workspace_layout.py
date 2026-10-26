# [파일 기능명세]
# 새봄 앱 7개 메뉴의 본문/관련 링크 2단 화면을 실제 Chromium으로 검사한다.
# fixture만 새 DB에 등록하며 실사이트 접속·상신·사용자 DB 변경은 수행하지 않는다.
from datetime import datetime
import json
from pathlib import Path
import sys
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright, expect
import verify_raw_amounts as raw
import verify_statement as statement
from saebom.store import Store

SCREENS = [('mails', '메일 · 문서 선택'), ('results', '비교 결과'), ('contracts', '계약서 목록'),
           ('local', '로컬 세금계산서 대조'), ('history', '작업 이력'), ('settings', '설정'), ('docs', '개발문서')]


# [기능명세] main
# 목적: 4개 폭×7개 화면과 링크 목적지·독립 스크롤·키보드 접근을 검사한다.
# 입력 없음, 출력 report.json·28개 PNG. 실패 시 예외를 전파한다.
# 처리: fixture→격리 서버→로그인→각 메뉴와 관련 링크→본문 wheel→원문200·메뉴 이동.
# 부수효과: tmp/workspace-review 산출물·테스트 서버/브라우저. finally에서 모두 종료한다.
def main():
    out = ROOT/'tmp/workspace-review'/datetime.now().strftime('%Y%m%d-%H%M%S')
    out.mkdir(parents=True)
    data = out/'data'
    raw.seed_data(data)
    statement.seed_data(data, data/'originals')
    store = Store(data)
    store.meta_set('local_invoice_folder', str(data/'originals/세금계산서'))
    store.close()
    checks, errors, writes = [], [], []
    log = (out/'server.log').open('w', encoding='utf-8')
    server = None
    try:
        server, base, token = statement.start_server(data, log)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page(viewport={'width':1440,'height':960})
                page.on('pageerror', lambda error: errors.append(str(error)))
                # [콜백 명세] 작업성 API 요청 수집: 로그인은 제외하고 링크 클릭이 쓰기를 유발하지 않는지 확인한다.
                page.on('request', lambda request: writes.append(request.url) if request.method in {'POST','PUT','DELETE'} and '/api/auth/' not in request.url else None)
                page.goto(base+'/?token='+token)
                page.get_by_label('비밀번호', exact=True).fill('0000')
                page.get_by_role('button', name='시작하기', exact=True).click()
                expect(page.locator('.sidebar')).to_be_visible()
                for width, height in [(1440,960),(1100,900),(760,900),(390,844)]:
                    page.set_viewport_size({'width':width,'height':height})
                    for sid, label in SCREENS:
                        page.locator('.sidebar nav').get_by_role('button', name=label, exact=False).click()
                        body = page.locator('.workspace-main')
                        links = page.get_by_role('complementary', name='관련 링크', exact=True)
                        expect(body).to_be_visible()
                        expect(links).to_be_attached()
                        if sid == 'contracts':
                            statement.open_contract(page, 'C-2026-002')
                            expect(links.locator('a[href*="/api/documents/"]')).to_have_count(1)
                        page.wait_for_timeout(200)
                        body.evaluate('(e)=>e.scrollTop=0')
                        metrics = page.evaluate('''()=>{const rect=s=>{let r=document.querySelector(s).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom}};
                          return {width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,clientWidth:document.documentElement.clientWidth,
                           scrollHeight:document.documentElement.scrollHeight,clientHeight:document.documentElement.clientHeight,
                           main:rect('.workspace-main'),links:rect('.related-links'),columns:getComputedStyle(document.querySelector('.workspace-layout')).gridTemplateColumns}}''')
                        assert metrics['scrollWidth'] <= metrics['clientWidth']+1, (sid,metrics)
                        assert metrics['main']['width'] > 0 and metrics['links']['width'] > 0, (sid,metrics)
                        if width >= 1100:
                            assert metrics['links']['x'] >= metrics['main']['right']-1, (sid,metrics)
                            assert metrics['links']['bottom'] <= height+1 and metrics['main']['bottom'] <= height+1, (sid,metrics)
                            assert metrics['scrollHeight'] <= metrics['clientHeight']+1, (sid,metrics)
                            # 휠은 본문만 스크롤하며 우측 패널의 위치·scrollTop은 유지한다.
                            previous_links = links.evaluate('(e)=>({y:e.getBoundingClientRect().y,scroll:e.scrollTop})')
                            body.hover()
                            page.mouse.wheel(0,20000)
                            page.wait_for_timeout(120)
                            assert links.evaluate('(e)=>({y:e.getBoundingClientRect().y,scroll:e.scrollTop})') == previous_links
                            assert body.evaluate('(e)=>e.scrollHeight<=e.clientHeight+1 || e.scrollTop>0'), sid
                            body.evaluate('(e)=>e.scrollTop=0')
                        else:
                            assert metrics['links']['y'] >= metrics['main']['y'], (sid,metrics)
                        assert links.locator('button,a[href]').count() > 0, sid
                        for anchor in links.locator('a[href*="/api/documents/"]').all():
                            response = page.request.get(urljoin(base, anchor.get_attribute('href')))
                            assert response.status == 200 and response.body().lstrip().startswith(b'%PDF-'), anchor.get_attribute('href')
                        for anchor in links.locator('a[href$="/csv"]').all():
                            response = page.request.get(urljoin(base, anchor.get_attribute('href')))
                            assert response.status == 200 and 'text/csv' in response.headers.get('content-type','')
                        page.screenshot(path=str(out/f'{width}-{sid}.png'), full_page=width<1100)
                        checks.append({'screen':sid,'viewport':f'{width}x{height}','metrics':metrics,'links':links.locator('button,a[href]').count()})
                page.set_viewport_size({'width':1440,'height':960})
                links = page.get_by_role('complementary', name='관련 링크', exact=True)
                target = links.locator('button').first
                if target.count():
                    destination = target.inner_text().replace('로 이동', '').strip()
                    target.focus()
                    expect(target).to_be_focused()
                    page.keyboard.press('Enter')
                    expect(links).to_be_visible()
                    expect(page.locator('.sidebar nav button.active')).to_contain_text(destination)
                    checks.append({'keyboardRelatedNavigation':True})
                assert not errors, errors
                assert not writes, writes
                report = {'checks':checks,'javascriptErrors':errors,'unexpectedWrites':writes,'artifacts':str(out)}
                (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps({'screens':28,'javascriptErrors':errors,'unexpectedWrites':writes,'artifacts':str(out)},ensure_ascii=False,indent=2))
            finally:
                browser.close()
    finally:
        if server:
            server.terminate()
            server.wait(timeout=20)
        log.close()


if __name__ == '__main__':
    main()
