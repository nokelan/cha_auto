# [파일 기능명세] 기능별 서비스 믹스인을 조합하는 공개 진입점. 기존 Service와 공용 도우미 import를 재수출한다.
# 이전의 `from .services.common import *`를 명시 import로 바꿨으며, `saebom.service`가 노출하던 이름은 그대로 유지한다
# (tests가 service.extract 등을 monkeypatch하고 routes·scripts가 LOCAL_FOLDER_KEY·contract_sort_key·select_contracts·allowed_url을 가져온다).
# 특히 services/local_audit_service._cached_invoice는 `saebom.service.extract`를 호출 시점에 지연 조회하므로 아래 extract 이름을 지우면 안 된다.
# 재수출만 하는 이름은 noqa로 표시한다.
# noqa 목록 중 copy·hashlib·re·threading·Path는 과거 `import *`로 우연히 노출되던 표준 모듈 이름의 호환 유지용이다.
import copy  # noqa: F401
import hashlib  # noqa: F401
import re  # noqa: F401
import threading  # noqa: F401
from pathlib import Path  # noqa: F401

from . import local_audit, statement  # noqa: F401
from .compare import compare, extract, norm  # noqa: F401
from .config import MAX_PAIRS, SITE_URL  # noqa: F401
from .contract_utils import CONTRACT_ID, contract_sort_key  # noqa: F401
from .errors import BusinessError, ContractNotFound, SubmitUncertain  # noqa: F401
from .files import KIND_FOLDERS, STATEMENT_FOLDER, safe_name  # noqa: F401
from .jobs import JobRunner  # noqa: F401
from .site import SiteClient, allowed_url, check_lists, request_pdf  # noqa: F401
from .store import Store, now  # noqa: F401
from .views import strip_doc_pages  # noqa: F401
from .services.common import (EMPTY_CONTRACTS_MESSAGE, INVOICE_CACHE_LIMIT, LOCAL_AUDIT_KEY, LOCAL_FOLDER_KEY,  # noqa: F401
                              select_contracts)
from .services.core import Core
from .services.compare_service import CompareMixin
from .services.contracts_service import ContractsMixin
from .services.local_audit_service import LocalAuditMixin


class Service(Core, CompareMixin, ContractsMixin, LocalAuditMixin):
    """기존 공개 import와 메서드를 유지하는 업무 서비스."""
    pass
