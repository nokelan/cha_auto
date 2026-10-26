# [파일 기능명세] 계약서 가져오기·목록·거래명세서 생성·지출결의서 상신과 마지막 상태를 담당하는 믹스인.
# 필요한 이름은 명시 import하며, self에서 기대하는 속성·메서드는 services/common.py의 ServiceHost 표에 정리돼 있다.
from .. import expense, statement
from ..errors import BusinessError, ContractNotFound, SubmitUncertain
from ..files import STATEMENT_FOLDER
from ..store import now
from ..views import strip_doc_pages
from .common import EMPTY_CONTRACTS_MESSAGE, select_contracts


class ContractsMixin:

    # [기능명세] Service.import_contracts
    # 목적: '계약서 목록' 메뉴의 계약서 가져오기 작업(사이트 목록 수집→조건 선택→PDF 저장·판독→가져온 기록 저장)
    # 입력: (self, job: 작업 ID, kind: "전체"|"수입"|"지출", limit: 최대 개수 int|None, only_new: 안 가져온 계약만 여부)
    # 출력: 완료 메시지 문자열('가져올 계약이 없습니다.' 또는 '계약서 N건을 가져왔습니다.'). JobRunner가 작업 완료 메시지로 쓴다
    # 처리: 진행 메시지 갱신 → SiteClient.fetch_contracts(kind)(작업 스레드에서 실행, 사이트 밖이면 계약 화면으로 직접 이동)
    #       → select_contracts(목록, limit, only_new, store.imported_contract_ids()) → 0건이면 total=1·done=1로 정상 종료
    #       → 계약마다: 종료 요청 확인 → file 없으면 '계약서 PDF가 없습니다.' 오류 → 있으면 download_one(file, "contract") 후 save_contract_import
    #       → 실패는 errors에 "{관리번호}: {오류}"로 모으고 기록하지 않음(다음 '안 가져온 것만'에서 재시도됨) → done·errors 갱신
    # 예외/실패: kind가 '전체'이고 사이트 목록이 비면 BusinessError('웹 계약서 목록이 비어 있습니다. …', 로그인·화면 확인 안내; 수입·지출 필터의 빈 결과는 정상 종료);
    #       종료 요청이면 ValueError('프로그램 종료 요청으로 중단했습니다. 가져온 계약은 유지됩니다.'); 일부 실패가 있으면 마지막에
    #       ValueError('{n}개 계약 가져오기 실패. …')로 작업을 failed 처리(성공한 건은 이미 기록됨); 사이트 탐색·열 수 오류는 전파
    # 부수효과: 사이트 접속·원본 PDF 저장·documents/contract_imports DB 갱신·작업 진행 상태 저장. items 스냅샷은 바꾸지 않음
    def import_contracts(self, job, kind="전체", limit=None, only_new=False):
        self.update(job, message=f"계약 문서함 목록을 가져오는 중 ({kind})")
        items = self.site.fetch_contracts(kind)
        if kind == "전체" and not items:
            raise BusinessError(EMPTY_CONTRACTS_MESSAGE)
        chosen = select_contracts(items, limit, only_new, self.store.imported_contract_ids())
        if not chosen:
            self.update(job, total=1, done=1)
            return "가져올 계약이 없습니다."
        self.update(job, total=len(chosen), done=0)
        errors = []
        for i, item in enumerate(chosen):
            if self.closing:
                raise ValueError("프로그램 종료 요청으로 중단했습니다. 가져온 계약은 유지됩니다.")
            self.update(job, message=f"계약서 저장·내용 읽기: {item['id']} {item.get('partner', '')}".rstrip())
            try:
                if not item.get("file"):
                    raise ValueError("계약서 PDF가 없습니다.")
                self.download_one(item["file"], "contract")
                self.store.save_contract_import(item)
            except Exception as e:
                errors.append(f"{item['id']}: {e}")
            self.update(job, done=i + 1, errors=errors)
        if errors:
            raise ValueError(f"{len(errors)}개 계약 가져오기 실패. 상세 오류를 확인하고 재시도하세요.")
        return f"계약서 {len(chosen)}건을 가져왔습니다."


    # [기능명세] Service.contract_catalog
    # 목적: '계약서 목록' 화면용 가져온 계약 목록 구성
    # 입력: (self)
    # 출력: [{id, kind, partner, title, period, amount_text, file, imported, document, status, approval, compare}] — 관리번호 큰 순
    #       compare는 store.contract_verdicts()의 문서비교 판정({status, result_id, mail_id, created, count, counts}) 또는 비교된 적 없으면 None
    # 처리: store.contract_imports() → 계약서 URL을 documents_by_sources로 한 번에 조회 → 문서마다 얕은 사본을 만들고
    #       _doc_path(...).is_file()로 available 표시, pages를 비우고 contract_status를 일괄 조회해 상태·마지막 상신 결과를 붙임
    # 예외/실패: DB·파일 검사 오류 전파; 문서가 없으면 document=None
    # 부수효과: DB·파일 존재 여부 읽기; 저장 데이터(documents.extraction)는 바꾸지 않음
    def contract_catalog(self):
        items = self.store.contract_imports()
        statuses = self.store.contract_statuses()
        verdicts = self.store.contract_verdicts()
        found =self.store.documents_by_sources([c["file"]["url"] for c in items if c.get("file")])
        for c in items:
            d = found.get(c["file"]["url"]) if c.get("file") else None
            if d:
                d = {**strip_doc_pages(d), "available": self._doc_path(d).is_file()}
            c["document"] = d
            c.update(statuses.get(c["id"], {"status": "없음", "approval": None}))
            c["compare"] = verdicts.get(c["id"])
        return items


    # [기능명세] Service.statement_folder
    # 목적: 거래명세서 엑셀 저장 폴더 경로 계산
    # 입력: (self)
    # 출력: Path — 현재 PDF 보관 폴더(store.document_root())/files.STATEMENT_FOLDER의 절대경로
    # 처리: 경로만 계산(존재 여부·생성은 하지 않음)
    # 예외/실패: DB 오류 전파
    # 부수효과: DB 읽기
    def statement_folder(self):
        return (self.store.document_root() / STATEMENT_FOLDER).absolute()


    # [기능명세] Service._statement_source
    # 목적: 거래명세서 대상 계약 행과 원문 페이지가 든 문서 찾기
    # 입력: (self, contract_id: 관리번호)
    # 출력: (row: contract_imports 계약 행, doc: 원문 pages가 든 문서 사전)
    # 처리: store.contract_imports()에서 id로 행 찾기 → 계약서 URL로 store.document(source=…)를 다시 조회
    #       (contract_catalog는 응답에서 pages를 비우므로 쓰지 않음) → store.path(doc) 파일 존재 확인
    # 예외/실패: 가져온 계약이 없으면 ContractNotFound(routes가 404); 파일 링크·문서 레코드·PDF 파일이 없으면 ValueError(statement.NO_SOURCE, api가 400)
    # 부수효과: DB 읽기·파일 존재 확인
    def _statement_source(self, contract_id):
        row = next((c for c in self.store.contract_imports() if c.get("id") == contract_id), None)
        if row is None:
            raise ContractNotFound(contract_id)
        doc = self.store.document(source=row["file"]["url"]) if row.get("file") else None
        if not doc or not self.store.path(doc).is_file():
            raise ValueError(statement.NO_SOURCE)
        return row, doc


    # [기능명세] Service.statement_draft
    # 목적: 거래명세서 확인 창 초기값 조회(GET /api/contracts/{id}/statement)
    # 입력: (self, contract_id: 관리번호)
    # 출력: statement.draft 결과 + folder(저장될 폴더 절대경로 문자열)
    # 처리: _statement_source → statement.draft(문서, 행) → folder 추가. 지출 계약도 eligible=false·reason으로 정상 반환
    # 예외/실패: 없는 계약 ContractNotFound, 원문 없음 ValueError(_statement_source 참조)
    # 부수효과: DB 읽기·파일 존재 확인; 파일·DB를 쓰지 않음
    def statement_draft(self, contract_id):
        row, doc = self._statement_source(contract_id)
        return {**statement.draft(doc, row), "folder": str(self.statement_folder())}


    # [기능명세] Service.create_statement
    # 목적: 확인 창에서 고친 값으로 거래명세서 엑셀 생성(POST /api/contracts/{id}/statement)
    # 입력: (self, contract_id: 관리번호, values: {customer, issue_date, from_month, to_month, items:[{name, spec, monthly_amount}]})
    # 출력: statement.build 결과 {file, path, rows, supply, vat, total, warnings}
    # 처리: _statement_source로 행·문서 확인 → exclusive("거래명세서 생성") 안에서 draft로 수입 여부 재확인 → 관리번호와
    #       계약기간(초안의 period_start/end)을 값에 붙여 statement.build(값, 저장 폴더) 호출
    # 예외/실패: 없는 계약 ContractNotFound; 원문 없음·수입 계약 아님(reason 문구)·입력 검증 실패는 ValueError;
    #           다른 작업 진행·종료 중·다른 배타 구간이면 exclusive가 ValueError('진행 중인 작업이 끝난 뒤 다시 시도해 주세요. (거래명세서 생성)')
    # 부수효과: 구간 동안 새 작업 접수 거절; 저장 폴더 생성과 새 xlsx 파일 1개 생성(기존 파일·템플릿은 덮어쓰지 않음)
    def create_statement(self, contract_id, values):
        row, doc = self._statement_source(contract_id)
        with self.exclusive("거래명세서 생성"):
            info = statement.draft(doc, row)
            if not info["eligible"]:
                raise ValueError(info["reason"])
            merged = {**values, "contract_no": row.get("id"), "period_start": info["period_start"], "period_end": info["period_end"]}
            return statement.build(merged, self.statement_folder())

    # [기능명세] Service.expense_draft
    # 목적: 지출결의서 확인 창의 초기값을 조회한다.
    # 입력: 관리번호. 출력: expense.draft 사전.
    # 처리: 가져온 계약·원문과 마지막 상신 정보를 읽어 순수 규칙에 전달한다.
    # 예외/실패: 없는 계약 ContractNotFound, 원문 없음은 지출결의서용 안내의 ValueError. 부수효과: DB·파일 존재 읽기.
    def expense_draft(self, contract_id):
        try:
            row, doc = self._statement_source(contract_id)
        except ValueError as exc:
            raise ValueError("계약서 원문 PDF가 없어 지출결의서를 상신할 수 없습니다.") from exc
        approval = self.store.contract_statuses().get(contract_id, {}).get("approval")
        return expense.draft(doc, row, approval)

    # [기능명세] Service.submit_expense
    # 목적: 확인된 지출결의서 값을 검증하고 상신 작업을 접수한다.
    # 입력: 관리번호와 수정값. 출력: 작업 ID 사전.
    # 처리: 원문·지출 여부 확인 → 입력 검증 → 실제 청구월 기준 중복 경고 갱신 → 계약 거래처 강제 부여 → 단일 작업 스레드 예약.
    # 예외/실패: 없는 계약 ContractNotFound; 부적격·잘못된 값·작업 충돌 ValueError.
    # 부수효과: 작업 상태 저장과 백그라운드 사이트 상신 예약. 검증 실패 시 기존 승인 결과 유지.
    def submit_expense(self, contract_id, values):
        info = self.expense_draft(contract_id)
        if not info["eligible"]:
            raise ValueError(info["reason"])
        data = expense.validate(values)
        warnings = [w for w in info["warnings"] if "중복 상신" not in w]
        previous = expense.completed_record(info.get("approval"))
        if previous and previous.get("month") == data["month"]:
            warnings.append("같은 달에 품의완료한 기록이 있습니다. 중복 상신 여부를 확인하세요.")
        return self.submit("지출결의서 상신", self.run_expense, contract_id, {**data, "partner": info["partner"]}, warnings)

    # [기능명세] Service.run_expense
    # 목적: 사이트 상신과 작성본 검토를 수행하고 계약 상태를 갱신한다.
    # 입력: 작업 ID, 관리번호, 검증값, 초안 경고 목록. 출력: 완료 메시지.
    # 처리: 이전 상태를 없음으로 초기화(사용자 정책) → 자동 상신 → 순수 검토 → 전 항목 일치만 품의완료 저장.
    #       초기화 때 이전 승인 정보는 버리지 않고, 이전 품의완료 기록(expense.completed_record)을 새 data의 prior_approval로 보존해
    #       같은 달 중복 경고(expense.draft·submit_expense)가 재시도·실패 뒤에도 사라지지 않게 한다. 품의완료 저장 때는 prior_approval을 제거한다.
    #       작성본이 만들어졌으나 검토가 불일치하면 상태 없음에 site_draft=True를 함께 저장한다(사이트에 기안이 있음).
    # 예외/실패: 사이트·파싱 오류는 없음과 오류 정보를 저장 후 전파. 상신 클릭 이후 오류(SubmitUncertain)는 site_draft=True도 저장한다
    #       (클릭 이전 오류는 site_draft를 넣지 않음). 사이트 작성본(document)을 받은 뒤 검토·파싱·저장에서 난 오류도 사이트에 기안이 있으므로
    #       site_draft=True와 가능한 doc_id·doc_no·doc_url·error를 저장한다(상태는 없음). 자동 재상신하지 않는다. 이 함수 안에서는 종료 요청으로 중단하지 않는다.
    # 부수효과: 사이트 기안·contract_status·작업 진행 상태 저장. 이전 성공 결과를 새 결과로 오인하지 않도록 교체한다.
    def run_expense(self, job, contract_id, values, warnings):
        data = {k: values[k] for k in ("title", "month", "supply", "vat", "total")}
        data.update({"submitted_at": now(), "review": [], "warnings": list(warnings)})
        prior = expense.completed_record(self.store.contract_statuses().get(contract_id, {}).get("approval"))
        if prior:
            data["prior_approval"] = {k: v for k, v in prior.items() if k != "prior_approval"}
        document = None
        self.store.save_contract_status(contract_id, "없음", data)
        self.update(job, total=3, done=0, message="그룹웨어 지출결의서 입력·상신 중")
        try:
            document = self.site.submit_expense(contract_id, values)
            self.update(job, done=1, message="작성본 금액·업체·기간·제목 검토 중")
            checks = expense.review(values, document)
            parsed = expense.parse_document(document)
            data.update({"doc_id": document.get("doc_id"), "doc_no": document.get("doc_no"), "doc_url": document.get("doc_url"),
                         "document_total": parsed["document_total"], "review": checks,
                         "warnings": list(dict.fromkeys([*warnings, *(document.get("warnings") or [])]))})
            ok = bool(checks) and all(c["ok"] for c in checks)
            if not ok:
                data["site_draft"] = True
            status = "품의완료" if ok else "없음"
            self.update(job, done=2, message="검토 결과와 계약 상태 저장 중")
            self.store.save_contract_status(contract_id, status, {k: v for k, v in data.items() if k != "prior_approval"} if ok else data)
            self.update(job, done=3, message="품의완료" if ok else "작성본 검토 불일치: 검토 항목을 확인하세요.")
            return "지출결의서 상신·검토 완료: 품의완료" if ok else "지출결의서 작성본 검토 불일치: 상태는 없음입니다."
        except SubmitUncertain as exc:
            self.store.save_contract_status(contract_id, "없음", {**data, "site_draft": True, "error": str(exc)})
            raise
        except Exception as exc:
            extra = {"error": str(exc)}
            if document:
                extra.update({"site_draft": True, "doc_id": document.get("doc_id"), "doc_no": document.get("doc_no"), "doc_url": document.get("doc_url")})
            self.store.save_contract_status(contract_id, "없음", {**data, **extra})
            raise

