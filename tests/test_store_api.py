# [파일 기능명세]
# 저장·HTTP 계층 리팩토링 회귀 검사. tmp_path의 임시 DB·파일만 사용해 Store의 일괄 문서 조회·kind 열 마이그레이션·결과 단건/요약 조회와
# API의 결과 요약·상세(pages 비움, 저장본 유지)·로그인 연속 실패 잠금·저장 위치 변경을 검증한다. 외부 네트워크를 쓰지 않는다.
# 유지보수: Store·API 계약(공유 API 계약 포함)이 바뀌면 이 검사와 기능명세를 함께 갱신한다.

import hashlib
import sqlite3
import types

from fastapi.testclient import TestClient
import pytest

import saebom.api as api_module
from saebom import config
from saebom.api import create_app
from saebom.store import Store

BASE = "http://127.0.0.1:12345"


# [기능명세] make_doc
# 목적: 테스트용 PDF 파일을 만들고 Store에 문서로 등록
# 입력: (store, folder: Path, url: 원본 URL, name: 파일 이름, payload: bytes, kind=None)
# 출력: 저장된 문서 사전
# 처리: 폴더 생성→파일 쓰기→sha256 계산→save_document(pages가 있는 extraction 포함)
# 예외/실패: 파일·DB 오류 전파
# 부수효과: tmp_path 안의 파일과 임시 DB 변경
def make_doc(store, folder, url, name, payload, kind=None):
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / name
    f.write_bytes(payload)
    extraction = {"fields": {"vat": {"value": 1}}, "pages": ["페이지 전문"]}
    return store.save_document(url, name, hashlib.sha256(payload).hexdigest(), extraction, f, kind=kind)


# [기능명세] sample_result
# 목적: 행 3개 이상과 큰 pages 필드를 가진 결과 레코드 저장
# 입력: (store, inv: 계산서 문서 사전, con: 계약 문서 사전, rows=4, parent=None)
# 출력: save_result가 반환한 결과 사전
# 처리: 상태를 일치/불일치로 번갈아 둔 행을 만들고 effective_invoice에도 pages를 넣어 저장
# 예외/실패: DB 오류 전파
# 부수효과: 임시 DB results에 행 추가
def sample_result(store, inv, con, rows=4, parent=None):
    data = []
    for i in range(rows):
        data.append({"mail_id": f"m{i}", "contract_id": "c1", "subject": "제목", "partner": f"업체{i}", "invoice": inv, "contract": con,
                     "effective_invoice": {"fields": {}, "pages": ["효과 전문"]}, "status": "불일치" if i % 2 else "일치", "checks": [], "error": None})
    return store.save_result({"rows": data, "pairs": [], "overrides": {}, "parent": parent})


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


# [기능명세] test_documents_by_sources
# 목적: 여러 URL 일괄 조회가 document()와 같은 형태(kind 포함)를 반환하는지 검증
# 입력: (tmp_path)
# 출력: None; 조건을 어기면 AssertionError
# 처리: 문서 2건 저장→존재·부재·중복·None URL 섞어 조회→빈 입력·900개 초과 입력 확인
# 예외/실패: 예상 밖 예외는 테스트 실패
# 부수효과: tmp_path 내부 DB·파일만 변경
def test_documents_by_sources(tmp_path):
    store = Store(tmp_path / "db")
    a = make_doc(store, tmp_path / "f", "https://x/a.pdf", "a.pdf", b"%PDF-a", kind="invoice")
    b = make_doc(store, tmp_path / "f", "https://x/b.pdf", "b.pdf", b"%PDF-b")
    found = store.documents_by_sources(["https://x/a.pdf", "https://x/b.pdf", "https://x/a.pdf", "https://x/none.pdf", None])
    assert set(found) == {"https://x/a.pdf", "https://x/b.pdf"}
    assert found["https://x/a.pdf"] == store.document(id=a["id"]) and found["https://x/a.pdf"]["kind"] == "invoice"
    assert found["https://x/b.pdf"] == b and b["kind"] is None
    assert store.documents_by_sources([]) == {}
    many = [f"https://x/{i}.pdf" for i in range(2000)] + ["https://x/b.pdf"]
    assert list(store.documents_by_sources(many)) == ["https://x/b.pdf"]
    store.close()


# [기능명세] test_kind_migration_and_preservation
# 목적: kind 열이 없는 옛 DB를 열면 열이 추가되고, kind가 저장·유지·이동 폴더 결정에 쓰이는지 검증
# 입력: (tmp_path)
# 출력: None; 조건을 어기면 AssertionError
# 처리: 옛 스키마 DB 직접 생성→Store로 열기→기존 문서 kind None 확인→kind 저장 후 kind 없이 재저장해도 유지→이름이 '세금계산서'로 시작하지만 kind=contract인 문서가 계약서 폴더로 이동하는지 확인
# 예외/실패: 예상 밖 예외는 테스트 실패
# 부수효과: tmp_path 내부 DB·파일만 변경
def test_kind_migration_and_preservation(tmp_path):
    root = tmp_path / "db"
    root.mkdir()
    old = sqlite3.connect(root / "saebom.sqlite3")
    old.execute("CREATE TABLE documents(id TEXT PRIMARY KEY, source TEXT UNIQUE, name TEXT, hash TEXT, extraction TEXT, disk_path TEXT)")
    old.execute("INSERT INTO documents VALUES('old1','https://x/old.pdf','old.pdf','h','{}',NULL)")
    old.commit()
    old.close()
    store = Store(root)
    assert "kind" in {r[1] for r in store.db.execute("PRAGMA table_info(documents)")}
    assert store.document(id="old1")["kind"] is None
    store.db.execute("DELETE FROM documents")
    store.db.commit()
    payload = b"%PDF-k"
    d = make_doc(store, tmp_path / "src", "https://x/k.pdf", "세금계산서처럼보이는계약.pdf", payload, kind="contract")
    again = store.save_document(d["source"], d["name"], d["hash"], {}, d["disk_path"])
    assert again["id"] == d["id"] and again["kind"] == "contract"
    store.set_document_root(str(tmp_path / "new"))
    assert store.path(again).parent == (tmp_path / "new" / "계약서").resolve()
    assert store.path(again).read_bytes() == payload
    store.close()
    reopened = Store(root)
    assert reopened.document(id=d["id"])["kind"] == "contract"
    reopened.close()


# [기능명세] test_result_and_summaries
# 목적: result 단건 조회와 result_summaries 요약 필드·최신순 정렬 검증
# 입력: (tmp_path)
# 출력: None; 조건을 어기면 AssertionError
# 처리: 결과 2건(두 번째가 첫 번째를 parent로 참조) 저장→단건·부재 조회→요약 형태 확인
# 예외/실패: 예상 밖 예외는 테스트 실패
# 부수효과: tmp_path 내부 DB·파일만 변경
def test_result_and_summaries(tmp_path):
    store = Store(tmp_path / "db")
    inv = make_doc(store, tmp_path / "f", "https://x/i.pdf", "i.pdf", b"%PDF-i", kind="invoice")
    con = make_doc(store, tmp_path / "f", "https://x/c.pdf", "c.pdf", b"%PDF-c", kind="contract")
    first = sample_result(store, inv, con, rows=4)
    second = sample_result(store, inv, con, rows=1, parent=first["id"])
    assert store.result(first["id"]) == first
    assert store.result("missing") is None
    summaries = store.result_summaries()
    assert [s["id"] for s in summaries] == [second["id"], first["id"]]
    assert summaries[1] == {"id": first["id"], "created": first["created"], "parent": None, "count": 4, "mismatch": 2,
                            "partners": ["업체0", "업체1", "업체2"], "mail_ids": ["m0", "m1", "m2", "m3"],
                            "verdicts": summaries[1]["verdicts"]}
    assert [v["mail_id"] for v in summaries[1]["verdicts"]] == ["m0", "m1", "m2", "m3"]
    assert summaries[0]["parent"] == first["id"] and summaries[0]["count"] == 1 and summaries[0]["mismatch"] == 0
    store.close()


# [기능명세] test_results_api_summary_and_detail
# 목적: /api/results 요약 형태와 /api/results/{id} 상세의 pages 비움·저장본 유지·404·CSV 경로 공존 검증
# 입력: (tmp_path)
# 출력: None; 조건을 어기면 AssertionError
# 처리: 결과 저장→로그인→요약·상세·CSV·부재 상세 요청→저장본의 pages가 그대로인지 확인
# 예외/실패: 예상 밖 예외는 테스트 실패
# 부수효과: tmp_path 내부 DB·파일만 변경
def test_results_api_summary_and_detail(tmp_path):
    store = Store(tmp_path / "data")
    inv = make_doc(store, tmp_path / "f", "https://x/i.pdf", "i.pdf", b"%PDF-i", kind="invoice")
    con = make_doc(store, tmp_path / "f", "https://x/c.pdf", "c.pdf", b"%PDF-c", kind="contract")
    saved = sample_result(store, inv, con, rows=2)
    with TestClient(create_app(store, static_dir(tmp_path), "tok"), base_url=BASE) as client:
        unlock(client, "tok")
        summary = client.get("/api/results").json()
        assert summary == [{"id": saved["id"], "created": saved["created"], "parent": None, "count": 2, "mismatch": 1, "partners": ["업체0", "업체1"], "mail_ids": ["m0", "m1"]}]
        detail = client.get(f"/api/results/{saved['id']}")
        assert detail.status_code == 200
        body = detail.json()
        assert set(body) >= {"id", "created", "parent", "rows", "pairs", "overrides"}
        for row in body["rows"]:
            assert row["invoice"]["extraction"]["pages"] == []
            assert row["contract"]["extraction"]["pages"] == []
            assert row["effective_invoice"]["pages"] == []
            assert row["invoice"]["extraction"]["fields"] == {"vat": {"value": 1}}
        assert client.get("/api/results/missing").status_code == 404
        assert client.get(f"/api/results/{saved['id']}/csv").status_code == 200
        assert client.get("/api/results/missing/csv").status_code == 404
        stored = store.result(saved["id"])
        assert stored["rows"][0]["invoice"]["extraction"]["pages"] == ["페이지 전문"]
        assert stored["rows"][0]["effective_invoice"]["pages"] == ["효과 전문"]


# [기능명세] test_login_lockout
# 목적: 연속 실패 잠금(429, 정답도 거절)·만료 후 성공·성공 시 횟수 초기화 검증
# 입력: (tmp_path, monkeypatch)
# 출력: None; 조건을 어기면 AssertionError
# 처리: api 모듈의 time만 가짜 시계로 교체→4회 실패 후 성공으로 초기화 확인→5회 실패(모두 401)→정답도 429·남은 초 안내→시계를 잠금 시간만큼 진행→정답 200
# 예외/실패: 예상 밖 예외는 테스트 실패
# 부수효과: tmp_path 내부 DB만 변경; monkeypatch가 시계를 복원
def test_login_lockout(tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(api_module, "time", types.SimpleNamespace(monotonic=lambda: clock[0]))
    with TestClient(create_app(Store(tmp_path / "data"), static_dir(tmp_path), "tok"), base_url=BASE) as client:
        assert client.get("/?token=tok").status_code == 200
        for _ in range(config.LOGIN_MAX_FAILURES - 1):
            assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
        assert client.post("/api/auth/login", json={"password": config.APP_PASSWORD}).status_code == 200
        for _ in range(config.LOGIN_MAX_FAILURES - 1):
            assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
        wrong = client.post("/api/auth/login", json={"password": "wrong"})
        assert wrong.status_code == 401 and wrong.json()["detail"] == "비밀번호가 올바르지 않습니다."
        locked = client.post("/api/auth/login", json={"password": config.APP_PASSWORD})
        assert locked.status_code == 429
        assert locked.json()["detail"] == f"비밀번호를 여러 번 틀렸습니다. {config.LOGIN_LOCK_SECONDS}초 후 다시 시도해 주세요."
        clock[0] += config.LOGIN_LOCK_SECONDS - 0.5
        assert client.post("/api/auth/login", json={"password": config.APP_PASSWORD}).json()["detail"].endswith("1초 후 다시 시도해 주세요.")
        clock[0] += 0.5
        assert client.post("/api/auth/login", json={"password": config.APP_PASSWORD}).status_code == 200


# [기능명세] test_login_uses_configured_password
# 목적: 비밀번호를 config.APP_PASSWORD로 비교하는지 검증
# 입력: (tmp_path, monkeypatch)
# 출력: None; 조건을 어기면 AssertionError
# 처리: config.APP_PASSWORD를 다른 값으로 바꿈→기본값 0000은 401, 새 값은 200
# 예외/실패: 예상 밖 예외는 테스트 실패
# 부수효과: tmp_path 내부 DB만 변경; monkeypatch가 설정을 복원
def test_login_uses_configured_password(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_PASSWORD", "새비번-1234")
    with TestClient(create_app(Store(tmp_path / "data"), static_dir(tmp_path), "tok"), base_url=BASE) as client:
        assert client.get("/?token=tok").status_code == 200
        assert client.post("/api/auth/login", json={"password": "0000"}).status_code == 401
        assert client.post("/api/auth/login", json={"password": "새비번-1234"}).status_code == 200


# [기능명세] test_state_and_settings_use_service_contract
# 목적: /api/state가 jobs_snapshot·config.SITE_URL을 쓰고 /api/settings가 exclusive 안에서 저장 위치를 옮기는지 검증
# 입력: (tmp_path)
# 출력: None; 조건을 어기면 AssertionError
# 처리: 실제 create_app으로 로그인→state의 jobs·site 확인→문서 1건 등록 후 settings로 이동→경로 확인
# 예외/실패: Service.jobs_snapshot/exclusive(에이전트 C 작업)가 없으면 이 테스트는 실패함
# 부수효과: tmp_path 내부 DB·파일만 변경
def test_state_and_settings_use_service_contract(tmp_path):
    store = Store(tmp_path / "data")
    doc = make_doc(store, tmp_path / "f", "https://x/i.pdf", "i.pdf", b"%PDF-i", kind="invoice")
    with TestClient(create_app(store, static_dir(tmp_path), "tok"), base_url=BASE) as client:
        unlock(client, "tok")
        state = client.get("/api/state")
        assert state.status_code == 200
        assert state.json()["site"] == config.SITE_URL and isinstance(state.json()["jobs"], list)
        moved = client.put("/api/settings", json={"document_root": str(tmp_path / "userdocs")})
        assert moved.status_code == 200
        assert store.path(doc).is_relative_to((tmp_path / "userdocs" / "세금계산서").resolve())
        bad = client.put("/api/settings", json={"document_root": "relative"})
        assert bad.status_code == 400 and "절대 폴더" in bad.json()["detail"]
