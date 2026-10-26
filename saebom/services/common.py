# [파일 기능명세]
# 서비스 믹스인(core·compare_service·contracts_service·local_audit_service)이 함께 쓰는 상수·순수 함수와, 믹스인이 self에서 기대하는 속성·메서드 계약(ServiceHost).
# 이전에는 이 파일이 업무 모듈 import를 모두 모아 믹스인이 `from .common import *`로 가져갔다. 이제 각 믹스인이 필요한 이름만 원래 모듈에서 명시 import하며,
# 이 파일에는 서비스 계층 고유의 상수(INVOICE_CACHE_LIMIT, LOCAL_*_KEY, EMPTY_CONTRACTS_MESSAGE), select_contracts, ServiceHost만 둔다.
# 기존 `saebom.service`가 노출하던 이름(예: service.extract, allowed_url, SiteClient, Store, contract_sort_key)은 service.py가 명시 import로 계속 재노출한다.
#
# [믹스인이 self에서 기대하는 것 — Service = Core + CompareMixin + ContractsMixin + LocalAuditMixin]
#   store                   Core.__init__    Store 인스턴스(모든 믹스인)
#   site                    Core.__init__    SiteClient(sync·import_contracts·run_local_audit·run_expense가 fetch_*/submit_expense 호출)
#   runner/jobs/closing     Core             작업 실행기와 종료 플래그(download·import_contracts 등이 self.closing을 확인)
#   update(job, **kw)       Core             작업 진행 필드 저장(모든 작업 함수)
#   submit(kind, fn, *args) Core             작업 접수(submit_expense)
#   exclusive(label, msg)   Core             배타 구간(create_statement)
#   browser()/context       Core             사이트 페이지·컨텍스트(sync, download_one)
#   _stop_if_closing(msg)   Core             종료 요청 확인(sync·open_browser)
#   _doc_path(doc)          Core             최신 문서 레코드의 파일 경로(catalog·run_compare·contract_catalog·_audit_doc)
#   download_one(file,kind) Core             PDF 한 건 확보(download·import_contracts·run_local_audit)
#   _invoice_cache(+_lock)  Core.__init__    로컬 세금계산서 판독 캐시(LocalAuditMixin._cached_invoice)
#   _statement_source(id)   ContractsMixin   expense_draft가 사용(같은 믹스인 안)
#   validate_pairs(pairs)   CompareMixin     download·run_compare가 사용(같은 믹스인 안)
# 유지보수: 믹스인이 self의 새 속성·메서드를 쓰게 되면 아래 ServiceHost와 이 표를 함께 갱신한다.

from typing import Protocol

from ..contract_utils import contract_sort_key
from ..site import SiteClient

# 로컬 세금계산서 판독 캐시의 최대 항목 수. 넘으면 비우고 다시 채운다.
INVOICE_CACHE_LIMIT = 2000
# meta 키: 로컬 세금계산서 폴더(JSON 문자열)와 마지막 대조 결과(JSON 사전).
LOCAL_FOLDER_KEY = "local_invoice_folder"
LOCAL_AUDIT_KEY = "local_audit"
# 웹 계약서 전체 목록이 비었을 때의 안내(로그인 풀림·화면 변경 의심). 대조·가져오기 서비스가 공용으로 쓴다.
EMPTY_CONTRACTS_MESSAGE = "웹 계약서 목록이 비어 있습니다. 전용 브라우저의 로그인과 화면을 확인해 주세요."


# [자료형/클래스 명세] ServiceHost
# 목적: 서비스 믹스인이 self에 있다고 가정하는 속성·메서드의 형식 계약(typing.Protocol). 런타임 동작은 없고 문서·정적 검사용이다.
# 구현: Service(Core, CompareMixin, ContractsMixin, LocalAuditMixin)가 모두 만족한다. 믹스인 단독 인스턴스화는 지원하지 않는다.
# 부수효과: 없음
class ServiceHost(Protocol):
    store: object  # Store
    site: SiteClient
    closing: bool
    _invoice_cache: dict
    _invoice_cache_lock: object  # threading.Lock

    def update(self, job, **kw): ...

    def submit(self, kind, fn, *args): ...

    def exclusive(self, label, message=None): ...

    def browser(self): ...

    def _stop_if_closing(self, message): ...

    def _doc_path(self, doc): ...

    def download_one(self, file, kind): ...


# [기능명세] select_contracts
# 목적: 사이트 계약 목록에서 이번에 가져올 계약을 고르는 순수 함수
# 입력: (items: 계약 행 목록 [{id, ...}], limit: 최대 개수 int 또는 None(전체), only_new: bool, imported_ids: 이미 가져온 관리번호 집합)
# 출력: 선택된 계약 행의 새 리스트(관리번호 큰 순)
# 처리: 1) only_new면 imported_ids에 있는 ID 제외 → 2) contract_sort_key로 관리번호 내림차순 정렬(형식이 다른 ID는 뒤) → 3) limit이 있으면 앞에서 N개
# 예외/실패: 없음; limit이 None이면 개수 제한 없음(API가 1~MAX_PAIRS를 검증)
# 부수효과: 없음(입력 리스트와 행 사전을 바꾸지 않음)
def select_contracts(items, limit, only_new, imported_ids):
    chosen = [c for c in items if not (only_new and c["id"] in imported_ids)]
    chosen.sort(key=lambda c: contract_sort_key(c["id"]))
    return chosen[:limit] if limit is not None else chosen
