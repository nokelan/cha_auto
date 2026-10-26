# [파일 기능명세]
# 화면·응답용 사본 만들기. 저장 데이터의 PDF 페이지 전문(extraction.pages)은 매우 커서 목록·상세 응답에 싣지 않으므로,
# 이를 비운 사본을 만드는 규칙을 한곳에 둔다(이전에는 api.py·contracts_service·local_audit_service에 같은 코드가 3벌 있었다).
# 처리 흐름: 저장된 문서·결과 사전 → strip_doc_pages / strip_result_pages → pages가 빈 새 사전(입력은 바꾸지 않음).
# 유지보수: 응답에서 제외할 큰 필드가 늘면 이 모듈만 고친다. 화면이 pages를 필요로 하면 별도 API(원문 보기)로 제공한다.


# [기능명세] strip_doc_pages
# 목적: 문서 레코드에서 페이지 전문을 뺀 얕은 사본 생성
# 입력: (doc: documents 문서 레코드 사전 — extraction 안에 pages가 있을 수 있음)
# 출력: extraction.pages가 []인 새 사전. extraction이 사전이 아니면 doc의 얕은 사본을 그대로 돌려줌
# 처리: 문서·extraction 단계마다 새 dict를 만들어 교체(입력과 저장 데이터는 변경하지 않음)
# 예외/실패: doc이 사전이 아니면 그대로 반환(None 등)
# 부수효과: 없음
def strip_doc_pages(doc):
    if not isinstance(doc, dict):
        return doc
    extraction = doc.get("extraction")
    if not isinstance(extraction, dict):
        return dict(doc)
    return {**doc, "extraction": {**extraction, "pages": []}}


# [기능명세] strip_result_pages
# 목적: 비교 결과 상세 응답에서 큰 페이지 전문을 뺀 사본 생성(기존 api.strip_pages와 같은 동작)
# 입력: (result: Store.result가 반환한 결과 사전)
# 출력: rows의 invoice·contract의 extraction.pages와 effective_invoice.pages를 빈 배열로 바꾼 새 결과 사전
# 처리: 결과·행 단계마다 새 dict를 만들어 교체. 사전이 아닌 값은 그대로 둠
# 예외/실패: rows가 없으면 빈 목록으로 처리
# 부수효과: 없음
def strip_result_pages(result):
    rows = []
    for row in result.get("rows") or []:
        row = dict(row)
        for key in ("invoice", "contract"):
            if isinstance(row.get(key), dict) and isinstance(row[key].get("extraction"), dict):
                row[key] = strip_doc_pages(row[key])
        if isinstance(row.get("effective_invoice"), dict):
            row["effective_invoice"] = {**row["effective_invoice"], "pages": []}
        rows.append(row)
    return {**result, "rows": rows}
