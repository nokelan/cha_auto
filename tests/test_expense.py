# [파일 기능명세] 지출결의서의 초안·검증·작성본 검토·API·상태 영속성 회귀 검사.
# 사이트는 가짜 대역만 사용하며 실제 네트워크·사용자 데이터·브라우저 프로필은 쓰지 않는다.
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from saebom import config, expense
from saebom.api import create_app
from saebom.service import Service
from saebom.store import Store


# [기능명세] contract
# 목적: 판독된 시험 계약 사전 생성. 입력: 부가세 조건·금액·기간·종류. 출력: 문서와 계약 행.
# 처리: 실제 추출 스키마에 맞는 필드만 구성. 예외/실패: 없음. 부수효과: 없음.
def contract(mode="excluded", amount=2100000, start="2026-01-01", end="2026-12-31", kind="지출", basis="monthly"):
    fields = {k: {"value": v} for k, v in {"vat_mode": mode, "amount": amount, "start": start, "end": end, "basis": basis, "partner": "(주)한울정보"}.items()}
    doc = {"extraction": {"fields": fields, "pages": [], "error": None}}
    row = {"id": "C-2026-031", "kind": kind, "partner": "(주)한울정보", "title": "유지보수 계약서", "period": f"{start} ~ {end}",
           "amount_text": "2,100,000원", "file": {"name": "계약서_한울정보.pdf", "url": "https://sbgw.vercel.app/files/contract.pdf"}}
    return doc, row


# [기능명세] values
# 목적: 확인 창 입력값 생성. 입력: 덮어쓸 필드. 출력: 상신값 사전.
# 처리: 고정된 금액·청구월·업체명과 변경값 병합. 예외/실패: 없음. 부수효과: 없음.
def values(**changes):
    return {"title": "[IT기획팀] 한울정보 지출의 건", "month": "2026-09", "supply": 2100000, "vat": 210000,
            "total": 2310000, "partner": "(주)한울정보", "attachments": [], "note": "", **changes}


# [기능명세] written
# 목적: 사이트 작성본 DOM 원문의 가짜 결과 생성. 입력: 상신값. 출력: DOM 원문 사전.
# 처리: 실제 사이트처럼 업체명 뒤 괄호 사업자번호와 '26년 09월' 사용기간을 사용한다. 예외/실패: 없음. 부수효과: 없음.
def written(data):
    return {"doc_id": "U-1", "doc_no": "IT-2026-001", "doc_url": "https://sbgw.vercel.app/#/doc/U-1", "title": data["title"],
            "amount": f"KRW {data['total']:,}", "content": f"2. 업 체 명 : {data['partner']}(000-81-00041)\n4. 사용기간 : {data['month'][2:4]}년 {data['month'][5:7]}월\n5. 금 액 : {data['total']:,}원 (공급가액 {data['supply']:,}원 / 세액 {data['vat']:,}원)",
            "warnings": ["시험용 첨부 누락 경고"]}


# [기능명세] FakeSite
# 목적: 네트워크 없이 사이트 상신을 재현. calls는 접속 시도 횟수, mode는 성공·실패·불일치 분기.
class FakeSite:
    # [기능명세] __init__: 입력 없음, 대역의 호출 기록과 성공 분기를 초기화한다. 출력 없음. 실패·외부 부수효과 없음.
    def __init__(self):
        self.calls, self.mode = [], "ok"

    # [기능명세] submit_expense
    # 목적: 상신값 기록 후 작성본 반환. 입력: 관리번호와 검증값. 출력: 가짜 DOM 사전.
    # 처리: mode에 따라 성공·금액 오류·접속 오류 반환. 예외: fail이면 ValueError. 부수효과: 메모리 calls 기록.
    def submit_expense(self, id, data):
        self.calls.append((id, data))
        if self.mode == "fail":
            raise ValueError("시험 사이트 상신 실패")
        result = written(data)
        if self.mode == "mismatch":
            result["amount"] = "KRW 999"
        return result

    # [기능명세] close: 대역 종료. 입력 없음. 출력·부수효과·실패 없음.
    def close(self):
        pass


# [기능명세] registered
# 목적: 임시 DB와 원문 파일이 있는 계약 생성. 입력: tmp_path, 구분. 출력: Store와 FakeSite를 주입한 Service.
# 처리: 최소 PDF 파일과 판독값·가져온 기록 저장. 예외: 파일·DB 오류 전파. 부수효과: tmp_path 내부 파일과 DB.
def registered(tmp_path, kind="지출"):
    store = Store(tmp_path / "data")
    doc, row = contract(kind=kind)
    path = tmp_path / "contract.pdf"
    path.write_bytes(b"%PDF-test")
    store.save_document(row["file"]["url"], row["file"]["name"], "abcdef", doc["extraction"], path, kind="contract")
    store.save_contract_import(row)
    service = Service(store)
    service.site = FakeSite()
    return store, service


# [기능명세] wait_job
# 목적: 가짜 사이트 작업 완료 대기. 입력: 서비스·작업 ID. 출력: 최종 작업 사전.
# 처리: 최대 3초 조회. 예외: 시간 초과 AssertionError. 부수효과: 짧은 시험 대기만 발생.
def wait_job(service, id):
    until = time.monotonic() + 3
    while time.monotonic() < until:
        job = next(j for j in service.jobs_snapshot() if j["id"] == id)
        if job["status"] != "running":
            return job
        time.sleep(0.01)
    raise AssertionError("시험 작업이 종료되지 않았습니다.")


# [기능명세] test_draft_rules
# 목적: 비교 엔진 금액·계약기간 보정·총액·중복 경고와 첨부 이름 규칙 검증.
# 입력 없음. 출력 없음. 처리: 여러 계약 초안을 기대값과 비교. 예외: 단언 실패. 부수효과 없음.
def test_draft_rules():
    doc, row = contract()
    result = expense.draft(doc, row, today=date(2026, 10, 21))
    assert (result["month"], result["supply"], result["vat"], result["total"]) == ("2026-09", 2100000, 210000, 2310000)
    assert "세금계산서_한울정보_2026-09.pdf" in result["attachments"]
    assert result["title"].endswith("유지보수 지출의 건 (26.09월)")
    doc, row = contract(mode="included", amount=440000)
    result = expense.draft(doc, row, today=date(2026, 10, 21))
    assert (result["supply"], result["vat"], result["total"]) == (400000, 40000, 440000)
    doc, row = contract(start="2026-11-01", end="2026-12-31")
    assert expense.draft(doc, row, today=date(2026, 10, 21))["month"] == "2026-11"
    doc, row = contract(start="2026-01-01", end="2026-05-31", basis="total")
    result = expense.draft(doc, row, {"month": "2026-05", "review": [{"ok": True}]}, today=date(2026, 10, 21))
    assert result["month"] == "2026-05"
    assert any("총액" in w for w in result["warnings"])
    assert any("중복" in w for w in result["warnings"])


# [기능명세] test_validate_rejects
# 목적: 상신 전 잘못된 업무 입력 차단. 입력: 변경값 매개변수. 출력 없음.
# 처리: validate가 ValueError인지 확인. 예외: 단언 실패. 부수효과 없음.
@pytest.mark.parametrize("changes", [{"month": "2026-13"}, {"month": "2026-1"}, {"month": "0000-01"}, {"title": " "},
                                     {"total": 1}, {"supply": -1}, {"vat": True}, {"total": 10**12 + 1}, {"attachments": [1]}])
def test_validate_rejects(changes):
    with pytest.raises(ValueError):
        expense.validate(values(**changes))


# [기능명세] test_review_missing_and_mismatch
# 목적: 전 항목 일치와 DOM 누락·불일치·0 오인 방지 검증. 입력 없음. 출력 없음.
# 처리: 작성본 변형별 ok 검사. 예외: 단언 실패. 부수효과 없음.
def test_review_missing_and_mismatch():
    data = values()
    assert len(expense.review(data, written(data))) == 8
    assert all(c["ok"] for c in expense.review(data, written(data)))
    for key in ("amount", "content", "title"):
        document = written(data)
        document.pop(key)
        assert not all(c["ok"] for c in expense.review(data, document))
    assert expense.parse_document({})["document_total"] is None
    assert not all(c["ok"] for c in expense.review(values(supply=0, vat=0, total=0), {}))
    document = written(data)
    document["content"] = document["content"].replace("26년 09월", "26년 08월")
    assert not next(c for c in expense.review(data, document) if c["label"] == "사용기간")["ok"]
    document = written(data)
    document["content"] = document["content"].replace("26년 09월", "26.09")
    assert all(c["ok"] for c in expense.review(data, document))
    document["content"] = document["content"].replace("(주)한울정보", "다른업체(주)")
    assert not next(c for c in expense.review(data, document) if c["label"] == "업체명")["ok"]


# [기능명세] test_service_status_replaced_on_failure
# 목적: 성공 뒤 재상신 실패·검토 불일치가 이전 품의완료를 남기지 않는지 검증.
# 입력: tmp_path. 출력 없음. 처리: 세 분기를 순서대로 실행하고 목록 상태·검토 확인.
# 예외: 단언 실패. 부수효과: tmp_path의 DB와 가짜 호출 기록.
def test_service_status_replaced_on_failure(tmp_path):
    store, service = registered(tmp_path)
    try:
        for mode, status, job_status in (("ok", "품의완료", "done"), ("fail", "없음", "failed"), ("ok", "품의완료", "done"), ("mismatch", "없음", "done")):
            service.site.mode = mode
            job = wait_job(service, service.submit_expense("C-2026-031", values())["id"])
            row = service.contract_catalog()[0]
            assert job["status"] == job_status
            assert row["status"] == status
            if mode == "fail":
                assert row["approval"]["review"] == [] and "doc_no" not in row["approval"]
            elif mode == "mismatch":
                assert row["approval"]["document_total"] == 999
                assert not row["approval"]["review"][0]["ok"]
    finally:
        service.close()
        store.close()


# [기능명세] test_store_status_persists_snapshot
# 목적: DB 재열기·목록 동기화가 계약 상태를 지우지 않는지 검증.
# 입력: tmp_path. 출력 없음. 처리: 상태 저장→snapshot→재열기 비교. 예외: 단언 실패.
# 부수효과: tmp_path의 DB만 쓰고 닫는다.
def test_store_status_persists_snapshot(tmp_path):
    store = Store(tmp_path)
    store.save_contract_status("C-2026-031", "품의완료", {"month": "2026-09"})
    store.snapshot([], [])
    store.close()
    store = Store(tmp_path)
    try:
        assert store.contract_statuses()["C-2026-031"] == {"status": "품의완료", "approval": {"month": "2026-09"}}
    finally:
        store.close()


# [기능명세] test_api_contract_and_rejections
# 목적: 초안·상신 API, 기본 상태, 유효성·작업 충돌 차단과 가짜 상신 결과 검증.
# 입력: tmp_path. 출력 없음. 처리: 인증→초안→잘못된 요청·배타 작업→정상 상신→결과 조회.
# 예외: 단언 실패. 부수효과: 임시 DB·쿠키만 사용. 실제 네트워크 호출 없음.
def test_api_contract_and_rejections(tmp_path):
    store, source_service = registered(tmp_path)
    fake = source_service.site
    source_service.close()
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("app", encoding="utf-8")
    app = create_app(store, static, "expense-test")
    app.state.service.site = fake
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/contracts/C-2026-031/expense").status_code == 401
        client.get("/?token=expense-test")
        client.post("/api/auth/login", json={"password": config.APP_PASSWORD})
        assert client.get("/api/contracts").json()[0]["status"] == "없음"
        assert client.get("/api/contracts").json()[0]["approval"] is None
        assert client.get("/api/contracts/C-2026-031/expense").json()["eligible"]
        url = "/api/contracts/C-2026-031/expense"
        assert client.post(url, json=values(month="2026-13")).status_code == 400
        assert client.post(url, json=values(total=1)).status_code == 400
        assert client.post(url, json=values(vat=True)).status_code == 422
        assert client.get("/api/contracts/no-such/expense").status_code == 404
        with app.state.service.exclusive("시험 작업"):
            assert client.post(url, json=values()).status_code == 400
        assert fake.calls == []
        result = client.post(url, json=values())
        assert result.status_code == 200
        assert wait_job(app.state.service, result.json()["id"])["status"] == "done"
        row = client.get("/api/contracts").json()[0]
        assert row["status"] == "품의완료" and all(c["ok"] for c in row["approval"]["review"])
        assert "시험용 첨부 누락 경고" in row["approval"]["warnings"]


# [기능명세] test_income_rejects_without_site
# 목적: 수입 계약 상신을 네트워크 호출 전에 차단한다. 입력: tmp_path. 출력 없음.
# 처리: 수입 초안 eligible=false와 상신 ValueError 검사. 예외: 단언 실패. 부수효과: 임시 DB만 사용.
def test_income_rejects_without_site(tmp_path):
    store, service = registered(tmp_path, kind="수입")
    try:
        assert not service.expense_draft("C-2026-031")["eligible"]
        with pytest.raises(ValueError):
            service.submit_expense("C-2026-031", values())
        assert service.site.calls == []
    finally:
        service.close()
        store.close()


# [기능명세] test_duplicate_warning_uses_requested_month
# 목적: 기본 청구월이 아닌 수정한 실제 청구월로 중복 경고를 판단하는지 검증한다.
# 입력: tmp_path. 출력 없음. 처리: 같은 달 재상신과 다른 달 상신의 경고·저장 월 비교.
# 예외: 단언 실패. 부수효과: 임시 DB·가짜 사이트 호출만 사용.
def test_duplicate_warning_uses_requested_month(tmp_path):
    store, service = registered(tmp_path)
    try:
        for month, duplicate in (("2026-08", False), ("2026-08", True), ("2026-07", False)):
            job = wait_job(service, service.submit_expense("C-2026-031", values(month=month))["id"])
            assert job["status"] == "done"
            data = service.contract_catalog()[0]["approval"]
            assert data["month"] == month
            assert any("중복 상신" in w for w in data["warnings"]) == duplicate
    finally:
        service.close()
        store.close()
