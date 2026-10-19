# [파일 기능명세]
# 업무 처리 계층. 단일 작업 스레드에서 사이트 수집·다운로드·비교를 순차 실행하고, 진행 상태와 결과 ID를 저장한다. 사이트 DOM과 PDF 양식 변경 시 수집·판독 규칙을 확인한다.
# 유지보수: 함수·데이터 계약이 바뀌면 해당 기능명세와 실제 회귀 검사를 함께 갱신한다.

import copy
import hashlib
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.sync_api import sync_playwright

from .compare import compare, extract, norm
from .store import Store, now

SITE = "https://sbgw.vercel.app/"


# [기능명세] allowed_url
# 목적: 다운로드 링크의 도메인·형식 제한
# 입력: (url)
# 출력: 검증된 원본 URL 문자열
# 처리: urlsplit 후 HTTPS·지정 도메인·.pdf 경로 검사
# 예외/실패: 조건 불일치는 ValueError
# 부수효과: 없음; 네트워크 접속하지 않음
def allowed_url(url):
    u = urlsplit(url)
    if u.scheme != "https" or u.netloc != "sbgw.vercel.app" or not u.path.lower().endswith(".pdf"):
        raise ValueError("대상 사이트의 PDF 다운로드 링크만 사용할 수 있습니다.")
    return url


# [자료형/클래스 명세] Service: 업무 서비스. Store·단일 작업 실행기·브라우저·작업 상태를 소유하며 동시 주요 작업을 제한한다.
class Service:
    # [기능명세] Service.__init__
    # 목적: 작업 서비스와 이전 작업 상태 초기화
    # 입력: (self, store: Store)
    # 출력: None
    # 처리: Store 보관·단일 작업 실행기·RLock 생성 후 meta.jobs 복원
    # 예외/실패: 기존 running 작업은 실패 표시; 손상 JSON/DB 오류는 전파
    # 부수효과: 메모리 작업 상태 생성; 이 시점에는 사이트 브라우저를 열지 않음
    def __init__(self, store: Store):
        self.store = store
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="site-worker")
        self.lock = threading.RLock()
        self.jobs = {}
        self.pw = self.context = self.page = None
        self.closing = False
        with store.lock:
            row = store.db.execute("SELECT value FROM meta WHERE key='jobs'").fetchone()
        if row:
            self.jobs = json.loads(row[0])
            for j in self.jobs.values():
                if j["status"] == "running":
                    j.update(status="failed", message="이전 실행이 종료되었습니다. 저장 파일은 유지되며 작업을 다시 실행할 수 있습니다.")

    # [기능명세] Service.persist_jobs
    # 목적: 현재 작업 상태를 DB에 저장
    # 입력: (self)
    # 출력: None
    # 처리: Store 잠금과 SQLite 트랜잭션으로 meta.jobs JSON 교체
    # 예외/실패: DB 오류는 호출자에게 전파
    # 부수효과: meta 테이블 갱신
    def persist_jobs(self):
        with self.store.lock, self.store.db:
            self.store.db.execute("INSERT OR REPLACE INTO meta VALUES('jobs',?)", (json.dumps(self.jobs, ensure_ascii=False),))

    # [기능명세] Service.update
    # 목적: 한 작업의 진행 필드를 갱신하고 저장
    # 입력: (self, job, **kw)
    # 출력: None
    # 처리: 서비스 잠금 안에서 jobs[job]에 kw 병합 후 영속화
    # 예외/실패: 없는 작업 ID는 KeyError; 저장 오류 전파
    # 부수효과: 메모리 작업과 meta.jobs 변경
    def update(self, job, **kw):
        with self.lock:
            self.jobs[job].update(**kw)
            self.persist_jobs()

    # [기능명세] Service.submit
    # 목적: 주요 작업을 접수하고 백그라운드 실행
    # 입력: (self, kind, fn, *args)
    # 출력: 작업 ID를 담은 사전
    # 처리: 종료·진행 중 검사→약 20개 작업 유지→running 저장→실행기에 run 제출
    # 예외/실패: 종료 중 또는 다른 작업 실행 중이면 ValueError
    # 부수효과: 작업 스레드 예약·작업 상태 DB 저장; 완료 결과는 후속 조회
    def submit(self, kind, fn, *args):
        with self.lock:
            if self.closing or any(j["status"] == "running" for j in self.jobs.values()):
                raise ValueError("현재 작업이 끝난 뒤 실행해 주세요.")
            id = uuid4().hex
            self.jobs = dict(list(self.jobs.items())[-19:])
            self.jobs[id] = {"id": id, "kind": kind, "status": "running", "message": "작업 준비 중", "done": 0, "total": 1, "errors": [], "created": now()}
            self.persist_jobs()

        # [기능명세] Service.submit.run
        # 목적: 제출 함수 실행과 성공·실패 상태 전환
        # 입력: ()
        # 출력: None
        # 처리: fn(id,*args) 호출 후 done; 예외는 failed와 메시지로 변환
        # 예외/실패: 업무 예외를 작업 상태로 기록하고 외부로 다시 던지지 않음
        # 부수효과: 해당 작업 상태 저장; 실제 부수효과는 fn의 명세를 따름
        def run():
            try:
                fn(id, *args)
                self.update(id, status="done", message="작업 완료")
            except Exception as e:
                self.update(id, status="failed", message=f"작업 실패: {e}")
        self.pool.submit(run)
        return {"id": id}

    # [기능명세] Service.browser
    # 목적: 사이트 자동화용 페이지를 재사용하거나 생성
    # 입력: (self)
    # 출력: Playwright Page
    # 처리: 유효 페이지 재사용→닫힌 컨텍스트 정리→번들 Chromium·지속 프로필로 생성
    # 예외/실패: 브라우저 실행 실패는 전파
    # 부수효과: 사이트용 프로필과 브라우저 프로세스 생성; 기본 제한시간 15초
    def browser(self):
        if self.context:
            try:
                self.context.pages
                if self.page and not self.page.is_closed():
                    return self.page
            except Exception:
                pass
            self.close_browser()
        bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "browser"
        if bundle.exists():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundle)
        self.pw = sync_playwright().start()
        self.context = self.pw.chromium.launch_persistent_context(str(self.store.root / "browser-profile"), headless=False, accept_downloads=True, viewport={"width": 1280, "height": 860})
        self.context.set_default_timeout(15000)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self.page

    # [기능명세] Service.close_browser
    # 목적: 사이트 브라우저와 Playwright 정리
    # 입력: (self)
    # 출력: None
    # 처리: context.close와 pw.stop을 각각 시도 후 참조 비우기
    # 예외/실패: 정리 중 예외는 삼켜 종료 흐름 지속
    # 부수효과: 사이트 자동화 브라우저 종료; 앱 화면 컨텍스트는 launcher가 담당
    def close_browser(self):
        try:
            if self.context:
                self.context.close()
        except Exception:
            pass
        try:
            if self.pw:
                self.pw.stop()
        except Exception:
            pass
        self.context = self.page = self.pw = None

    # [기능명세] Service.open_browser
    # 목적: 사용자 로그인용 그룹웨어 메일 화면 열기
    # 입력: (self, job)
    # 출력: None
    # 처리: browser로 페이지 확보→#/mail 이동→완료 수 갱신
    # 예외/실패: 탐색 실패는 상위 작업 래퍼가 실패 처리
    # 부수효과: 사이트 네트워크 접속·브라우저 표시·작업 DB 갱신
    def open_browser(self, job):
        self.browser().goto(SITE + "#/mail", wait_until="domcontentloaded")
        self.update(job, done=1, message="전용 브라우저를 열었습니다.")

    # [기능명세] Service.sync
    # 목적: 그룹웨어의 메일·계약 목록 동기화
    # 입력: (self, job)
    # 출력: None
    # 처리: 메일 DOM 수집→계약 전체 필터·행 수집→양식 검사→snapshot 일괄 저장
    # 예외/실패: 빈 목록·계약 열 수 불일치·탐색 실패 시 기존 스냅샷 유지
    # 부수효과: 사이트 접속·목록과 동기화 시각·진행 상태 저장
    def sync(self, job):
        page = self.browser()
        self.update(job, total=2, message="메일함 목록을 가져오는 중")
        page.goto(SITE + "#/mail", wait_until="domcontentloaded")
        page.locator('#app h2').filter(has_text="받은 메일함").wait_for(timeout=30000)
        mails = page.locator('tr[data-testid="mail-row"]').evaluate_all("""rows => rows.map(r=>({id:r.dataset.id, cells:[...r.querySelectorAll('td')].map(c=>c.innerText), attachments:[...r.querySelectorAll('a[download]')].map(a=>({name:a.getAttribute('download'),url:a.href}))}))""")
        mail_items = []
        for m in mails:
            cells = m["cells"]
            mail_items.append({"id": m["id"], "sender": cells[0], "subject": cells[1], "received": cells[2], "attachments": m["attachments"]})
        self.update(job, done=1, message="계약 문서함 목록을 가져오는 중")
        page.get_by_role("link", name="계약 문서함", exact=True).click()
        page.locator("#contract-filter").wait_for()
        page.locator("#contract-filter").select_option(label="전체")
        contracts = page.locator('tr[data-testid="contract-row"]').evaluate_all("""rows => rows.map(r=>({id:r.dataset.id, cells:[...r.querySelectorAll('td')].map(c=>c.innerText), files:[...r.querySelectorAll('a[download]')].map(a=>({name:a.getAttribute('download'),url:a.href}))}))""")
        contract_items = []
        for c in contracts:
            xs = c["cells"]
            if len(xs) != 7:
                raise ValueError("계약 목록 양식이 바뀌었습니다. 기존 목록을 유지합니다.")
            contract_items.append({"id": c["id"], "kind": xs[1], "partner": xs[2], "title": xs[3], "period": xs[4], "amount_text": xs[5], "file": next((f for f in c["files"] if f["name"].lower().endswith(".pdf")), None)})
        if not mail_items or not contract_items:
            raise ValueError("메일·계약 목록이 비어 있습니다. 전용 브라우저의 로그인과 화면을 확인해 주세요.")
        self.store.snapshot(mail_items, contract_items)
        self.update(job, done=2, message="목록 저장 완료")

    # [기능명세] Service.catalog
    # 목적: 화면용 목록과 추천 계약 구성
    # 입력: (self)
    # 출력: mails/contracts/synced 사전
    # 처리: 목록 조회→PDF 첨부·파일 존재 여부 구성→지출 계약의 업체명 후보 및 사업자번호 우선 후보 계산
    # 예외/실패: 조회·파일 검사 오류는 전파; 후보 여러 건은 그대로 제공
    # 부수효과: 조회한 메모리 사전 보강; DB 목록을 다시 쓰지 않음
    def catalog(self):
        mails = sorted(self.store.items("mails"), key=lambda m: m["received"], reverse=True)
        contracts = self.store.items("contracts")
        contract_docs = {c["id"]: self.store.document(source=c["file"]["url"]) if c["file"] else None for c in contracts}
        for m in mails:
            m["pdfs"] = [a for a in m["attachments"] if a["name"].lower().endswith(".pdf")]
            m["documents"] = {a["url"]: self.store.document(source=a["url"]) for a in m["pdfs"]}
            for a in m["pdfs"]:
                d = m["documents"][a["url"]]
                if d:
                    d["available"] = self.store.path(d).is_file()
            # 추천 람다/내포: 지출 계약의 정규화 업체명 후보를 구한 뒤, 추출된 사업자번호 일치 후보가 있으면 우선한다.
            matches = [c["id"] for c in contracts if c["kind"] == "지출" and norm(c["partner"]) in norm(m["sender"])]
            invoice_biz = {d["extraction"].get("fields", {}).get("biz", {}).get("value") for d in m["documents"].values() if d and d.get("available")}
            biz_matches = [c["id"] for c in contracts if c["kind"] == "지출" and contract_docs[c["id"]] and contract_docs[c["id"]]["extraction"].get("fields", {}).get("biz", {}).get("value") in invoice_biz - {None}]
            if biz_matches:
                matches = biz_matches
            m["candidates"] = matches
        for c in contracts:
            c["document"] = contract_docs[c["id"]]
            if c["document"]:
                c["document"]["available"] = self.store.path(c["document"]).is_file()
        return {"mails": mails, "contracts": contracts, "synced": self.store.synced()}

    # [기능명세] Service.validate_pairs
    # 목적: 비교 연결 관계의 유효성 검사
    # 입력: (self, pairs)
    # 출력: 메일 ID 사전과 계약 ID 사전의 튜플
    # 처리: 1~500건·메일/계약 존재·PDF 첨부 URL·메일 중복 검사
    # 예외/실패: 유효하지 않은 연결은 ValueError
    # 부수효과: DB 읽기만 수행; 파일 다운로드 없음
    def validate_pairs(self, pairs):
        if not pairs or len(pairs) > 500:
            raise ValueError("비교할 메일을 1~500건 선택해 주세요.")
        mails = {x["id"]: x for x in self.store.items("mails")}
        contracts = {x["id"]: x for x in self.store.items("contracts")}
        seen = set()
        for pair in pairs:
            m, c = mails.get(pair["mail_id"]), contracts.get(pair["contract_id"])
            if not m or not c or not c["file"]:
                raise ValueError("메일과 PDF 계약서를 연결해 주세요.")
            url = pair.get("invoice_url")
            if not any(a["url"] == url and a["name"].lower().endswith(".pdf") for a in m["attachments"]):
                raise ValueError("메일에 실제 첨부된 PDF를 선택해 주세요.")
            if pair["mail_id"] in seen:
                raise ValueError("같은 메일을 중복 선택할 수 없습니다.")
            seen.add(pair["mail_id"])
        return mails, contracts

    # [기능명세] Service.download_one
    # 목적: PDF 한 건 확보와 텍스트 추출·등록
    # 입력: (self, file, kind)
    # 출력: 문서 레코드 사전
    # 처리: 존재 파일 재사용→URL 검증→HTTP 다운로드→50MiB·PDF 시그니처 검사→해시·파일 저장→extract
    # 예외/실패: HTTP 오류·비PDF·크기 초과는 ValueError; 브라우저·파일 오류 전파
    # 부수효과: 네트워크·원본 PDF·추출값 DB 갱신; 재사용 시 재추출하지 않음
    def download_one(self, file, kind):
        # 캐시 재사용은 파일 존재 기준이다. URL의 원격 변경 감지나 기존 PDF 자동 재추출은 수행하지 않는다.
        old = self.store.document(source=file["url"])
        if old and self.store.path(old).is_file():
            return old
        url = allowed_url(file["url"])
        self.browser()
        response = self.context.request.get(url, timeout=30000, max_redirects=0)
        if response.status != 200:
            raise ValueError(f"다운로드 HTTP {response.status}: {file['name']}")
        body = response.body()
        if len(body) > 50 * 1024 * 1024 or not body.lstrip().startswith(b"%PDF-"):
            raise ValueError("PDF 형식이 아니거나 파일이 50MB를 초과합니다.")
        digest = hashlib.sha256(body).hexdigest()
        folder = self.store.document_root() / ("세금계산서" if kind == "invoice" else "계약서")
        folder.mkdir(parents=True, exist_ok=True)
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', file["name"])[:160].rstrip(". ")
        path = folder / (digest[:12] + "_" + name)
        if not path.exists():
            tmp = path.with_suffix(".part")
            tmp.write_bytes(body)
            tmp.replace(path)
        # 판독은 다운로드 시 수행해 documents.extraction에 저장한다. 비교 시에는 이 저장값을 사용한다.
        parsed = extract(path, kind)
        return self.store.save_document(url, file["name"], digest, parsed, path)

    # [기능명세] Service.download
    # 목적: 선택 연결의 PDF를 중복 없이 저장
    # 입력: (self, job, pairs)
    # 출력: None
    # 처리: 연결 검증→URL 기준 파일 합치기→개별 저장→파일별 오류 수집
    # 예외/실패: 종료 요청 또는 일부 실패면 ValueError; 성공한 파일은 유지
    # 부수효과: 여러 PDF·문서 DB·작업 진행 상태 변경
    def download(self, job, pairs):
        mails, contracts = self.validate_pairs(pairs)
        files = {}
        for pair in pairs:
            invoice = next(a for a in mails[pair["mail_id"]]["attachments"] if a["url"] == pair["invoice_url"])
            files[invoice["url"]] = (invoice, "invoice")
            f = contracts[pair["contract_id"]]["file"]
            files[f["url"]] = (f, "contract")
        self.update(job, total=len(files))
        errors = []
        for i, (f, kind) in enumerate(files.values()):
            if self.closing:
                raise ValueError("프로그램 종료 요청으로 중단했습니다. 저장한 파일은 유지됩니다.")
            self.update(job, message=f"PDF 저장·내용 읽기: {f['name']}")
            try:
                self.download_one(f, kind)
            except Exception as e:
                errors.append(f"{f['name']}: {e}")
            self.update(job, done=i + 1, errors=errors)
        if errors:
            raise ValueError(f"{len(errors)}개 파일 저장 실패. 상세 오류를 확인하고 재시도하세요.")

    # [기능명세] Service.run_compare
    # 목적: 저장된 추출값으로 비교 및 보정 이력 생성
    # 입력: (self, job, pairs, overrides=None, parent=None)
    # 출력: None; 작업에 result_id 기록
    # 처리: 파일 존재 확인→추출값 deepcopy→보정·동일 계약 그룹 적용→compare→새 결과 저장
    # 예외/실패: 문서 누락은 ValueError; 추출값과 원본 PDF는 덮어쓰지 않음
    # 부수효과: 로컬 결과·작업 DB 저장; 외부 네트워크 접속 없음
    def run_compare(self, job, pairs, overrides=None, parent=None):
        mails, contracts = self.validate_pairs(pairs)
        records = []
        for pair in pairs:
            inv = self.store.document(source=pair["invoice_url"])
            con = self.store.document(source=contracts[pair["contract_id"]]["file"]["url"])
            if not inv or not con or not self.store.path(inv).exists() or not self.store.path(con).exists():
                raise ValueError("선택 문서 다운로드를 먼저 완료해 주세요. 비교는 네트워크를 사용하지 않습니다.")
            records.append((pair, inv, con))
        edits = overrides or {}
        result_rows = []
        self.update(job, total=len(records), message="로컬 문서 비교 중 · 네트워크·AI 미사용")
        for index, (pair, inv, con) in enumerate(records):
            parsed = copy.deepcopy(inv["extraction"])
            for key, value in edits.get(inv["id"], {}).items():
                previous = parsed["fields"].get(key)
                parsed["fields"][key] = {"value": value, "quote": "사용자 수동 보정", "page": None, "method": "수동 보정", "previous": previous}
            # Reuse the same corrected values in grouped installment checks.
            group = []
            for p, di, dc in records:
                if p["contract_id"] == pair["contract_id"]:
                    d = copy.deepcopy(di["extraction"])
                    for k, v in edits.get(di["id"], {}).items():
                        d["fields"][k] = {"value": v}
                    group.append(d)
            result_rows.append({"mail_id": pair["mail_id"], "contract_id": pair["contract_id"], "subject": mails[pair["mail_id"]]["subject"], "partner": contracts[pair["contract_id"]]["partner"],
                                "invoice": inv, "contract": con, "effective_invoice": parsed,
                                **compare(parsed, con["extraction"], group)})
            self.update(job, done=index + 1)
        result = self.store.save_result({"rows": result_rows, "pairs": pairs, "overrides": edits, "parent": parent})
        self.update(job, result_id=result["id"])

    # [기능명세] Service.close
    # 목적: 작업 접수를 막고 실행기와 브라우저 종료
    # 입력: (self)
    # 출력: None
    # 처리: closing 설정→같은 작업 스레드에 브라우저 정리 예약→실행기 종료 대기
    # 예외/실패: 실행기 예약·종료 오류는 전파
    # 부수효과: 작업 스레드·사이트 브라우저 종료; 대기 작업은 마무리될 수 있음
    def close(self):
        self.closing = True
        self.pool.submit(self.close_browser)
        self.pool.shutdown(wait=True)
