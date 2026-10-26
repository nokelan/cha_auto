# [파일 기능명세] 리팩토링 1단계(도메인 계층) 보강 회귀 검사.
# R1-1 ContractNotFound, R1-2 종료 요청 중단, R1-3 빈 웹 목록 오류, R1-5 /api/state의 pages 제거, R1-6 상신 불확실 상태(site_draft),
# R1-7 금액 토큰, R1-8 메일 셀 수 검사, R1-9 documents.kind 채움을 가짜 사이트·임시 DB로 검증한다.
# 외부 네트워크·실제 브라우저·실사이트를 쓰지 않으며 DB·파일은 tmp_path 안에서만 만든다.
import re
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from saebom import compare
from saebom.api import create_app
from saebom.errors import ContractNotFound, SubmitUncertain
from saebom.service import Service
from saebom.site import SiteClient, mail_item
from saebom.store import Store

from test_contracts_import import FakeRequest, FakeSite as ContractSite, static_dir, unlock
from test_expense import FakeSite as ExpenseSite, registered, values, wait_job
from test_local_audit import fake_service


# [기능명세] run_job
# 목적: 작업 접수 후 완료까지 기다려 최종 작업 사전을 돌려준다.
# 입력: (service, kind: 작업 종류, fn: 실행 함수, *args). 출력: 작업 사전. 예외/실패: 시간 초과 AssertionError. 부수효과: 작업 스레드 실행.
def run_job(service, kind, fn, *args):
    return wait_job(service, service.submit(kind, fn, *args)["id"])


# [기능명세] test_import_empty_list_rules
# 목적: R1-3 가져오기 — '전체'의 빈 목록은 안내 오류, 구분 필터의 빈 결과는 정상 종료인지 검증. 입력: tmp_path. 출력 없음.
# 부수효과: 임시 DB만 사용.
def test_import_empty_list_rules(tmp_path):
    store = Store(tmp_path / "db")
    service = Service(store)
    service.site = ContractSite([])
    try:
        job = run_job(service, "계약서 가져오기", service.import_contracts, "전체", None, False)
        assert job["status"] == "failed" and "웹 계약서 목록이 비어 있습니다" in job["message"]
        job = run_job(service, "계약서 가져오기", service.import_contracts, "수입", None, False)
        assert job["status"] == "done" and "가져올 계약이 없습니다" in job["message"]
    finally:
        service.close()
        store.close()


# [기능명세] test_local_audit_empty_contracts
# 목적: R1-3 로컬 대조 — 웹 계약서 목록이 비면 모든 행이 '계약서 없음'이 되지 않고 작업이 안내 오류로 실패하는지 검증.
# 입력: tmp_path. 출력 없음. 부수효과: 임시 폴더·DB만 사용, 이전 결과 meta는 쓰지 않음.
def test_local_audit_empty_contracts(tmp_path):
    folder = tmp_path / "세금계산서"
    folder.mkdir()
    (folder / "세금계산서_가온데이터_2026-09.png").write_bytes(b"\x89PNG fake")
    store = Store(tmp_path / "db")
    store.meta_set("local_invoice_folder", str(folder))
    service = fake_service(store, ContractSite([]), FakeRequest({}, set()))
    try:
        job = run_job(service, "로컬 세금계산서 대조", service.run_local_audit)
        assert job["status"] == "failed" and "웹 계약서 목록이 비어 있습니다" in job["message"]
        assert store.meta_get("local_audit") is None
    finally:
        service.close()
        store.close()


# [기능명세] test_contract_not_found
# 목적: R1-1 없는 관리번호가 ContractNotFound로 던져지는지 검증. 입력: tmp_path. 출력 없음. 부수효과: 임시 DB만 사용.
def test_contract_not_found(tmp_path):
    store, service = registered(tmp_path)
    try:
        for call in (service.statement_draft, service.expense_draft, lambda i: service.create_statement(i, {}), lambda i: service.submit_expense(i, values())):
            with pytest.raises(ContractNotFound):
                call("no-such")
    finally:
        service.close()
        store.close()


# [기능명세] test_state_has_no_pages
# 목적: R1-5 /api/state 응답의 모든 문서에 pages가 비고 저장 데이터는 그대로인지 검증. 입력: tmp_path. 출력 없음.
# 부수효과: 임시 DB·PDF 파일만 사용.
def test_state_has_no_pages(tmp_path):
    store = Store(tmp_path / "db")
    url = "https://sbgw.vercel.app/files/inv.pdf"
    curl = "https://sbgw.vercel.app/files/con.pdf"
    path = tmp_path / "a.pdf"
    path.write_bytes(b"%PDF-x")
    big = {"fields": {"biz": {"value": "111-11-11111"}}, "pages": [{"page": 1, "text": "본문전문"}], "error": None}
    store.save_document(url, "inv.pdf", "h1", big, path, kind="invoice")
    store.save_document(curl, "con.pdf", "h2", big, path, kind="contract")
    store.snapshot([{"id": "m1", "sender": "가온", "subject": "s", "received": "2026-09-01", "attachments": [{"name": "inv.pdf", "url": url}]}],
                   [{"id": "c1", "kind": "지출", "partner": "가온", "title": "t", "period": "", "amount_text": "", "file": {"name": "con.pdf", "url": curl}}])
    app = create_app(store, static_dir(tmp_path), "hard-test")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        unlock(client, "hard-test")
        response = client.get("/api/state")
        state = response.json()
        assert state["mails"][0]["documents"][url]["available"] is True
        docs = list(state["mails"][0]["documents"].values()) + [c["document"] for c in state["contracts"]]
        assert len(docs) == 2 and all(d["extraction"]["pages"] == [] for d in docs)
        assert "본문전문" not in response.text
    # 앱 종료 때 store가 닫히므로 다시 열어 저장 데이터가 그대로인지 확인한다.
    store = Store(tmp_path / "db")
    assert store.document(source=url)["extraction"]["pages"] == big["pages"]
    store.close()


# [기능명세] submit_client
# 목적: 상신 버튼 클릭 전후의 오류를 재현하는 Playwright 페이지 대역(MagicMock)과 그 페이지를 쓰는 SiteClient 생성.
# 입력: (tmp_path, wait_error: 클릭 뒤 대기에서 던질 예외, click_error: 클릭에서 던질 예외, rejected: 사이트 폼 오류 표시 재현). 출력: SiteClient.
# 부수효과: 없음(브라우저를 열지 않음).
def submit_client(tmp_path, wait_error=None, click_error=None, rejected=False):
    page = MagicMock()
    page.url = "https://sbgw.vercel.app/#/draft"
    page.locator.return_value.evaluate_all.return_value = ["C-2026-031"]
    if click_error:
        page.get_by_test_id.return_value.click.side_effect = click_error
    page.wait_for_function.side_effect = wait_error
    if rejected:
        page.get_by_test_id.return_value.inner_text.return_value = "필수 항목 누락"
    client = SiteClient(tmp_path)
    client.page = lambda: page
    return client


# [기능명세] test_site_submit_after_click_is_uncertain
# 목적: R1-6 클릭 이후 오류는 SubmitUncertain, 클릭 이전 오류와 사이트 폼 오류는 일반 오류로 남는지 검증. 입력: tmp_path. 출력 없음.
def test_site_submit_after_click_is_uncertain(tmp_path):
    v = values()
    with pytest.raises(SubmitUncertain):
        submit_client(tmp_path, wait_error=TimeoutError("30초 초과")).submit_expense("C-2026-031", v)
    # 클릭 호출 중 오류도 기안 생성 여부를 알 수 없으므로 SubmitUncertain(검토 수정 반영)
    with pytest.raises(SubmitUncertain):
        submit_client(tmp_path, click_error=RuntimeError("클릭 실패")).submit_expense("C-2026-031", v)
    with pytest.raises(ValueError, match="사이트 상신 오류") as e:
        submit_client(tmp_path, rejected=True).submit_expense("C-2026-031", v)
    assert not isinstance(e.value, SubmitUncertain)


# [기능명세] raiser
# 목적: 호출되면 지정 예외를 던지는 함수 생성(가짜 사이트의 submit_expense 대체용). 입력: 예외 객체. 출력: 함수. 부수효과 없음.
def raiser(exc):
    def fail(*args):
        raise exc
    return fail


# [기능명세] test_run_expense_site_draft_flag
# 목적: R1-6 서비스의 site_draft 저장 규칙 검증(클릭 이후 오류 True·error, 클릭 이전 오류 없음, 검토 불일치 True, 품의완료 없음).
# 입력: tmp_path. 출력 없음. 부수효과: 임시 DB만 사용.
def test_run_expense_site_draft_flag(tmp_path):
    store, service = registered(tmp_path)
    try:
        service.site.submit_expense = raiser(SubmitUncertain("상신 뒤 시간 초과"))
        job = run_job(service, "지출결의서 상신", service.run_expense, "C-2026-031", values(), [])
        row = service.contract_catalog()[0]
        assert job["status"] == "failed" and row["status"] == "없음"
        assert row["approval"]["site_draft"] is True and "상신 뒤 시간 초과" in row["approval"]["error"]
        service.site.submit_expense = raiser(ValueError("클릭 전 실패"))
        run_job(service, "지출결의서 상신", service.run_expense, "C-2026-031", values(), [])
        row = service.contract_catalog()[0]
        assert "site_draft" not in row["approval"] and row["approval"]["error"] == "클릭 전 실패"
        fake = ExpenseSite()
        service.site = fake
        fake.mode = "mismatch"
        run_job(service, "지출결의서 상신", service.run_expense, "C-2026-031", values(), [])
        row = service.contract_catalog()[0]
        assert row["status"] == "없음" and row["approval"]["site_draft"] is True
        fake.mode = "ok"
        run_job(service, "지출결의서 상신", service.run_expense, "C-2026-031", values(), [])
        row = service.contract_catalog()[0]
        assert row["status"] == "품의완료" and not row["approval"].get("site_draft")
    finally:
        service.close()
        store.close()


# [기능명세] test_money_token_and_integer
# 목적: R1-7 쉼표만 있는 금액이 매칭되지 않아 추출이 예외 없이 끝나고, 정상 금액은 그대로 읽히는지 검증. 입력 없음. 출력 없음.
def test_money_token_and_integer():
    assert re.fullmatch(compare.MONEY, "1,234,567").group(1) == "1,234,567"
    assert not re.search(compare.MONEY, ",,")
    assert compare.integer("1,234") == 1234
    seen = {}
    compare.extract_invoice("작성일자 공급가액 세액\n2026-09-01 ,, ,\n합계 현금 ,", lambda k, v, m: seen.setdefault(k, v))
    assert "supply" not in seen and "total" not in seen


# [기능명세] test_mail_item_cell_count
# 목적: R1-8 셀이 3개 미만인 메일 행은 양식 변경 오류, 3개 이상이면 정상 변환인지 검증. 입력 없음. 출력 없음.
def test_mail_item_cell_count():
    ok = mail_item({"id": "m", "cells": ["가", "나", "다"], "files": []})
    assert ok == {"id": "m", "sender": "가", "subject": "나", "received": "다", "attachments": []}
    with pytest.raises(ValueError, match="메일 목록 양식이 바뀌었습니다"):
        mail_item({"id": "m", "cells": ["가", "나"], "files": []})


# [기능명세] test_download_one_fills_kind
# 목적: R1-9 이미 있는 문서를 재사용할 때 비어 있던 kind만 채우고 기존 값은 유지하는지 검증. 입력: tmp_path. 출력 없음.
# 부수효과: 임시 DB·PDF 파일만 사용.
def test_download_one_fills_kind(tmp_path):
    store = Store(tmp_path / "db")
    path = tmp_path / "a.pdf"
    path.write_bytes(b"%PDF-x")
    url = "https://sbgw.vercel.app/files/a.pdf"
    store.save_document(url, "a.pdf", "h", {"fields": {}, "pages": []}, path)
    assert not store.document(source=url)["kind"]
    service = Service(store)
    try:
        assert service.download_one({"name": "a.pdf", "url": url}, "contract")["kind"] == "contract"
        assert store.document(source=url)["kind"] == "contract"
        service.download_one({"name": "a.pdf", "url": url}, "invoice")
        assert store.document(source=url)["kind"] == "contract"
    finally:
        service.close()
        store.close()


# [기능명세] test_closing_stops_sync_and_compare
# 목적: R1-2 종료 요청 시 sync·run_compare·open_browser가 사이트 접근이나 결과 저장 없이 중단되는지 검증. 입력: tmp_path. 출력 없음.
# 부수효과: 임시 DB만 사용. 진행 상태 갱신은 대역으로 막는다.
def test_closing_stops_sync_and_compare(tmp_path):
    store = Store(tmp_path / "db")
    service = Service(store)
    site = MagicMock()
    service.site = site
    service.update = lambda *a, **k: None
    service.runner.closing = True
    try:
        for call in (lambda: service.sync("j"), lambda: service.open_browser("j")):
            with pytest.raises(ValueError, match="종료 요청"):
                call()
        site.fetch_mails.assert_not_called()
        site.open_mail.assert_not_called()
        service.validate_pairs = lambda pairs: ({}, {})
        with pytest.raises(ValueError, match="종료 요청"):
            service.run_compare("j", [{"mail_id": "m", "contract_id": "c", "invoice_url": "u"}])
        assert store.results() == []
    finally:
        service.runner.closing = False
        service.close()
        store.close()
