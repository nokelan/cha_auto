# [파일 기능명세]
# 작업 실행 계층. 단일 작업 스레드(ThreadPoolExecutor, max_workers=1)에서 주요 작업을 순차 실행하고, 작업 상태를 Store.meta_get/meta_set('jobs')로 저장·복원한다(DB 직접 접근 없음).
# 처리 흐름: 생성 시 이전 작업 복원(running→failed) → submit으로 접수·실행 → update로 진행 갱신·저장 → close로 접수 차단·종료.
# exclusive(label)는 작업 스레드 밖에서 실행하는 배타 구간(예: 저장 위치 변경)으로, 진행 중에는 submit을 거절하고 잠금은 쥐지 않는다.
# 유지보수: 함수·데이터 계약이 바뀌면 해당 기능명세와 실제 회귀 검사를 함께 갱신한다.

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import uuid4

from .store import now

log = logging.getLogger(__name__)

# 재시작 시 running으로 남은 작업에 기록하는 안내 문구.
RESTART_MESSAGE = "이전 실행이 종료되었습니다. 저장 파일은 유지되며 작업을 다시 실행할 수 있습니다."
# 다른 작업·배타 구간이 진행 중일 때 submit이 내는 안내 문구.
BUSY_MESSAGE = "현재 작업이 끝난 뒤 실행해 주세요."
# exclusive의 기본 거절 문구(저장 위치 변경 문맥).
EXCLUSIVE_MESSAGE = "진행 중인 작업이 끝난 뒤 저장 위치를 변경해 주세요."


# [자료형/클래스 명세] JobRunner: 작업 실행기. Store·단일 작업 스레드·RLock·작업 상태 사전(jobs)·종료 플래그·배타 구간 표시를 소유한다.
# jobs는 {작업ID: {id, kind, status, message, done, total, errors, created, result_id?}} 형태이며 삽입 순서가 생성 순서다.
class JobRunner:
    # [기능명세] JobRunner.__init__
    # 목적: 작업 실행기 생성과 이전 작업 상태 복원
    # 입력: (self, store: Store)
    # 출력: None
    # 처리: 단일 작업 실행기·RLock 생성 → Store.meta_get('jobs')로 JSON 복원 → running 상태는 failed와 재시작 안내로 변경
    # 예외/실패: 손상 JSON·DB 오류는 전파(저장 키 'jobs'·JSON 형식은 기존 DB와 호환)
    # 부수효과: 작업 스레드 실행기와 메모리 작업 상태 생성; 복원 결과는 다음 저장 때 DB에 반영
    def __init__(self, store):
        self.store = store
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="site-worker")
        self.lock = threading.RLock()
        self.jobs = {}
        self.closing = False
        self.busy = None
        saved = store.meta_get("jobs")
        if saved:
            self.jobs = saved
            for j in self.jobs.values():
                if j["status"] == "running":
                    j.update(status="failed", message=RESTART_MESSAGE)

    # [기능명세] JobRunner.persist
    # 목적: 현재 작업 상태를 DB에 저장
    # 입력: (self)
    # 출력: None
    # 처리: Store.meta_set('jobs', jobs)로 meta.jobs JSON 교체(Store 잠금·트랜잭션은 Store가 담당; JobRunner는 store.db·store.lock을 직접 쓰지 않음)
    # 예외/실패: DB 오류는 호출자에게 전파
    # 부수효과: meta 테이블 갱신
    def persist(self):
        self.store.meta_set("jobs", self.jobs)

    # [기능명세] JobRunner.update
    # 목적: 한 작업의 진행 필드를 갱신하고 저장
    # 입력: (self, job: 작업 ID, **kw: 병합할 필드)
    # 출력: None
    # 처리: 실행기 잠금 안에서 jobs[job]에 kw 병합 후 영속화
    # 예외/실패: 없는 작업 ID는 KeyError; 저장 오류 전파
    # 부수효과: 메모리 작업과 meta.jobs 변경
    def update(self, job, **kw):
        with self.lock:
            self.jobs[job].update(**kw)
            self.persist()

    # [기능명세] JobRunner.submit
    # 목적: 주요 작업을 접수하고 백그라운드 실행
    # 입력: (self, kind: 화면 표시용 작업 이름, fn: fn(job_id, *args) 형태 함수, *args)
    # 출력: {"id": 작업 ID}
    # 처리: 종료·배타 구간·running 작업 검사 → 최근 19개만 남기고 새 running 작업 추가(최대 20개) → 저장 → 실행기에 run 제출
    # 예외/실패: 종료 중, exclusive 진행 중, 다른 작업 실행 중이면 ValueError('현재 작업이 끝난 뒤 실행해 주세요.')
    # 부수효과: 작업 스레드 예약·작업 상태 DB 저장; 완료 결과는 후속 조회
    def submit(self, kind, fn, *args):
        with self.lock:
            if self.closing or self.busy or any(j["status"] == "running" for j in self.jobs.values()):
                raise ValueError(BUSY_MESSAGE)
            id = uuid4().hex
            self.jobs = dict(list(self.jobs.items())[-19:])
            self.jobs[id] = {"id": id, "kind": kind, "status": "running", "message": "작업 준비 중", "done": 0, "total": 1, "errors": [], "created": now()}
            self.persist()

        # [기능명세] JobRunner.submit.run
        # 목적: 제출 함수 실행과 성공·실패 상태 전환
        # 입력: ()
        # 출력: None
        # 처리: fn(id,*args) 호출 후 done. fn이 문자열을 반환하면 그것을 완료 메시지로, 아니면 '작업 완료'를 쓴다.
        #       예외는 failed와 '작업 실패: {예외}' 메시지로 변환. 최종 상태 저장(update)이 DB 오류로 실패하면
        #       log.exception을 남기고 메모리 상태(jobs[id])만이라도 같은 최종 상태로 바꿔 영구 running을 막는다
        #       (제한시간·강제 중단은 없음: fn이 끝나지 않고 멈추면 작업은 계속 running이다 — 알려진 한계)
        # 예외/실패: 업무 예외를 작업 상태로 기록하고 외부로 다시 던지지 않음; 최종 상태 저장 실패도 삼키고 기록만 함
        # 부수효과: 해당 작업 상태 저장·실패 시 logging.exception 기록; 저장 실패 시 DB에는 running이 남을 수 있으나 재시작 때 failed로 복원됨; 실제 부수효과는 fn의 명세를 따름
        def run():
            try:
                message = fn(id, *args)
                final = {"status": "done", "message": message if isinstance(message, str) and message else "작업 완료"}
            except Exception as e:
                log.exception("작업 실패: %s", kind)
                final = {"status": "failed", "message": f"작업 실패: {e}"}
            try:
                self.update(id, **final)
            except Exception:
                # DB 저장 오류로 최종 상태를 못 남겨도 메모리 상태는 반드시 종료 상태로 바꿔 영구 running을 막는다.
                log.exception("작업 상태 저장 실패: %s", kind)
                with self.lock:
                    if id in self.jobs:
                        self.jobs[id].update(**final)
        self.pool.submit(run)
        return {"id": id}

    # [기능명세] JobRunner.snapshot
    # 목적: 화면 표시용 작업 목록 사본 제공
    # 입력: (self)
    # 출력: 최신순(생성 역순) 작업 사전 사본 리스트
    # 처리: 잠금 안에서 jobs 값을 역순으로 얕은 복사(errors 리스트도 복사)
    # 예외/실패: 없음
    # 부수효과: 없음; 반환값을 고쳐도 내부 상태는 바뀌지 않음
    def snapshot(self):
        with self.lock:
            return [{**j, "errors": list(j.get("errors", []))} for j in reversed(list(self.jobs.values()))]

    # [기능명세] JobRunner.exclusive
    # 목적: 작업 스레드 밖에서 실행하는 배타 구간 제공(예: 저장 위치 변경)
    # 입력: (self, label: 구간 이름, message=None: 거절 문구, 없으면 label 문맥의 기본 문구)
    # 출력: 컨텍스트 매니저(값 없음)
    # 처리: 잠금 안에서 종료 중·running 작업·다른 exclusive 진행 여부 검사 → 통과하면 busy=label 표시 후 잠금 해제 → 블록 실행 → 종료 시 busy 해제
    # 예외/실패: 검사에 걸리면 ValueError; label이 '저장 위치 변경'이면 '진행 중인 작업이 끝난 뒤 저장 위치를 변경해 주세요.'
    #           블록 안 예외는 busy를 해제한 뒤 그대로 전파
    # 부수효과: busy 표시 변경; 구간 동안 submit 거절. 블록 실행 중에는 잠금을 쥐지 않으므로 상태 조회는 막히지 않음
    @contextmanager
    def exclusive(self, label, message=None):
        with self.lock:
            if self.closing or self.busy or any(j["status"] == "running" for j in self.jobs.values()):
                if message is None:
                    message = EXCLUSIVE_MESSAGE if label == "저장 위치 변경" else f"진행 중인 작업이 끝난 뒤 다시 시도해 주세요. ({label})"
                raise ValueError(message)
            self.busy = label
        try:
            yield
        finally:
            with self.lock:
                self.busy = None

    # [기능명세] JobRunner.close
    # 목적: 작업 접수를 막고 실행기 종료
    # 입력: (self, cleanup=None: 작업 스레드에서 마지막으로 실행할 정리 함수)
    # 출력: None
    # 처리: closing 설정 → cleanup이 있으면 같은 작업 스레드에 예약 → 실행기 종료 대기
    # 예외/실패: 실행기 예약·종료 오류는 전파
    # 부수효과: 작업 스레드 종료; 대기 작업은 마무리될 수 있음
    def close(self, cleanup=None):
        self.closing = True
        if cleanup:
            self.pool.submit(cleanup)
        self.pool.shutdown(wait=True)
