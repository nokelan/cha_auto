# [파일 기능명세]
# '로컬 세금계산서 대조' 백엔드 회귀 검사. local_audit 순수 함수(check_folder·partner_from_name·scan_folder·match_contracts·pick_contract),
# Store.meta_get/meta_set, Service.run_local_audit 전체 흐름(가짜 SiteClient·가짜 PDF 요청과 tests/fixtures PDF), 상태 재조회와
# API 엔드포인트 4개(인증·입력 검증·폴더 선택창 대역·작업 접수)를 검증한다.
# 외부 네트워크·실제 브라우저·실제 폴더 선택창을 쓰지 않는다. DB·파일은 tmp_path 안에서만 만든다.
# 유지보수: 결과 행 형식(기획/로컬세금계산서_대조_구축계획.md)이나 대조 규칙이 바뀌면 이 검사와 기능명세를 함께 갱신한다.

import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from saebom import api as api_module
from saebom import local_audit
from saebom.api import create_app
from saebom.service import Service
from saebom.store import Store
from test_contracts_import import BASE, FILE_BASE, FakeRequest, FakeSite, static_dir, unlock

FIXTURES = Path(__file__).parent / "fixtures"


# [기능명세] contract
# 목적: 사이트 계약 행 형태의 테스트 사전 생성(fixture 계약서 PDF 이름을 파일 링크로 사용)
# 입력: (id: 관리번호, partner: 거래처, kind="지출", pdf=None: fixture 계약서 번호(예 "011") 또는 None(PDF 없음), alias=None: URL 파일 이름 대체)
# 출력: {id, kind, partner, title, period, amount_text, file:{name,url}|None}
# 처리: pdf가 있으면 fixture에서 '계약서_C-2026-{pdf}_*.pdf'를 찾아 이름을 쓰고, alias가 있으면 그 이름으로 URL을 만듦
# 예외/실패: fixture가 없으면 StopIteration
# 부수효과: 없음
def contract(id, partner, kind="지출", pdf=None, alias=None):
    file = None
    if pdf:
        name = alias or next(FIXTURES.glob(f"계약서_C-2026-{pdf}_*.pdf")).name
        file = {"name": name, "url": FILE_BASE + name}
    return {"id": id, "kind": kind, "partner": partner, "title": "유지보수", "period": "2026-01-01 ~ 2026-12-31",
            "amount_text": "1,000,000원", "file": file}


# [기능명세] payloads_for
# 목적: 계약 행 목록의 파일 URL → fixture PDF 바이트 사전 생성(FakeRequest용)
# 입력: (items: contract() 행 목록, sources: {관리번호: fixture 계약서 번호})
# 출력: {url: bytes}
# 처리: 파일 링크가 있는 행마다 sources의 번호로 fixture PDF를 읽음(같은 PDF를 다른 URL로 줄 수 있음)
# 예외/실패: fixture가 없으면 StopIteration
# 부수효과: fixture 파일 읽기
def payloads_for(items, sources):
    return {c["file"]["url"]: next(FIXTURES.glob(f"계약서_C-2026-{sources[c['id']]}_*.pdf")).read_bytes() for c in items if c["file"]}


# [기능명세] fake_service
# 목적: 가짜 사이트·가짜 PDF 요청을 붙인 Service 준비
# 입력: (store: Store, site: FakeSite, request: FakeRequest)
# 출력: Service
# 처리: Service 생성 → site 교체 → request 속성만 가진 컨텍스트 대역 주입 → browser()를 아무것도 하지 않게 교체
# 예외/실패: 없음
# 부수효과: 없음(브라우저를 열지 않음)
def fake_service(store, site, request):
    service = Service(store)
    service.site = site

    # [자료형/클래스 명세] Context: Playwright 컨텍스트 대역. request 속성만 제공한다.
    class Context:
        pass
    Context.request = request
    service.context = Context()
    service.browser = lambda: None
    return service


# [기능명세] wait_job
# 목적: 작업이 끝날 때까지 기다림
# 입력: (service, job_id)
# 출력: 끝난 작업 사전 사본
# 처리: 0.05초 간격으로 최대 20초 상태 확인
# 예외/실패: 시간 안에 끝나지 않으면 AssertionError
# 부수효과: 없음
def wait_job(service, job_id):
    for _ in range(400):
        job = next(j for j in service.jobs_snapshot() if j["id"] == job_id)
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("작업이 끝나지 않았습니다.")


# [기능명세] test_check_folder_rejects
# 목적: 폴더 검사가 빈 값·상대경로·드라이브 상대경로·없는 폴더·UNC·파일을 거부하고 실제 절대 폴더는 허용하는지 검증
# 입력: (tmp_path)
# 출력: None; 조건을 어기면 AssertionError
# 처리: 각 입력으로 check_folder 호출 후 ValueError와 한글 문구 확인
# 예외/실패: 단언 실패
# 부수효과: tmp_path 안에 파일 1개 생성
def test_check_folder_rejects(tmp_path):
    for bad, words in (("", "입력"), ("  ", "입력"), ("상대폴더", "절대"), ("C:상대", "절대"),
                       (str(tmp_path / "없음"), "찾을 수 없습니다"), ("\\\\server\\share", "네트워크"), ("//server/share", "네트워크")):
        with pytest.raises(ValueError, match=words):
            local_audit.check_folder(bad)
    file = tmp_path / "a.pdf"
    file.write_bytes(b"x")
    with pytest.raises(ValueError):
        local_audit.check_folder(str(file))
    assert local_audit.check_folder(f"  {tmp_path}  ") == tmp_path


# [기능명세] test_partner_from_name
# 목적: 파일명 규칙(세금계산서_{상호}_YYYY-MM.pdf|png)에서만 상호를 뽑는지 검증
# 입력: ()
# 출력: None; 조건을 어기면 AssertionError
# 처리: 규칙에 맞는 이름·대문자 확장자·경로 포함·밑줄 든 상호와 규칙 밖 이름을 비교
# 예외/실패: 단언 실패
# 부수효과: 없음
def test_partner_from_name():
    assert local_audit.partner_from_name("세금계산서_세움네트웍스_2026-09.pdf") == "세움네트웍스"
    assert local_audit.partner_from_name("세금계산서_초록IDC_2026-09.PNG") == "초록IDC"
    assert local_audit.partner_from_name(r"D:\폴더\세금계산서_가온_데이터_2026-10.png") == "가온_데이터"
    for bad in ("세금계산서_세움_2026-9.pdf", "계약서_세움_2026-09.pdf", "세금계산서_세움_2026-09.xlsx", "세금계산서__2026-09.pdf", "scan.png"):
        assert local_audit.partner_from_name(bad) is None, bad


# [기능명세] test_scan_folder_rules
# 목적: scan_folder의 파일 고르기(바로 아래 pdf/png만·대소문자 무시·이름순), PDF 판독·PNG 미판독·파일명 상호 보조·크기 초과·200개 제한을 검증
# 입력: (tmp_path, monkeypatch)
# 출력: None; 조건을 어기면 AssertionError
# 처리: fixture PDF 2개(하나는 .PDF 대문자)·가짜 PNG·txt·하위 폴더 PDF를 둔 폴더를 읽고 행 확인 → 크기 제한을 낮춰 오류 행 확인
#       → 파일 수 제한을 낮춰 앞 N개와 경고 확인(판독 대역으로 호출 횟수 확인)
# 예외/실패: 단언 실패
# 부수효과: tmp_path 안에 파일 생성
def test_scan_folder_rules(tmp_path, monkeypatch):
    folder = tmp_path / "in"
    (folder / "sub").mkdir(parents=True)
    shutil.copy(FIXTURES / "세금계산서_세움네트웍스_2026-09.pdf", folder / "세금계산서_세움네트웍스_2026-09.pdf")
    shutil.copy(FIXTURES / "세금계산서_가온데이터_2026-09.pdf", folder / "세금계산서_가온데이터_2026-09.PDF")
    shutil.copy(FIXTURES / "세금계산서_가온데이터_2026-09.pdf", folder / "sub" / "세금계산서_하위_2026-09.pdf")
    (folder / "세금계산서_누리클라우드_2026-09.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (folder / "메모.txt").write_text("x")
    rows = local_audit.scan_folder(folder)
    assert [r["file"] for r in rows] == ["세금계산서_가온데이터_2026-09.PDF", "세금계산서_누리클라우드_2026-09.png", "세금계산서_세움네트웍스_2026-09.pdf"]
    gaon, png, seum = rows
    assert gaon["type"] == "pdf" and gaon["partner"] == "가온데이터(주)" and gaon["partner_source"] == "pdf"
    assert seum["invoice"]["error"] is None and seum["invoice"]["fields"]["supply"]["value"] == 3150000
    assert set(seum["invoice"]) == {"fields", "error"} and seum["path"] == str(folder / seum["file"]) and seum["size"] > 0
    assert seum["invoice"]["fields"]["biz"]["page"] == 1 and seum["invoice"]["fields"]["biz"]["quote"]
    assert png["type"] == "png" and png["partner"] == "누리클라우드" and png["partner_source"] == "filename"
    assert png["invoice"] == {"fields": {}, "error": local_audit.PNG_ERROR}

    monkeypatch.setattr(local_audit, "MAX_FILE_BYTES", 10)
    rows = local_audit.scan_folder(folder)
    assert all(r["invoice"]["error"] == local_audit.SIZE_ERROR for r in rows) and rows[0]["partner_source"] == "filename"

    monkeypatch.setattr(local_audit, "MAX_FILE_BYTES", 10**9)
    monkeypatch.setattr(local_audit, "MAX_FILES", 2)
    calls, warnings = [], []
    rows = local_audit.scan_folder(folder, lambda p, k: calls.append((p.name, k)) or {"fields": {}, "error": "텍스트 추출 불가"}, warnings)
    assert [r["file"] for r in rows] == ["세금계산서_가온데이터_2026-09.PDF", "세금계산서_누리클라우드_2026-09.png"]
    assert calls == [("세금계산서_가온데이터_2026-09.PDF", "invoice")] and rows[0]["partner_source"] == "filename"
    assert warnings and "3개" in warnings[0]


# [기능명세] test_match_contracts_norm
# 목적: 상호 정규화 매칭((주)·주식회사·공백 차이, 한쪽 포함)과 상호 없음·빈 거래처 처리를 검증
# 입력: ()
# 출력: None; 조건을 어기면 AssertionError
# 처리: 여러 표기의 계약 목록에 대해 match_contracts 결과 ID 순서 비교
# 예외/실패: 단언 실패
# 부수효과: 없음
def test_match_contracts_norm():
    items = [contract("A", "(주) 한빛 시큐어"), contract("B", "주식회사 한빛시큐어", "수입"), contract("C", "한빛"),
             contract("D", "푸른정보통신"), contract("E", ""), contract("F", "한빛시큐어테크")]
    assert [c["id"] for c in local_audit.match_contracts("한빛시큐어(주)", items)] == ["A", "B", "C", "F"]
    assert [c["id"] for c in local_audit.match_contracts("㈜ 푸른 정보통신", items)] == ["D"]
    assert local_audit.match_contracts(None, items) == [] and local_audit.match_contracts("(주)", items) == []
    assert local_audit.match_contracts("가온데이터", items) == []


# [기능명세] test_pick_contract_rules
# 목적: pick_contract의 우선순위(지출 우선 → 사업자번호 → 청구월·계약기간)와 미결·수입만·후보 없음 사유를 검증
# 입력: ()
# 출력: None; 조건을 어기면 AssertionError
# 처리: 문서 사전(URL→{extraction:{fields}})을 직접 만들어 여러 후보 조합으로 호출
# 예외/실패: 단언 실패
# 부수효과: 없음
def test_pick_contract_rules():
    def doc(biz, start, end):
        return {"extraction": {"fields": {"biz": {"value": biz}, "start": {"value": start}, "end": {"value": end}}}}
    a, b, c, inc = (contract("A", "x", pdf="011"), contract("B", "x", pdf="012"), contract("C", "x", pdf="013"),
                    contract("I", "x", "수입", pdf="001"))
    docs = {a["file"]["url"]: doc("111", "2026-01-01", "2026-06-30"), b["file"]["url"]: doc("222", "2026-01-01", "2026-12-31"),
            c["file"]["url"]: doc("111", "2026-07-01", "2026-12-31"), inc["file"]["url"]: doc("111", "2026-01-01", "2026-12-31")}
    inv = {"biz": {"value": "111"}, "month": {"value": "2026-09"}}
    assert local_audit.pick_contract([], inv, docs) == (None, "웹 계약서 목록에 같은 거래처 계약이 없습니다.")
    chosen, reason = local_audit.pick_contract([inc, b], inv, docs)
    assert chosen is b and "지출 계약 1건" in reason
    chosen, reason = local_audit.pick_contract([a, b], inv, docs)
    assert chosen is a and "사업자번호" in reason
    chosen, reason = local_audit.pick_contract([a, b, c], inv, docs)
    assert chosen is c and "계약기간" in reason
    chosen, reason = local_audit.pick_contract([a, c], {"biz": {"value": "111"}}, docs)
    assert chosen is None and reason == "후보 2건, 확인 필요"
    chosen, reason = local_audit.pick_contract([inc], inv, docs)
    assert chosen is inc and reason.startswith("수입 계약입니다")
    chosen, reason = local_audit.pick_contract([inc, dict(inc, id="I2")], {}, {})
    assert chosen is None and reason == "후보 2건, 확인 필요 (수입 계약만 있음)"


# [기능명세] test_meta_get_set
# 목적: Store.meta_get/meta_set의 JSON 저장·덮어쓰기·없는 키·재연결 뒤 유지를 검증
# 입력: (tmp_path)
# 출력: None; 조건을 어기면 AssertionError
# 처리: 문자열·사전 저장 후 조회 → 덮어쓰기 → DB 재연결 후 조회
# 예외/실패: 단언 실패
# 부수효과: tmp_path 임시 DB 생성
def test_meta_get_set(tmp_path):
    store = Store(tmp_path / "db")
    assert store.meta_get("local_audit") is None
    store.meta_set("local_invoice_folder", "D:\\세금계산서")
    store.meta_set("local_audit", {"rows": [{"status": "일치"}]})
    store.meta_set("local_audit", {"rows": []})
    assert store.meta_get("local_invoice_folder") == "D:\\세금계산서"
    store.close()
    again = Store(tmp_path / "db")
    assert again.meta_get("local_audit") == {"rows": []}
    again.close()


# [기능명세] test_run_local_audit_flow
# 목적: run_local_audit 전체 흐름과 결과 행 계약(상태별 규칙·후보·기대 금액·계약서 문서·저장·재조회)을 검증
# 입력: (tmp_path)
# 출력: None; 조건을 어기면 AssertionError
# 처리: fixture 세금계산서 PDF 5개·가짜 PNG 2개 폴더와 가짜 사이트 계약 9건으로 대조
#       - 세움네트웍스: 표기가 다른 지출 후보 2건 중 사업자번호로 011 선택 → 일치
#       - 가온데이터: 사이트 목록에 없음 → 계약서 없음
#       - 누리클라우드 PNG: 파일명 상호로 012 선택 → 확인 필요, 기대 금액·계약서 문서 채움
#       - 푸른정보통신: 같은 계약서의 지출 후보 2건 → 확인 필요(후보 2건)
#       - 다솜오피스: 수입 계약만 → 확인 필요, checks는 채움
#       - 하늘전산: 계약서 404 → 처리 실패, 작업 errors
#       - 바른회선: 계약기간(~2026-08)이 지난 청구 → 불일치
#       - 메모.png: 상호 없음 → 확인 필요
#       → 사이트 목록은 '전체'로 1회만, 고른 계약만 계약서 목록 기록, meta 저장, 완료 문구, 상태 재조회(available·pages 비움), 판독 캐시 재사용
# 예외/실패: 단언 실패
# 부수효과: tmp_path 안의 DB·PDF 생성; 네트워크·실제 브라우저 사용하지 않음
def test_run_local_audit_flow(tmp_path, monkeypatch):
    folder = tmp_path / "세금계산서"
    folder.mkdir()
    for name in ("세움네트웍스", "가온데이터", "푸른정보통신", "다솜오피스", "하늘전산", "바른회선"):
        shutil.copy(FIXTURES / f"세금계산서_{name}_2026-09.pdf", folder)
    (folder / "세금계산서_누리클라우드_2026-09.png").write_bytes(b"\x89PNG fake")
    (folder / "메모.png").write_bytes(b"\x89PNG fake")
    items = [contract("C-2026-011", "세움네트웍스", pdf="011"), contract("C-2026-001", "(주)세움 네트웍스", pdf="001"),
             contract("C-2026-012", "누리클라우드(주)", pdf="012"),
             contract("C-2026-013", "푸른정보통신", pdf="013"), contract("C-2026-023", "푸른정보통신", pdf="013", alias="계약서_C-2026-023_푸른.pdf"),
             contract("C-2026-021", "다솜오피스", "수입", pdf="021"), contract("C-2026-018", "하늘전산", pdf="018"),
             contract("C-2026-019", "바른회선(주)", pdf="019"), contract("C-2026-030", "다른업체", pdf="015")]
    sources = {c["id"]: c["id"][-3:] for c in items}
    sources.update({"C-2026-023": "013", "C-2026-030": "015"})
    fail_url = items[6]["file"]["url"]
    store = Store(tmp_path / "db")
    store.set_document_root(str(tmp_path / "saved"))
    site, request = FakeSite(items), FakeRequest(payloads_for(items, sources), {fail_url})
    service = fake_service(store, site, request)
    try:
        jid = service.submit("로컬 세금계산서 대조", service.run_local_audit)["id"]
        job = wait_job(service, jid)
        assert job["status"] == "failed" and "세금계산서 폴더를 먼저 선택하세요." in job["message"]

        state = service.set_local_folder(str(folder))
        assert state["folder"] == str(folder) and state["folder_error"] is None and len(state["files"]) == 8 and state["last"] is None

        job = wait_job(service, service.submit("로컬 세금계산서 대조", service.run_local_audit)["id"])
        assert job["status"] == "done", job
        assert job["message"] == "세금계산서 8건 대조: 일치 1 · 불일치 1 · 확인 필요 4 · 처리 실패 1 · 계약서 없음 1"
        assert job["total"] == 9 and job["done"] == 9
        assert len(job["errors"]) == 1 and job["errors"][0].startswith("세금계산서_하늘전산_2026-09.pdf: 계약서 내려받기 실패")
        assert site.kinds == ["전체"]
        # 내려받기 대상: 지출 후보만(가온데이터·메모는 없음), 같은 URL은 한 번만. 다른업체(030)는 요청하지 않음.
        assert sorted(u.rsplit("/", 1)[1][:14] for u in request.urls) == sorted(
            ["계약서_C-2026-011", "계약서_C-2026-001", "계약서_C-2026-012", "계약서_C-2026-013", "계약서_C-2026-023",
             "계약서_C-2026-021", "계약서_C-2026-018", "계약서_C-2026-019"])
        assert store.imported_contract_ids() == {"C-2026-011", "C-2026-012", "C-2026-021", "C-2026-019"}

        last = store.meta_get("local_audit")
        assert last["folder"] == str(folder) and last["ran_at"] and last["contracts_total"] == 9
        assert last["counts"] == {"일치": 1, "불일치": 1, "확인 필요": 4, "처리 실패": 1, "계약서 없음": 1}
        rows = {r["file"]: r for r in last["rows"]}
        keys = {"file", "type", "size", "partner", "partner_source", "invoice", "contract", "contract_doc", "candidates", "expected", "status", "checks", "note"}
        assert all(set(r) == keys for r in last["rows"])

        seum = rows["세금계산서_세움네트웍스_2026-09.pdf"]
        assert seum["status"] == "일치" and seum["contract"]["id"] == "C-2026-011" and "사업자번호" in seum["note"]
        assert seum["contract"] == {k: items[0][k] for k in ("id", "kind", "partner", "title", "period", "amount_text")}
        assert [c["id"] for c in seum["candidates"]] == ["C-2026-011", "C-2026-001"] and set(seum["candidates"][0]) == {"id", "kind", "partner", "title"}
        assert seum["expected"] == {"supply": 3150000, "vat": 315000, "total": 3465000}
        assert seum["contract_doc"]["available"] is True and seum["contract_doc"]["extraction"]["pages"] == []
        assert seum["contract_doc"]["kind"] == "contract" and seum["contract_doc"]["id"]
        assert {c["key"] for c in seum["checks"]} >= {"biz", "partner", "supply", "vat", "total", "period"}
        assert seum["invoice"]["fields"]["partner"]["value"] == "세움네트웍스" and seum["partner_source"] == "pdf"

        gaon = rows["세금계산서_가온데이터_2026-09.pdf"]
        assert gaon["status"] == "계약서 없음" and gaon["contract"] is None and gaon["candidates"] == [] and gaon["expected"] is None

        nuri = rows["세금계산서_누리클라우드_2026-09.png"]
        assert nuri["status"] == "확인 필요" and nuri["type"] == "png" and nuri["partner_source"] == "filename"
        assert nuri["contract"]["id"] == "C-2026-012" and nuri["contract_doc"]["available"] is True and nuri["checks"] == []
        assert nuri["expected"] == {"supply": 2350000, "vat": 235000, "total": 2585000}

        blue = rows["세금계산서_푸른정보통신_2026-09.pdf"]
        assert blue["status"] == "확인 필요" and blue["contract"] is None and blue["note"] == "후보 2건, 확인 필요"
        assert [c["id"] for c in blue["candidates"]] == ["C-2026-013", "C-2026-023"]

        dasom = rows["세금계산서_다솜오피스_2026-09.pdf"]
        assert dasom["status"] == "확인 필요" and dasom["contract"]["kind"] == "수입" and "수입 계약" in dasom["note"] and dasom["checks"]

        sky = rows["세금계산서_하늘전산_2026-09.pdf"]
        assert sky["status"] == "처리 실패" and sky["contract"]["id"] == "C-2026-018" and sky["contract_doc"] is None

        line = rows["세금계산서_바른회선_2026-09.pdf"]
        assert line["status"] == "불일치" and "청구기간" in line["note"]
        assert next(c for c in line["checks"] if c["key"] == "period")["status"] == "불일치"

        memo = rows["메모.png"]
        assert memo["status"] == "확인 필요" and memo["partner"] is None and memo["partner_source"] is None

        # 상태 재조회: 판독 캐시로 PDF를 다시 읽지 않고, 마지막 결과의 계약서 문서 표시를 현재 기준으로 갱신한다.
        calls = []
        import saebom.service as service_module
        monkeypatch.setattr(service_module, "extract", lambda *a: calls.append(a) or {"fields": {}, "error": "x"})
        state = service.local_audit_state()
        assert calls == [] and len(state["files"]) == 8 and state["last"]["counts"] == last["counts"]
        doc_path = store.path(store.document(id=seum["contract_doc"]["id"]))
        doc_path.unlink()
        state = service.local_audit_state()
        again = next(r for r in state["last"]["rows"] if r["file"] == seum["file"])
        assert again["contract_doc"]["available"] is False and again["contract_doc"]["extraction"]["pages"] == []
        assert store.document(id=seum["contract_doc"]["id"])["extraction"]["pages"]

        # 폴더가 사라지면 folder_error로 알리고 마지막 결과는 유지한다.
        shutil.rmtree(folder)
        state = service.local_audit_state()
        assert state["folder_error"] and state["files"] == [] and state["last"]["counts"] == last["counts"]
    finally:
        service.close()
        store.close()


# [기능명세] test_local_audit_api
# 목적: 로컬 세금계산서 대조 API 4개의 인증·입력 검증(422/400)·상태 응답·폴더 선택창 시작 폴더·작업 접수를 검증
# 입력: (tmp_path, monkeypatch)
# 출력: None; 조건을 어기면 AssertionError
# 처리: 잠금 해제 전 401 → GET 초기 상태 → PUT 빈 값 422·상대경로·없는 폴더 400 → PUT 정상 폴더 → pick-folder(api.ask_folder 대역) 인자 확인
#       → run 접수(run_local_audit 대역)와 작업 이름 확인
# 예외/실패: 단언 실패
# 부수효과: tmp_path 임시 DB·파일 생성; 실제 대화상자·네트워크 사용하지 않음
def test_local_audit_api(tmp_path, monkeypatch):
    store = Store(tmp_path / "data")
    app = create_app(store, static_dir(tmp_path), "tok")
    asked = []
    monkeypatch.setattr(api_module, "ask_folder", lambda title, initialdir: asked.append((title, initialdir)) or "D:\\고른폴더")
    with TestClient(app, base_url=BASE) as client:
        assert client.get("/?token=tok").status_code == 200
        assert client.get("/api/local-audit").status_code == 401
        assert client.put("/api/local-audit/folder", json={"folder": str(tmp_path)}).status_code == 401
        assert client.post("/api/local-audit/pick-folder").status_code == 401
        assert client.post("/api/local-audit/run").status_code == 401
        unlock(client, "tok")

        assert client.get("/api/local-audit").json() == {"folder": None, "folder_error": None, "files": [], "warnings": [], "last": None}
        assert client.put("/api/local-audit/folder", json={"folder": ""}).status_code == 422
        assert client.put("/api/local-audit/folder", json={}).status_code == 422
        r = client.put("/api/local-audit/folder", json={"folder": "상대폴더"})
        assert r.status_code == 400 and "절대" in r.json()["detail"]
        r = client.put("/api/local-audit/folder", json={"folder": "\\\\server\\share"})
        assert r.status_code == 400 and "네트워크" in r.json()["detail"]
        assert store.meta_get("local_invoice_folder") is None

        r = client.post("/api/local-audit/pick-folder")
        assert r.status_code == 200 and r.json() == {"folder": "D:\\고른폴더"}
        assert asked[-1] == ("세금계산서 폴더 선택", str(store.document_root()))
        assert store.meta_get("local_invoice_folder") is None

        folder = tmp_path / "inv"
        folder.mkdir()
        shutil.copy(FIXTURES / "세금계산서_세움네트웍스_2026-09.pdf", folder)
        r = client.put("/api/local-audit/folder", json={"folder": str(folder)})
        assert r.status_code == 200
        body = r.json()
        assert body["folder"] == str(folder) and [f["file"] for f in body["files"]] == ["세금계산서_세움네트웍스_2026-09.pdf"]
        assert body["files"][0]["invoice"]["fields"]["total"]["value"] == 3465000 and "pages" not in body["files"][0]["invoice"]
        client.post("/api/local-audit/pick-folder")
        assert asked[-1] == ("세금계산서 폴더 선택", str(folder))

        service = app.state.service
        calls = []
        service.run_local_audit = lambda job: calls.append(job) or "세금계산서 0건 대조"
        r = client.post("/api/local-audit/run")
        assert r.status_code == 200 and r.json()["id"]
        job = wait_job(service, r.json()["id"])
        assert job["kind"] == "로컬 세금계산서 대조" and job["status"] == "done" and job["message"] == "세금계산서 0건 대조"
        assert calls == [r.json()["id"]]
