# [파일 기능명세] 한 화면 2단 업무 공간의 실제 스크롤 검증 도우미.
# 브라우저 DOM의 스크롤 위치만 바꾸며 서버·사용자 파일을 변경하지 않는다.


# [기능명세] workspace_top
# 목적: 문서와 본문 패널을 모두 처음으로 이동한다.
# 입력: Playwright Page, 출력 없음. DOM 상태만 변경하며 요소 부재는 허용한다.
def workspace_top(page):
    page.evaluate("()=>{window.scrollTo(0,0);const e=document.querySelector('.workspace-main');if(e)e.scrollTop=0}")


# [기능명세] workspace_bottom
# 목적: 본문 안 실제 휠로 footer에 도달하는지 검사한다.
# 입력: Playwright Page, 출력은 footer bounding box. 실패하면 AssertionError.
# 처리: 본문 스크롤바 안쪽으로 포인터를 옮겨 휠을 반복하고 footer가 패널 안에 있는지 확인한다.
# 부수효과: 스크롤 위치 변경. 우측 관련 링크 스크롤·서버 요청을 수행하지 않는다.
def workspace_bottom(page):
    workspace = page.locator('.workspace-main')
    box = workspace.bounding_box()
    assert box, '업무 본문이 표시되지 않았습니다.'
    page.mouse.move(box['x']+box['width']-20, box['y']+box['height']/2)
    for _ in range(15):
        page.mouse.wheel(0,2000)
        page.wait_for_timeout(35)
    bottom = page.locator('footer').bounding_box()
    assert bottom and bottom['y'] >= box['y']-1 and bottom['y']+bottom['height'] <= box['y']+box['height']+1, (box,bottom)
    return bottom
