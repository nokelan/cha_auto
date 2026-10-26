# [파일 기능명세] 로컬 세금계산서 폴더·판독 캐시·웹 계약 후보 수집·파일별 대조·마지막 결과를 담당하는 믹스인.
# 필요한 이름은 명시 import하며, self에서 기대하는 속성·메서드는 services/common.py의 ServiceHost 표에 정리돼 있다.
import copy
from pathlib import Path

from .. import local_audit
from ..errors import BusinessError
from ..store import now
from ..views import strip_doc_pages
from .common import EMPTY_CONTRACTS_MESSAGE, INVOICE_CACHE_LIMIT, LOCAL_AUDIT_KEY, LOCAL_FOLDER_KEY


class LocalAuditMixin:

    # [기능명세] Service._cached_invoice
    # 목적: 로컬 세금계산서 PDF 판독 결과를 (경로, 수정 시각, 크기) 기준으로 재사용(local_audit.scan_folder의 extractor)
    # 입력: (self, path: Path, kind: 판독 종류 — scan_folder는 "invoice"만 넘김)
    # 출력: {fields, error} 사전의 깊은 사본(pages 제외)
    # 처리: stat으로 (str(path), st_mtime_ns, st_size, kind) 키 계산 → 캐시에 있으면 사본 반환 → 없으면 compare.extract 후
    #       fields·error만 저장(INVOICE_CACHE_LIMIT를 넘으면 캐시를 비우고 저장)
    # 예외/실패: stat·판독 예외는 전파(scan_folder가 행 오류로 바꿈). 파일이 바뀌면 키가 달라져 다시 판독
    # 부수효과: PDF 읽기와 메모리 캐시 갱신; 파일·DB를 쓰지 않음
    def _cached_invoice(self, path, kind):
        st = Path(path).stat()
        key = (str(path), st.st_mtime_ns, st.st_size, kind)
        with self._invoice_cache_lock:
            hit = self._invoice_cache.get(key)
        if hit is None:
            # 테스트가 saebom.service.extract를 monkeypatch할 수 있도록 호출 시점에 service 모듈에서 조회한다(import 시점에 묶으면 안 됨).
            from .. import service as service_module
            parsed = service_module.extract(Path(path), kind)
            hit = {"fields": parsed.get("fields") or {}, "error": parsed.get("error")}
            with self._invoice_cache_lock:
                if len(self._invoice_cache) >= INVOICE_CACHE_LIMIT:
                    self._invoice_cache.clear()
                self._invoice_cache[key] = hit
        return copy.deepcopy(hit)


    # [기능명세] Service._audit_doc
    # 목적: 대조 결과 행에 넣을 계약서 문서 사본 만들기(contract_catalog의 document와 같은 모양)
    # 입력: (self, doc: documents 문서 레코드)
    # 출력: {...문서, extraction: {...추출, pages: []}, available: 파일 존재 여부}
    # 처리: views.strip_doc_pages로 pages를 비운 사본에 _doc_path(...).is_file() 결과를 붙임
    # 예외/실패: 파일 검사 오류 전파
    # 부수효과: 파일 존재 여부 읽기; 저장 데이터는 바꾸지 않음
    def _audit_doc(self, doc):
        return {**strip_doc_pages(doc), "available": self._doc_path(doc).is_file()}


    # [기능명세] Service.local_audit_state
    # 목적: '로컬 세금계산서 대조' 화면 상태 조회(GET /api/local-audit)
    # 입력: (self)
    # 출력: {folder: 저장된 폴더 문자열|None, folder_error: 폴더 검사 오류 문구|None,
    #        files: local_audit.scan_folder 행 목록(path 포함), warnings: [경고 문구], last: meta.local_audit 사전|None}
    # 처리: meta.local_invoice_folder 읽기 → 있으면 check_folder → scan_folder(판독 캐시 _cached_invoice 사용)
    #       → 마지막 결과의 contract_doc을 원본 URL로 다시 조회해 현재 경로·available을 갱신(문서가 사라졌으면 available=false)
    # 예외/실패: 폴더 검사 실패(삭제·권한)·폴더 열기 OSError는 folder_error 문구로 바꾸고 files=[]; DB 오류 전파
    # 부수효과: 폴더·PDF 읽기, 판독 캐시 갱신, DB 읽기; meta는 바꾸지 않음
    def local_audit_state(self):
        folder = self.store.meta_get(LOCAL_FOLDER_KEY)
        files, warnings, error = [], [], None
        if folder:
            try:
                files = local_audit.scan_folder(local_audit.check_folder(folder), self._cached_invoice, warnings)
            except ValueError as e:
                error = str(e)
            except OSError as e:
                error = f"폴더를 읽지 못했습니다. ({type(e).__name__})"
        last = self.store.meta_get(LOCAL_AUDIT_KEY)
        if last:
            docs = [r["contract_doc"] for r in last.get("rows", []) if r.get("contract_doc")]
            found = self.store.documents_by_sources([d.get("source") for d in docs])
            for r in last.get("rows", []):
                d = r.get("contract_doc")
                if d:
                    fresh = found.get(d.get("source"))
                    r["contract_doc"] = self._audit_doc(fresh) if fresh else {**d, "available": False}
        return {"folder": folder, "folder_error": error, "files": files, "warnings": warnings, "last": last}


    # [기능명세] Service.set_local_folder
    # 목적: 로컬 세금계산서 폴더 설정(PUT /api/local-audit/folder)
    # 입력: (self, folder: 폴더 경로 문자열)
    # 출력: local_audit_state() 결과
    # 처리: local_audit.check_folder로 검사 → meta.local_invoice_folder에 문자열로 저장 → 상태 반환
    # 예외/실패: 빈 값·상대경로·UNC·없는 폴더는 ValueError(api가 400); 기존 설정은 유지
    # 부수효과: meta 갱신; 마지막 대조 결과(meta.local_audit)는 지우지 않음
    def set_local_folder(self, folder):
        path = local_audit.check_folder(folder)
        self.store.meta_set(LOCAL_FOLDER_KEY, str(path))
        return self.local_audit_state()


    # [기능명세] Service.run_local_audit
    # 목적: 로컬 세금계산서와 웹 계약서 대조 작업(작업 이름 "로컬 세금계산서 대조")
    # 입력: (self, job: 작업 ID)
    # 출력: 완료 문구(local_audit.summarize, 예: "세금계산서 26건 대조: 일치 8 · 불일치 2 · 확인 필요 14 · 계약서 없음 2")
    # 처리: 저장 폴더 확인·check_folder → scan_folder(판독 캐시) → site.fetch_contracts("전체") 1회
    #       → 파일마다: 종료 요청 확인 → match_contracts → 지출 후보(없으면 전체 후보)의 계약서 PDF를 download_one(file, "contract")로 확보
    #         (같은 URL은 이번 실행에서 한 번만 시도) → pick_contract → 고른 계약은 save_contract_import로 '계약서 목록'에도 기록
    #         → local_audit.audit_row(compare 판정) → done·errors 갱신
    #       → {folder, ran_at, contracts_total, counts, warnings, rows}를 meta.local_audit에 저장
    # 예외/실패: 폴더 미설정 ValueError('세금계산서 폴더를 먼저 선택하세요.'); 폴더 검사 실패·파일 0건·사이트 수집 실패·웹 계약서 목록 비어 있음(BusinessError, 로그인·화면 확인 안내)은 작업 실패(이전 결과 유지);
    #           종료 요청이면 ValueError로 중단(이전 결과 유지). 행 단위 실패는 '처리 실패' 행과 errors("{파일}: {사유}")로 남기고 계속:
    #           고른 계약에 PDF가 없거나 내려받기 실패, 후보가 여럿인데 일부 계약서를 내려받지 못한 경우
    # 부수효과: 로컬 파일 읽기, 사이트 접속·계약서 PDF 저장(documents), contract_imports·meta.local_audit·작업 진행 상태 DB 갱신
    def run_local_audit(self, job):
        folder = self.store.meta_get(LOCAL_FOLDER_KEY)
        if not folder:
            raise ValueError("세금계산서 폴더를 먼저 선택하세요.")
        path = local_audit.check_folder(folder)
        self.update(job, message="세금계산서 파일을 읽는 중")
        warnings = []
        files = local_audit.scan_folder(path, self._cached_invoice, warnings)
        if not files:
            raise ValueError("선택한 폴더에 PDF·PNG 세금계산서가 없습니다.")
        self.update(job, total=len(files) + 1, done=0, message="웹 계약서 목록을 가져오는 중")
        contracts = self.site.fetch_contracts("전체")
        if not contracts:
            raise BusinessError(EMPTY_CONTRACTS_MESSAGE)
        self.update(job, done=1)
        # 이번 실행에서 계약서 URL별 내려받기 결과(문서 레코드 또는 예외). 같은 계약서를 여러 세금계산서가 써도 한 번만 시도한다.
        downloaded = {}
        rows, errors = [], []
        for i, f in enumerate(files):
            if self.closing:
                raise ValueError("프로그램 종료 요청으로 중단했습니다. 이전 대조 결과는 유지됩니다.")
            self.update(job, message=f"대조 중: {f['file']}")
            candidates = local_audit.match_contracts(f["partner"], contracts)
            pool = [c for c in candidates if c.get("kind") == "지출"] or candidates
            docs, failed = {}, []
            for c in pool:
                url = (c.get("file") or {}).get("url")
                if not url:
                    continue
                if url not in downloaded:
                    self.update(job, message=f"계약서 저장·내용 읽기: {c.get('id')} {c.get('partner') or ''}".rstrip())
                    try:
                        downloaded[url] = self.download_one(c["file"], "contract")
                    except Exception as e:
                        downloaded[url] = e
                if isinstance(downloaded[url], Exception):
                    failed.append(f"{c.get('id')}: {downloaded[url]}")
                else:
                    docs[url] = downloaded[url]
            chosen, reason = local_audit.pick_contract(candidates, f["invoice"]["fields"], docs)
            doc, failure = None, None
            if len(pool) > 1 and failed:
                # 내려받지 못한 후보가 있으면 사업자번호·기간 좁히기가 틀릴 수 있어 고르지 않는다.
                chosen, failure = None, "후보 계약서를 내려받지 못했습니다: " + "; ".join(failed)
            elif chosen:
                url = (chosen.get("file") or {}).get("url")
                if not url:
                    failure = "계약서 PDF가 없습니다."
                elif url not in docs:
                    failure = "계약서 내려받기 실패: " + "; ".join(failed)
                else:
                    doc = self._audit_doc(docs[url])
                    self.store.save_contract_import(chosen)
            if failure:
                errors.append(f"{f['file']}: {failure}")
            rows.append(local_audit.audit_row(f, candidates, chosen, reason, doc, failure))
            self.update(job, done=i + 2, errors=errors)
        counts, message = local_audit.summarize(rows)
        self.store.meta_set(LOCAL_AUDIT_KEY, {"folder": str(path), "ran_at": now(), "contracts_total": len(contracts),
                                              "counts": counts, "warnings": warnings, "rows": rows})
        self.update(job, message=message)
        return message

