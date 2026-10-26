# [파일 기능명세]
# 비교 결과 내보내기. routes/compare.py의 CSV 생성 본문을 순수 함수로 분리했다.
# 응답 헤더·파일명·404 처리는 라우트가 맡고, 이 모듈은 결과 사전을 CSV 문자열로 바꾸기만 한다.
# 셀 수식 방지는 rules.spreadsheet_safe를 사용한다. 파일·네트워크를 쓰지 않는다.
# 유지보수: 열 구성이 바뀌면 이 주석, 라우트 명세, tests/test_refactor_api.py, 개발문서를 함께 갱신한다.

import csv
import io

from .rules import spreadsheet_safe

# CSV 머리글(열 구성).
CSV_HEADER = ["업체", "메일", "계약번호", "전체판정", "항목", "계산서", "계약·기준", "차이(계산서-기준)", "항목판정", "설명", "계산서 근거", "계약 근거"]


# [기능명세] result_csv
# 목적: 비교 결과를 CSV 텍스트로 변환
# 입력: (result: 저장된 결과 사전 — rows[].partner·subject·contract_id·status·error·checks)
# 출력: UTF-8 BOM("﻿")으로 시작하는 CSV 문자열(csv 모듈 기본 방언, 줄바꿈 \r\n)
# 처리: 머리글 → 행마다 checks 항목별 한 줄(checks가 비면 '문서 처리' 한 줄에 행 상태·오류) → 모든 셀을 spreadsheet_safe로 변환(None은 빈 값)
# 예외/실패: rows·checks의 필수 키가 없으면 KeyError 전파
# 부수효과: 없음(메모리 문자열만 생성)
def result_csv(result):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(CSV_HEADER)
    for row in result["rows"]:
        for c in row["checks"] or [{"label": "문서 처리", "status": row["status"], "note": row["error"]}]:
            writer.writerow([spreadsheet_safe(x) for x in (row["partner"], row["subject"], row["contract_id"], row["status"], c["label"], c.get("actual"), c.get("expected"), c.get("difference"), c["status"], c.get("note"), (c.get("invoice_source") or {}).get("quote"), (c.get("contract_source") or {}).get("quote"))])
    return "﻿" + out.getvalue()
