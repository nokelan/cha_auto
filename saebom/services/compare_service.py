# [파일 기능명세] 메일·계약 목록 동기화·추천·연결 검증·다운로드·오프라인 비교를 담당하는 믹스인.
# 필요한 이름은 명시 import하며, self에서 기대하는 속성·메서드는 services/common.py의 ServiceHost 표에 정리돼 있다.
import copy

from ..compare import compare, norm, val
from ..config import MAX_PAIRS
from ..site import check_lists
from ..views import strip_doc_pages


class CompareMixin:

    # [기능명세] Service.sync
    # 목적: 그룹웨어의 메일·계약 목록 동기화
    # 입력: (self, job)
    # 출력: None
    # 처리: 브라우저 확보 → 메일 수집(SiteClient.fetch_mails) → 계약 전체 필터·행 수집(fetch_contracts, 열 수 검사) → 빈 목록 검사 → snapshot 일괄 저장
    #       (단계 사이마다 종료 요청 확인)
    # 예외/실패: 빈 목록·계약 열 수 불일치·탐색 실패 시 기존 스냅샷 유지; 종료 요청이면 ValueError('프로그램 종료 요청으로 중단했습니다. 기존 목록은 유지됩니다.')
    # 부수효과: 사이트 접속·목록과 동기화 시각·진행 상태 저장
    def sync(self, job):
        self._stop_if_closing("프로그램 종료 요청으로 중단했습니다. 기존 목록은 유지됩니다.")
        self.browser()
        self.update(job, total=2, message="메일함 목록을 가져오는 중")
        self._stop_if_closing("프로그램 종료 요청으로 중단했습니다. 기존 목록은 유지됩니다.")
        mail_items = self.site.fetch_mails()
        self.update(job, done=1, message="계약 문서함 목록을 가져오는 중")
        self._stop_if_closing("프로그램 종료 요청으로 중단했습니다. 기존 목록은 유지됩니다.")
        contract_items = self.site.fetch_contracts()
        self._stop_if_closing("프로그램 종료 요청으로 중단했습니다. 기존 목록은 유지됩니다.")
        check_lists(mail_items, contract_items)
        self.store.snapshot(mail_items, contract_items)
        self.update(job, done=2, message="목록 저장 완료")


    # [기능명세] Service.catalog
    # 목적: 화면용 목록과 추천 계약 구성
    # 입력: (self)
    # 출력: {"mails": [...], "contracts": [...], "synced": 시각|None}
    #       메일에는 pdfs/documents({url: 문서|None})/candidates, 계약에는 document(문서|None)가 추가되고, 문서에는 available(파일 존재)이 붙는다
    # 처리: 목록 조회 → 메일 PDF 첨부·계약 파일 URL을 documents_by_sources로 한 번에 조회 → 원본 URL별 파일 존재 확인 1회
    #       → 지출 계약의 정규화 업체명·사업자번호를 미리 계산 → 메일별 업체명 부분 문자열 후보, 사업자번호 일치 후보가 있으면 그것을 우선(계약 목록 순서 유지)
    # 예외/실패: 조회·파일 검사 오류는 전파; 후보 여러 건은 그대로 제공
    #       응답의 문서는 views.strip_doc_pages로 extraction.pages를 비운 사본이다(내부 재사용 없음, /api/state 전용). 후보 계산은 fields만 쓴다
    # 부수효과: 조회한 메모리 사전 보강; DB 목록을 다시 쓰지 않음. 문서 사전은 사용처마다 얕은 사본을 둔다
    def catalog(self):
        mails = sorted(self.store.items("mails"), key=lambda m: m["received"], reverse=True)
        contracts = self.store.items("contracts")
        for m in mails:
            m["pdfs"] = [a for a in m["attachments"] if a["name"].lower().endswith(".pdf")]
        sources = [c["file"]["url"] for c in contracts if c["file"]] + [a["url"] for m in mails for a in m["pdfs"]]
        found = self.store.documents_by_sources([s for s in dict.fromkeys(sources) if s])
        available = {}

        # [기능명세] Service.catalog.doc
        # 목적: 원본 URL의 문서 사본과 파일 존재 표시 제공
        # 입력: (source, mark: available을 붙일지)
        # 출력: 문서 사전 얕은 사본 또는 None
        # 처리: 일괄 조회 결과에서 찾아 pages를 비운 사본(strip_doc_pages)으로 만들고, mark이면 URL별로 한 번만 계산한 is_file 결과를 available로 기록
        # 예외/실패: 파일 검사 오류 전파
        # 부수효과: available 캐시 갱신
        def doc(source, mark=True):
            d = found.get(source) if source else None
            if not d:
                return None
            d = strip_doc_pages(d)
            if mark:
                if source not in available:
                    available[source] = self._doc_path(d).is_file()
                d["available"] = available[source]
            return d

        contract_docs = {c["id"]: doc(c["file"]["url"], mark=False) if c["file"] else None for c in contracts}
        # 지출 계약만 후보 대상이다. (계약ID, 정규화 업체명, 계약서 문서 존재 여부, 계약서 사업자번호)를 계약 목록 순서로 미리 계산한다.
        spend = []
        if mails:
            for c in contracts:
                if c["kind"] == "지출":
                    cd = contract_docs[c["id"]]
                    spend.append((c["id"], norm(c["partner"]), bool(cd), val(cd["extraction"], "biz") if cd else None))
        for m in mails:
            m["documents"] = {a["url"]: doc(a["url"]) for a in m["pdfs"]}
            # 업체명 후보: 정규화 업체명이 정규화 발신자에 부분 문자열로 포함되는 지출 계약. 정규화 결과가 빈 문자열인 거래처는 제외한다("" in 발신자는 항상 참).
            sender = norm(m["sender"]) if spend else None
            matches = [cid for cid, partner, _, _ in spend if partner and partner in sender]
            invoice_biz = {val(d["extraction"], "biz") for d in m["documents"].values() if d and d.get("available")}
            # 사업자번호 후보: 계약서 문서가 있고 그 번호가 사용 가능한 계산서 번호 중 하나인 지출 계약. 있으면 업체명 후보를 대체한다.
            biz_matches = [cid for cid, _, has_doc, biz in spend if has_doc and biz in invoice_biz - {None}]
            if biz_matches:
                matches = biz_matches
            m["candidates"] = matches
        for c in contracts:
            c["document"] = contract_docs[c["id"]]
            if c["document"]:
                source = c["file"]["url"]
                if source not in available:
                    available[source] = self._doc_path(c["document"]).is_file()
                c["document"]["available"] = available[source]
        return {"mails": mails, "contracts": contracts, "synced": self.store.synced()}


    # [기능명세] Service.validate_pairs
    # 목적: 비교 연결 관계의 유효성 검사
    # 입력: (self, pairs, saved=None: 보정 재비교 때 부모 결과 사전)
    # 출력: 메일 ID 사전과 계약 ID 사전의 튜플
    # 처리: 1~MAX_PAIRS(500)건·메일/계약 존재·PDF 첨부 URL·메일 중복 검사.
    #       saved가 있으면 현재 동기화 스냅샷에 없는 메일·계약에 한해 저장된 결과 행의 문서(원본 URL·파일명)·제목·거래처로 만든 대역을 보충한다
    #       (동기화로 목록이 바뀐 뒤에도 보정 재비교가 가능하도록. 스냅샷에 있는 항목은 항상 스냅샷이 우선)
    # 예외/실패: 유효하지 않은 연결은 ValueError
    # 부수효과: DB 읽기만 수행; 파일 다운로드 없음
    def validate_pairs(self, pairs, saved=None):
        if not pairs or len(pairs) > MAX_PAIRS:
            raise ValueError("비교할 메일을 1~500건 선택해 주세요.")
        mails = {x["id"]: x for x in self.store.items("mails")}
        contracts = {x["id"]: x for x in self.store.items("contracts")}
        for r in (saved or {}).get("rows", []):
            inv, con = r.get("invoice") or {}, r.get("contract") or {}
            if r.get("mail_id") not in mails and inv.get("source"):
                mails[r["mail_id"]] = {"id": r["mail_id"], "subject": r.get("subject", ""), "attachments": [{"name": inv.get("name", ""), "url": inv["source"]}]}
            if r.get("contract_id") not in contracts and con.get("source"):
                contracts[r["contract_id"]] = {"id": r["contract_id"], "partner": r.get("partner", ""), "file": {"name": con.get("name", ""), "url": con["source"]}}
        seen = set()
        for pair in pairs:
            m, c = mails.get(pair["mail_id"]), contracts.get(pair["contract_id"])
            if not m or not c or not c["file"]:
                raise ValueError("메일과 PDF 계약서를 연결해 주세요.")
            url = pair.get("invoice_url")
            if not any(a["url"] == url and a["name"].lower().endswith(".pdf") for a in m["attachments"]):
                raise ValueError("메일에 실제 첨부된 PDF를 선택해 주세요.")
            if pair["mail_id"] in seen:
                raise ValueError("같은 메일을 중복 선택할 수 없습니다.")
            seen.add(pair["mail_id"])
        return mails, contracts


    # [기능명세] Service.download
    # 목적: 선택 연결의 PDF를 중복 없이 저장
    # 입력: (self, job, pairs)
    # 출력: None
    # 처리: 연결 검증 → URL 기준 파일 합치기 → 개별 저장 → 파일별 오류 수집
    # 예외/실패: 종료 요청 또는 일부 실패면 ValueError; 성공한 파일은 유지
    # 부수효과: 여러 PDF·문서 DB·작업 진행 상태 변경
    def download(self, job, pairs):
        mails, contracts = self.validate_pairs(pairs)
        files = {}
        for pair in pairs:
            invoice = next(a for a in mails[pair["mail_id"]]["attachments"] if a["url"] == pair["invoice_url"])
            files[invoice["url"]] = (invoice, "invoice")
            f = contracts[pair["contract_id"]]["file"]
            files[f["url"]] = (f, "contract")
        self.update(job, total=len(files))
        errors = []
        for i, (f, kind) in enumerate(files.values()):
            if self.closing:
                raise ValueError("프로그램 종료 요청으로 중단했습니다. 저장한 파일은 유지됩니다.")
            self.update(job, message=f"PDF 저장·내용 읽기: {f['name']}")
            try:
                self.download_one(f, kind)
            except Exception as e:
                errors.append(f"{f['name']}: {e}")
            self.update(job, done=i + 1, errors=errors)
        if errors:
            raise ValueError(f"{len(errors)}개 파일 저장 실패. 상세 오류를 확인하고 재시도하세요.")


    # [기능명세] Service.run_compare
    # 목적: 저장된 추출값으로 비교 및 보정 이력 생성
    # 입력: (self, job, pairs, overrides=None: {문서ID: {필드: 값}}, parent=None: 원본 결과 ID)
    # 출력: None; 작업에 result_id 기록
    # 처리: (parent가 있으면 저장된 부모 결과를 읽어 validate_pairs의 보충 자료로 씀) 연결 검증 → 계산서·계약서 문서 일괄 조회·파일 존재 확인 → 계약 ID별 그룹을 한 번만 구성(fields만 deepcopy, 보정은 {"value": v})
    #       → 행마다 effective_invoice 구성(fields만 deepcopy, 보정은 value/quote/page/method/previous, pages는 원본 참조) → compare → 새 결과 저장
    # 예외/실패: 문서 누락·파일 없음은 ValueError('선택 문서 다운로드를 먼저 완료해 주세요. …'); 추출값과 원본 PDF는 덮어쓰지 않음;
    #           검증 직후와 행 비교 사이에 종료 요청이 있으면 ValueError('프로그램 종료 요청으로 중단했습니다. 결과는 저장하지 않았습니다.')
    # 부수효과: 로컬 결과·작업 DB 저장; 외부 네트워크 접속 없음
    def run_compare(self, job, pairs, overrides=None, parent=None):
        mails, contracts = self.validate_pairs(pairs, self.get_result(parent)) if parent else self.validate_pairs(pairs)
        self._stop_if_closing("프로그램 종료 요청으로 중단했습니다. 결과는 저장하지 않았습니다.")
        found = self.store.documents_by_sources(list(dict.fromkeys(
            [p["invoice_url"] for p in pairs] + [contracts[p["contract_id"]]["file"]["url"] for p in pairs])))
        records = []
        for pair in pairs:
            inv = found.get(pair["invoice_url"])
            con = found.get(contracts[pair["contract_id"]]["file"]["url"])
            if not inv or not con or not self._doc_path(inv).exists() or not self._doc_path(con).exists():
                raise ValueError("선택 문서 다운로드를 먼저 완료해 주세요. 비교는 네트워크를 사용하지 않습니다.")
            records.append((pair, inv, con))
        edits = overrides or {}
        # 같은 계약의 분할 청구 누적 검사용 그룹. 보정값을 같은 방식으로 반영하며 계약 ID별로 한 번만 만든다.
        groups = {}
        for p, di, _ in records:
            d = dict(di["extraction"])
            if "fields" in d:
                d["fields"] = copy.deepcopy(d["fields"])
            for k, v in edits.get(di["id"], {}).items():
                d["fields"][k] = {"value": v}
            groups.setdefault(p["contract_id"], []).append(d)
        result_rows = []
        self.update(job, total=len(records), message="로컬 문서 비교 중 · 네트워크·AI 미사용")
        for index, (pair, inv, con) in enumerate(records):
            self._stop_if_closing("프로그램 종료 요청으로 중단했습니다. 결과는 저장하지 않았습니다.")
            parsed = dict(inv["extraction"])
            if "fields" in parsed:
                parsed["fields"] = copy.deepcopy(parsed["fields"])
            for key, value in edits.get(inv["id"], {}).items():
                previous = parsed["fields"].get(key)
                parsed["fields"][key] = {"value": value, "quote": "사용자 수동 보정", "page": None, "method": "수동 보정", "previous": previous}
            result_rows.append({"mail_id": pair["mail_id"], "contract_id": pair["contract_id"], "subject": mails[pair["mail_id"]]["subject"], "partner": contracts[pair["contract_id"]]["partner"],
                                "invoice": inv, "contract": con, "effective_invoice": parsed,
                                **compare(parsed, con["extraction"], groups[pair["contract_id"]])})
            self.update(job, done=index + 1)
        result = self.store.save_result({"rows": result_rows, "pairs": pairs, "overrides": edits, "parent": parent})
        self.update(job, result_id=result["id"])

