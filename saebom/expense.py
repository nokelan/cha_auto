# [파일 기능명세]
# 지출결의서의 초안·입력 검증·작성본 파싱·검토를 담당하는 순수 규칙 모듈.
# PDF 저장값과 화면에서 읽은 문자열만 사용하며 AI·OCR·네트워크·DB 쓰기를 하지 않는다.
import re
from datetime import date, timedelta

from . import config
from .compare import compare, norm, val
from .rules import is_amount, is_month


# [기능명세] completed_record
# 목적: 같은 달 중복 상신 경고에 쓸 '품의완료 기록'을 마지막 상신 정보에서 골라낸다.
# 입력: approval — contract_status의 data 사전 또는 None.
# 출력: 전 항목 일치(review 비어 있지 않고 모두 ok)면 approval 자신, 아니면 approval["prior_approval"](새 상신 시작 때 보존한 이전 완료 기록), 둘 다 아니면 None.
# 처리: 순수 판단만 한다. 예외/실패: 없음. 부수효과: 없음.
def completed_record(approval):
    for rec in (approval, (approval or {}).get("prior_approval")):
        if rec and rec.get("review") and all(c.get("ok") for c in rec["review"]):
            return rec
    return None


# [기능명세] draft
# 목적: 가져온 지출 계약의 확인 창 초기값을 만든다.
# 입력: 문서 doc, 계약 row, 마지막 approval, 시험용 기준일 today.
# 출력: 적격 여부·제목·청구월·금액·첨부 후보·경고 사전.
# 처리: 직전 달을 계약기간 안으로 맞추고 compare 기대금액을 재사용한다.
# 예외/실패: 판독되지 않은 금액은 0으로 대체하고 경고한다. 부수효과: 없음.
def draft(doc, row, approval=None, today=None):
    parsed = doc.get("extraction") or {}
    start, end = val(parsed, "start"), val(parsed, "end")
    today = today or date.today()
    month = (today.replace(day=1) - timedelta(days=1)).isoformat()[:7]
    warnings = []
    for boundary, lower in ((start, True), (end, False)):
        try:
            bound = date.fromisoformat(boundary).isoformat()[:7]
        except (ValueError, TypeError):
            warnings.append("계약기간을 판독하지 못했습니다. 청구월을 확인하세요.")
            continue
        month = max(month, bound) if lower else min(month, bound)
    expected = {c["key"]: c.get("expected") for c in compare({"fields": {}}, parsed)["checks"]}
    supply, vat, total = (expected.get(k) for k in ("supply", "vat", "total"))
    if any(type(v) is not int for v in (supply, vat, total)):
        supply = vat = total = 0
        warnings.append("계약 금액·부가세 조건을 판독하지 못했습니다. 금액을 직접 입력하세요.")
    if val(parsed, "basis") == "total":
        warnings.append("총액 계약입니다. 이번 청구분의 공급가액·세액·합계를 직접 확인하고 고치세요.")
    if parsed.get("error"):
        warnings.append("계약서 판독 오류가 있습니다. 원문을 확인하세요.")
    done = completed_record(approval)
    if done and done.get("month") == month:
        warnings.append("같은 달에 품의완료한 기록이 있습니다. 중복 상신 여부를 확인하세요.")
    partner = row.get("partner") or val(parsed, "partner") or ""
    service = (row.get("title") or "").replace("계약서", "").strip()
    title = f"{config.EXPENSE_PREFIX} {partner} {service} 지출의 건 ({month[2:4]}.{month[5:7]}월)"
    invoice_partner = re.sub(r"\(\s*[주유]\s*\)|㈜|주식회사|유한회사", "", partner).strip()
    attachments = [name for name in ((row.get("file") or {}).get("name"), f"세금계산서_{invoice_partner}_{month}.pdf") if name]
    eligible = row.get("kind") == "지출"
    return {"contract_id": row["id"], "eligible": eligible, "reason": "" if eligible else "지출 계약만 지출결의서를 상신할 수 있습니다.",
            "title": title, "month": month, "supply": supply, "vat": vat, "total": total, "attachments": attachments,
            "note": "", "warnings": list(dict.fromkeys(warnings)), "approval": approval, "partner": partner,
            "period_start": start, "period_end": end}


# [기능명세] validate
# 목적: 확인 창에서 받은 상신값을 검증·정규화한다.
# 입력: 값 사전. 출력: 정규화된 새 사전.
# 처리: 제목·월·정수 금액·검산·첨부·특이사항 범위를 확인한다(월 달력 검사와 금액 범위 판단은 rules.is_month·is_amount 공용).
# 예외/실패: 잘못된 값은 한글 ValueError. 부수효과: 없음.
def validate(values):
    data = dict(values)
    title, month = data.get("title"), data.get("month")
    if not isinstance(title, str) or not title.strip() or len(title) > 500:
        raise ValueError("제목을 1~500자로 입력해 주세요.")
    if not isinstance(month, str) or not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("청구월을 YYYY-MM 형식으로 입력해 주세요.")
    if not is_month(month):
        raise ValueError("청구월을 올바른 YYYY-MM 형식으로 입력해 주세요.")
    if not all(is_amount(data.get(k)) for k in ("supply", "vat", "total")):
        raise ValueError("금액은 0~1조 원 범위의 정수로 입력해 주세요.")
    if data["supply"] <= 0 or data["total"] <= 0:
        raise ValueError("공급가액과 합계는 0보다 커야 합니다.")
    if data["supply"] + data["vat"] != data["total"]:
        raise ValueError("공급가액 + 세액이 합계와 다릅니다.")
    atts = data.get("attachments", [])
    if not isinstance(atts, list) or len(atts) > 100 or any(not isinstance(x, str) or not x or len(x) > 500 for x in atts):
        raise ValueError("첨부 파일 이름을 올바르게 입력해 주세요.")
    note = data.get("note", "")
    if not isinstance(note, str) or len(note) > 2000:
        raise ValueError("특이사항을 2000자 이내로 입력해 주세요.")
    return {**data, "title": title.strip(), "attachments": list(dict.fromkeys(atts)), "note": note.strip()}


# [기능명세] parse_document
# 목적: 상신 후 화면 문자열에서 검토용 값을 파싱한다.
# 입력: title, amount, content 등 DOM 원문을 담은 사전.
# 출력: 원문과 파싱한 금액·업체·사용기간 사전.
# 처리: 항목별 정규식으로 읽고 금액 칸은 전체 형식을 검사한다. 업체명 뒤 괄호 사업자번호만 제거하며,
#       실제 사이트의 '26년 09월'과 기존 '26.09' 월 표기를 읽는다. 법인표시 괄호는 유지한다.
# 예외/실패: 누락·형식 변경은 None으로 둔다. 0으로 추정하지 않는다. 부수효과: 없음.
def parse_document(document):
    content = document.get("content") or ""
    amounts = re.search(r"금\s*액\s*[:：]\s*([\d,]+)\s*원\s*\(\s*공급가액\s*([\d,]+)\s*원\s*/\s*세액\s*([\d,]+)\s*원\s*\)", content)
    amount = re.fullmatch(r"\s*KRW\s+([\d,]+)\s*", document.get("amount") or "")
    partner = re.search(r"업\s*체\s*명\s*[:：]\s*([^\r\n]+)", content)
    month = re.search(r"사용기간\s*[:：]\s*(\d{4}|\d{2})\s*(?:년\s*|\.)\s*(\d{2})(?!\d)\s*(?:월)?", content)
    partner_name = re.sub(r"\s*\(\s*\d{3}-\d{2}-\d{5}\s*\)\s*$", "", partner.group(1)).strip() if partner else None
    return {**document, "document_total": int(amount.group(1).replace(",", "")) if amount else None,
            "body_total": int(amounts.group(1).replace(",", "")) if amounts else None,
            "body_supply": int(amounts.group(2).replace(",", "")) if amounts else None,
            "body_vat": int(amounts.group(3).replace(",", "")) if amounts else None,
            "partner": partner_name,
            "month": (("20" + month.group(1)) if len(month.group(1)) == 2 else month.group(1)) + "-" + month.group(2) if month else None}


# [기능명세] review
# 목적: 입력값과 작성본을 항목별로 보수적으로 대조한다.
# 입력: 검증된 입력값 values와 DOM 원문 document.
# 출력: [{label,ok,actual,expected}] 검토 목록.
# 처리: 금액 칸·본문 세 금액·검산·업체·월·제목을 모두 확인한다.
# 예외/실패: 파싱 누락은 반드시 ok=False. 부수효과: 없음.
def review(values, document):
    parsed = parse_document(document)
    checks = [("작성본 금액", parsed["document_total"], values["total"]),
              ("본문 합계", parsed["body_total"], values["total"]),
              ("본문 공급가액", parsed["body_supply"], values["supply"]),
              ("본문 세액", parsed["body_vat"], values["vat"]),
              ("공급가액 + 세액 = 합계", values["supply"] + values["vat"], values["total"]),
              ("업체명", parsed["partner"], values["partner"]),
              ("사용기간", parsed["month"], values["month"]),
              ("제목", document.get("title"), values["title"])]
    return [{"label": label, "actual": actual, "expected": expected,
             "ok": actual is not None and expected is not None and (norm(actual) == norm(expected) if label == "업체명" and actual and expected else actual == expected)}
            for label, actual, expected in checks]
