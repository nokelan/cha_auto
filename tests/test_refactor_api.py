# [파일 기능명세]
# 리팩토링 2단계(서버 접점) 회귀 검사. overrides.py(보정 검증·병합), export.py(CSV), api.py 예외 매핑, jobs.py의 Store.meta_get/meta_set 사용,
# 서비스 메서드(get_result·list_results·document_file)를 경유하는 라우트를 검증한다. 라우트 검사는 fake 서비스를 주입한 임시 앱을 쓰고,
# 모든 데이터는 tmp_path 임시 폴더를 쓰며 실사이트·네트워크에는 접속하지 않는다.
# 유지보수: 함수·데이터 계약이 바뀌면 해당 기능명세와 실제 회귀 검사를 함께 갱신한다.

import csv
import io
import logging
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from saebom.api import create_app
from saebom.errors import BusinessError
from saebom.export import result_csv
from saebom.jobs import JobRunner, RESTART_MESSAGE
from saebom.overrides import merge_overrides, validate_overrides
from saebom.routes import compare as compare_routes, system as system_routes
from saebom.store import Store

RANGE_MSG = "금액·차수·비율은 범위 안의 정수로 입력해 주세요."


# [기능명세] sample_result
# 목적: 보정·CSV 검사용 최소 결과 사전 생성
# 입력: ()
# 출력: rows 2개(검사 항목 있음/없음)를 가진 결과 사전
# 처리: 수식 접두 문자열을 섞은 값 구성
# 예외/실패: 없음
# 부수효과: 없음
def sample_result():
    return {
        "id": "abcdef123456", "pairs": [{"invoice": "i1", "contract": "c1"}], "overrides": {"i1": {"vat": 5}},
        "rows": [
            {"invoice": {"id": "i1"}, "partner": "=SUM(A1)", "subject": "+메일", "contract_id": "-C-1", "status": "불일치", "error": None,
             "checks": [{"label": "공급가액", "status": "불일치", "actual": 100, "expected": "@x", "difference": "\t1", "note": "\r메모",
                         "invoice_source": {"quote": "근거"}, "contract_source": None}]},
            {"invoice": {"id": "i2"}, "partner": "업체", "subject": "메일", "contract_id": "C-2", "status": "오류", "error": "읽기 실패", "checks": []},
        ],
    }


# [기능명세] test_validate_overrides_accepts_valid
# 목적: 정상 보정 입력이 통과하고 병합이 기존 보정 위에 덮어쓰는지 검증
# 입력: ()
# 출력: None; 조건을 어기면 AssertionError
# 처리: 모든 허용 필드를 한 번에 검증 후 merge_overrides 결과·입력 불변성 확인
# 예외/실패: 없음
# 부수효과: 없음
def test_validate_overrides_accepts_valid():
    r = sample_result()
    ok = {"i1": {"supply": 0, "vat": 10 ** 12, "total": 3, "month": "2026-09", "biz": "123", "percent": 100, "installment": 2, "partner": "가"}}
    assert validate_overrides(r, ok) is None
    merged = merge_overrides(r, {"i1": {"vat": 7, "total": 1}, "i2": {"partner": "x"}})
    assert merged == {"i1": {"vat": 7, "total": 1}, "i2": {"partner": "x"}}
    assert r["overrides"] == {"i1": {"vat": 5}}


# [기능명세] test_validate_overrides_rejects
# 목적: 잘못된 보정이 기존과 같은 문구의 ValueError가 되는지 검증
# 입력: (overrides, message) 매개변수
# 출력: None; 조건을 어기면 AssertionError
# 처리: validate_overrides 호출 후 예외 문구 비교
# 예외/실패: 없음
# 부수효과: 없음
@pytest.mark.parametrize("overrides,message", [
    ({"zzz": {"vat": 1}}, "수정할 문서 또는 항목이 잘못되었습니다."),
    ({"i1": {"unknown": 1}}, "수정할 문서 또는 항목이 잘못되었습니다."),
    ({"i1": {"vat": -1}}, RANGE_MSG),
    ({"i1": {"vat": 10 ** 12 + 1}}, RANGE_MSG),
    ({"i1": {"vat": True}}, RANGE_MSG),
    ({"i1": {"vat": 1.5}}, RANGE_MSG),
    ({"i1": {"vat": "1"}}, RANGE_MSG),
    ({"i1": {"percent": 101}}, RANGE_MSG),
    ({"i1": {"partner": "가" * 201}}, "수정값을 200자 이내 문자열로 입력해 주세요."),
    ({"i1": {"biz": 123}}, "수정값을 200자 이내 문자열로 입력해 주세요."),
    ({"i1": {"month": "2026-13"}}, "청구 월은 YYYY-MM 형식으로 입력해 주세요."),
    ({"i1": {"month": "abc"}}, "청구 월은 YYYY-MM 형식으로 입력해 주세요."),
])
def test_validate_overrides_rejects(overrides, message):
    with pytest.raises(ValueError) as e:
        validate_overrides(sample_result(), overrides)
    assert str(e.value) == message


# [기능명세] test_result_csv_matches_legacy
# 목적: result_csv가 BOM·열 구성·수식 방지에서 분리 전 구현과 바이트 동일한지 검증
# 입력: ()
# 출력: None; 조건을 어기면 AssertionError
# 처리: 분리 전 로직을 테스트 안에 재현해 출력 비교, 수식 접두가 모두 작은따옴표로 막혔는지 확인
# 예외/실패: 없음
# 부수효과: 없음
def test_result_csv_matches_legacy():
    r = sample_result()

    def safe(v):
        s = "" if v is None else str(v)
        return "'" + s if s.startswith(("=", "+", "-", "@", "\t", "\r")) else s
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["업체", "메일", "계약번호", "전체판정", "항목", "계산서", "계약·기준", "차이(계산서-기준)", "항목판정", "설명", "계산서 근거", "계약 근거"])
    for row in r["rows"]:
        for c in row["checks"] or [{"label": "문서 처리", "status": row["status"], "note": row["error"]}]:
            w.writerow([safe(x) for x in (row["partner"], row["subject"], row["contract_id"], row["status"], c["label"], c.get("actual"), c.get("expected"), c.get("difference"), c["status"], c.get("note"), (c.get("invoice_source") or {}).get("quote"), (c.get("contract_source") or {}).get("quote"))])
    text = result_csv(r)
    assert text == "﻿" + out.getvalue()
    assert text.encode("utf-8").startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    assert len(rows[0]) == 12 and len(rows) == 3
    assert rows[1][:3] == ["'=SUM(A1)", "'+메일", "'-C-1"]
    assert rows[1][6] == "'@x" and rows[1][7] == "'\t1" and rows[1][9] == "'\r메모"
    assert rows[2][4] == "문서 처리" and rows[2][9] == "읽기 실패"


# [기능명세] test_exception_mapping
# 목적: BusinessError는 로그 없이 400, 일반 ValueError는 400과 로그, 응답 형식은 {"detail": 메시지}인지 검증
# 입력: (tmp_path, caplog)
# 출력: None; 조건을 어기면 AssertionError
# 처리: 서비스 submit을 예외 발생 함수로 바꿔 /api/sync 호출 후 응답·로그 확인
# 예외/실패: 없음
# 부수효과: tmp_path 임시 DB만 변경
def test_exception_mapping(tmp_path, caplog):
    store = Store(tmp_path / "data")
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("app")
    app = create_app(store, static, "test-secret")
    with TestClient(app, base_url="http://127.0.0.1:12345") as client:
        client.get("/?token=test-secret")
        assert client.post("/api/auth/login", json={"password": "0000"}).status_code == 200

        def boom(*a, **k):
            raise BusinessError("업무 오류")
        app.state.service.submit = boom
        with caplog.at_level(logging.ERROR, logger="saebom.api"):
            r = client.post("/api/sync")
        assert r.status_code == 400 and r.json() == {"detail": "업무 오류"}
        assert not [x for x in caplog.records if x.name == "saebom.api"]

        def bug(*a, **k):
            raise ValueError("내부 버그")
        app.state.service.submit = bug
        caplog.clear()
        with caplog.at_level(logging.ERROR, logger="saebom.api"):
            r = client.post("/api/sync")
        assert r.status_code == 400 and r.json() == {"detail": "내부 버그"}
        assert [x for x in caplog.records if x.name == "saebom.api" and x.exc_info]


# [기능명세] test_job_runner_uses_meta_and_restores
# 목적: JobRunner가 Store.meta_get/meta_set로 상태를 저장하고 재시작 시 running을 failed로 복원하는지 검증
# 입력: (tmp_path)
# 출력: None; 조건을 어기면 AssertionError
# 처리: meta_set을 감시하며 느린 작업 제출 → 저장된 jobs 확인 → 같은 Store로 새 JobRunner 생성해 복원 확인
# 예외/실패: 없음
# 부수효과: tmp_path 임시 DB만 변경
def test_job_runner_uses_meta_and_restores(tmp_path):
    store = Store(tmp_path / "data")
    calls = []
    original = store.meta_set

    def spy(key, value):
        calls.append(key)
        original(key, value)
    store.meta_set = spy
    runner = JobRunner(store)
    gate = threading.Event()
    job = runner.submit("시험", lambda jid: gate.wait(5) and "끝")["id"]
    assert "jobs" in calls
    assert store.meta_get("jobs")[job]["status"] == "running"
    # 실행 중 상태가 DB에 남은 채 재시작하면 failed로 복원된다.
    restarted = JobRunner(store)
    assert restarted.jobs[job]["status"] == "failed" and restarted.jobs[job]["message"] == RESTART_MESSAGE
    gate.set()
    end = time.time() + 5
    while time.time() < end and runner.jobs[job]["status"] == "running":
        time.sleep(.01)
    assert runner.jobs[job]["status"] == "done"
    assert store.meta_get("jobs")[job]["message"] == "끝"
    runner.close()
    restarted.close()


# [자료형/클래스 명세] FakeService: 라우트 검사용 서비스 대역. get_result·list_results·document_file·submit만 구현하고 호출을 calls에 기록한다.
# 입력: (results: {id: 결과}, doc: (Path, 이름) 또는 None — 문서 ID 'd1'에만 반환). 부수효과 없음.
class FakeService:
    run_compare = object()

    def __init__(self, results, doc=None):
        self.results, self.doc, self.calls = results, doc, []

    def get_result(self, result_id):
        self.calls.append(("get_result", result_id))
        return self.results.get(result_id)

    def list_results(self):
        self.calls.append(("list_results",))
        return [{"id": k} for k in self.results]

    def document_file(self, doc_id):
        self.calls.append(("document_file", doc_id))
        return self.doc if doc_id == "d1" else None

    def submit(self, kind, fn, *args):
        self.calls.append(("submit", kind, args))
        return {"id": "job1"}


# [기능명세] test_routes_use_service_methods
# 목적: /api/results·/api/results/{id}(+csv·correct)·/api/documents/{id}가 store가 아닌 서비스 메서드를 경유하는지 검증
# 입력: (tmp_path)
# 출력: None; 조건을 어기면 AssertionError
# 처리: store=None인 임시 앱에 fake 서비스를 주입해 호출·응답·404 확인
# 예외/실패: 없음
# 부수효과: tmp_path에 임시 PDF 파일 생성
def test_routes_use_service_methods(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    svc = FakeService({"abcdef123456": sample_result()}, (pdf, "표시.pdf"))
    app = FastAPI()
    compare_routes.register(app, svc, None, strip_pages=lambda r: {**r, "stripped": True})
    system_routes.register(app, svc, None)

    @app.exception_handler(ValueError)
    async def bad(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)
    client = TestClient(app)
    assert client.get("/api/results").json() == [{"id": "abcdef123456"}]
    assert client.get("/api/results/abcdef123456").json()["stripped"] is True
    assert client.get("/api/results/none").status_code == 404
    r = client.get("/api/results/abcdef123456/csv")
    assert r.status_code == 200 and r.content.startswith(b"\xef\xbb\xbf") and "saebom-abcdef12.csv" in r.headers["content-disposition"]
    assert client.get("/api/results/none/csv").status_code == 404
    ok = client.post("/api/results/abcdef123456/correct", json={"overrides": {"i1": {"vat": 9}}})
    assert ok.json() == {"id": "job1"}
    assert svc.calls[-1] == ("submit", "보정 후 재비교", ([{"invoice": "i1", "contract": "c1"}], {"i1": {"vat": 9}}, "abcdef123456"))
    bad_resp = client.post("/api/results/abcdef123456/correct", json={"overrides": {"i1": {"percent": 101}}})
    assert bad_resp.status_code == 400 and bad_resp.json()["detail"] == RANGE_MSG
    assert client.post("/api/results/none/correct", json={"overrides": {}}).status_code == 404
    d = client.get("/api/documents/d1")
    assert d.status_code == 200 and d.content == b"%PDF-1.4 fake" and d.headers["content-type"] == "application/pdf"
    assert client.get("/api/documents/zzz").status_code == 404
    assert {c[0] for c in svc.calls} >= {"get_result", "list_results", "document_file"}
