# [파일 기능명세]
# 그룹웨어 사이트 접속 계층. 사이트 자동화용 Playwright 브라우저(지속 프로필)의 생성·재사용·정리, 메일 화면 열기, 메일·계약 목록 수집, PDF 다운로드 검사, 지출결의서 기안 입력·상신(submit_expense)을 맡는다.
# 처리 흐름: page()로 브라우저 확보 → open_mail/fetch_mails/fetch_contracts(구분 필터 선택, 사이트 밖이면 계약 화면으로 직접 이동)로 DOM 읽기 → check_lists로 빈 목록 검사 → request_pdf(context, …)로 PDF 바이트 확보 → close로 정리.
# 사이트에 쓰는(상신하는) 메서드는 submit_expense(지출결의서 기안 입력·상신) 하나뿐이며, 나머지는 모두 읽기 전용이다. 이 메서드의 상신 이후 오류는 SubmitUncertain으로 구분한다.
# 작업 진행 상태 갱신은 하지 않는다(Service가 단계 사이에 갱신). 사이트 DOM이 바뀌면 선택자·열 수 규칙을 확인한다.
# 유지보수: 함수·데이터 계약이 바뀌면 해당 기능명세와 실제 회귀 검사를 함께 갱신한다.

import logging
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from .config import MAX_PDF_BYTES, SITE_HOST, SITE_URL
from .errors import SubmitUncertain

log = logging.getLogger(__name__)

# 목록 행 읽기 JS. 각 행의 data-id, 셀 텍스트, 다운로드 링크(이름·절대 URL)를 반환한다. 메일·계약이 같은 구조를 쓴다.
ROWS_JS = """rows => rows.map(r=>({id:r.dataset.id, cells:[...r.querySelectorAll('td')].map(c=>c.innerText), files:[...r.querySelectorAll('a[download]')].map(a=>({name:a.getAttribute('download'),url:a.href}))}))"""


# [기능명세] allowed_url
# 목적: 다운로드 링크의 도메인·형식 제한
# 입력: (url)
# 출력: 검증된 원본 URL 문자열
# 처리: urlsplit 후 HTTPS·config.SITE_HOST 도메인·.pdf 경로 검사
# 예외/실패: 조건 불일치는 ValueError('대상 사이트의 PDF 다운로드 링크만 사용할 수 있습니다.')
# 부수효과: 없음; 네트워크 접속하지 않음
def allowed_url(url):
    u = urlsplit(url)
    if u.scheme != "https" or u.netloc != SITE_HOST or not u.path.lower().endswith(".pdf"):
        raise ValueError("대상 사이트의 PDF 다운로드 링크만 사용할 수 있습니다.")
    return url


# [기능명세] read_pdf_response
# 목적: PDF 다운로드 응답의 상태·크기·형식 검사
# 입력: (response: status 속성과 body()를 가진 응답, name: 오류 문구에 쓸 파일 이름)
# 출력: PDF 본문 bytes
# 처리: HTTP 200 확인 → 본문 읽기 → MAX_PDF_BYTES 이하이고 앞 공백 제거 후 '%PDF-'로 시작하는지 확인
# 예외/실패: 200이 아니면 ValueError('다운로드 HTTP {상태}: {이름}'); 크기 초과·비PDF는 ValueError('PDF 형식이 아니거나 파일이 50MB를 초과합니다.')
# 부수효과: 없음(응답 본문 읽기만)
def read_pdf_response(response, name):
    if response.status != 200:
        raise ValueError(f"다운로드 HTTP {response.status}: {name}")
    body = response.body()
    if len(body) > MAX_PDF_BYTES or not body.lstrip().startswith(b"%PDF-"):
        raise ValueError("PDF 형식이 아니거나 파일이 50MB를 초과합니다.")
    return body


# [기능명세] request_pdf
# 목적: 브라우저 컨텍스트의 요청 기능으로 PDF 한 건을 받아 검사
# 입력: (context: request.get을 가진 Playwright BrowserContext 또는 대역, url, name)
# 출력: PDF 본문 bytes
# 처리: allowed_url 검증 → request.get(timeout 30초, 리다이렉트 금지) → read_pdf_response
# 예외/실패: URL 거부·HTTP 오류·비PDF·크기 초과는 ValueError; 네트워크 오류는 전파
# 부수효과: 사이트 네트워크 접속(로그인 쿠키 사용)
def request_pdf(context, url, name):
    url = allowed_url(url)
    response = context.request.get(url, timeout=30000, max_redirects=0)
    return read_pdf_response(response, name)


# [자료형/클래스 명세] SiteClient: 사이트 자동화 브라우저 소유자. Playwright 인스턴스(pw)·지속 컨텍스트(context)·작업 페이지(page)와 프로필 폴더를 보관한다.
# 모든 메서드는 단일 작업 스레드에서 호출하는 것이 전제다(Playwright sync API 스레드 제약).
class SiteClient:
    # [기능명세] SiteClient.__init__
    # 목적: 브라우저 프로필 위치만 기억하고 실제 브라우저는 늦게 연다
    # 입력: (self, profile_dir: 지속 프로필 폴더 Path)
    # 출력: None
    # 처리: 경로 보관, pw/context/page를 None으로 초기화
    # 예외/실패: 없음
    # 부수효과: 없음; 이 시점에는 브라우저를 열지 않음
    def __init__(self, profile_dir):
        self.profile_dir = Path(profile_dir)
        self.pw = self.context = self.page_obj = None

    # [기능명세] SiteClient.page
    # 목적: 사이트 자동화용 페이지를 재사용하거나 생성
    # 입력: (self)
    # 출력: Playwright Page
    # 처리: 유효 페이지 재사용 → 닫힌 컨텍스트 정리 → 번들 Chromium·지속 프로필로 생성
    # 예외/실패: 브라우저 실행 실패는 전파; 재사용 판정 중 예외는 debug 로그 후 재생성
    # 부수효과: 프로필과 브라우저 프로세스 생성, PLAYWRIGHT_BROWSERS_PATH 설정(번들 있을 때); 기본 제한시간 15초
    def page(self):
        if self.context:
            try:
                self.context.pages
                if self.page_obj and not self.page_obj.is_closed():
                    return self.page_obj
            except Exception:
                log.debug("사이트 브라우저 재사용 불가, 다시 엽니다.", exc_info=True)
            self.close()
        bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "browser"
        if bundle.exists():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundle)
        self.pw = sync_playwright().start()
        self.context = self.pw.chromium.launch_persistent_context(str(self.profile_dir), headless=False, accept_downloads=True, viewport={"width": 1280, "height": 860})
        self.context.set_default_timeout(15000)
        self.page_obj = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self.page_obj

    # [기능명세] SiteClient.close
    # 목적: 사이트 브라우저와 Playwright 정리
    # 입력: (self)
    # 출력: None
    # 처리: context.close와 pw.stop을 각각 시도 후 참조 비우기
    # 예외/실패: 정리 중 예외는 warning 로그만 남기고 종료 흐름 지속
    # 부수효과: 사이트 자동화 브라우저 종료; 앱 화면 컨텍스트는 launcher가 담당
    def close(self):
        try:
            if self.context:
                self.context.close()
        except Exception:
            log.warning("사이트 브라우저 컨텍스트 정리 실패", exc_info=True)
        try:
            if self.pw:
                self.pw.stop()
        except Exception:
            log.warning("Playwright 정리 실패", exc_info=True)
        self.context = self.page_obj = self.pw = None

    # [기능명세] SiteClient.open_mail
    # 목적: 사용자 로그인용 그룹웨어 메일 화면 열기
    # 입력: (self)
    # 출력: Playwright Page
    # 처리: page 확보 → SITE_URL#/mail 이동(domcontentloaded)
    # 예외/실패: 탐색 실패는 전파
    # 부수효과: 사이트 네트워크 접속·브라우저 표시
    def open_mail(self):
        page = self.page()
        page.goto(SITE_URL + "#/mail", wait_until="domcontentloaded")
        return page

    # [기능명세] SiteClient._rows
    # 목적: 메일·계약 목록 행 읽기 공통 헬퍼
    # 입력: (page, testid: 행의 data-testid 값)
    # 출력: [{id, cells:[str], files:[{name,url}]}] 목록
    # 처리: tr[data-testid=testid] 전체에 ROWS_JS 실행
    # 예외/실패: 페이지 오류는 전파
    # 부수효과: 없음(DOM 읽기)
    @staticmethod
    def _rows(page, testid):
        return page.locator(f'tr[data-testid="{testid}"]').evaluate_all(ROWS_JS)

    # [기능명세] SiteClient.fetch_mails
    # 목적: 받은 메일함 목록 수집
    # 입력: (self)
    # 출력: [{id, sender, subject, received, attachments:[{name,url}]}]
    # 처리: 메일 화면 이동 → '받은 메일함' 제목 대기(30초) → 행 읽기 → mail_item으로 셀 0/1/2를 발신자·제목·수신일로 매핑
    # 예외/실패: 탐색·대기 실패는 전파; 셀이 3개 미만이면 ValueError('메일 목록 양식이 바뀌었습니다. 기존 목록을 유지합니다.')
    # 부수효과: 사이트 접속; 저장하지 않음
    def fetch_mails(self):
        page = self.open_mail()
        page.locator('#app h2').filter(has_text="받은 메일함").wait_for(timeout=30000)
        return [mail_item(m) for m in self._rows(page, "mail-row")]

    # [기능명세] SiteClient._stable_rows
    # 목적: 필터 변경 직후 표가 다시 그려지는 도중의 행을 읽지 않도록 안정된 행 목록을 읽는다.
    # 입력: (page, testid, timeout=5.0: 최대 대기 초, interval_ms=200: 읽기 간격)
    # 출력: _rows와 같은 형식의 행 목록(연속 두 번 읽은 결과가 같아진 값, 빈 표도 두 번 연속 비어 있으면 안정으로 봄)
    # 처리: _rows 읽기 → page.wait_for_timeout(interval_ms) → 다시 읽어 직전과 같으면 반환. 제한시간이 지나면 마지막으로 읽은 값을 반환
    # 예외/실패: 페이지 오류는 전파(제한시간 초과 자체는 오류로 만들지 않음 — 열 수 검사가 최종 방어)
    # 부수효과: 짧은 대기(보통 약 0.2초)만 발생; DOM을 바꾸지 않음
    @classmethod
    def _stable_rows(cls, page, testid, timeout=5.0, interval_ms=200):
        deadline = time.monotonic() + timeout
        last = cls._rows(page, testid)
        while True:
            page.wait_for_timeout(interval_ms)
            rows = cls._rows(page, testid)
            if rows == last or time.monotonic() >= deadline:
                return rows
            last = rows

    # [기능명세] SiteClient.fetch_contracts
    # 목적: 계약 문서함 목록을 구분(전체/수입/지출)별로 수집
    # 입력: (self, kind="전체": 구분 필터 표시 이름 — "전체"|"수입"|"지출")
    # 출력: [{id, kind, partner, title, period, amount_text, file:{name,url}|None}] — 사이트 표시 순서
    # 처리: 페이지가 이미 사이트(SITE_HOST) 안이면 기존처럼 '계약 문서함' 링크 클릭(동기화 흐름 유지),
    #       사이트 밖(about:blank 등)이면 SITE_URL#/contracts로 직접 이동 → #contract-filter 대기 → select_option(label=kind)
    #       → 필터 적용 뒤 표가 안정될 때까지 대기(_stable_rows)한 행 읽기 → 열 7개 검사 → 첫 PDF 파일 선택
    # 예외/실패: 열 수가 7이 아니면 ValueError('계약 목록 양식이 바뀌었습니다. 기존 목록을 유지합니다.'); 없는 구분 이름·탐색 실패는 Playwright 오류 전파
    # 부수효과: 사이트 접속·화면 이동·필터 변경; 저장하지 않음
    def fetch_contracts(self, kind="전체"):
        items = []
        page = self.page()
        if urlsplit(page.url).netloc == SITE_HOST:
            page.get_by_role("link", name="계약 문서함", exact=True).click()
        else:
            page.goto(SITE_URL + "#/contracts", wait_until="domcontentloaded")
        page.locator("#contract-filter").wait_for()
        page.locator("#contract-filter").select_option(label=kind)
        for c in self._stable_rows(page, "contract-row"):
            xs = c["cells"]
            if len(xs) != 7:
                raise ValueError("계약 목록 양식이 바뀌었습니다. 기존 목록을 유지합니다.")
            items.append({"id": c["id"], "kind": xs[1], "partner": xs[2], "title": xs[3], "period": xs[4], "amount_text": xs[5], "file": next((f for f in c["files"] if f["name"].lower().endswith(".pdf")), None)})
        return items

    # [기능명세] SiteClient.submit_expense
    # 목적: 확인한 지출결의서 값을 사이트에 입력·상신하고 작성본 DOM을 읽는다.
    # 입력: 관리번호 contract_id, 검증된 values(제목·월·금액·첨부·특이사항).
    # 출력: 문서 ID·번호·URL·제목·금액 칸·본문 원문과 첨부 누락 경고 사전.
    # 처리: 기안 양식과 계약 option 확인 → 입력 → 존재하는 첨부만 체크 → 상신 → 오류 또는 작성본 이동 대기 → DOM 읽기.
    # 예외/실패: 계약 없음·사이트 폼 오류 표시는 ValueError, 상신 버튼 클릭 이전의 탐색·DOM 변경·시간 초과는 그대로 전파.
    #           클릭 호출 중 오류와 클릭 이후의 시간 초과·선택자 오류·결과 읽기 실패는 errors.SubmitUncertain(기안이 이미 있을 수 있음)으로 감싸 던진다. 자동 재상신하지 않는다.
    # 부수효과: 사이트 접속과 전용 브라우저 localStorage에 기안 저장. DB 갱신은 서비스가 담당한다.
    def submit_expense(self, contract_id, values):
        page = self.page()
        page.goto(SITE_URL + "#/draft", wait_until="domcontentloaded")
        page.locator("#f-form").wait_for()
        options = page.locator("#f-contract option").evaluate_all("xs => xs.map(x => x.value)")
        if contract_id not in options:
            raise ValueError("사이트의 기안 계약 목록에서 해당 계약을 찾을 수 없습니다.")
        page.locator("#f-form").select_option(label="지출결의서")
        page.locator("#f-title").fill(values["title"])
        page.locator("#f-contract").select_option(contract_id)
        for selector, key in (("#f-month", "month"), ("#f-supply", "supply"), ("#f-vat", "vat"), ("#f-total", "total"), ("#f-note", "note")):
            page.locator(selector).fill(str(values[key]))
        available = page.locator('input[name="attachments"]').evaluate_all("xs => xs.map(x => x.value)")
        warnings = []
        for name in values["attachments"]:
            if name in available:
                page.locator('input[name="attachments"]').nth(available.index(name)).check()
            else:
                warnings.append(f"사이트에 첨부 후보가 없어 선택하지 못했습니다: {name}")
        # 상신 버튼 클릭 자체와 그 뒤의 오류는 사이트에 기안이 만들어졌는지 알 수 없으므로 SubmitUncertain으로 감싼다(사이트 폼 오류 표시는 제외).
        rejected = None
        try:
            page.get_by_test_id("submit").click()
            page.wait_for_function("() => location.hash.startsWith('#/doc/') || !!document.querySelector('[data-testid=\"form-error\"]:not([hidden])')", timeout=30000)
            if "#/doc/" not in page.url:
                rejected = page.get_by_test_id("form-error").inner_text()
            else:
                page.get_by_test_id("doc-title").wait_for()
                return {"doc_id": page.url.split("#/doc/", 1)[1], "doc_no": page.locator(".user-tbl tr").filter(has_text="문서번호").locator("td").inner_text().strip(),
                        "doc_url": page.url, "title": page.get_by_test_id("doc-title").inner_text(),
                        "amount": page.get_by_test_id("doc-amount").inner_text(), "content": page.get_by_test_id("doc-content").inner_text(), "warnings": warnings}
        except Exception as exc:
            raise SubmitUncertain(f"상신 버튼을 누른 뒤 오류가 나 사이트에 기안이 만들어졌는지 확인이 필요합니다. ({type(exc).__name__}: {exc})") from exc
        raise ValueError("사이트 상신 오류: " + rejected)


# [기능명세] mail_item
# 목적: 메일 목록 행 한 건을 목록 항목으로 변환(셀 수 검사 포함, fetch_mails에서 분리한 순수 함수)
# 입력: (m: {id, cells:[str], files:[{name,url}]})
# 출력: {id, sender, subject, received, attachments}
# 처리: 셀 0/1/2를 발신자·제목·수신일로 매핑하고 files를 attachments로 둠
# 예외/실패: 셀이 3개 미만이면 ValueError('메일 목록 양식이 바뀌었습니다. 기존 목록을 유지합니다.')
# 부수효과: 없음
def mail_item(m):
    cells = m["cells"]
    if len(cells) < 3:
        raise ValueError("메일 목록 양식이 바뀌었습니다. 기존 목록을 유지합니다.")
    return {"id": m["id"], "sender": cells[0], "subject": cells[1], "received": cells[2], "attachments": m["files"]}


# [기능명세] check_lists
# 목적: 동기화 결과가 비어 있지 않은지 확인
# 입력: (mail_items, contract_items)
# 출력: None
# 처리: 둘 중 하나라도 비면 오류
# 예외/실패: ValueError('메일·계약 목록이 비어 있습니다. 전용 브라우저의 로그인과 화면을 확인해 주세요.')
# 부수효과: 없음
def check_lists(mail_items, contract_items):
    if not mail_items or not contract_items:
        raise ValueError("메일·계약 목록이 비어 있습니다. 전용 브라우저의 로그인과 화면을 확인해 주세요.")
