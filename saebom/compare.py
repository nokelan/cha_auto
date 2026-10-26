# [파일 기능명세]
# PDF 텍스트 판독과 규칙 비교 엔진. 입력은 현재 양식의 텍스트 PDF 또는 추출 사전이며 출력은 값·근거·페이지·판정이다. OCR·AI·네트워크를 사용하지 않는다.
# 처리 흐름: extract(진입점: 페이지 텍스트 읽기·검사) → extract_invoice / extract_contract(양식별 규칙) → compare(항목별 check와 최종 판정).
# 페이지 제한(MAX_PDF_PAGES)과 자사 사업자번호는 config.OWN_BIZ를 호출 시점에 읽는다(import 시점에 복사하지 않음).
# 유지보수: 함수·데이터 계약이 바뀌면 해당 기능명세와 실제 회귀 검사를 함께 갱신한다.

"""Conservative rules for the current groupware templates. No OCR, AI or network."""
# 한글 설명: 현재 그룹웨어 양식에 맞춘 보수적 규칙 판독·비교 모듈(OCR·AI·네트워크 미사용).
import calendar
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pdfplumber

from . import config
from .config import MAX_PDF_PAGES

# 양식 토큰: 금액은 숫자로 시작하는 쉼표 포함 정수(쉼표만 있는 값은 매칭하지 않음), 사업자번호는 3-2-5자리, 날짜는 한글 년·월·일과 선택 대괄호를 허용한다.
MONEY = r"(\d[\d,]*)"
BIZ = r"\d{3}-\d{2}-\d{5}"
DATE = r"\[?(\d{4})\]?년\s*\[?(\d{1,2})\]?월\s*\[?(\d{1,2})\]?\s*일"


# [기능명세] norm
# 목적: 업체명 비교용 문자열 정규화
# 입력: (value)
# 출력: 법인 표기·공백·괄호를 정리한 소문자 문자열
# 처리: 주식회사/(주)/㈜ 제거 후 정규표현식과 casefold 적용
# 예외/실패: 문자열 입력이 전제; None 처리는 호출자가 수행
# 부수효과: 없음; 입력 문자열 원본은 변경하지 않음
def norm(value):
    return re.sub(r"[\s()㈜]", "", value.replace("주식회사", "").replace("(주)", "").replace("㈜", "")).casefold()


# [기능명세] integer
# 목적: 쉼표가 포함된 금액 문자열을 정수화
# 입력: (s)
# 출력: int
# 처리: 쉼표 제거 후 int 변환
# 예외/실패: 숫자로 해석되지 않으면 ValueError
# 부수효과: 없음
def integer(s):
    return int(s.replace(",", ""))


# [기능명세] extract
# 목적: PDF를 페이지 텍스트로 읽고 양식별 항목 추출(진입점)
# 입력: (path: Path, kind: str — 'invoice'이면 계산서, 그 외는 계약서)
# 출력: fields/pages/error 사전; 필드에는 value/quote/page/method 포함
# 처리: config.MAX_PDF_PAGES(100) 페이지 제한→페이지 텍스트 결합→30자 검사→extract_invoice 또는 extract_contract 호출
# 예외/실패: 파일 열기·판독 실패는 error에 기록; 누락 필드는 생략
# 부수효과: PDF 읽기만 수행; 파일·DB 수정과 네트워크 접속 없음
def extract(path: Path, kind: str):
    try:
        with pdfplumber.open(path) as pdf:
            if len(pdf.pages) > MAX_PDF_PAGES:
                return {"error": f"{MAX_PDF_PAGES}페이지를 초과해 자동 판독하지 않았습니다.", "fields": {}, "pages": []}
            # 1단계: PDF.js 화면 렌더링과 별개로 각 페이지의 텍스트를 읽는다. OCR·좌표 영역 분석은 하지 않는다.
            pages = [{"page": n + 1, "text": p.extract_text() or ""} for n, p in enumerate(pdf.pages)]
    except Exception as e:
        return {"error": f"PDF 열기 실패 (손상 또는 암호화): {type(e).__name__}", "fields": {}, "pages": []}
    text = "\n".join(p["text"] for p in pages)
    fields = {}

    # [기능명세] extract.put
    # 목적: 추출 항목에 값과 근거를 함께 기록
    # 입력: (key, value, match)
    # 출력: None
    # 처리: 매칭 원문을 정리하고 해당 원문이 포함된 첫 페이지를 찾아 fields에 저장
    # 예외/실패: value가 None이거나 매칭이 없으면 기록하지 않음; 페이지를 못 찾으면 None
    # 부수효과: 부모 extract의 fields 사전 갱신
    def put(key, value, match):
        if value is None or not match:
            return
        quote = match.group(0).strip()
        page = next((p["page"] for p in pages if quote in p["text"]), None)
        fields[key] = {"value": value, "quote": quote, "page": page, "method": "PDF 텍스트·양식 규칙"}

    if len(re.sub(r"\s", "", text)) < 30:
        return {"error": "텍스트 추출 불가: 이미지 PDF는 지원하지 않습니다. OCR·AI 미사용.", "fields": {}, "pages": pages}
    if kind == "invoice":
        extract_invoice(text, put)
    else:
        extract_contract(text, put)
    return {"fields": fields, "pages": pages, "error": None}


# [기능명세] extract_invoice
# 목적: 세금계산서 텍스트에서 항목 추출
# 입력: (text: 전체 페이지 텍스트, put: put(key, value, match) 기록 함수)
# 출력: None(결과는 put으로 기록)
# 처리: 최초 매칭 사용 — 사업자번호(첫 번호=공급자), 상호, 작성일자·공급가액·세액(헤더 다음 줄), 합계, 청구 월(1~12월만), 차수, 계약금액 비율
# 예외/실패: 매칭이 없으면 해당 항목 생략; 금액 정수화 실패는 ValueError 전파
# 부수효과: put을 통해 호출자의 fields 갱신
def extract_invoice(text, put):
    # 2단계: 계산서는 최초 매칭을 사용한다. 공급자 번호와 헤더 다음 줄 배치는 현재 양식에 의존한다.
    m = re.search(BIZ, text)
    put("biz", m.group(0) if m else None, m)
    m = re.search(r"상호\*?\s+(.+?)\s+성명", text)
    put("partner", m.group(1).strip() if m else None, m)
    m = re.search(r"작성일자\*?\s+공급가액\*?\s+세액\*?\s*\n(\d{4}-\d{2}-\d{2})\s+" + MONEY + r"\s+" + MONEY, text)
    if m:
        put("issued", m.group(1), m)
        put("supply", integer(m.group(2)), m)
        put("vat", integer(m.group(3)), m)
    m = re.search(r"합계\s+현금[^\n]*\n(?:[^\n]*청구[^\n]*\n)?\s*" + MONEY, text)
    if m:
        put("total", integer(m.group(1)), m)
    m = re.search(r"(\d{4})년\s*(\d{1,2})월분", text)
    if m and 1 <= int(m.group(2)) <= 12:
        put("month", f"{m.group(1)}-{int(m.group(2)):02d}", m)
    m = re.search(r"(\d+)차분", text)
    put("installment", int(m.group(1)) if m else None, m)
    m = re.search(r"계약금액[^\n]*?(\d{1,3})%", text)
    put("percent", int(m.group(1)) if m else None, m)


# [기능명세] extract_contract
# 목적: 계약서 텍스트에서 항목 추출
# 입력: (text: 전체 페이지 텍스트, put: put(key, value, match) 기록 함수)
# 출력: None(결과는 put으로 기록)
# 처리: 을의 업체명·사업자번호(자사 config.OWN_BIZ가 먼저 나오면 마지막 번호)·계약기간·월/총 금액과 부가세 표현·분할 비율·지급 기한·지급 조건 검색
# 예외/실패: 매칭이 없거나 날짜가 잘못되면 해당 항목 생략; 금액 정수화 실패는 ValueError 전파
# 부수효과: put을 통해 호출자의 fields 갱신
def extract_contract(text, put):
    # 계약 분기: 을의 업체명·사업자번호·기간·월/총 금액·부가세 표현을 각각 찾는다.
    m = re.search(r'["“]을["”]\s*:\s*([^\n]+)', text)
    put("partner", m.group(1).strip() if m else None, m)
    # Business numbers occur in the business information clause or signature table.
    m = re.search(r"사업자등록번호(?:는|\s*[:：])?\s*(" + BIZ + ")", text)
    if m:
        numbers = re.findall(BIZ, text[m.start():m.end() + 35])
        # Legacy contracts list 갑 (our company) before 을 (vendor).
        val = numbers[-1] if len(numbers) > 1 and numbers[0] == config.OWN_BIZ else m.group(1)
        put("biz", val, re.search(re.escape(val), text))
    m = re.search(r"계약기간[^\n]*?" + DATE + r"부터\s*" + DATE + r"\s*까지", text)
    if m:
        try:
            put("start", date(*map(int, m.groups()[:3])).isoformat(), m)
            put("end", date(*map(int, m.groups()[3:])).isoformat(), m)
        except ValueError:
            pass
    m = re.search(r"(월|총)\s*금\s*" + MONEY + r"원\s*\((부가가치세\s*(?:별도|포함))\)", text)
    if m:
        put("basis", "monthly" if m.group(1) == "월" else "total", m)
        put("amount", integer(m.group(2)), m)
        put("vat_mode", "included" if "포함" in m.group(3) else "excluded", m)
    # 비율 수집은 같은 숫자를 중복 제거한다. 동일 비율 반복 차수와 범용 기성 청구의 식별 알고리즘은 아니다.
    # Only explicitly enumerated ratios are eligible for automatic installment checks.
    ratios = []
    for m in re.finditer(r"(?:1차|2차|선급|잔금|검수|계약금)[^\n]{0,100}?([1-9]\d?|100)%", text):
        p = int(m.group(1))
        if p not in ratios:
            ratios.append(p)
    if ratios:
        m = re.search(r"[^\n]*(?:70%|30%|\d+%)[^\n]*", text)
        put("ratios", ratios, m)
    m = re.search(r"[^\n]*(?:익월말|다음 달 말일)[^\n]*", text)
    if m:
        put("payment", "발행·청구 다음 달 말일", m)
    m = re.search(r"[^\n]*(?:검수|설치)[^\n]*지급[^\n]*", text)
    if m:
        put("condition", m.group(0).strip(), m)


# [기능명세] val
# 목적: 추출 사전의 특정 필드 값 조회
# 입력: (doc, key)
# 출력: 필드 value 또는 None
# 처리: fields→key→value 순서로 안전하게 조회
# 예외/실패: 필드 부재는 예외 대신 None
# 부수효과: 없음
def val(doc, key):
    return doc.get("fields", {}).get(key, {}).get("value")


# [기능명세] compare
# 목적: 계산서와 계약의 값을 보수적으로 대조
# 입력: (invoice, contract, group=None)
# 출력: status/checks/error 사전
# 처리: 문서 오류→식별 정보→합계·10% 세액→계약 금액→기간·분할·지급 조건 검사
# 예외/실패: 값·기준 누락은 확인 필요; 처리 오류는 처리 실패; 불일치가 확인 필요보다 우선
# 부수효과: 입력 추출 사전·파일·DB를 수정하지 않음
def compare(invoice, contract, group=None):
    if invoice.get("error") or contract.get("error"):
        error = invoice.get("error") or contract.get("error")
        status = "확인 필요" if "텍스트 추출 불가" in error else "처리 실패"
        return {"status": status, "checks": [], "error": error}
    checks = []

    # [기능명세] compare.check
    # 목적: 항목 판정과 양쪽 원문 근거를 결과에 추가
    # 입력: (key, label, actual, expected, *, unknown=None, note='', sources=None, status=None)
    # 출력: None
    # 처리: status가 주어지면 그 판정을 그대로 쓰고, 없으면 실제값·기준값·unknown에 따라 판정. 두 값이 int이면 차이 계산. note는 unknown이 우선
    # 예외/실패: status 미지정 시 어느 값이 None이거나 unknown이 있으면 확인 필요
    # 부수효과: 부모 compare의 checks 목록에 항목 추가
    def check(key, label, actual, expected, *, unknown=None, note="", sources=None, status=None):
        if status is None:
            status = "확인 필요" if unknown or actual is None or expected is None else "일치" if actual == expected else "불일치"
        checks.append({"key": key, "label": label, "actual": actual, "expected": expected, "status": status,
                       "difference": actual - expected if type(actual) is int and type(expected) is int else None,
                       "note": unknown or note, "invoice_source": invoice.get("fields", {}).get((sources or (key, key))[0]),
                       "contract_source": contract.get("fields", {}).get((sources or (key, key))[1])})

    # a/c 람다: invoice/contract에서 지정 키의 value를 읽는 순수 조회 함수. 누락값은 None이다.
    a, c = lambda k: val(invoice, k), lambda k: val(contract, k)
    check("biz", "사업자등록번호", a("biz"), c("biz"))
    check("partner", "업체명", norm(a("partner")) if a("partner") else None, norm(c("partner")) if c("partner") else None)
    if all(a(k) is not None for k in ("supply", "vat", "total")):
        check("arithmetic", "계산서 합계 검산", a("total"), a("supply") + a("vat"), sources=("total", "amount"))
        check("vat_check", "계산서 세액 10% 검산", a("vat"), int((Decimal(a("supply")) / 10).quantize(Decimal(1), rounding=ROUND_HALF_UP)), sources=("vat", "vat_mode"), note="현재 양식의 일반과세 10% 기준")
    else:
        check("arithmetic", "계산서 금액 추출", None, None, unknown="공급가액·세액·합계 중 누락된 항목이 있습니다.")
    amount, basis, mode = c("amount"), c("basis"), c("vat_mode")
    ratio = None
    if basis == "total":
        ratio = a("percent")
        allowed = c("ratios") or []
        check("installment", "분할 지급 비율", ratio, ratio if ratio in allowed else None,
              unknown=None if ratio in allowed else "계약서에 명시된 분할 비율과 청구 비율 확인이 필요합니다.", sources=("percent", "ratios"))
        if ratio not in allowed:
            amount = None
        elif amount is not None:
            amount = int(Decimal(amount) * Decimal(ratio) / 100)
    # 세액은 Decimal+ROUND_HALF_UP으로 원 단위 사사오입한다. 총액×비율의 직전 int 변환은 절삭이다.
    if amount is not None and mode in ("included", "excluded"):
        expected_supply = int((Decimal(amount) / Decimal("1.1")).quantize(Decimal(1), rounding=ROUND_HALF_UP)) if mode == "included" else amount
        expected_vat = amount - expected_supply if mode == "included" else int((Decimal(amount) / 10).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        check("supply", "공급가액", a("supply"), expected_supply, sources=("supply", "amount"))
        check("vat", "부가세", a("vat"), expected_vat, sources=("vat", "vat_mode"))
        check("total", "합계액", a("total"), expected_supply + expected_vat, sources=("total", "amount"))
    else:
        check("total", "계약 금액 대조", a("total"), None, unknown="계약 금액·부가세 조건·지급 기준을 확정할 수 없습니다.", sources=("total", "amount"))
    start, end, month = c("start"), c("end"), a("month")
    if basis == "total":
        # No service month is assumed from the issue date of a milestone invoice.
        check("period", "분할 지급 조건", a("installment"), None, unknown="납품·설치·검수 등 실제 이행 여부는 문서만으로 확정하지 않습니다.", sources=("installment", "condition"))
        # 누적은 선택된 청구 비율 합계와 공급가액 합계만 검사한다. 실제 검수·지급 사실은 확정하지 않는다.
        if group:
            percents = [val(x, "percent") for x in group]
            sums = [val(x, "supply") for x in group]
            duplicate = len(percents) != len(set(percents))
            check("group", "선택 청구분 누적", sum(sums) if all(x is not None for x in sums) else None, c("amount"),
                  unknown="차수가 중복되거나 전체 청구분이 선택되지 않았습니다." if duplicate or any(p is None for p in percents) or sum(p or 0 for p in percents) != 100 else None,
                  sources=("supply", "amount"))
    elif month and start and end:
        y, m = map(int, month.split("-"))
        lo, hi = date(y, m, 1).isoformat(), date(y, m, calendar.monthrange(y, m)[1]).isoformat()
        # 기간 판정은 문자열 동일 비교가 아니라 청구 월 전체가 계약기간 안에 있는지로 정한다.
        check("period", "청구기간 / 계약기간", f"{lo} ~ {hi}", f"{start} ~ {end}", sources=("month", "start"),
              status="일치" if start <= lo and hi <= end else "불일치",
              note="청구 월 전체가 명시된 계약기간 안에 있는지 확인. 갱신 계약은 별도로 확인하세요.")
    else:
        check("period", "청구기간 / 계약기간", month, f"{start or '?'} ~ {end or '?'}", unknown="청구 대상 월 또는 계약기간을 추출하지 못했습니다. 발행일로 대신하지 않습니다.", sources=("month", "start"))
    if basis == "monthly":
        check("payment", "지급 조건", c("payment"), "발행·청구 다음 달 말일", sources=("issued", "payment"), note="지급 기한 규칙 확인이며 실제 지급 여부를 판정하지 않습니다.")
    # 최종 우선순위: 문서 오류는 함수 앞에서 처리, 그 외 불일치 > 확인 필요 > 일치.
    status = "불일치" if any(x["status"] == "불일치" for x in checks) else "확인 필요" if any(x["status"] == "확인 필요" for x in checks) else "일치"
    return {"status": status, "checks": checks, "error": None}
