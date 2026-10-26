# [파일 기능명세]
# '계약서 목록' 백엔드 회귀 검사. 계약 선택 순수 함수(select_contracts·contract_sort_key), Store의 가져온 계약 기록(contract_imports)과
# snapshot 뒤 유지, API 입력 검증(422)·작업 접수 인자·pages 비움, Service.import_contracts 전체 흐름(가짜 SiteClient와 fixture PDF)을 검증한다.
# 외부 네트워크와 실제 브라우저를 쓰지 않는다. DB·파일은 tmp_path 안에서만 만든다.
# 유지보수: 공유 API 계약(기획/계약서목록_구축계획.md)이나 import 흐름이 바뀌면 이 검사와 기능명세를 함께 갱신한다.

import time
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from saebom import config
from saebom.api import create_app
from saebom.service import Service, contract_sort_key, select_contracts
from saebom.store import Store

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "http://127.0.0.1:12345"
FILE_BASE = "https://sbgw.vercel.app/files/"


# [기능명세] row
# 목적: 사이트 계약 행 형태의 테스트 사전 생성
# 입력: (id: 관리번호, kind="지출", file=True: PDF 링크 포함 여부, name=None: 파일 이름)
# 출력: {id, kind, partner, title, period, amount_text, file:{name,url}|None}
# 처리: file이면 FILE_BASE + 이름으로 URL을 만듦(이름 기본값은 '계약서_{id}.pdf')
# 예외/실패: 없음
# 부수효과: 없음
def row(id, kind="지출", file=True, name=None):
    name = name or f"계약서_{id}.pdf"
    return {"id": id, "kind": kind, "partner": f"업체{id[-3:]}", "title": "유지보수", "period": "2026-01-01 ~ 2026-12-31",
            "amount_text": "1,000,000원", "file": {"name": name, "url": FILE_BASE + name} if file else None}


# [기능명세] unlock
# 목적: 실행 토큰과 비밀번호 인증을 마친 TestClient 준비
# 입력: (client: TestClient, token: 실행 토큰)
# 출력: None
# 처리: /?token= 으로 실행 쿠키 발급→config.APP_PASSWORD로 로그인
# 예외/실패: 인증 실패 시 AssertionError
# 부수효과: client 쿠키 설정
def unlock(client, token):
    assert client.get(f"/?token={token}").status_code == 200
    assert client.post("/api/auth/login", json={"password": config.APP_PASSWORD}).status_code == 200


# [기능명세] static_dir
# 목적: create_app에 넘길 최소 정적 폴더 생성
# 입력: (tmp_path)
# 출력: index.html이 있는 Path
# 처리: static 폴더와 index.html 생성
# 예외/실패: 파일 오류 전파
# 부수효과: tmp_path 안에 파일 생성
def static_dir(tmp_path):
    static = tmp_path / "static"
    static.mkdir(exist_ok=True)
    (static / "index.html").write_text("app")
    return static


# [기능명세] test_contract_sort_key_order
# 목적: 관리번호가 (연도, 번호) 숫자 기준 내림차순이 되고 형식이 다른 ID는 뒤로 가는지 검증
# 입력: ()
# 출력: None; 조건을 어기면 AssertionError
# 처리: 섞인 ID 목록을 contract_sort_key로 정렬해 기대 순서와 비교(연도 차이·None 포함)
# 예외/실패: 단언 실패
# 부수효과: 없음
def test_contract_sort_key_order():
    ids = ["C-2026-003", "X-1", "C-2026-040", "C-2025-999", "C-2026-015", None, "C-2026-039", "ABC"]
    ordered = sorted(ids, key=contract_sort_key)
    assert ordered[:5] == ["C-2026-040", "C-2026-039", "C-2026-015", "C-2026-003", "C-2025-999"]
    assert set(ordered[5:]) == {"X-1", "ABC", None}
    # 접두·접미가 붙은 문자열은 형식 불일치로 본다.
    assert contract_sort_key("C-2026-001x")[0] == 1


# [기능명세] test_select_contracts_combinations
# 목적: select_contracts의 최근 N개·안 가져온 것만·둘 다·limit 없음·정렬·입력 불변을 검증
# 입력: (only_new, limit, expected: 기대 관리번호 순서) — parametrize
# 출력: None; 조건을 어기면 AssertionError
# 처리: 순서가 섞인 목록과 가져온 ID {040, 038}로 호출해 결과 ID 순서 비교 후 입력 목록 순서 불변 확인
# 예외/실패: 단언 실패
# 부수효과: 없음
@pytest.mark.parametrize("only_new, limit, expected", [
    (False, None, ["C-2026-040", "C-2026-039", "C-2026-038", "C-2026-015", "C-2026-003", "기타"]),
    (False, 3, ["C-2026-040", "C-2026-039", "C-2026-038"]),
    (True, None, ["C-2026-039", "C-2026-015", "C-2026-003", "기타"]),
    (True, 2, ["C-2026-039", "C-2026-015"]),
    (False, 100, ["C-2026-040", "C-2026-039", "C-2026-038", "C-2026-015", "C-2026-003", "기타"]),
    (True, 1, ["C-2026-039"]),
])
def test_select_contracts_combinations(only_new, limit, expected):
    items = [row(i) for i in ("C-2026-003", "C-2026-040", "기타", "C-2026-015", "C-2026-038", "C-2026-039")]
    before = [c["id"] for c in items]
    chosen = select_contracts(items, limit, only_new, {"C-2026-040", "C-2026-038"})
    assert [c["id"] for c in chosen] == expected
    assert [c["id"] for c in items] == before


# [기능명세] test_select_contracts_all_imported
# 목적: 모두 가져온 상태에서 only_new면 빈 목록, 아니면 전체가 나오는지 검증
# 입력: ()
# 출력: None; 조건을 어기면 AssertionError
# 처리: 두 건을 모두 imported_ids에 넣고 두 모드로 호출
# 예외/실패: 단언 실패
# 부수효과: 없음
def test_select_contracts_all_imported():
    items = [row("C-2026-001"), row("C-2026-002")]
    assert select_contracts(items, None, True, {"C-2026-001", "C-2026-002"}) == []
    assert [c["id"] for c in select_contracts(items, None, False, {"C-2026-001", "C-2026-002"})] == ["C-2026-002", "C-2026-001"]


# [기능명세] test_contract_imports_survive_snapshot
# 목적: 가져온 계약 기록이 저장·재저장·정렬되고 snapshot()의 items 전체 교체 뒤에도 유지되는지 검증
# 입력: (tmp_path)
# 출력: None; 조건을 어기면 AssertionError
# 처리: 세 건 저장→ID 집합·관리번호 큰 순·imported 시각 확인→snapshot→재조회→같은 ID 재저장 시 행 갱신(중복 없음)→DB 재연결 후 유지
# 예외/실패: 단언 실패
# 부수효과: tmp_path 임시 DB 변경
def test_contract_imports_survive_snapshot(tmp_path):
    store = Store(tmp_path / "db")
    for i in ("C-2026-003", "C-2026-040", "C-2026-015"):
        store.save_contract_import(row(i))
    assert store.imported_contract_ids() == {"C-2026-003", "C-2026-040", "C-2026-015"}
    listed = store.contract_imports()
    assert [c["id"] for c in listed] == ["C-2026-040", "C-2026-015", "C-2026-003"]
    assert all(c["imported"] for c in listed)
    store.snapshot([{"id": "m1"}], [row("C-2026-099")])
    assert store.imported_contract_ids() == {"C-2026-003", "C-2026-040", "C-2026-015"}
    store.save_contract_import({**row("C-2026-015"), "title": "변경"})
    listed = store.contract_imports()
    assert len(listed) == 3 and next(c for c in listed if c["id"] == "C-2026-015")["title"] == "변경"
    store.close()
    again = Store(tmp_path / "db")
    assert again.imported_contract_ids() == {"C-2026-003", "C-2026-040", "C-2026-015"}
    again.close()


# [기능명세] test_contracts_api_validation_and_pages
# 목적: 계약서 API의 잠금 보호, 입력 검증(422), 작업 접수 인자 전달, GET 응답의 pages 비움·available 표시·저장본 유지를 검증
# 입력: (tmp_path)
# 출력: None; 조건을 어기면 AssertionError
# 처리: 잠금 해제 전 두 경로 401 → 잠금 해제 → 잘못된 kind·limit 0·501·문자열 limit 422 → import_contracts를 가짜 함수로 바꿔 접수 인자 확인
#       → 문서·가져온 기록 저장(pages 포함) 후 GET /api/contracts에서 pages 빈 배열·available·순서 확인 → Store 저장본은 pages 유지
# 예외/실패: 단언 실패
# 부수효과: tmp_path 임시 DB·파일 생성; 가짜 작업 함수만 실행(네트워크 없음)
def test_contracts_api_validation_and_pages(tmp_path):
    store = Store(tmp_path / "data")
    app = create_app(store, static_dir(tmp_path), "tok")
    with TestClient(app, base_url=BASE) as client:
        assert client.get("/?token=tok").status_code == 200
        assert client.get("/api/contracts").status_code == 401
        assert client.post("/api/contracts/import", json={}).status_code == 401
        unlock(client, "tok")
        for bad in ({"kind": "기타"}, {"limit": 0}, {"limit": config.MAX_PAIRS + 1}, {"limit": "많이"}, {"only_new": "아마"}):
            assert client.post("/api/contracts/import", json=bad).status_code == 422, bad

        calls = []
        service = app.state.service
        # 실제 사이트 대신 접수 인자만 기록하는 가짜 작업 함수(인스턴스 속성으로 대체).
        service.import_contracts = lambda job, kind, limit, only_new: calls.append((kind, limit, only_new))
        r = client.post("/api/contracts/import", json={"kind": "지출", "limit": 3, "only_new": True})
        assert r.status_code == 200 and r.json()["id"]
        for _ in range(100):
            if any(j["status"] != "running" for j in service.jobs_snapshot()):
                break
            time.sleep(0.05)
        assert calls == [("지출", 3, True)]
        job = service.jobs_snapshot()[0]
        assert job["kind"] == "계약서 가져오기" and job["status"] == "done"
        r = client.post("/api/contracts/import", json={})
        assert r.status_code == 200
        for _ in range(100):
            if len(calls) == 2:
                break
            time.sleep(0.05)
        assert calls[1] == ("전체", None, False)

        assert client.get("/api/contracts").json() == []
        folder = tmp_path / "pdf"
        folder.mkdir()
        (folder / "a.pdf").write_bytes(b"%PDF-1 a")
        with_file = row("C-2026-040", name="a.pdf")
        missing_file = row("C-2026-003", name="b.pdf")
        store.save_document(with_file["file"]["url"], "a.pdf", "h1", {"fields": {"biz": {"value": "1"}}, "pages": ["전문"], "error": None}, folder / "a.pdf", kind="contract")
        store.save_document(missing_file["file"]["url"], "b.pdf", "h2", {"fields": {}, "pages": ["전문2"], "error": None}, folder / "b.pdf", kind="contract")
        no_doc = row("C-2026-015", name="c.pdf")
        for item in (missing_file, with_file, no_doc):
            store.save_contract_import(item)
        body = client.get("/api/contracts").json()
        assert [c["id"] for c in body] == ["C-2026-040", "C-2026-015", "C-2026-003"]
        assert body[0]["document"]["extraction"]["pages"] == [] and body[0]["document"]["available"] is True
        assert body[0]["document"]["extraction"]["fields"]["biz"]["value"] == "1"
        assert body[0]["document"]["kind"] == "contract" and body[0]["imported"]
        assert body[1]["document"] is None
        assert body[2]["document"]["available"] is False and body[2]["document"]["extraction"]["pages"] == []
        assert store.document(source=with_file["file"]["url"])["extraction"]["pages"] == ["전문"]


# [자료형/클래스 명세] FakeSite: SiteClient의 테스트 대역. fetch_contracts(kind)는 고정 계약 목록을 구분으로 걸러 반환하고 호출 구분을 기록한다.
class FakeSite:
    # [기능명세] FakeSite.__init__
    # 목적: 반환할 계약 목록과 호출 기록 준비
    # 입력: (self, items: 계약 행 목록)
    # 출력: None
    # 처리: 목록 보관, kinds 빈 리스트
    # 예외/실패: 없음
    # 부수효과: 없음
    def __init__(self, items):
        self.items = items
        self.kinds = []

    # [기능명세] FakeSite.fetch_contracts
    # 목적: 사이트 계약 목록 수집 대역
    # 입력: (self, kind="전체")
    # 출력: kind가 전체면 전체, 아니면 같은 구분 행만 담은 새 리스트(행 사본)
    # 처리: kinds에 호출 구분 기록 후 필터링
    # 예외/실패: 없음
    # 부수효과: 호출 기록 갱신; 네트워크·브라우저 사용하지 않음
    def fetch_contracts(self, kind="전체"):
        self.kinds.append(kind)
        return [dict(c) for c in self.items if kind == "전체" or c["kind"] == kind]

    # [기능명세] FakeSite.close
    # 목적: Service.close 시 호출되는 브라우저 정리 대역
    # 입력: (self)
    # 출력: None
    # 처리: 아무것도 하지 않음
    # 예외/실패: 없음
    # 부수효과: 없음
    def close(self):
        pass


# [자료형/클래스 명세] FakeResponse: PDF 다운로드 응답 대역. status와 body()를 제공한다.
class FakeResponse:
    # [기능명세] FakeResponse.__init__
    # 목적: 응답 상태와 본문 보관
    # 입력: (self, status: HTTP 상태 int, payload: bytes)
    # 출력: None
    # 처리: 속성 저장
    # 예외/실패: 없음
    # 부수효과: 없음
    def __init__(self, status, payload):
        self.status = status
        self.payload = payload

    # [기능명세] FakeResponse.body
    # 목적: 응답 본문 반환
    # 입력: (self)
    # 출력: bytes
    # 처리: 보관한 payload 반환
    # 예외/실패: 없음
    # 부수효과: 없음
    def body(self):
        return self.payload


# [자료형/클래스 명세] FakeRequest: context.request 대역. URL별 fixture PDF를 돌려주고, fail 집합의 URL은 HTTP 404를 반환하며 요청 URL을 기록한다.
class FakeRequest:
    # [기능명세] FakeRequest.__init__
    # 목적: URL→PDF 바이트 사전과 실패 URL 집합 준비
    # 입력: (self, payloads: {url: bytes}, fail: 404로 응답할 URL 집합)
    # 출력: None
    # 처리: 속성 저장, urls 빈 리스트
    # 예외/실패: 없음
    # 부수효과: 없음
    def __init__(self, payloads, fail):
        self.payloads = payloads
        self.fail = fail
        self.urls = []

    # [기능명세] FakeRequest.get
    # 목적: PDF 다운로드 HTTP 요청 대역
    # 입력: (self, url, **kw)
    # 출력: FakeResponse — fail에 있으면 404, 아니면 200과 fixture 바이트
    # 처리: 요청 URL 기록 후 응답 생성
    # 예외/실패: payloads에 없는 URL은 KeyError(테스트 구성 오류)
    # 부수효과: urls 기록; 네트워크 사용하지 않음
    def get(self, url, **kw):
        self.urls.append(url)
        if url in self.fail:
            return FakeResponse(404, b"")
        return FakeResponse(200, self.payloads[url])


# [기능명세] run_job
# 목적: Service.submit으로 작업을 실행하고 끝날 때까지 기다림
# 입력: (service, *args: import_contracts 인자(kind, limit, only_new))
# 출력: 끝난 작업 사전 사본
# 처리: submit("계약서 가져오기", import_contracts, …) → 0.05초 간격으로 최대 20초 상태 확인
# 예외/실패: 시간 안에 끝나지 않으면 AssertionError
# 부수효과: 작업 스레드 실행·임시 DB 갱신
def run_job(service, *args):
    jid = service.submit("계약서 가져오기", service.import_contracts, *args)["id"]
    for _ in range(400):
        job = next(j for j in service.jobs_snapshot() if j["id"] == jid)
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("작업이 끝나지 않았습니다.")


# [기능명세] test_import_contracts_flow
# 목적: import_contracts 전체 흐름(구분 전달·선택·PDF 저장·판독·기록·실패 미기록·안 가져온 것만 재시도·0건 정상 종료)을 검증
# 입력: (tmp_path)
# 출력: None; 조건을 어기면 AssertionError
# 처리: fixture 계약서 PDF 5건(011~015, 지출)·PDF 없는 1건(010)·수입 1건(001)으로 가짜 사이트 구성, 014는 404로 실패시킴
#       → 지출·최근 3개: 015/014/013 시도, 014 실패로 작업 failed·errors 기록, 015/013만 기록·PDF 저장·추출값 존재
#       → 지출·안 가져온 것만·전체(014 성공으로 전환): 014·012·011·010만 대상, 010은 PDF 없음 오류, 014는 이번에만 요청
#       → 010을 사이트 목록에서 뺀 뒤 지출·안 가져온 것만 재실행은 0건 정상 종료(요청 없음) → contract_catalog의 순서·document·pages 비움 확인
#       → 수입·안 가져온 것만은 001을 가져오고 구분이 사이트에 전달되는지 확인
# 예외/실패: 단언 실패
# 부수효과: tmp_path 안의 DB·PDF 생성; 네트워크·실제 브라우저 사용하지 않음
def test_import_contracts_flow(tmp_path):
    store = Store(tmp_path / "db")
    store.set_document_root(str(tmp_path / "saved"))
    service = Service(store)
    items, payloads = [], {}
    for n in ("011", "012", "013", "014", "015", "001"):
        path = next(FIXTURES.glob(f"계약서_C-2026-{n}_*.pdf"))
        item = row(f"C-2026-{n}", kind="수입" if n == "001" else "지출", name=path.name)
        items.append(item)
        payloads[item["file"]["url"]] = path.read_bytes()
    items.append(row("C-2026-010", file=False))
    fail_url = next(c["file"]["url"] for c in items if c["id"] == "C-2026-014")
    site = FakeSite(items)
    request = FakeRequest(payloads, {fail_url})
    service.site = site
    # [자료형/클래스 명세] Context: Playwright 컨텍스트 대역. request 속성만 제공한다.
    class Context:
        pass
    Context.request = request
    service.context = Context()
    service.browser = lambda: None
    try:
        job = run_job(service, "지출", 3, False)
        assert site.kinds == ["지출"]
        assert job["status"] == "failed" and job["done"] == 3 and job["total"] == 3
        assert len(job["errors"]) == 1 and job["errors"][0].startswith("C-2026-014: ")
        assert "1개 계약 가져오기 실패" in job["message"]
        assert store.imported_contract_ids() == {"C-2026-015", "C-2026-013"}
        assert [u.rsplit("/", 1)[1][:14] for u in request.urls] == ["계약서_C-2026-015", "계약서_C-2026-014", "계약서_C-2026-013"]
        for c in store.contract_imports():
            doc = store.document(source=c["file"]["url"])
            assert doc["kind"] == "contract" and store.path(doc).is_file() and "계약서" in str(store.path(doc))
            assert doc["extraction"].get("fields")

        request.fail.clear()
        request.urls.clear()
        job = run_job(service, "지출", None, True)
        assert job["status"] == "failed" and job["total"] == 4
        assert job["errors"] == ["C-2026-010: 계약서 PDF가 없습니다."]
        assert [u.rsplit("/", 1)[1][:14] for u in request.urls] == ["계약서_C-2026-014", "계약서_C-2026-012", "계약서_C-2026-011"]
        assert store.imported_contract_ids() == {"C-2026-015", "C-2026-014", "C-2026-013", "C-2026-012", "C-2026-011"}

        site.items = [c for c in items if c["id"] != "C-2026-010"]
        request.urls.clear()
        job = run_job(service, "지출", 5, True)
        assert job["status"] == "done" and job["done"] == 1 and job["total"] == 1 and job["errors"] == []
        assert request.urls == []

        catalog = service.contract_catalog()
        assert [c["id"] for c in catalog] == ["C-2026-015", "C-2026-014", "C-2026-013", "C-2026-012", "C-2026-011"]
        assert all(c["document"]["available"] and c["document"]["extraction"]["pages"] == [] for c in catalog)
        assert store.document(source=catalog[0]["file"]["url"])["extraction"]["pages"]

        job = run_job(service, "수입", None, True)
        assert job["status"] == "done" and store.imported_contract_ids() >= {"C-2026-001"}
        assert site.kinds[-1] == "수입"
    finally:
        service.close()
        store.close()


# [기능명세] test_import_contracts_empty_message
# 목적: 선택 0건일 때 작업이 done으로 끝나고 최종 메시지가 '가져올 계약이 없습니다.'로 남는지 검증
#       (작업 래퍼 JobRunner.submit을 거쳐 화면에 보이는 최종 메시지를 확인)
# 입력: (tmp_path)
# 출력: None; 조건을 어기면 AssertionError
# 처리: (구분 필터 수입 기준, 전체의 빈 목록은 test_hardening_domain이 오류로 검증) 빈 목록을 주는 가짜 사이트로 import_contracts를 submit→완료 대기→작업 status/total/done/message 확인
# 예외/실패: 단언 실패, 5초 안에 끝나지 않으면 AssertionError
# 부수효과: tmp_path 임시 DB 변경
def test_import_contracts_empty_message(tmp_path):
    store = Store(tmp_path / "db")
    service = Service(store)
    service.site = FakeSite([])
    job_id = service.submit("계약서 가져오기", service.import_contracts, "수입", None, False)["id"]
    for _ in range(250):
        if service.jobs[job_id]["status"] != "running":
            break
        time.sleep(.02)
    job = service.jobs[job_id]
    assert (job["status"], job["total"], job["done"], job["message"]) == ("done", 1, 1, "가져올 계약이 없습니다.")
    service.close()
    store.close()
