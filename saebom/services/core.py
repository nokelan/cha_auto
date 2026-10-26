# [파일 기능명세] 서비스 초기화·작업 실행기 위임·브라우저 수명·PDF 한 건 저장을 담당하는 공통 기반.
# 결과·문서 파일 조회(get_result·list_results·document_file)처럼 라우트가 Store를 직접 만지지 않도록 하는 읽기 전용 위임도 둔다.
# 필요한 이름은 명시 import하며, self에서 기대하는 속성·메서드는 services/common.py의 ServiceHost 표에 정리돼 있다.
import hashlib
import threading
from pathlib import Path

from ..compare import extract
from ..files import KIND_FOLDERS, safe_name
from ..jobs import JobRunner
from ..site import SiteClient, allowed_url, request_pdf
from ..store import Store


class Core:
    # [기능명세] Service.__init__
    # 목적: 작업 서비스와 이전 작업 상태 초기화
    # 입력: (self, store: Store)
    # 출력: None
    # 처리: Store 보관 → JobRunner 생성(meta.jobs 복원, running은 failed) → 앱 루트/browser-profile을 쓰는 SiteClient 생성
    #       → 로컬 세금계산서 판독 캐시({(경로, mtime_ns, 크기, 종류): {fields, error}})와 그 잠금 생성
    # 예외/실패: 손상 JSON/DB 오류는 전파
    # 부수효과: 작업 실행기와 메모리 작업 상태 생성; 이 시점에는 사이트 브라우저를 열지 않음
    def __init__(self, store: Store):
        self.store = store
        self.runner = JobRunner(store)
        self.site = SiteClient(store.root / "browser-profile")
        self._invoice_cache = {}
        self._invoice_cache_lock = threading.Lock()


    # [기능명세] Service.lock / jobs / closing (property)
    # 목적: 기존 호출자(api, scripts/verify_raw_amounts.py) 호환용 작업 상태 노출
    # 입력: (self)
    # 출력: JobRunner의 RLock / 작업 사전 / 종료 플래그
    # 처리: 호출 시점의 JobRunner 속성을 그대로 반환(jobs는 submit에서 재할당되므로 매번 읽음)
    # 예외/실패: 없음
    # 부수효과: 없음
    @property
    def lock(self):
        return self.runner.lock


    @property
    def jobs(self):
        return self.runner.jobs


    @property
    def closing(self):
        return self.runner.closing


    # [기능명세] Service.context (property·setter)
    # 목적: 사이트 브라우저 컨텍스트 노출과 테스트 대역 주입 지점 유지
    # 입력: getter (self) / setter (self, value)
    # 출력: SiteClient.context(없으면 None)
    # 처리: SiteClient.context를 읽거나 바꾼다
    # 예외/실패: 없음
    # 부수효과: setter는 SiteClient의 컨텍스트 참조를 교체(정리하지 않음)
    @property
    def context(self):
        return self.site.context


    @context.setter
    def context(self, value):
        self.site.context = value


    # [기능명세] Service.update
    # 목적: 한 작업의 진행 필드를 갱신하고 저장
    # 입력: (self, job, **kw)
    # 출력: None
    # 처리: JobRunner.update 위임
    # 예외/실패: 없는 작업 ID는 KeyError; 저장 오류 전파
    # 부수효과: 메모리 작업과 meta.jobs 변경
    def update(self, job, **kw):
        self.runner.update(job, **kw)


    # [기능명세] Service.submit
    # 목적: 주요 작업을 접수하고 백그라운드 실행
    # 입력: (self, kind, fn, *args)
    # 출력: {"id": 작업 ID}
    # 처리: JobRunner.submit 위임(종료·배타 구간·진행 중 검사, 최근 20개 유지, 실패는 '작업 실패: …')
    # 예외/실패: 종료 중·exclusive 진행 중·다른 작업 실행 중이면 ValueError('현재 작업이 끝난 뒤 실행해 주세요.')
    # 부수효과: 작업 스레드 예약·작업 상태 DB 저장
    def submit(self, kind, fn, *args):
        return self.runner.submit(kind, fn, *args)


    # [기능명세] Service.jobs_snapshot
    # 목적: 화면 표시용 작업 목록 사본
    # 입력: (self)
    # 출력: 최신순 작업 사전 사본 리스트
    # 처리: JobRunner.snapshot 위임
    # 예외/실패: 없음
    # 부수효과: 없음
    def jobs_snapshot(self):
        return self.runner.snapshot()


    # [기능명세] Service.exclusive
    # 목적: 작업 스레드 밖 배타 구간(예: 저장 위치 변경, 거래명세서 생성) 제공
    # 입력: (self, label, message=None)
    # 출력: 컨텍스트 매니저
    # 처리: JobRunner.exclusive 위임
    # 예외/실패: 작업 진행·종료 중·다른 배타 구간이면 ValueError('진행 중인 작업이 끝난 뒤 저장 위치를 변경해 주세요.' 등)
    # 부수효과: 구간 동안 submit 거절
    def exclusive(self, label, message=None):
        return self.runner.exclusive(label, message)


    # [기능명세] Service.browser
    # 목적: 사이트 자동화용 페이지를 재사용하거나 생성
    # 입력: (self)
    # 출력: Playwright Page
    # 처리: SiteClient.page 위임(유효 페이지 재사용, 아니면 번들 Chromium·지속 프로필로 생성)
    # 예외/실패: 브라우저 실행 실패는 전파
    # 부수효과: 프로필과 브라우저 프로세스 생성 가능. 테스트는 인스턴스 속성으로 이 메서드를 대체할 수 있으나,
    #   대체가 적용되는 곳은 download_one과 sync(둘 다 작업 시작 전에 self.browser()를 호출)이다.
    #   그 뒤 실제 DOM 읽기(fetch_mails·fetch_contracts 등)와 open_browser·import_contracts·run_local_audit·run_expense는 SiteClient를 직접 사용한다
    def browser(self):
        return self.site.page()


    # [기능명세] Service.close_browser
    # 목적: 사이트 브라우저와 Playwright 정리
    # 입력: (self)
    # 출력: None
    # 처리: SiteClient.close 위임
    # 예외/실패: 정리 예외는 로그만 남기고 삼킴
    # 부수효과: 사이트 자동화 브라우저 종료
    def close_browser(self):
        self.site.close()


    # [기능명세] Service._stop_if_closing
    # 목적: 작업 단계 사이에서 종료 요청을 확인해 안전하게 중단(download·import_contracts의 기존 확인 방식과 같은 문구 형태)
    # 입력: (self, message: 중단 오류 문구)
    # 출력: None
    # 처리: self.closing이면 오류를 던지고, 아니면 아무것도 하지 않음
    # 예외/실패: 종료 요청이면 ValueError(message)
    # 부수효과: 없음. 지출결의서 상신 클릭 이후 구간에서는 호출하지 않는다(기안 중복·불확실 방지)
    def _stop_if_closing(self, message):
        if self.closing:
            raise ValueError(message)


    # [기능명세] Service.open_browser
    # 목적: 사용자 로그인용 그룹웨어 메일 화면 열기
    # 입력: (self, job)
    # 출력: None
    # 처리: 종료 요청 확인 → SiteClient.open_mail → 완료 수 갱신(열기 직후 종료 요청이 있어도 이미 열린 브라우저는 close가 정리)
    # 예외/실패: 탐색 실패는 상위 작업 래퍼가 실패 처리; 종료 요청이면 ValueError('프로그램 종료 요청으로 중단했습니다.')
    # 부수효과: 사이트 네트워크 접속·브라우저 표시·작업 DB 갱신
    def open_browser(self, job):
        self._stop_if_closing("프로그램 종료 요청으로 중단했습니다.")
        self.site.open_mail()
        self.update(job, done=1, message="전용 브라우저를 열었습니다.")


    # [기능명세] Service._doc_path
    # 목적: 최신 문서 레코드의 파일 경로 계산(store.path와 같은 규칙, DB 재조회 없음)
    # 입력: (self, doc: 방금 조회한 최신 문서 사전)
    # 출력: Path
    # 처리: disk_path가 있으면 그 경로, 없으면 앱 루트/documents/{hash}.pdf
    # 예외/실패: 존재 여부는 확인하지 않음. 이력 속 오래된 문서 사본에는 store.path를 써야 함
    # 부수효과: 없음
    def _doc_path(self, doc):
        return Path(doc["disk_path"]) if doc.get("disk_path") else self.store.root / "documents" / (doc["hash"] + ".pdf")


    # [기능명세] Service.download_one
    # 목적: PDF 한 건 확보와 텍스트 추출·등록
    # 입력: (self, file: {url, name}, kind: 'invoice'|'contract')
    # 출력: 문서 레코드 사전
    # 처리: 존재 파일 재사용(documents.kind가 비어 있으면 store.set_document_kind로 채움) → browser()로 컨텍스트 확보 → request_pdf(URL 검증·HTTP 200·50MiB·PDF 시그니처) → 해시
    #       → 저장 폴더/KIND_FOLDERS[kind]/{해시12}_{safe_name} 저장(.part 후 교체) → extract → save_document(kind 포함)
    # 예외/실패: URL 거부·HTTP 오류·비PDF·크기 초과는 ValueError; 브라우저·파일 오류 전파
    # 부수효과: 네트워크·원본 PDF·추출값 DB 갱신; 재사용 시 재추출하지 않음(단 비어 있던 kind만 채움)
    def download_one(self, file, kind):
        # 캐시 재사용은 파일 존재 기준이다. URL의 원격 변경 감지나 기존 PDF 자동 재추출은 수행하지 않는다.
        old = self.store.document(source=file["url"])
        if old and self.store.path(old).is_file():
            if not old.get("kind"):
                self.store.set_document_kind(old["id"], kind)
                old = self.store.document(id=old["id"])
            return old
        url = allowed_url(file["url"])
        # 테스트가 browser/context를 대역으로 바꿀 수 있도록 Service의 주입 지점을 거친다.
        self.browser()
        body = request_pdf(self.context, url, file["name"])
        digest = hashlib.sha256(body).hexdigest()
        folder = self.store.document_root() / KIND_FOLDERS.get(kind, KIND_FOLDERS["contract"])
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (digest[:12] + "_" + safe_name(file["name"]))
        if not path.exists():
            tmp = path.with_suffix(".part")
            tmp.write_bytes(body)
            tmp.replace(path)
        # 판독은 다운로드 시 수행해 documents.extraction에 저장한다. 비교 시에는 이 저장값을 사용한다.
        parsed = extract(path, kind)
        return self.store.save_document(url, file["name"], digest, parsed, path, kind=kind)


    # [기능명세] Service.get_result
    # 목적: 비교 결과 한 건 조회(GET /api/results/{id} 등 라우트용 위임)
    # 입력: (self, result_id: 결과 ID 문자열)
    # 출력: 결과 사전(저장본의 새 사본) 또는 None(없는 ID)
    # 처리: store.result(result_id) 위임
    # 예외/실패: 없는 ID는 None; DB·JSON 오류 전파
    # 부수효과: DB 읽기
    def get_result(self, result_id):
        return self.store.result(result_id)


    # [기능명세] Service.list_results
    # 목적: 비교 결과 목록 화면용 요약 조회
    # 입력: (self)
    # 출력: store.result_summaries() 결과 — [{id, created, parent, count, mismatch, partners, mail_ids}] (created 내림차순, 같으면 저장 역순)
    # 처리: store.result_summaries() 위임(summary 열 사용, 옛 행은 첫 조회 때 채움). 계약서 목록 전용 verdicts는 화면 목록에 필요 없어 뺀다
    # 예외/실패: DB·JSON 오류 전파
    # 부수효과: DB 읽기; 옛 결과 행의 summary 열이 비어 있으면 한 번 채움
    def list_results(self):
        return [{k: v for k, v in s.items() if k != "verdicts"} for s in self.store.result_summaries()]


    # [기능명세] Service.document_file
    # 목적: 문서 ID로 내려받을 PDF 파일의 경로와 표시 이름 조회
    # 입력: (self, doc_id: 문서 ID 문자열)
    # 출력: (Path, 문서 이름) 튜플 또는 None
    # 처리: store.document(id=doc_id) 조회 → store.path(문서)로 현재 경로 해석 → 실제 파일이 있을 때만 반환
    # 예외/실패: 없는 문서이거나 파일이 사라졌으면 None(호출자가 404 처리); DB 오류 전파
    # 부수효과: DB 읽기·파일 존재 확인; 파일을 읽거나 쓰지 않음
    def document_file(self, doc_id):
        doc = self.store.document(id=doc_id)
        if not doc:
            return None
        path = self.store.path(doc)
        if not path.is_file():
            return None
        return path, doc["name"]


    # [기능명세] Service.close
    # 목적: 작업 접수를 막고 실행기와 브라우저 종료
    # 입력: (self)
    # 출력: None
    # 처리: JobRunner.close에 close_browser를 정리 함수로 넘겨 같은 작업 스레드에서 브라우저 정리 후 실행기 종료 대기
    # 예외/실패: 실행기 예약·종료 오류는 전파
    # 부수효과: 작업 스레드·사이트 브라우저 종료; 대기 작업은 마무리될 수 있음
    def close(self):
        self.runner.close(self.close_browser)

