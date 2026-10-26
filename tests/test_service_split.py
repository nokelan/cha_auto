# [파일 기능명세]
# pytest 회귀 검사. 서비스 분리 리팩토링(jobs.JobRunner, site.allowed_url, Service.catalog/run_compare)의 동작을 tmp_path의 임시 Store로 검증한다.
# 네트워크·브라우저를 쓰지 않으며, 단언 실패는 결함이다.
# 유지보수: 함수·데이터 계약이 바뀌면 해당 기능명세와 실제 회귀 검사를 함께 갱신한다.

import json
import threading
import time

import pytest

from saebom.jobs import JobRunner
from saebom.service import Service, allowed_url as service_allowed_url
from saebom.site import allowed_url
from saebom.store import Store


# [기능명세] wait_done
# 목적: 작업이 running을 벗어날 때까지 대기
# 입력: (runner: JobRunner, job_id, timeout=5)
# 출력: 마지막 작업 상태 문자열
# 처리: 0.01초 간격으로 jobs[job_id]['status'] 확인
# 예외/실패: 제한시간 안에 끝나지 않으면 'running'을 반환해 호출자의 단언이 실패
# 부수효과: 없음
def wait_done(runner, job_id, timeout=5):
    end = time.time() + timeout
    while time.time() < end and runner.jobs[job_id]["status"] == "running":
        time.sleep(.01)
    return runner.jobs[job_id]["status"]


# [기능명세] test_job_runner_exclusive_and_submit
# 목적: submit과 exclusive의 상호 배제, 거절 문구, 해제 후 재사용 검증
# 입력: (tmp_path)
# 출력: None; 조건을 어기면 AssertionError
# 처리: 이벤트로 막힌 작업 실행 중 exclusive 거절 → 작업 종료 후 exclusive 진입 중 submit·중첩 exclusive 거절 → 해제 후 submit 성공
# 예외/실패: 예상 거절은 pytest.raises로 확인
# 부수효과: tmp_path 안 임시 DB만 변경
def test_job_runner_exclusive_and_submit(tmp_path):
    store = Store(tmp_path / "db")
    runner = JobRunner(store)
    gate = threading.Event()
    job = runner.submit("막힌 작업", lambda job_id: gate.wait(5))["id"]
    with pytest.raises(ValueError, match="^진행 중인 작업이 끝난 뒤 저장 위치를 변경해 주세요.$"):
        with runner.exclusive("저장 위치 변경"):
            pass
    with pytest.raises(ValueError, match="현재 작업이 끝난 뒤 실행해 주세요."):
        runner.submit("두 번째", lambda job_id: None)
    gate.set()
    assert wait_done(runner, job) == "done"
    with runner.exclusive("저장 위치 변경"):
        assert runner.busy == "저장 위치 변경"
        with pytest.raises(ValueError, match="현재 작업이 끝난 뒤 실행해 주세요."):
            runner.submit("이동 중 작업", lambda job_id: None)
        with pytest.raises(ValueError):
            with runner.exclusive("저장 위치 변경"):
                pass
        # 배타 구간 동안에도 상태 조회는 잠금에 막히지 않는다.
        assert runner.snapshot()[0]["id"] == job
    assert runner.busy is None
    # 블록 안 예외 뒤에도 busy가 해제된다.
    with pytest.raises(RuntimeError):
        with runner.exclusive("저장 위치 변경"):
            raise RuntimeError("boom")
    assert runner.busy is None
    after = runner.submit("이후 작업", lambda job_id: None)["id"]
    assert wait_done(runner, after) == "done"
    runner.close()
    with pytest.raises(ValueError):
        with runner.exclusive("저장 위치 변경"):
            pass
    store.close()


# [기능명세] test_job_runner_failure_restore_and_snapshot
# 목적: 실패 메시지 형식, running 복원 시 failed 전환, snapshot 최신순·사본 여부 검증
# 입력: (tmp_path)
# 출력: None; 조건을 어기면 AssertionError
# 처리: 실패 작업·성공 작업 실행 → snapshot 순서 확인 → meta.jobs에 running 작업을 넣고 새 JobRunner로 복원
# 예외/실패: 없음
# 부수효과: tmp_path 안 임시 DB만 변경
def test_job_runner_failure_restore_and_snapshot(tmp_path):
    store = Store(tmp_path / "db")
    runner = JobRunner(store)

    # [기능명세] test_job_runner_failure_restore_and_snapshot.fail
    # 목적: 실패하는 작업 함수 대역
    # 입력: (job_id)
    # 출력: 없음
    # 처리: 즉시 ValueError 발생
    # 예외/실패: 항상 ValueError('일부러 실패')
    # 부수효과: 없음
    def fail(job_id):
        raise ValueError("일부러 실패")
    first = runner.submit("실패 작업", fail)["id"]
    assert wait_done(runner, first) == "failed"
    assert runner.jobs[first]["message"] == "작업 실패: 일부러 실패"
    second = runner.submit("성공 작업", lambda job_id: runner.update(job_id, done=1))["id"]
    assert wait_done(runner, second) == "done"
    snap = runner.snapshot()
    assert [j["id"] for j in snap] == [second, first]
    snap[0]["status"] = "changed"
    assert runner.jobs[second]["status"] == "done"
    runner.close()
    # 이전 실행에서 running으로 남은 작업은 다시 열 때 failed가 된다.
    jobs = json.loads(store.db.execute("SELECT value FROM meta WHERE key='jobs'").fetchone()[0])
    jobs[second]["status"] = "running"
    with store.db:
        store.db.execute("INSERT OR REPLACE INTO meta VALUES('jobs',?)", (json.dumps(jobs, ensure_ascii=False),))
    again = JobRunner(store)
    assert again.jobs[second]["status"] == "failed"
    assert again.jobs[second]["message"].startswith("이전 실행이 종료되었습니다.")
    assert again.jobs[first]["status"] == "failed"
    again.close()
    store.close()


# [기능명세] test_allowed_url
# 목적: 다운로드 URL 허용 규칙과 service 재노출 검증
# 입력: ()
# 출력: None; 조건을 어기면 AssertionError
# 처리: 허용 URL 통과, http·다른 도메인·비PDF 거절
# 예외/실패: 예상 거절은 pytest.raises로 확인
# 부수효과: 없음
def test_allowed_url():
    assert service_allowed_url is allowed_url
    ok = "https://sbgw.vercel.app/files/a.PDF"
    assert allowed_url(ok) == ok
    for bad in ("http://sbgw.vercel.app/a.pdf", "https://evil.example/a.pdf", "https://sbgw.vercel.app/a.txt", "https://sbgw.vercel.app.evil/a.pdf"):
        with pytest.raises(ValueError, match="대상 사이트의 PDF"):
            allowed_url(bad)


# [기능명세] make_catalog_store
# 목적: catalog·run_compare 검사용 임시 Store 구성
# 입력: (tmp_path)
# 출력: (store, urls 사전)
# 처리: 메일 3건·계약 4건 스냅샷 저장, 계산서 2건·계약서 2건 문서 등록(일부는 파일 없음)
# 예외/실패: 없음
# 부수효과: tmp_path 안 DB·PDF 파일 생성
def make_catalog_store(tmp_path):
    store = Store(tmp_path / "db")
    base = "https://sbgw.vercel.app/files/"
    u = {k: base + k + ".pdf" for k in ("inv1", "inv2", "con1", "con2")}
    store.snapshot(
        [
            {"id": "m1", "sender": "가온데이터 담당자", "subject": "계산서1", "received": "2026-10-01 09:00", "attachments": [{"name": "inv1.pdf", "url": u["inv1"]}, {"name": "memo.xlsx", "url": base + "memo.xlsx"}]},
            {"id": "m2", "sender": "(주)가온데이터", "subject": "계산서2", "received": "2026-10-03 09:00", "attachments": [{"name": "inv2.PDF", "url": u["inv2"]}]},
            {"id": "m3", "sender": "무관한 회사", "subject": "공지", "received": "2026-10-02 09:00", "attachments": []},
        ],
        [
            {"id": "c1", "kind": "지출", "partner": "가온데이터(주)", "title": "A", "period": "", "amount_text": "", "file": {"name": "con1.pdf", "url": u["con1"]}},
            {"id": "c2", "kind": "지출", "partner": "다른회사", "title": "B", "period": "", "amount_text": "", "file": {"name": "con2.pdf", "url": u["con2"]}},
            {"id": "c3", "kind": "수입", "partner": "가온데이터", "title": "C", "period": "", "amount_text": "", "file": None},
            {"id": "c4", "kind": "지출", "partner": "가온", "title": "D", "period": "", "amount_text": "", "file": None},
        ])
    folder = tmp_path / "pdf"
    folder.mkdir()

    # [기능명세] make_catalog_store.add
    # 목적: 문서 한 건 등록(파일 생성 여부 선택)
    # 입력: (key, biz, exists=True, fields=None)
    # 출력: 저장된 문서 사전
    # 처리: exists이면 PDF 바이트 파일 생성 → save_document
    # 예외/실패: 없음
    # 부수효과: 임시 파일·DB 변경
    def add(key, biz, exists=True, fields=None):
        path = folder / (key + ".pdf")
        if exists:
            path.write_bytes(b"%PDF-" + key.encode())
        f = {"biz": {"value": biz, "quote": biz, "page": 1, "method": "test"}, **(fields or {})}
        return store.save_document(u[key], key + ".pdf", "h" + key, {"fields": f, "pages": [{"page": 1, "text": key}], "error": None}, path)
    add("inv1", "222-22-22222", fields={"supply": {"value": 100}, "vat": {"value": 10}, "total": {"value": 110}})
    add("inv2", "111-11-11111", exists=False)
    add("con1", "111-11-11111")
    add("con2", "222-22-22222", exists=False)
    return store, u


# [기능명세] test_catalog_candidates_and_available
# 목적: catalog의 정렬·PDF 첨부·문서 available·추천 후보(업체명 부분 문자열, 사업자번호 우선) 검증
# 입력: (tmp_path)
# 출력: None; 조건을 어기면 AssertionError
# 처리: make_catalog_store → Service.catalog → 기대값 단언
# 예외/실패: 없음
# 부수효과: tmp_path 안 DB·파일만 사용
def test_catalog_candidates_and_available(tmp_path):
    store, u = make_catalog_store(tmp_path)
    service = Service(store)
    data = service.catalog()
    mails = {m["id"]: m for m in data["mails"]}
    assert [m["id"] for m in data["mails"]] == ["m2", "m3", "m1"]
    assert data["synced"] == store.synced()
    # m1: 사용 가능한 계산서 번호 222-22-22222와 같은 계약서(c2, 파일 없음이어도 문서 존재)가 업체명 후보를 대체
    assert [a["name"] for a in mails["m1"]["pdfs"]] == ["inv1.pdf"]
    assert list(mails["m1"]["documents"]) == [u["inv1"]]
    assert mails["m1"]["documents"][u["inv1"]]["available"] is True
    assert mails["m1"]["candidates"] == ["c2"]
    # m2: 계산서 파일이 없어 사업자번호 후보가 없으므로 업체명 부분 문자열 후보(계약 목록 순서, 지출만)
    assert mails["m2"]["documents"][u["inv2"]]["available"] is False
    assert mails["m2"]["candidates"] == ["c1", "c4"]
    assert mails["m3"]["pdfs"] == [] and mails["m3"]["documents"] == {} and mails["m3"]["candidates"] == []
    contracts = {c["id"]: c for c in data["contracts"]}
    assert contracts["c1"]["document"]["available"] is True
    assert contracts["c2"]["document"]["available"] is False
    assert contracts["c3"]["document"] is None and contracts["c4"]["document"] is None
    assert contracts["c1"]["document"]["id"] == store.document(source=u["con1"])["id"]
    service.close()
    store.close()


# [기능명세] test_run_compare_overrides_and_groups
# 목적: run_compare의 보정 반영 형식, 저장 추출값 보존, 결과 행 형태 검증
# 입력: (tmp_path)
# 출력: None; 조건을 어기면 AssertionError
# 처리: 파일이 있는 계산서(inv1)·계약서(con1) 연결 → 보정값과 함께 run_compare 작업 실행 → 결과 확인
# 예외/실패: 파일 없는 문서 연결은 ValueError
# 부수효과: tmp_path 안 결과·작업 DB 저장
def test_run_compare_overrides_and_groups(tmp_path):
    store, u = make_catalog_store(tmp_path)
    service = Service(store)
    inv = store.document(source=u["inv1"])
    pairs = [{"mail_id": "m1", "contract_id": "c1", "invoice_url": u["inv1"]}]
    job = service.submit("비교", service.run_compare, pairs, {inv["id"]: {"vat": 0}}, "parent-id")["id"]
    assert wait_done(service.runner, job) == "done", service.jobs[job]
    result = store.results()[0]
    assert result["parent"] == "parent-id" and result["overrides"] == {inv["id"]: {"vat": 0}}
    row = result["rows"][0]
    assert set(row) >= {"mail_id", "contract_id", "subject", "partner", "invoice", "contract", "effective_invoice", "status", "checks", "error"}
    eff = row["effective_invoice"]
    assert list(eff) == ["fields", "pages", "error"]
    assert eff["fields"]["vat"] == {"value": 0, "quote": "사용자 수동 보정", "page": None, "method": "수동 보정", "previous": {"value": 10}}
    assert eff["pages"] == inv["extraction"]["pages"]
    # 저장된 추출값은 바뀌지 않는다.
    assert store.document(source=u["inv1"])["extraction"]["fields"]["vat"] == {"value": 10}
    assert row["invoice"]["extraction"]["fields"]["vat"] == {"value": 10}
    assert service.jobs[job]["result_id"] == result["id"]
    with pytest.raises(ValueError, match="선택 문서 다운로드를 먼저"):
        service.run_compare(job, [{"mail_id": "m2", "contract_id": "c1", "invoice_url": u["inv2"]}])
    service.close()
    store.close()
