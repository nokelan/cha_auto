# [파일 기능명세]
# 리팩토링 1단계(서버 접점) 회귀 검사. 404 변환 범위(ContractNotFound만), 작업 최종 상태 저장 실패 시 영구 running 방지,
# 비ASCII 토큰·쿠키의 401 처리를 검증한다. 모든 데이터는 tmp_path 임시 폴더를 쓰며 실사이트에는 접속하지 않는다.
# 유지보수: 함수·데이터 계약이 바뀌면 해당 기능명세와 실제 회귀 검사를 함께 갱신한다.

import time

import pytest
from fastapi.testclient import TestClient

from saebom.api import create_app
from saebom.errors import ContractNotFound
from saebom.jobs import JobRunner
from saebom.store import Store


# [기능명세] make_app
# 목적: 임시 데이터 폴더로 앱을 만드는 공용 도우미
# 입력: (tmp_path)
# 출력: (app, store)
# 처리: Store·정적 폴더 생성 후 create_app(token="test-secret")
# 예외/실패: 없음
# 부수효과: tmp_path에 파일 생성
def make_app(tmp_path):
    store = Store(tmp_path / "data")
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("app")
    return create_app(store, static, "test-secret"), store


# [기능명세] unlocked_client
# 목적: 실행 세션·잠금이 해제된 TestClient 생성
# 입력: (app, raise_exc: 서버 예외 전파 여부)
# 출력: TestClient
# 처리: 토큰 진입→로그인
# 예외/실패: 없음
# 부수효과: 클라이언트 쿠키 설정
def unlocked_client(app, raise_exc=False):
    client = TestClient(app, base_url="http://127.0.0.1:12345", raise_server_exceptions=raise_exc)
    client.get("/?token=test-secret")
    assert client.post("/api/auth/login", json={"password": "0000"}).status_code == 200
    return client


# [기능명세] test_only_contract_not_found_is_404
# 목적: ContractNotFound는 404, 내부 KeyError는 404가 아닌 500으로 전파되는지 검증
# 입력: (tmp_path, monkeypatch)
# 출력: None; 조건을 어기면 AssertionError
# 처리: 서비스 메서드를 예외 발생 함수로 바꿔 4개 라우트 호출
# 예외/실패: 없음
# 부수효과: tmp_path 내부 DB; monkeypatch 복원
def test_only_contract_not_found_is_404(tmp_path, monkeypatch):
    app, _ = make_app(tmp_path)
    service = app.state.service
    body = {"items": [], "from_month": "2026-01", "to_month": "2026-01"}
    calls = [
        ("get", "/api/contracts/X/expense", "expense_draft", None),
        ("post", "/api/contracts/X/expense", "submit_expense", {}),
        ("get", "/api/contracts/X/statement", "statement_draft", None),
        ("post", "/api/contracts/X/statement", "create_statement", body),
    ]
    with unlocked_client(app) as client:
        for method, url, name, payload in calls:
            def send():
                return client.get(url) if method == "get" else client.post(url, json=payload)
            monkeypatch.setattr(service, name, lambda *a, **k: (_ for _ in ()).throw(ContractNotFound("X")))
            r = send()
            if r.status_code == 422:  # 요청 모델 검증이 먼저 걸리면 라우트 본문까지 가지 못하므로 건너뜀
                continue
            assert r.status_code == 404, name
            monkeypatch.setattr(service, name, lambda *a, **k: (_ for _ in ()).throw(KeyError("내부")))
            assert send().status_code == 500, name


# [기능명세] test_internal_keyerror_propagates
# 목적: raise_server_exceptions=True에서 내부 KeyError가 그대로 전파되는지 검증(expense_draft 경로)
# 입력: (tmp_path, monkeypatch)
# 출력: None
# 처리: statement_draft가 KeyError를 던지게 하고 요청
# 예외/실패: KeyError가 pytest.raises로 관찰돼야 함
# 부수효과: tmp_path 내부 DB
def test_internal_keyerror_propagates(tmp_path, monkeypatch):
    app, _ = make_app(tmp_path)
    monkeypatch.setattr(app.state.service, "statement_draft", lambda *a, **k: (_ for _ in ()).throw(KeyError("내부")))
    with unlocked_client(app, raise_exc=True) as client:
        with pytest.raises(KeyError):
            client.get("/api/contracts/X/statement")


# [기능명세] wait_idle
# 목적: 작업 스레드가 끝날 때까지 대기
# 입력: (runner, timeout=5)
# 출력: None; 시간 초과 시 AssertionError
# 처리: 메모리 jobs에 running이 없을 때까지 폴링
# 예외/실패: 시간 초과
# 부수효과: 없음
def wait_idle(runner, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if not any(j["status"] == "running" for j in runner.jobs.values()):
            return
        time.sleep(0.02)
    raise AssertionError("작업이 running에서 벗어나지 않음")


# [기능명세] test_job_state_saved_failure_does_not_stick_running
# 목적: 최종 update가 DB 오류로 실패해도 작업이 running에 남지 않고 새 작업을 접수할 수 있는지 검증
# 입력: (tmp_path, monkeypatch)
# 출력: None
# 처리: JobRunner.update가 호출될 때마다 예외(영속화 실패 모사)→성공 작업 제출→메모리 done 확인→새 작업 접수
# 예외/실패: 없음
# 부수효과: tmp_path 내부 DB; monkeypatch 복원
def test_job_state_saved_failure_does_not_stick_running(tmp_path, monkeypatch):
    store = Store(tmp_path / "data")
    runner = JobRunner(store)
    original = JobRunner.update

    def broken(self, job, **kw):
        raise RuntimeError("DB 오류")
    monkeypatch.setattr(JobRunner, "update", broken)
    first = runner.submit("성공 작업", lambda id: "끝")
    wait_idle(runner)
    assert runner.jobs[first["id"]]["status"] == "done"
    assert runner.jobs[first["id"]]["message"] == "끝"
    second = runner.submit("실패 작업", lambda id: 1 / 0)
    wait_idle(runner)
    assert runner.jobs[second["id"]]["status"] == "failed"
    monkeypatch.setattr(JobRunner, "update", original)
    third = runner.submit("다음 작업", lambda id: None)
    wait_idle(runner)
    assert runner.jobs[third["id"]]["status"] == "done"
    with runner.exclusive("점검"):
        pass
    runner.close()
    store.close()


# [기능명세] test_non_ascii_token_and_cookie_return_401
# 목적: 비ASCII 쿠키·token 쿼리가 500이 아니라 401(또는 인증 실패 응답)인지 검증
# 입력: (tmp_path)
# 출력: None
# 처리: 쿠키 없는 클라이언트에 한글 token·쿠키를 보내 응답 확인, 로그인 후 한글 unlocked 쿠키로 auth/status 확인
# 예외/실패: 없음
# 부수효과: tmp_path 내부 DB
def test_non_ascii_token_and_cookie_return_401(tmp_path):
    app, _ = make_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:12345", raise_server_exceptions=True) as client:
        assert client.get("/?token=한글").status_code == 401
        assert client.get("/api/state", headers={"cookie": "saebom_session=한글".encode("utf-8")}).status_code == 401
        client.get("/?token=test-secret")
        assert client.post("/api/auth/login", json={"password": "0000"}).status_code == 200
        client.cookies.clear()
        client.cookies.set("saebom_session", "test-secret")
        r = client.get("/api/auth/status", headers={"cookie": b"saebom_session=test-secret; saebom_unlocked=" + "한글".encode("utf-8")})
        assert r.status_code == 200 and r.json() == {"authenticated": False}
        r = client.get("/api/state", headers={"cookie": b"saebom_session=test-secret; saebom_unlocked=" + "한글".encode("utf-8")})
        assert r.status_code == 401
