# [파일 기능명세]
# pytest 회귀 검사. tests/fixtures의 PDF와 tmp_path의 임시 DB·파일을 사용해 추출·금액·기간·파일 이동·접근 보호를 검증한다. 단언 실패는 결함이며 테스트용 실패 주입은 monkeypatch가 복원한다.
# 유지보수: 함수·데이터 계약이 바뀌면 해당 기능명세와 실제 회귀 검사를 함께 갱신한다.

from pathlib import Path
import copy
import hashlib
import socket
import shutil
import time

from fastapi.testclient import TestClient
import pytest

from saebom.api import create_app
from saebom.compare import extract, compare
from saebom.service import Service
from saebom.store import Store

FIXTURES = Path(__file__).parent / "fixtures"


# [기능명세] invoice
# 목적: 업체·월에 맞는 계산서 fixture 추출
# 입력: (partner, month='2026-09')
# 출력: Extraction 사전
# 처리: fixture 파일명 검색 후 extract(invoice)
# 예외/실패: 파일 부재 StopIteration; 판독 오류는 추출 error
# 부수효과: 테스트 PDF 읽기만 수행
def invoice(partner, month="2026-09"):
    return extract(next(FIXTURES.glob(f"세금계산서_{partner}_{month}.pdf")), "invoice")


# [기능명세] contract
# 목적: 업체에 맞는 계약 fixture 추출
# 입력: (partner)
# 출력: Extraction 사전
# 처리: fixture 파일명 검색 후 extract(contract)
# 예외/실패: 파일 부재 StopIteration; 판독 오류는 추출 error
# 부수효과: 테스트 PDF 읽기만 수행
def contract(partner):
    return extract(next(FIXTURES.glob(f"계약서_*_{partner}_*.pdf")), "contract")


# [기능명세] test_real_pdf_comparison
# 목적: 실제 업체별 PDF 쌍의 기대 전체 판정 검증
# 입력: (partner, status)
# 출력: None; 조건을 어기면 AssertionError
# 처리: 임시 자료 또는 fixture 준비→대상 호출→값·오류·파일 상태 단언
# 예외/실패: 예상 실패는 pytest.raises로 확인; 예상 밖 예외는 테스트 실패
# 부수효과: fixture는 읽기, DB·파일 변경은 tmp_path 내부; monkeypatch는 테스트 종료 후 복원
@pytest.mark.parametrize("partner,status", [("세움네트웍스", "일치"), ("가온데이터", "일치"), ("다솜오피스", "일치"), ("이음소프트", "불일치"), ("하늘전산", "불일치"), ("바른회선", "불일치"), ("푸른정보통신", "불일치")])
def test_real_pdf_comparison(partner, status):
    assert compare(invoice(partner), contract(partner))["status"] == status


# [기능명세] test_specific_differences_and_evidence
# 목적: 세액 차이·사업자번호·기간 판정과 원문 페이지 근거 검증
# 입력: ()
# 출력: None; 조건을 어기면 AssertionError
# 처리: 임시 자료 또는 fixture 준비→대상 호출→값·오류·파일 상태 단언
# 예외/실패: 예상 실패는 pytest.raises로 확인; 예상 밖 예외는 테스트 실패
# 부수효과: fixture는 읽기, DB·파일 변경은 tmp_path 내부; monkeypatch는 테스트 종료 후 복원
def test_specific_differences_and_evidence():
    checks = {c["key"]: c for c in compare(invoice("이음소프트"), contract("이음소프트"))["checks"]}
    assert checks["vat"]["actual"] == 99000
    assert checks["vat"]["expected"] == 90000
    assert checks["vat"]["difference"] == 9000
    assert checks["vat"]["status"] == "불일치"
    assert checks["vat"]["invoice_source"]["page"] == 1
    assert checks["vat"]["contract_source"]["page"] is not None
    assert next(c for c in compare(invoice("하늘전산"), contract("하늘전산"))["checks"] if c["key"] == "biz")["status"] == "불일치"
    assert next(c for c in compare(invoice("바른회선"), contract("바른회선"))["checks"] if c["key"] == "period")["status"] == "불일치"


# [기능명세] test_installments_and_incomplete_selection
# 목적: 분할 누적 정상·일부 선택·중복 선택과 실제 검수 미확정 검증
# 입력: ()
# 출력: None; 조건을 어기면 AssertionError
# 처리: 임시 자료 또는 fixture 준비→대상 호출→값·오류·파일 상태 단언
# 예외/실패: 예상 실패는 pytest.raises로 확인; 예상 밖 예외는 테스트 실패
# 부수효과: fixture는 읽기, DB·파일 변경은 tmp_path 내부; monkeypatch는 테스트 종료 후 복원
def test_installments_and_incomplete_selection():
    a, b, c = invoice("한빛시큐어"), invoice("한빛시큐어", "2026-10"), contract("한빛시큐어")
    r = compare(a, c, [a, b])
    assert r["status"] == "확인 필요"  # Actual acceptance cannot be inferred from an invoice.
    assert next(x for x in r["checks"] if x["key"] == "group")["status"] == "일치"
    assert next(x for x in compare(a, c, [a])["checks"] if x["key"] == "group")["status"] == "확인 필요"
    assert next(x for x in compare(a, c, [a, a])["checks"] if x["key"] == "group")["status"] == "확인 필요"


# [기능명세] test_missing_fields_never_pass
# 목적: 청구 월 누락과 텍스트 판독 오류가 일치로 통과하지 않는지 검증
# 입력: ()
# 출력: None; 조건을 어기면 AssertionError
# 처리: 임시 자료 또는 fixture 준비→대상 호출→값·오류·파일 상태 단언
# 예외/실패: 예상 실패는 pytest.raises로 확인; 예상 밖 예외는 테스트 실패
# 부수효과: fixture는 읽기, DB·파일 변경은 tmp_path 내부; monkeypatch는 테스트 종료 후 복원
def test_missing_fields_never_pass():
    d = invoice("가온데이터")
    d["fields"].pop("month")
    assert compare(d, contract("가온데이터"))["status"] == "확인 필요"
    assert compare({"error": "텍스트 추출 불가", "fields": {}}, contract("가온데이터"))["status"] == "확인 필요"


# [기능명세] test_broken_pdf
# 목적: 손상 PDF가 추출 오류를 반환하는지 검증
# 입력: (tmp_path)
# 출력: None; 조건을 어기면 AssertionError
# 처리: 임시 자료 또는 fixture 준비→대상 호출→값·오류·파일 상태 단언
# 예외/실패: 예상 실패는 pytest.raises로 확인; 예상 밖 예외는 테스트 실패
# 부수효과: fixture는 읽기, DB·파일 변경은 tmp_path 내부; monkeypatch는 테스트 종료 후 복원
def test_broken_pdf(tmp_path):
    p = tmp_path / "broken.pdf"
    p.write_bytes(b"%PDF-invalid")
    assert extract(p, "invoice")["error"]


# [기능명세] test_folder_settings_persistence_and_old_documents
# 목적: PDF 실제 이동·이전 메타데이터 경로 해석·재시작 설정 복원 검증
# 입력: (tmp_path)
# 출력: None; 조건을 어기면 AssertionError
# 처리: 임시 자료 또는 fixture 준비→대상 호출→값·오류·파일 상태 단언
# 예외/실패: 예상 실패는 pytest.raises로 확인; 예상 밖 예외는 테스트 실패
# 부수효과: fixture는 읽기, DB·파일 변경은 tmp_path 내부; monkeypatch는 테스트 종료 후 복원
def test_folder_settings_persistence_and_old_documents(tmp_path):
    store = Store(tmp_path / "db")
    one, two = tmp_path / "one", tmp_path / "two"
    store.set_document_root(str(one))
    original = one / "세금계산서" / "file.pdf"
    original.write_bytes(b"%PDF-old")
    d = store.save_document("https://sbgw.vercel.app/files/file.pdf", "file.pdf", hashlib.sha256(original.read_bytes()).hexdigest(), {"fields": {}}, original)
    store.set_document_root(str(two))
    assert store.path(d).read_bytes() == b"%PDF-old"
    assert store.path(d).is_relative_to(two)
    assert not original.exists()
    store.close()
    again = Store(tmp_path / "db")
    assert again.document_root() == two
    assert (two / "계약서").is_dir()
    assert again.path(again.document(id=d["id"])).is_file()
    with pytest.raises(ValueError):
        again.set_document_root("relative-folder")
    again.close()


# [기능명세] test_storage_migration_failure_preserves_originals
# 목적: 중간 복사 실패 후 원본·설정 보존과 새 복사본 정리 검증
# 입력: (tmp_path, monkeypatch)
# 출력: None; 조건을 어기면 AssertionError
# 처리: 임시 자료 또는 fixture 준비→대상 호출→값·오류·파일 상태 단언
# 예외/실패: 예상 실패는 pytest.raises로 확인; 예상 밖 예외는 테스트 실패
# 부수효과: fixture는 읽기, DB·파일 변경은 tmp_path 내부; monkeypatch는 테스트 종료 후 복원
def test_storage_migration_failure_preserves_originals(tmp_path, monkeypatch):
    store = Store(tmp_path / "db")
    one, two = tmp_path / "one", tmp_path / "two"
    store.set_document_root(str(one))
    docs = []
    for i in range(2):
        f = one / "세금계산서" / f"{i}.pdf"
        f.write_bytes(b"%PDF-" + bytes([i]))
        docs.append(store.save_document(f"https://sbgw.vercel.app/{i}.pdf", f.name, hashlib.sha256(f.read_bytes()).hexdigest(), {}, f))
    copy = shutil.copyfileobj
    calls = []
    # [기능명세] test_storage_migration_failure_preserves_originals.fail_second
    # 목적: 두 번째 복사에서 디스크 실패 재현
    # 입력: (src, dst)
    # 출력: 정상 첫 복사는 None
    # 처리: 호출 수 기록→두 번째 대상에 일부 기록→실패
    # 예외/실패: 두 번째 호출에서 의도적으로 OSError 발생
    # 부수효과: 테스트용 대상 파일과 호출 목록만 변경
    def fail_second(src, dst):
        calls.append(1)
        if len(calls) == 2:
            dst.write(b"partial")
            raise OSError("disk full")
        copy(src, dst)
    monkeypatch.setattr(shutil, "copyfileobj", fail_second)
    with pytest.raises(OSError):
        store.set_document_root(str(two))
    assert store.document_root() == one
    assert all(store.path(d).is_file() and store.path(d).is_relative_to(one) for d in docs)
    assert not list(two.rglob("*.pdf"))
    store.close()


# [기능명세] test_storage_migration_missing_and_conflicting_files
# 목적: 원본 누락·이름 충돌 중단 및 동일 파일 재사용 검증
# 입력: (tmp_path)
# 출력: None; 조건을 어기면 AssertionError
# 처리: 임시 자료 또는 fixture 준비→대상 호출→값·오류·파일 상태 단언
# 예외/실패: 예상 실패는 pytest.raises로 확인; 예상 밖 예외는 테스트 실패
# 부수효과: fixture는 읽기, DB·파일 변경은 tmp_path 내부; monkeypatch는 테스트 종료 후 복원
def test_storage_migration_missing_and_conflicting_files(tmp_path):
    store = Store(tmp_path / "db")
    one, two = tmp_path / "one", tmp_path / "two"
    store.set_document_root(str(one))
    source = one / "source.pdf"
    payload = b"%PDF-original"
    digest = hashlib.sha256(payload).hexdigest()
    doc = store.save_document("https://sbgw.vercel.app/c.pdf", "contract.pdf", digest, {}, source)
    with pytest.raises(ValueError, match="원본 파일을 찾을 수"):
        store.set_document_root(str(two))
    assert store.document_root() == one
    source.write_bytes(payload)
    conflict = two / "계약서" / (digest[:12] + "_contract.pdf")
    conflict.write_bytes(b"different file")
    with pytest.raises(ValueError, match="내용이 다른"):
        store.set_document_root(str(two))
    assert conflict.read_bytes() == b"different file" and source.read_bytes() == payload
    assert store.document_root() == one
    conflict.write_bytes(payload)
    store.set_document_root(str(two))
    assert not source.exists() and store.path(doc) == conflict
    store.close()


# [기능명세] test_pdf_cache_path_recovery
# 목적: 누락 파일 재다운로드가 문서 ID를 보존하는지 검증
# 입력: (tmp_path)
# 출력: None; 조건을 어기면 AssertionError
# 처리: 임시 자료 또는 fixture 준비→대상 호출→값·오류·파일 상태 단언
# 예외/실패: 예상 실패는 pytest.raises로 확인; 예상 밖 예외는 테스트 실패
# 부수효과: fixture는 읽기, DB·파일 변경은 tmp_path 내부; monkeypatch는 테스트 종료 후 복원
def test_pdf_cache_path_recovery(tmp_path):
    store = Store(tmp_path / "db")
    store.set_document_root(str(tmp_path / "saved"))
    file = next(FIXTURES.glob("세금계산서_가온데이터*.pdf"))
    payload = file.read_bytes()
    service = Service(store)
    # [자료형/클래스 명세] Response: PDF 다운로드 응답의 테스트 대역. 상태 200과 fixture 바이트를 제공한다.
    class Response:
        status = 200
        # [기능명세] test_pdf_cache_path_recovery.Response.body
        # 목적: 다운로드 응답 본문 테스트 대역
        # 입력: (self)
        # 출력: fixture PDF bytes
        # 처리: 부모 테스트의 payload 반환
        # 예외/실패: 고정된 테스트 입력 사용
        # 부수효과: 없음; 네트워크 사용하지 않음
        def body(self): return payload
    # [자료형/클래스 명세] Request: HTTP 요청 객체의 테스트 대역. 네트워크 없이 Response를 반환한다.
    class Request:
        # [기능명세] test_pdf_cache_path_recovery.Request.get
        # 목적: 다운로드 HTTP 요청 테스트 대역
        # 입력: (self, *a, **kw)
        # 출력: 응답 대역 객체
        # 처리: 인자를 받되 고정 Response 생성
        # 예외/실패: 실제 서버 접속과 HTTP 실패를 재현하지 않음
        # 부수효과: 없음; 네트워크 사용하지 않음
        def get(self, *a, **kw): return Response()
    # [자료형/클래스 명세] Context: Playwright 컨텍스트의 테스트 대역. request 속성만 제공한다.
    class Context:
        request = Request()
    service.context = Context()
    service.browser = lambda: None
    url = "https://sbgw.vercel.app/files/test.pdf"
    d = service.download_one({"url": url, "name": file.name}, "invoice")
    assert "세금계산서" in str(store.path(d))
    assert store.path(d).read_bytes() == payload
    store.path(d).unlink()
    newer = service.download_one({"url": url, "name": file.name}, "invoice")
    assert newer["id"] == d["id"]
    assert store.path(newer).is_file()
    service.context = None
    service.close()
    store.close()


# [기능명세] test_api_auth_origin_and_offline_workflow
# 목적: 실행 인증·출처 보호와 네트워크 차단 상태의 비교·보정·CSV·이동 검증
# 입력: (tmp_path, monkeypatch)
# 출력: None; 조건을 어기면 AssertionError
# 처리: 임시 자료 또는 fixture 준비→대상 호출→값·오류·파일 상태 단언
# 예외/실패: 예상 실패는 pytest.raises로 확인; 예상 밖 예외는 테스트 실패
# 부수효과: fixture는 읽기, DB·파일 변경은 tmp_path 내부; monkeypatch는 테스트 종료 후 복원
def test_api_auth_origin_and_offline_workflow(tmp_path, monkeypatch):
    store = Store(tmp_path / "data")
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("app")
    app = create_app(store, static, "test-secret")
    with TestClient(app, base_url="http://127.0.0.1:12345") as client:
        assert client.get("/api/state").status_code == 401
        assert client.get("/?token=test-secret").status_code == 200
        assert client.post("/api/auth/login", json={"password": "0000"}).status_code == 200
        assert client.post("/api/sync", headers={"origin": "https://evil.example"}).status_code == 403
        assert client.get("/api/state", headers={"host": "evil.example"}).status_code == 403
        invfile = next(FIXTURES.glob("세금계산서_가온데이터*.pdf"))
        confile = next(FIXTURES.glob("계약서_*_가온데이터_*.pdf"))
        # These registered documents will be relocated by the settings test.
        invfile = Path(shutil.copy2(invfile, tmp_path / invfile.name))
        confile = Path(shutil.copy2(confile, tmp_path / confile.name))
        iu, cu = "https://sbgw.vercel.app/files/i.pdf", "https://sbgw.vercel.app/files/c.pdf"
        store.snapshot([{"id": "m1", "sender": "가온데이터 담당자", "subject": "세금계산서", "received": "2026-10-07 09:30", "attachments": [{"url": iu, "name": invfile.name}]}], [{"id": "c1", "kind": "지출", "partner": "가온데이터(주)", "title": "임대", "period": "2026", "file": {"url": cu, "name": confile.name}}])
        for f, u, kind in ((invfile, iu, "invoice"), (confile, cu, "contract")):
            store.save_document(u, f.name, hashlib.sha256(f.read_bytes()).hexdigest(), extract(f, kind), f)
        # Any attempt to access the Internet during compare is an immediate failure.
        monkeypatch.setattr(socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Network forbidden")))
        work = {"pairs": [{"mail_id": "m1", "contract_id": "c1", "invoice_url": iu}]}
        job = client.post("/api/compare", json=work)
        assert job.status_code == 200
        for _ in range(100):
            jobs = client.get("/api/state").json()["jobs"]
            if jobs[0]["status"] != "running": break
            time.sleep(.02)
        assert jobs[0]["status"] == "done"
        result = client.get("/api/results").json()[0]
        assert result["rows"][0]["status"] == "일치"
        assert client.get(f"/api/results/{result['id']}/csv").status_code == 200
        docid = result["rows"][0]["invoice"]["id"]
        assert client.get(f"/api/documents/{docid}").content.startswith(b"%PDF")
        assert client.get("/api/documents/../../launcher.py").status_code != 200
        corrected = client.post(f"/api/results/{result['id']}/correct", json={"overrides": {docid: {"vat": 0}}})
        assert corrected.status_code == 200
        for _ in range(100):
            rr = client.get("/api/results").json()
            if len(rr) == 2: break
            time.sleep(.02)
        assert rr[0]["parent"] == result["id"]
        assert rr[0]["rows"][0]["status"] == "불일치"
        assert rr[0]["rows"][0]["effective_invoice"]["fields"]["vat"]["previous"]["value"] == 180000
        assert client.put("/api/settings", json={"document_root": str(tmp_path / "userdocs")}).status_code == 200
        for kind in ("invoice", "contract"):
            d = result["rows"][0][kind]
            assert client.get(f"/api/documents/{d['id']}").content.startswith(b"%PDF")
            assert store.path(d).is_relative_to(tmp_path / "userdocs")

# [기능명세] test_password_gate_and_restart
# 목적: 비밀번호 입력 전 API 차단·잘못된 비밀번호·인증 쿠키·재시작 재잠금 검증
# 입력: (tmp_path)
# 출력: None; 조건을 어기면 AssertionError
# 처리: 임시 자료 또는 fixture 준비→대상 호출→값·오류·파일 상태 단언
# 예외/실패: 예상 실패는 pytest.raises로 확인; 예상 밖 예외는 테스트 실패
# 부수효과: fixture는 읽기, DB·파일 변경은 tmp_path 내부; monkeypatch는 테스트 종료 후 복원
def test_password_gate_and_restart(tmp_path):
    static = tmp_path / 'static'
    static.mkdir()
    (static / 'index.html').write_text('app')
    root = tmp_path / 'data'
    with TestClient(create_app(Store(root), static, 'boot-one'), base_url='http://127.0.0.1:12345') as client:
        assert client.post('/api/auth/login', json={'password': '0000'}).status_code == 401
        assert client.get('/?token=boot-one').status_code == 200
        assert client.get('/api/auth/status').json() == {'authenticated': False}
        for route in ('state', 'results', 'documents/any', 'results/any/csv'):
            assert client.get('/api/' + route).status_code == 401
        for route in ('sync', 'download', 'compare', 'shutdown', 'settings/pick-folder'):
            assert client.post('/api/' + route, json={}).status_code == 401
        assert client.put('/api/settings', json={'document_root': str(tmp_path/'new')}).status_code == 401
        assert client.post('/api/auth/login', json={'password': 'wrong'}).status_code == 401
        assert client.get('/api/auth/status').json()['authenticated'] is False
        assert client.post('/api/auth/login', json={'password': '0000'}, headers={'origin':'https://evil.example'}).status_code == 403
        response = client.post('/api/auth/login', json={'password': '0000'})
        assert response.status_code == 200
        assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=strict' in response.headers['set-cookie']
        assert client.get('/api/state').status_code == 200
        assert client.get('/api/auth/status').json()['authenticated'] is True
        cookies = dict(client.cookies)
    with TestClient(create_app(Store(root), static, 'boot-two'), base_url='http://127.0.0.1:12345') as client:
        client.cookies.update(cookies)
        assert client.get('/?token=boot-two').status_code == 200
        assert client.get('/api/auth/status').json()['authenticated'] is False
        assert client.get('/api/results').status_code == 401
        assert client.post('/api/auth/login', json={'password': '0000'}).status_code == 200
        assert client.get('/api/state').status_code == 200
