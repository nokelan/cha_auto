# [파일 기능명세]
# 로컬 세금계산서 대조 규칙. 사용자가 고른 PC 폴더의 세금계산서(PDF·PNG)를 읽어 상호를 뽑고, 웹 계약서 목록에서 같은 거래처 계약을
# 찾아 고른 뒤, 기존 비교 엔진(compare.compare)으로 판정한 결과 행을 만든다. 네트워크·DB·OCR·AI를 쓰지 않는 순수 함수 위주이며,
# 사이트 목록 수집·계약서 내려받기·저장은 service.Service.run_local_audit가 담당한다.
# 처리 흐름: check_folder(경로 검사) → scan_folder(파일 목록·판독·상호) → match_contracts(후보) → pick_contract(선택)
#           → audit_row(compare 판정·기대 금액·상태·설명으로 결과 행 구성) → summarize(상태별 건수·완료 문구).
# 결과 행 형식은 프런트(LocalAuditScreen)와 맞춘 계약이다(기획/로컬세금계산서_대조_구축계획.md).
# 유지보수: 함수·데이터 계약이 바뀌면 해당 기능명세와 tests/test_local_audit.py를 함께 갱신한다.

import calendar
import re
from datetime import date
from pathlib import Path

from .compare import compare, extract, norm
from .config import MAX_PDF_BYTES

# 한 번에 읽는 최대 파일 수와 파일 하나의 최대 크기(50MiB, config.MAX_PDF_BYTES와 같음).
MAX_FILES = 200
MAX_FILE_BYTES = MAX_PDF_BYTES
# 읽는 확장자(대소문자 무시). 하위 폴더는 읽지 않는다.
SUFFIXES = (".pdf", ".png")
# 결과 상태 표시 순서. counts와 완료 문구가 이 순서를 쓴다.
STATUSES = ("일치", "불일치", "확인 필요", "처리 실패", "계약서 없음")
# PNG는 판독하지 않는다(OCR 미사용 원칙). 이 문구가 invoice.error에 들어간다.
PNG_ERROR = "이미지 파일은 판독하지 않습니다(OCR 미사용)."
# 파일 크기 초과 오류 문구.
SIZE_ERROR = "파일이 50MiB를 넘어 읽지 않았습니다."
# 그룹웨어 첨부 파일명 규칙: 세금계산서_{상호}_YYYY-MM.pdf|png
NAME_RULE = re.compile(r"세금계산서_(.+)_(\d{4})-(\d{2})\.(pdf|png)", re.IGNORECASE)
# 기대 금액으로 뽑는 compare 검사 항목 key.
AMOUNT_KEYS = ("supply", "vat", "total")


# [기능명세] check_folder
# 목적: 세금계산서 폴더 경로가 이 PC의 실제 폴더인지 검사
# 입력: (folder: 경로 문자열 또는 Path)
# 출력: Path — 입력 경로(앞뒤 공백 제거, resolve하지 않음)
# 처리: 빈 값 거부 → UNC(\\ 또는 // 로 시작) 거부 → 절대경로가 아니면 거부(C:폴더 같은 드라이브 상대경로 포함) → 폴더가 아니면 거부
# 예외/실패: 위 조건을 어기면 한글 문구의 ValueError
# 부수효과: 파일 시스템 존재 여부 읽기만 수행
def check_folder(folder):
    text = str(folder or "").strip()
    if not text:
        raise ValueError("세금계산서 폴더 경로를 입력해 주세요.")
    if text.startswith(("\\\\", "//")):
        raise ValueError("네트워크 공유 폴더(UNC)는 지원하지 않습니다. PC의 폴더를 선택해 주세요.")
    path = Path(text)
    if not path.is_absolute():
        raise ValueError("PC의 절대 폴더 경로를 선택해 주세요. (예: D:\\세금계산서)")
    if not path.is_dir():
        raise ValueError(f"폴더를 찾을 수 없습니다: {text}")
    return path


# [기능명세] partner_from_name
# 목적: 파일명 규칙에서 상호를 보조로 추출
# 입력: (filename: 파일명 또는 경로 문자열)
# 출력: 상호 문자열 또는 None
# 처리: 경로의 마지막 이름이 NAME_RULE(세금계산서_{상호}_YYYY-MM.pdf|png, 확장자 대소문자 무시)에 전체 일치하면 상호(앞뒤 공백 제거)
# 예외/실패: 규칙에 맞지 않거나 상호가 비면 None
# 부수효과: 없음
def partner_from_name(filename):
    m = NAME_RULE.fullmatch(Path(str(filename)).name)
    return (m.group(1).strip() or None) if m else None


# [기능명세] scan_folder
# 목적: 폴더 바로 아래 세금계산서 파일 목록과 판독값·상호 구성
# 입력: (folder: 폴더 경로, extractor=compare.extract: extractor(path, "invoice") → {fields, error, ...},
#        warnings=None: 경고 문구를 덧붙일 리스트)
# 출력: [{file, path, type: "pdf"|"png", size, partner, partner_source: "pdf"|"filename"|None, invoice: {fields, error}}] — 파일명 순
# 처리: 바로 아래 파일 중 확장자 .pdf/.png(대소문자 무시)만 이름순 → MAX_FILES(200)개 초과면 앞 200개만 쓰고 warnings에 경고
#       → 파일마다 크기 확인: 50MiB 초과는 오류 행, PNG는 판독하지 않고 PNG_ERROR, PDF는 extractor 결과의 fields·error만 보관(pages 제외)
#       → partner는 판독 fields.partner 값, 없으면 partner_from_name(출처 "filename"), 둘 다 없으면 None
# 예외/실패: 폴더 열기 실패는 OSError 전파; 파일별 stat·판독 예외는 그 행의 invoice.error로 기록하고 계속
# 부수효과: 파일 읽기(PDF 판독)와 warnings 리스트 갱신; 파일·DB를 쓰지 않음
def scan_folder(folder, extractor=extract, warnings=None):
    files = sorted((p for p in Path(folder).iterdir() if p.suffix.lower() in SUFFIXES and p.is_file()), key=lambda p: p.name)
    if len(files) > MAX_FILES:
        if warnings is not None:
            warnings.append(f"PDF·PNG 파일이 {len(files)}개라 이름순 앞 {MAX_FILES}개만 읽었습니다.")
        files = files[:MAX_FILES]
    rows = []
    for p in files:
        kind = p.suffix.lower()[1:]
        size = None
        try:
            size = p.stat().st_size
            if size > MAX_FILE_BYTES:
                invoice = {"fields": {}, "error": SIZE_ERROR}
            elif kind == "png":
                invoice = {"fields": {}, "error": PNG_ERROR}
            else:
                parsed = extractor(p, "invoice")
                invoice = {"fields": parsed.get("fields") or {}, "error": parsed.get("error")}
        except Exception as e:
            # 판독 중 금액 정수화 실패 같은 예외도 행 오류로 남기고 다음 파일을 계속 읽는다.
            invoice = {"fields": {}, "error": f"파일 판독 실패: {type(e).__name__}"}
        partner = (invoice["fields"].get("partner") or {}).get("value")
        source = "pdf" if partner else None
        if not partner:
            partner = partner_from_name(p.name)
            source = "filename" if partner else None
        rows.append({"file": p.name, "path": str(p), "type": kind, "size": size, "partner": partner,
                     "partner_source": source, "invoice": invoice})
    return rows


# [기능명세] match_contracts
# 목적: 세금계산서 상호와 같은 거래처의 웹 계약 후보 찾기
# 입력: (partner: 상호 문자열 또는 None, contracts: 사이트 계약 행 목록 [{id, kind, partner, ...}])
# 출력: 후보 계약 행 리스트(입력 목록 순서 유지, 행 사전은 원본 참조)
# 처리: norm(상호)와 norm(계약 거래처)가 같거나 한쪽이 다른 쪽에 포함되면 후보. 정규화 결과가 빈 문자열이면 비교하지 않음
# 예외/실패: partner가 None·빈 값이면 []
# 부수효과: 없음
def match_contracts(partner, contracts):
    key = norm(partner) if partner else ""
    if not key:
        return []
    out = []
    for c in contracts:
        other = norm(c.get("partner") or "")
        if other and (other == key or other in key or key in other):
            out.append(c)
    return out


# [기능명세] _doc_value
# 목적: 계약 URL의 내려받은 문서에서 판독 필드 값 조회
# 입력: (docs_by_url: {url: 문서 레코드({extraction:{fields}}) 또는 추출 사전({fields})}, contract: 계약 행, key: 필드 이름)
# 출력: 필드 value 또는 None
# 처리: contract.file.url로 문서를 찾고 extraction(없으면 문서 자체)의 fields[key].value를 읽음
# 예외/실패: 파일·문서·필드가 없으면 None
# 부수효과: 없음
# 통일하지 않은 이유: 문서 레코드와 추출 사전을 모두 받고 fields·값이 None이어도 견디는 반면 compare.val은 그렇지 않아 의미가 다르다.
def _doc_value(docs_by_url, contract, key):
    url = (contract.get("file") or {}).get("url")
    doc = docs_by_url.get(url) if url else None
    if not doc:
        return None
    ext = doc.get("extraction", doc)
    return ((ext.get("fields") or {}).get(key) or {}).get("value")


# [기능명세] pick_contract
# 목적: 후보 계약 중 대조할 계약 한 건 고르기
# 입력: (candidates: match_contracts 결과, invoice_fields: 세금계산서 판독 fields 사전,
#        docs_by_url: {계약서 URL: 내려받은 문서 레코드 또는 추출 사전} — 내려받지 못한 계약은 키가 없음)
# 출력: (chosen: 계약 행 또는 None, reason: 한 줄 설명 문자열)
# 처리: 1) 지출 계약이 있으면 지출만, 없으면 전체(수입)를 대상으로 둠
#       2) 여럿이면 계약서 PDF 사업자번호 == 세금계산서 사업자번호인 것만 남김(남는 것이 없으면 그대로)
#       3) 그래도 여럿이면 청구월(month 'YYYY-MM') 전체가 계약서 시작~종료일 안인 것만 남김(남는 것이 없으면 그대로)
#       4) 1건이면 선택, 아니면 None과 "후보 N건, 확인 필요". 수입 계약을 고르면 reason 앞에 "수입 계약입니다."를 붙여
#          호출자가 상태를 '확인 필요'로 만들 수 있게 함
# 예외/실패: 후보 0건은 (None, 안내 문구); 판독값이 없으면 해당 좁히기 단계를 건너뜀
# 부수효과: 없음
def pick_contract(candidates, invoice_fields, docs_by_url):
    if not candidates:
        return None, "웹 계약서 목록에 같은 거래처 계약이 없습니다."
    spend = [c for c in candidates if c.get("kind") == "지출"]
    income = not spend
    pool = spend or list(candidates)
    first = len(pool)
    label = "수입" if income else "지출"
    reason = f"거래처가 같은 {label} 계약 1건과 대조했습니다."
    fields = invoice_fields or {}
    biz = (fields.get("biz") or {}).get("value")
    if len(pool) > 1 and biz:
        same = [c for c in pool if _doc_value(docs_by_url, c, "biz") == biz]
        if same:
            pool = same
            reason = f"{label} 후보 {first}건 중 사업자번호가 같은 계약과 대조했습니다."
    month = (fields.get("month") or {}).get("value")
    if len(pool) > 1 and month:
        y, m = map(int, month.split("-"))
        lo, hi = date(y, m, 1).isoformat(), date(y, m, calendar.monthrange(y, m)[1]).isoformat()
        inside = [c for c in pool if (_doc_value(docs_by_url, c, "start") or "9999") <= lo and hi <= (_doc_value(docs_by_url, c, "end") or "")]
        if inside:
            pool = inside
            reason = f"{label} 후보 {first}건 중 청구월이 계약기간 안에 있는 계약과 대조했습니다."
    if len(pool) != 1:
        return None, f"후보 {len(pool)}건, 확인 필요" + (" (수입 계약만 있음)" if income else "")
    if income:
        reason = "수입 계약입니다. 매입 세금계산서와 맞는 계약인지 확인하세요. " + reason
    return pool[0], reason


# [기능명세] expected_from_checks
# 목적: compare 검사 목록에서 공급가액·세액·합계 기대값 뽑기
# 입력: (checks: compare 결과 checks)
# 출력: {supply, vat, total} (없는 항목은 None) 또는 셋 다 None이면 None
# 처리: key가 supply/vat/total인 검사의 expected를 모음
# 예외/실패: 없음
# 부수효과: 없음
def expected_from_checks(checks):
    out = {k: None for k in AMOUNT_KEYS}
    for c in checks or []:
        if c.get("key") in out:
            out[c["key"]] = c.get("expected")
    return out if any(v is not None for v in out.values()) else None


# [기능명세] expected_amounts
# 목적: 세금계산서 판독값 없이 계약서만으로 기대 금액 계산(PNG·판독 오류 행 표시용)
# 입력: (contract_extraction: 계약서 추출 사전 {fields, error})
# 출력: {supply, vat, total} 또는 None
# 처리: 빈 세금계산서({"fields": {}, "error": None})와 compare를 돌려 같은 금액 규칙(월/총액·부가세 별도/포함)을 재사용
#       → expected_from_checks. 총액·분할 지급 계약은 청구 비율이 없어 None
# 예외/실패: 계약서 오류가 있으면 compare가 checks를 비우므로 None
# 부수효과: 없음
def expected_amounts(contract_extraction):
    return expected_from_checks(compare({"fields": {}, "error": None}, contract_extraction or {"fields": {}})["checks"])


# [기능명세] contract_brief
# 목적: 결과 행에 넣을 계약 요약 만들기
# 입력: (contract: 사이트 계약 행)
# 출력: {id, kind, partner, title, period, amount_text}
# 처리: 각 키를 get으로 복사(없으면 None)
# 예외/실패: 없음
# 부수효과: 없음
def contract_brief(contract):
    return {k: contract.get(k) for k in ("id", "kind", "partner", "title", "period", "amount_text")}


# [기능명세] audit_row
# 목적: 세금계산서 한 건의 대조 결과 행 구성(프런트와 맞춘 형식)
# 입력: (scan: scan_folder 행, candidates: 후보 계약 행 목록, chosen: 고른 계약 행|None, reason: pick_contract 설명,
#        contract_doc=None: 고른 계약의 문서 레코드(extraction.pages 비움, available 포함)|None, failure=None: 처리 실패 사유 문자열)
# 출력: {file, type, size, partner, partner_source, invoice:{fields, error}, contract|None, contract_doc|None,
#        candidates:[{id, kind, partner, title}], expected:{supply, vat, total}|None, status, checks, note}
# 처리: failure가 있으면 '처리 실패' → 상호 없음은 '확인 필요' → 후보 0건 '계약서 없음' → 선택 못 함 '확인 필요'(checks 없음)
#       → 선택했으면 compare(세금계산서 판독, 계약서 추출) 결과의 status·checks 사용, expected는 checks 또는 expected_amounts
#       → PNG는 판정을 '확인 필요'로 고정, 수입 계약은 '처리 실패'가 아니면 '확인 필요'로 낮춤
#       → note는 선택 사유에 불일치·확인 필요 항목 이름 또는 문서 오류를 덧붙인 한 줄
# 예외/실패: 계약서 문서가 없는데 계약을 골랐으면 '처리 실패'('계약서 판독값이 없습니다.')
# 부수효과: 없음(입력 사전을 바꾸지 않음)
def audit_row(scan, candidates, chosen, reason, contract_doc=None, failure=None):
    row = {"file": scan["file"], "type": scan["type"], "size": scan["size"], "partner": scan["partner"],
           "partner_source": scan["partner_source"], "invoice": scan["invoice"],
           "contract": contract_brief(chosen) if chosen else None, "contract_doc": contract_doc if chosen else None,
           "candidates": [{k: c.get(k) for k in ("id", "kind", "partner", "title")} for c in candidates],
           "expected": None, "status": "확인 필요", "checks": [], "note": reason}
    if chosen and contract_doc:
        row["expected"] = expected_amounts(contract_doc.get("extraction"))
    if failure:
        row.update(status="처리 실패", note=failure)
        return row
    if not scan["partner"]:
        row["note"] = "세금계산서에서 상호를 찾지 못했습니다. 파일을 열어 거래처를 확인하세요."
        return row
    if not candidates:
        row.update(status="계약서 없음", note=f"웹 계약서 목록에 '{scan['partner']}' 거래처 계약이 없습니다.")
        return row
    if not chosen:
        return row
    if not contract_doc:
        row.update(status="처리 실패", note="계약서 판독값이 없습니다.")
        return row
    invoice = {"fields": scan["invoice"].get("fields") or {}, "error": scan["invoice"].get("error")}
    result = compare(invoice, contract_doc.get("extraction") or {"fields": {}})
    status, notes = result["status"], [reason]
    row["checks"] = result["checks"]
    row["expected"] = expected_from_checks(result["checks"]) or row["expected"]
    if scan["type"] == "png":
        status = "확인 필요"
        notes.append("이미지 파일이라 금액을 읽지 않았습니다. 계약 금액과 직접 비교하세요.")
    elif result.get("error"):
        notes.append(result["error"])
    else:
        for label in ("불일치", "확인 필요"):
            names = [c["label"] for c in result["checks"] if c["status"] == label]
            if names:
                notes.append(f"{label}: {', '.join(names)}")
    if chosen.get("kind") != "지출" and status != "처리 실패":
        status = "확인 필요"
    row.update(status=status, note=" · ".join(notes))
    return row


# [기능명세] summarize
# 목적: 결과 행의 상태별 건수와 작업 완료 문구 만들기
# 입력: (rows: audit_row 결과 목록)
# 출력: (counts: {상태: 건수} — STATUSES 다섯 상태를 모두 포함, message: 완료 문구)
# 처리: 상태별 개수 집계 → "세금계산서 N건 대조: 일치 a · 불일치 b · 확인 필요 c · 계약서 없음 d"(처리 실패는 1건 이상일 때만 넣음)
# 예외/실패: STATUSES 밖의 상태도 counts에 더함
# 부수효과: 없음
def summarize(rows):
    counts = {s: 0 for s in STATUSES}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    parts = [f"{s} {n}" for s, n in counts.items() if n or s != "처리 실패"]
    return counts, f"세금계산서 {len(rows)}건 대조: " + " · ".join(parts)
