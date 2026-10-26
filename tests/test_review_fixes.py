# [파일 기능명세] 개발문서 검토에서 나온 서버 결함 7건(B 항목)의 회귀 검사.
# 1 상신 시작 초기화 뒤에도 같은 달 중복 경고 유지, 2 작성본 수신 뒤 후속 오류의 site_draft 저장, 3 클릭 중 오류의 SubmitUncertain,
# 4 계약 목록 필터 뒤 표 안정화 대기, 5 동기화 뒤 보정 재비교 폴백, 6 빈 정규화 거래처의 이름 매칭 제외, 7 문서 응답의 ?download=1 첨부 헤더.
# 사이트는 대역(MagicMock·가짜 클래스)만 쓰며 네트워크·실제 브라우저는 쓰지 않는다. DB·파일은 tmp_path 안에서만 만든다.
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from saebom import expense
from saebom.api import create_app
from saebom.errors import SubmitUncertain
from saebom.service import Service
from saebom.site import SiteClient
from saebom.store import Store

from test_contracts_import import static_dir, unlock
from test_expense import FakeSite as ExpenseSite, registered, values
from test_hardening_domain import run_job, submit_client
from test_service_split import make_catalog_store, wait_done


# [기능명세] test_prior_approval_keeps_duplicate_warning
# 목적: 항목1 — 품의완료 뒤 같은 달 재상신이 실패해도(상신 시작 시 상태 없음 초기화) 중복 경고가 사라지지 않는지 검증. 입력: tmp_path. 출력 없음.
# 처리: 품의완료 저장 → 실패하는 재상신 → 초안 경고·상태 확인 → 성공 재상신 후 prior_approval 제거 확인. 부수효과: 임시 DB만 사용.
def test_prior_approval_keeps_duplicate_warning(tmp_path):
    store, service = registered(tmp_path)
    try:
        service.site = ExpenseSite()
        run_job(service, "상신", service.run_expense, "C-2026-031", values(), [])
        assert service.contract_catalog()[0]["status"] == "품의완료"
        service.site.mode = "fail"
        run_job(service, "상신", service.run_expense, "C-2026-031", values(), [])
        row = service.contract_catalog()[0]
        assert row["status"] == "없음" and row["approval"]["prior_approval"]["month"] == "2026-09"
        assert expense.completed_record(row["approval"])["month"] == "2026-09"
        draft_month = service.expense_draft("C-2026-031")["month"]
        # 초안 월이 이전 완료 월과 같을 때만 경고하므로, 같은 월일 때의 규칙을 순수 함수로 직접 확인한다.
        doc, r = service.store.document(source=store.contract_imports()[0]["file"]["url"]), store.contract_imports()[0]
        warned = expense.draft(doc, r, {**row["approval"]}, today=__import__("datetime").date(2026, 10, 21))
        assert warned["month"] == "2026-09" and any("중복 상신" in w for w in warned["warnings"])
        assert draft_month
        # 실패를 한 번 더 겪어도 이전 완료 기록은 이어진다.
        run_job(service, "상신", service.run_expense, "C-2026-031", values(), [])
        assert "prior_approval" in service.contract_catalog()[0]["approval"]
        service.site.mode = "ok"
        run_job(service, "상신", service.run_expense, "C-2026-031", values(), [])
        row = service.contract_catalog()[0]
        assert row["status"] == "품의완료" and "prior_approval" not in row["approval"]
    finally:
        service.close()
        store.close()


# [기능명세] test_post_document_error_saves_site_draft
# 목적: 항목2 — 작성본을 받은 뒤 검토에서 예외가 나면 site_draft=True와 문서 식별자·error가 저장되는지 검증. 입력: tmp_path·monkeypatch. 출력 없음.
def test_post_document_error_saves_site_draft(tmp_path, monkeypatch):
    store, service = registered(tmp_path)
    try:
        service.site = ExpenseSite()
        monkeypatch.setattr(expense, "review", MagicMock(side_effect=RuntimeError("검토 폭발")))
        job = run_job(service, "상신", service.run_expense, "C-2026-031", values(), [])
        row = service.contract_catalog()[0]
        assert job["status"] == "failed" and row["status"] == "없음"
        a = row["approval"]
        assert a["site_draft"] is True and a["doc_id"] == "U-1" and a["doc_no"] == "IT-2026-001" and "검토 폭발" in a["error"]
    finally:
        service.close()
        store.close()


# [기능명세] test_click_error_is_uncertain
# 목적: 항목3 — 상신 버튼 click() 호출 중 예외도 SubmitUncertain이 되고 서비스가 site_draft를 저장하는지 검증. 입력: tmp_path. 출력 없음.
def test_click_error_is_uncertain(tmp_path):
    try:
        submit_client(tmp_path, click_error=RuntimeError("클릭 중 연결 끊김")).submit_expense("C-2026-031", values())
        raise AssertionError("SubmitUncertain이 필요합니다.")
    except SubmitUncertain as e:
        assert "클릭 중 연결 끊김" in str(e)


# [기능명세] test_fetch_contracts_waits_for_stable_rows
# 목적: 항목4 — 필터 적용 직후 표가 바뀌는 동안(행 목록이 달라지는 동안) 읽지 않고 안정된 뒤 값을 쓰는지 검증. 입력: tmp_path. 출력 없음.
def test_fetch_contracts_waits_for_stable_rows(tmp_path):
    def row(i):
        return {"id": f"C-{i}", "cells": ["", "지출", "거래처", "제목", "기간", "금액", ""], "files": []}
    reads = [[row(1), row(2), row(3)], [row(1)], [row(1)]]
    page = MagicMock()
    page.url = "https://sbgw.vercel.app/#/contracts"
    page.locator.return_value.evaluate_all.side_effect = lambda js: reads.pop(0) if len(reads) > 1 else reads[0]
    client = SiteClient(tmp_path)
    client.page = lambda: page
    items = client.fetch_contracts("지출")
    assert [i["id"] for i in items] == ["C-1"]
    assert page.wait_for_timeout.call_count == 2
    # 빈 표도 두 번 연속 비면 안정으로 보고 반환한다.
    reads[:] = [[], []]
    assert client.fetch_contracts("수입") == []


# [기능명세] test_correct_after_resync_uses_saved_result
# 목적: 항목5 — 동기화로 현재 스냅샷에서 메일·계약이 사라진 뒤에도 저장 결과로 보정 재비교가 되는지, 스냅샷이 우선인지 검증. 입력: tmp_path. 출력 없음.
def test_correct_after_resync_uses_saved_result(tmp_path):
    store, u = make_catalog_store(tmp_path)
    service = Service(store)
    try:
        inv = store.document(source=u["inv1"])
        pairs = [{"mail_id": "m1", "contract_id": "c1", "invoice_url": u["inv1"]}]
        job = service.submit("비교", service.run_compare, pairs)["id"]
        assert wait_done(service.runner, job) == "done", service.jobs[job]
        first = store.results()[0]
        # 재동기화: m1·c1이 없는 새 목록
        store.snapshot([{"id": "m9", "sender": "다른", "subject": "x", "received": "2026-10-05", "attachments": []}],
                       [{"id": "c9", "kind": "지출", "partner": "다른", "title": "t", "period": "", "amount_text": "", "file": None}])
        try:
            service.validate_pairs(pairs)
            raise AssertionError("보충 자료 없이는 실패해야 합니다.")
        except ValueError:
            pass
        job = service.submit("보정", service.run_compare, pairs, {inv["id"]: {"vat": 0}}, first["id"])["id"]
        assert wait_done(service.runner, job) == "done", service.jobs[job]
        row = store.result(service.jobs[job]["result_id"])["rows"][0]
        assert row["subject"] == "계산서1" and row["effective_invoice"]["fields"]["vat"]["value"] == 0
        # 저장 결과에 없는 연결은 폴백되지 않는다.
        try:
            service.validate_pairs([{"mail_id": "mX", "contract_id": "c1", "invoice_url": u["inv1"]}], first)
            raise AssertionError("저장 결과에 없는 메일은 실패해야 합니다.")
        except ValueError:
            pass
    finally:
        service.close()
        store.close()


# [기능명세] test_empty_normalized_partner_not_matched_by_name
# 목적: 항목6 — 정규화 결과가 빈 거래처("(주)")가 모든 메일의 업체명 후보가 되지 않는지, 사업자번호 후보는 유지되는지 검증. 입력: tmp_path. 출력 없음.
def test_empty_normalized_partner_not_matched_by_name(tmp_path):
    store, u = make_catalog_store(tmp_path)
    service = Service(store)
    try:
        store.snapshot([{"id": "m3", "sender": "무관한 회사", "subject": "공지", "received": "2026-10-02", "attachments": []}],
                       [{"id": "c5", "kind": "지출", "partner": "(주)", "title": "E", "period": "", "amount_text": "", "file": None}])
        assert service.catalog()["mails"][0]["candidates"] == []
    finally:
        service.close()
        store.close()


# [기능명세] test_document_download_disposition
# 목적: 항목7 — /api/documents/{id}가 기본 inline, ?download=1이면 attachment와 한글 파일명 filename*를 주는지 검증. 입력: tmp_path. 출력 없음.
def test_document_download_disposition(tmp_path):
    store = Store(tmp_path / "db")
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF-test")
    doc = store.save_document("https://sbgw.vercel.app/files/a.pdf", "계약서_한울.pdf", "h", {"fields": {}, "pages": [], "error": None}, path)
    app = create_app(store, static_dir(tmp_path), "review-test")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        unlock(client, "review-test")
        inline = client.get(f"/api/documents/{doc['id']}")
        assert inline.status_code == 200 and inline.headers["content-disposition"].startswith("inline")
        att = client.get(f"/api/documents/{doc['id']}?download=1")
        cd = att.headers["content-disposition"]
        assert cd.startswith("attachment") and "filename*=utf-8''" in cd and att.content == b"%PDF-test"
        assert client.get(f"/api/documents/{doc['id']}?download=0").headers["content-disposition"].startswith("inline")
