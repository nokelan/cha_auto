# [파일 기능명세]
# 실제 브라우저 통합 검증 스크립트. 사용자 DB와 PDF를 tmp/ui-review로 복사하고 격리 서버에서 로그인·비교·확대·반응형·스크롤·저장 위치 이동을 검사한다. SAEBOM_VERIFY_EXE가 있으면 배포 EXE를 실행한다. 실패 시 예외를 전파하며 finally에서 테스트 서버를 종료한다. 실제 사용자 목록·PDF가 준비된 PC가 전제다.
# 유지보수: 함수·데이터 계약이 바뀌면 해당 기능명세와 실제 회귀 검사를 함께 갱신한다.

"""Exercise the three-column UI against an isolated backup of local app data."""
from pathlib import Path
import json, os, shutil, sqlite3, subprocess, sys, time, urllib.request
from playwright.sync_api import sync_playwright, expect
from ui_helpers import workspace_top, workspace_bottom
# [실행 블록 기능명세]
# 입력: LOCALAPPDATA의 현재 앱 DB·원본 파일, 설치된 Playwright Chromium과 빌드된 frontend/dist.
# 출력: checks.json, 화면 PNG, server.log. 실패 시 AssertionError/Playwright 예외로 중단한다.
# 격리: SQLite backup과 원본 PDF 복사 뒤 테스트 DB 경로를 바꾼다. 실제 사용자 문서의 이동·삭제를 피한다.
# 단계: 격리 서버 준비→비밀번호/API 차단→기업 선택·비교→클릭 확대·스크롤→6개 화면 크기→저장 위치 이동.
# finally: 테스트 서버 프로세스 종료·대기 및 로그 핸들 정리. 앱 배포 EXE를 교체하지 않는다.
# [기능명세] wait_canvas_width
# 목적: PDF 배율 변경 뒤 Canvas가 다시 그려져 기대 너비가 될 때까지 대기
# 입력: (pdf: .pdf 영역 Locator, width: 기대 CSS 너비 px, timeout: 초 단위 최대 대기, 기본 15)
# 출력: None
# 처리: 0.1초 간격으로 Canvas bounding_box를 읽어, 보이는 상태이고 너비 차이가 2px 미만이면 종료
# 예외/실패: 시간 안에 조건을 만족하지 못하면 마지막 측정값을 담은 AssertionError
# 부수효과: 없음(화면 읽기만 수행)
def wait_canvas_width(pdf,width,timeout=15):
 box=None
 for _ in range(int(timeout*10)):
  box=pdf.locator('canvas').bounding_box()
  if box and abs(box['width']-width)<2:return
  time.sleep(.1)
 raise AssertionError(('canvas width',width,box))
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'tmp'/'ui-review'; OUT.mkdir(parents=True,exist_ok=True)
DATA=OUT/'data'; DATA.mkdir(exist_ok=True)
source=sqlite3.connect(Path(os.environ['LOCALAPPDATA'])/'SaebomCompare'/'saebom.sqlite3')
target=sqlite3.connect(DATA/'saebom.sqlite3');source.backup(target);source.close()
# Settings migration must never relocate the user's originals during QA.
originals=DATA/'originals';originals.mkdir(exist_ok=True)
for docid,disk,digest in target.execute('SELECT id,disk_path,hash FROM documents').fetchall():
 src=Path(disk) if disk else Path(os.environ['LOCALAPPDATA'])/'SaebomCompare/documents'/f'{digest}.pdf'
 if src.is_file():
  dest=originals/f'{docid}.pdf';shutil.copy2(src,dest)
  target.execute('UPDATE documents SET disk_path=? WHERE id=?',(str(dest),docid))
target.execute("INSERT OR REPLACE INTO meta VALUES('document_root',?)",(str(originals),))
target.commit();target.close()
env={**os.environ,'SAEBOM_DATA_DIR':str(DATA),'SAEBOM_NO_OPEN':'1'}
log=(OUT/'server.log').open('w',encoding='utf-8')
executable=os.environ.get('SAEBOM_VERIFY_EXE')
command=[str(Path(executable).resolve())] if executable else [sys.executable,'launcher.py']
server=subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=log)
checks=[]
try:
 for _ in range(100):
  try:
   info=json.loads((DATA/'instance.json').read_text());base=f"http://127.0.0.1:{info['port']}"
   urllib.request.urlopen(base+'/health',timeout=1);break
  except Exception:time.sleep(.1)
 else:raise RuntimeError('Server did not start')
 with sync_playwright() as pw:
  browser=pw.chromium.launch(headless=False)
  page=browser.new_page(viewport={'width':1440,'height':900},device_scale_factor=1)
  # pageerror 콜백 명세: 입력은 브라우저 예외, 출력은 None이며 errors에 문자열을 누적해 마지막에 0건을 단언한다.
  errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  # 로그인 명세: 잘못된 비밀번호에서는 목록·결과를 차단하고 올바른 비밀번호와 새로고침에서 세션 유지를 확인한다.
  page.goto(base+'/?token='+info['token'])
  expect(page.get_by_label('비밀번호',exact=True)).to_be_visible()
  assert page.request.get(base+'/api/results').status==401
  page.get_by_label('비밀번호',exact=True).fill('1234')
  page.get_by_role('button',name='시작하기',exact=True).click()
  expect(page.get_by_role('alert')).to_contain_text('비밀번호가 올바르지 않습니다')
  expect(page.locator('.company-card')).to_have_count(0)
  page.get_by_label('비밀번호',exact=True).fill('0000')
  page.get_by_role('button',name='시작하기',exact=True).click()
  expect(page.locator('.company-card').first).to_be_visible()
  page.reload();expect(page.locator('.company-card').first).to_be_visible()
  checks.append({'passwordGate':'wrong password denied; 0000 unlocks; APIs blocked before login; refresh keeps session'})
  page.screenshot(path=str(OUT/'desktop-initial.png'),full_page=True)
  cards=page.locator('.company-card'); count=cards.count();assert count>0
  cards.first.click();expect(cards.first).to_have_attribute('aria-pressed','true')
  expect(page.locator('.connections select').first).to_be_visible()
  contract=page.locator('.connections select').last;assert contract.input_value(), 'Expected unique recommendation'
  compare=page.get_by_role('button',name='비교 실행',exact=True)
  # Deselect the most recently focused company; compare must still show the
  # remaining selected company's new result.
  cards.nth(1).click()
  cards.nth(1).click()
  if compare.is_disabled():
   page.get_by_role('button',name='선택 문서 다운로드',exact=True).click()
   expect(compare).to_be_enabled(timeout=60000)
  # 완료 검사: 기존 결과가 이미 보이는 것만으로 성공 처리하지 않고 결과 ID가 실제로 새로 저장될 때까지 기다린다.
  previous_id=page.evaluate("async()=>(await (await fetch('/api/results')).json())[0]?.id")
  compare.click()
  page.wait_for_function("async previous=>(await (await fetch('/api/results')).json())[0]?.id!==previous",arg=previous_id,timeout=30000)
  expect(compare).to_be_enabled(timeout=15000)
  expect(page.locator('.workspace-results .review')).to_be_visible(timeout=30000)
  expect(page.get_by_role('heading',name='비교 결과 · 원문')).to_be_visible()
  checks.append({'comparison':'company click auto-links contract; compare completes in third column','cards':count})
  page.get_by_role('checkbox',name='표시된 PDF 메일 전체 선택').check()
  expect(page.locator('.company-card[aria-pressed=true]')).to_have_count(count)
  expect(page.locator('.connection')).to_have_count(count)
  page.get_by_role('button',name='선택 해제',exact=True).click()
  expect(page.locator('.connection')).to_have_count(0)
  cards.first.click()
  checks.append({'multiSelect':count,'clearSelection':True})
  grid=page.locator('.compare-workspace');before=page.locator('.company-panel').bounding_box()['width']
  divider=page.get_by_role('separator',name='기업 목록 너비 조정');box=divider.bounding_box()
  page.mouse.move(box['x']+box['width']/2,box['y']+50);page.mouse.down();page.mouse.move(box['x']+70,box['y']+50);page.mouse.up()
  after=page.locator('.company-panel').bounding_box()['width'];assert after>before+15,(before,after)
  checks.append({'resize':{'before':before,'after':after}})
  page.get_by_role('button',name='단 너비 초기화').click()
  page.get_by_role('button',name='원문 나란히 보기',exact=True).click()
  expect(page.locator('.pdf-body canvas').first).to_be_visible(timeout=15000)
  expect(page.locator('.pdf .spin, .pdf .error')).to_have_count(0,timeout=15000)
  expect(page.locator('.pdf canvas').first).not_to_have_js_property('width',300)
  expect(page.locator('.pdf canvas').last).not_to_have_js_property('width',300)
  page.screenshot(path=str(OUT/'pdf-desktop.png'))
  # 확대 검사: Canvas 실제 CSS 너비 2배·좌우 독립 배율·가로 스크롤·클릭 복귀·배율 버튼을 단언한다.
  left=page.locator('.pdf').first
  right=page.locator('.pdf').last
  fitted=left.locator('canvas').bounding_box()['width']
  left.locator('canvas').click(position={'x':80,'y':80})
  expect(left.locator('output')).to_have_text('200%')
  expect(left.locator('.spin, .error')).to_have_count(0,timeout=15000)
  # 배율 변경 직후에는 로딩 표시가 아직 나타나기 전일 수 있으므로, Canvas 너비가 기대값이 될 때까지 기다린다.
  wait_canvas_width(left,fitted*2)
  expect(right.locator('output')).to_have_text('100%')
  page.wait_for_timeout(200)  # Let the click-anchor scroll effect settle.
  left.locator('.pdf-body').evaluate('(e)=>{e.scrollLeft=0;e.scrollTop=0}')
  left.locator('.pdf-body').hover()
  page.mouse.wheel(500,450);page.wait_for_timeout(200)
  assert left.locator('.pdf-body').evaluate('(e)=>e.scrollLeft')>0
  page.screenshot(path=str(OUT/'pdf-click-zoom.png'))
  left.locator('canvas').click()
  expect(left.locator('output')).to_have_text('100%')
  expect(left.locator('.spin, .error')).to_have_count(0,timeout=15000)
  left.locator('canvas').click()
  expect(left.locator('output')).to_have_text('200%')
  expect(left.locator('.spin, .error')).to_have_count(0,timeout=15000)
  left.get_by_role('button',name='화면 맞춤',exact=True).click()
  expect(left.locator('output')).to_have_text('100%')
  expect(left.locator('.spin, .error')).to_have_count(0,timeout=15000)
  wait_canvas_width(left,fitted)
  left.get_by_role('button',name='문서 확대',exact=True).click()
  expect(left.locator('output')).to_have_text('125%')
  expect(left.locator('.spin, .error')).to_have_count(0,timeout=15000)
  left.get_by_role('button',name='문서 축소',exact=True).click()
  expect(left.locator('.spin, .error')).to_have_count(0,timeout=15000)
  checks.append({'pdfZoom':'click 200%; independent panes; horizontal scroll; +/- buttons; fit reset'})
  page.get_by_role('button',name='원문 보기 닫기').click()
  checks.append({'pdf':'both original PDFs rendered'})
  # 반응형 검사: 본문 패널의 실제 wheel로 footer까지 도달하고 전체 창이 가로로 넘치지 않는지 확인한다.
  for width,height in [(1920,1080),(1440,900),(1024,768),(820,680),(600,700),(390,844)]:
   page.set_viewport_size({'width':width,'height':height});workspace_top(page);page.wait_for_timeout(150)
   metrics=page.evaluate('''()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,clientWidth:document.documentElement.clientWidth,columns:getComputedStyle(document.querySelector('.compare-workspace')).gridTemplateColumns})''')
   assert metrics['scrollWidth']<=metrics['clientWidth']+1,metrics
   # 우측 링크가 고정되어 있으므로 본문 안에서 휠을 보내고 두 영역의 스크롤을 혼동하지 않는다.
   workspace_bottom(page)
   metrics.update({'height':height,'footerVisible':True,'workspaceScrollTop':page.locator('.workspace-main').evaluate('(e)=>e.scrollTop')})
   checks.append(metrics)
   page.screenshot(path=str(OUT/f'layout-{width}-bottom.png'))
   workspace_top(page);page.screenshot(path=str(OUT/f'layout-{width}-top.png'))
  page.set_viewport_size({'width':390,'height':844})
  page.get_by_role('button',name='원문 나란히 보기',exact=True).click()
  expect(page.locator('.pdf canvas').last).to_be_attached()
  page.locator('.pdf-pair').hover();page.mouse.wheel(0,1200);page.wait_for_timeout(300)
  assert page.locator('.pdf-pair').evaluate('(e)=>e.scrollTop')>0
  page.screenshot(path=str(OUT/'pdf-mobile.png'))
  page.get_by_role('button',name='원문 보기 닫기').click()
  assert not errors,errors
  checks.append({'javascriptErrors':errors,'mobilePdfScroll':True})
  page.set_viewport_size({'width':1440,'height':900})
  # 이력 유지 검사: 저장 위치를 UI에서 변경한 뒤 이전 결과의 문서 ID URL과 양쪽 Canvas 표시를 다시 검증한다.
  # /api/results는 요약만 주므로 각 결과의 행은 상세 API로 받는다.
  old_results=page.evaluate("async()=>Promise.all((await(await fetch('/api/results')).json()).map(async s=>(await fetch('/api/results/'+s.id)).json()))")
  docs=[d for r in old_results for row in r['rows'] for d in (row['invoice'],row['contract'])]
  page.get_by_role('button',name='설정',exact=True).click()
  new_root=OUT/'relocated'
  page.locator('#folder').fill(str(new_root))
  page.get_by_role('button',name='저장 위치 적용',exact=True).click()
  expect(page.get_by_role('status')).to_contain_text('기존 PDF도 함께 옮겼습니다',timeout=30000)
  assert not list(originals.glob('*.pdf'))
  for d in {d['id']:d for d in docs}.values():
   response=page.request.get(base+'/api/documents/'+d['id'])
   assert response.status==200 and response.body().startswith(b'%PDF')
  page.get_by_role('button',name='비교 결과',exact=True).click()
  page.get_by_role('button',name='원문 나란히 보기',exact=True).click()
  expect(page.locator('.pdf .spin, .pdf .error')).to_have_count(0,timeout=15000)
  expect(page.locator('.pdf canvas').first).not_to_have_js_property('width',300)
  expect(page.locator('.pdf canvas').last).not_to_have_js_property('width',300)
  page.screenshot(path=str(OUT/'pdf-after-storage-move.png'))
  checks.append({'storageMigration':'UI folder change moved originals; historical PDF URLs and both viewers work'})
  browser.close()
 (OUT/'checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(checks,ensure_ascii=False,indent=2))
finally:
 server.terminate();server.wait(timeout=15);log.close()
