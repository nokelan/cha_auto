# [파일 역할] 계약서 목록의 문서비교 판정 표시(Store.contract_verdicts, Service.contract_catalog의 compare 필드) 검증.
# 처리 흐름: 임시 Store에 비교 결과를 저장 → 메일별 최신 결과 선택·가장 나쁜 판정 대표값·옛 요약 보충을 확인한다.
import json

from saebom.store import Store


# [기능명세] row
# 목적: 테스트용 결과 행 생성. 입력: 메일 ID·계약 관리번호·판정. 출력: 결과 행 사전. 부수효과 없음.
def row(mail, contract, status):
    return {"mail_id": mail, "contract_id": contract, "partner": "가", "status": status}


# [기능명세] test_worst_verdict_and_counts
# 목적: 한 계약이 여러 메일과 비교되면 가장 나쁜 판정이 대표값이고 건수가 집계되는지 검증
def test_worst_verdict_and_counts(tmp_path):
    store = Store(tmp_path / "data")
    saved = store.save_result({"rows": [row("m1", "C-1", "일치"), row("m2", "C-1", "확인 필요"), row("m3", "C-2", "일치")]})
    v = store.contract_verdicts()
    assert v["C-1"]["status"] == "확인 필요" and v["C-1"]["mail_id"] == "m2" and v["C-1"]["result_id"] == saved["id"]
    assert v["C-1"]["count"] == 2 and v["C-1"]["counts"] == {"일치": 1, "확인 필요": 1}
    assert v["C-2"]["status"] == "일치" and "C-3" not in v
    store.close()


# [기능명세] test_correction_result_replaces_parent
# 목적: 보정으로 만든 새 결과가 같은 (메일, 계약) 쌍의 원본 불일치를 대체하는지 검증
def test_correction_result_replaces_parent(tmp_path):
    store = Store(tmp_path / "data")
    first = store.save_result({"rows": [row("m1", "C-1", "불일치")]})
    second = store.save_result({"rows": [row("m1", "C-1", "일치")], "parent": first["id"]})
    v = store.contract_verdicts()["C-1"]
    assert v["status"] == "일치" and v["result_id"] == second["id"] and v["count"] == 1
    store.close()


# [기능명세] test_old_summary_without_verdicts_is_refilled
# 목적: verdicts 키가 없는 옛 요약 행도 첫 조회 때 data로 보충되는지 검증
def test_old_summary_without_verdicts_is_refilled(tmp_path):
    store = Store(tmp_path / "data")
    saved = store.save_result({"rows": [row("m1", "C-1", "불일치")]})
    old = json.loads(store.db.execute("SELECT summary FROM results WHERE id=?", (saved["id"],)).fetchone()[0])
    old.pop("verdicts")
    with store.db:
        store.db.execute("UPDATE results SET summary=? WHERE id=?", (json.dumps(old), saved["id"]))
    assert store.contract_verdicts()["C-1"]["status"] == "불일치"
    assert "verdicts" in json.loads(store.db.execute("SELECT summary FROM results WHERE id=?", (saved["id"],)).fetchone()[0])
    store.close()
