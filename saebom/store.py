# [파일 기능명세]
# 영속 저장 계층. SQLite의 6개 테이블(items·documents·results·meta·contract_imports·contract_status)을 RLock으로 보호하며 원본 경로를 문서 ID로 조회한다.
# contract_status는 계약별 작업 상태(품의완료 등)와 상세(지출결의서 상신 이력·검토 결과)를 저장하며 id가 기본 키이다. contract_statuses()로 일괄 조회한다.
# contract_imports는 '계약서 목록' 메뉴로 PDF까지 가져온 계약 기록이며, 목록 동기화(snapshot)의 items 전체 교체와 무관하게 유지된다.
# 문서 조회는 단건(document)과 원본 URL 일괄 조회(documents_by_sources)를 제공하고, documents.kind 열로 문서 종류(invoice/contract)를 기록한다.
# 결과 조회는 전체(results), 단건(result), 화면 목록용 요약(result_summaries)으로 나눈다.
# meta_get/meta_set은 JSON 값을 쓰는 meta 키(local_invoice_folder·local_audit 등)용 범용 도우미다.
# PDF 이동(set_document_root)은 경로·쓰기 검사→문서별 복사·해시 검증→DB 일괄 확정→이전 파일 정리 순서이다.
# DB를 건드리지 않는 파일 단계는 document_mover.py(prepare_root·copy_document·remove_old_copies)가, DB 확정(_commit_root)은 이 파일이 맡는다.
# results.summary 열은 목록 화면용 요약 JSON이며, 요약이 없는 옛 행은 result_summaries가 첫 조회 때 data로 계산해 채운다.
# 유지보수: 함수·데이터 계약이 바뀌면 해당 기능명세와 실제 회귀 검사를 함께 갱신한다.

import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from . import document_mover
from .contract_utils import contract_sort_key

# documents 테이블에서 읽는 열 순서. document()·documents_by_sources()·_documents()·save_document()가 같은 순서를 쓴다.
DOC_COLUMNS = ("id", "source", "name", "hash", "extraction", "disk_path", "kind")
DOC_SELECT = "SELECT " + ",".join(DOC_COLUMNS) + " FROM documents"
# SQLite 바인딩 변수 개수 제한(구버전 999)을 넘지 않도록 IN 조회를 나누는 단위.
SQL_CHUNK = 900


# [기능명세] now
# 목적: 시간대가 포함된 로컬 기록 시각 생성
# 입력: ()
# 출력: 초 단위 ISO 8601 문자열
# 처리: 현재 시각→시스템 시간대→isoformat
# 예외/실패: 시스템 시각이 기준
# 부수효과: 없음
def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


# [자료형/클래스 명세] Store: 로컬 저장소. 스레드 공유 SQLite 연결·RLock·앱 루트를 소유하고 JSON 레코드 및 PDF 경로 일관성을 관리한다.
class Store:
    # [기능명세] Store.__init__
    # 목적: 앱 저장 폴더와 SQLite 스키마 준비
    # 입력: (self, root=None)
    # 출력: None
    # 처리: 명시 root→환경변수→기본 루트 선택, 폴더·RLock·WAL DB·테이블과 contract_status 생성, 옛 documents 테이블에 없는 열 추가
    # 예외/실패: 폴더 권한·DB 오류 전파; 과거 문서 테이블에 disk_path·kind 열이 없으면, results 테이블에 summary 열이 없으면 ALTER TABLE로 추가(기존 행 값은 NULL)
    # 부수효과: 폴더·DB·스키마 생성/변경
    def __init__(self, root=None):
        self.root = Path(root or os.environ.get("SAEBOM_DATA_DIR") or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SaebomCompare")
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "documents").mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / "saebom.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        # 저장 계약: items=최신 목록, documents=현재 경로·추출값·종류, results=변경하지 않는 결과 JSON, meta=설정·작업,
        # contract_imports='계약서 목록' 메뉴로 가져온 계약 행(관리번호·행 JSON·가져온 시각). snapshot()이 지우지 않는 별도 테이블이다.
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS items(kind TEXT, id TEXT, data TEXT, PRIMARY KEY(kind,id));
        CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, source TEXT UNIQUE, name TEXT, hash TEXT, extraction TEXT, disk_path TEXT, kind TEXT);
        CREATE TABLE IF NOT EXISTS results(id TEXT PRIMARY KEY, created TEXT, data TEXT, summary TEXT);
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS contract_imports(id TEXT PRIMARY KEY, data TEXT, imported TEXT);
        CREATE TABLE IF NOT EXISTS contract_status(id TEXT PRIMARY KEY, status TEXT, data TEXT, updated TEXT);
        """)
        # 과거 버전 DB 호환: 없는 열만 추가한다. kind가 NULL인 옛 문서는 저장 위치 이동 시 기존 추측 로직으로 종류를 정한다.
        columns = {r[1] for r in self.db.execute("PRAGMA table_info(documents)")}
        for column in ("disk_path", "kind"):
            if column not in columns:
                self.db.execute(f"ALTER TABLE documents ADD COLUMN {column} TEXT")
        # results.summary: 목록용 요약 JSON. 옛 DB에는 없으므로 추가하며 기존 행은 NULL로 두고 result_summaries가 첫 조회 때 채운다.
        if "summary" not in {r[1] for r in self.db.execute("PRAGMA table_info(results)")}:
            self.db.execute("ALTER TABLE results ADD COLUMN summary TEXT")
        self.db.commit()

    # [기능명세] Store.snapshot
    # 목적: 메일·계약 스냅샷을 함께 교체
    # 입력: (self, mails, contracts)
    # 출력: None
    # 처리: 단일 트랜잭션에서 items 전체 삭제 후 두 목록 삽입·동기화 시각 저장
    # 예외/실패: 삽입 실패 시 DB 트랜잭션 취소
    # 부수효과: items/meta 갱신; PDF·과거 비교 이력·contract_imports(가져온 계약 기록)는 유지
    def snapshot(self, mails, contracts):
        # Commit both lists together; a failed synchronization leaves the old snapshot intact.
        with self.lock, self.db:
            self.db.execute("DELETE FROM items")
            self.db.executemany("INSERT INTO items VALUES(?,?,?)", [(k, x["id"], json.dumps(x, ensure_ascii=False)) for k, xs in (("mails", mails), ("contracts", contracts)) for x in xs])
            self.db.execute("INSERT OR REPLACE INTO meta VALUES('synced',?)", (now(),))

    # [기능명세] Store.items
    # 목적: 종류별 저장 목록 조회
    # 입력: (self, kind)
    # 출력: JSON 역직렬화 사전 목록
    # 처리: kind를 매개변수로 SELECT 후 JSON 파싱
    # 예외/실패: DB·손상 JSON 오류 전파
    # 부수효과: DB 읽기
    def items(self, kind):
        with self.lock:
            rows = self.db.execute("SELECT data FROM items WHERE kind=?", (kind,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    # [기능명세] Store.synced
    # 목적: 마지막 목록 동기화 시각 조회
    # 입력: (self)
    # 출력: 시각 문자열 또는 None
    # 처리: meta.synced 조회
    # 예외/실패: 값이 없으면 None; DB 오류 전파
    # 부수효과: DB 읽기
    def synced(self):
        with self.lock:
            r = self.db.execute("SELECT value FROM meta WHERE key='synced'").fetchone()
        return r[0] if r else None

    # [기능명세] Store.meta_get
    # 목적: meta 테이블에 JSON으로 저장한 값 읽기(로컬 세금계산서 대조의 local_invoice_folder·local_audit 등)
    # 입력: (self, key: meta 키 문자열)
    # 출력: JSON 복원 값 또는 None(키 없음)
    # 처리: RLock 안에서 meta.value SELECT → json.loads
    # 예외/실패: JSON이 아닌 옛 값(document_root·synced 같은 문자열 키)에 쓰면 JSON 오류 전파 — 그런 키는 전용 메서드를 쓴다
    # 부수효과: DB 읽기
    def meta_get(self, key):
        with self.lock:
            row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    # [기능명세] Store.meta_set
    # 목적: meta 테이블에 값을 JSON으로 저장
    # 입력: (self, key: meta 키 문자열, value: JSON 직렬화 가능한 값)
    # 출력: None
    # 처리: RLock과 SQLite 트랜잭션 안에서 INSERT OR REPLACE(ensure_ascii=False)
    # 예외/실패: 직렬화·DB 오류 전파(트랜잭션 취소로 기존 값 유지)
    # 부수효과: meta 갱신
    def meta_set(self, key, value):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, json.dumps(value, ensure_ascii=False)))

    # [기능명세] Store.imported_contract_ids
    # 목적: '계약서 목록' 메뉴로 이미 가져온 계약 관리번호 조회(안 가져온 것만 선택용)
    # 입력: (self)
    # 출력: 관리번호 문자열 set
    # 처리: contract_imports.id 전체 SELECT
    # 예외/실패: DB 오류 전파
    # 부수효과: DB 읽기
    def imported_contract_ids(self):
        with self.lock:
            rows = self.db.execute("SELECT id FROM contract_imports").fetchall()
        return {r[0] for r in rows}

    # [기능명세] Store.save_contract_import
    # 목적: PDF 저장·판독을 마친 계약 한 건을 가져온 기록으로 저장
    # 입력: (self, item: 사이트 계약 행 {id, kind, partner, title, period, amount_text, file})
    # 출력: None
    # 처리: id=item["id"], data=행 JSON, imported=now()로 INSERT OR REPLACE(같은 관리번호를 다시 가져오면 행과 시각을 갱신)
    # 예외/실패: id 키 부재는 KeyError; 직렬화·DB 오류 전파
    # 부수효과: contract_imports 갱신; PDF·documents는 호출자(download_one)가 담당
    def save_contract_import(self, item):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO contract_imports VALUES(?,?,?)", (item["id"], json.dumps(item, ensure_ascii=False), now()))

    # [기능명세] Store.contract_statuses
    # 목적: 계약별 마지막 상신 결과를 목록용으로 한 번에 조회한다.
    # 입력: self. 출력: 관리번호별 {status, approval} 사전.
    # 처리: 잠금 안에서 전체 상태 행을 읽고 JSON을 복원한다.
    # 예외/실패: DB·손상 JSON 오류 전파. 부수효과: DB 읽기.
    def contract_statuses(self):
        with self.lock:
            rows = self.db.execute("SELECT id, status, data FROM contract_status").fetchall()
        return {id: {"status": status, "approval": json.loads(data) if data else None} for id, status, data in rows}

    # [기능명세] Store.save_contract_status
    # 목적: 계약의 마지막 상신·검토 결과를 원자적으로 저장한다.
    # 입력: 관리번호, 상태(품의완료/없음), JSON 직렬화 가능한 data 또는 None.
    # 출력: 없음. 처리: 상태 검사 후 열 이름을 명시해 INSERT OR REPLACE한다.
    # 예외/실패: 알 수 없는 상태 ValueError, JSON·DB 오류 전파. 부수효과: contract_status 갱신.
    def save_contract_status(self, contract_id, status, data):
        if status not in {"품의완료", "없음"}:
            raise ValueError("계약 상태가 잘못되었습니다.")
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO contract_status(id,status,data,updated) VALUES(?,?,?,?)",
                            (contract_id, status, json.dumps(data, ensure_ascii=False) if data is not None else None, now()))

    # [기능명세] Store.contract_imports
    # 목적: 가져온 계약 기록 전체를 관리번호 큰 순으로 조회
    # 입력: (self)
    # 출력: [{...계약 행 필드, imported: 가져온 시각}] — contract_utils.contract_sort_key 기준 내림차순(형식이 다른 ID는 뒤)
    # 처리: 전체 SELECT → 행 JSON 복원 후 imported 추가 → contract_sort_key로 정렬
    # 예외/실패: DB·손상 JSON 오류 전파
    # 부수효과: DB 읽기
    def contract_imports(self):
        with self.lock:
            rows = self.db.execute("SELECT data, imported FROM contract_imports").fetchall()
        items = [{**json.loads(data), "imported": imported} for data, imported in rows]
        return sorted(items, key=lambda x: contract_sort_key(x.get("id")))

    # [기능명세] Store._row_to_doc
    # 목적: documents 행 튜플을 문서 사전으로 변환
    # 입력: (row: DOC_COLUMNS 순서의 튜플)
    # 출력: {id, source, name, hash, extraction(복원된 사전), disk_path, kind} 사전
    # 처리: extraction 열만 JSON 파싱하고 나머지 값은 그대로 담음
    # 예외/실패: 손상 JSON은 json 오류 전파
    # 부수효과: 없음
    @staticmethod
    def _row_to_doc(row):
        doc = dict(zip(DOC_COLUMNS, row))
        doc["extraction"] = json.loads(doc["extraction"])
        return doc

    # [기능명세] Store.document
    # 목적: 문서 ID 또는 원본 URL로 문서 조회
    # 입력: (self, *, source=None, id=None)
    # 출력: 문서 사전({id, source, name, hash, extraction, disk_path, kind}) 또는 None
    # 처리: source가 있으면 URL 우선, 없으면 ID로 검색하고 extraction JSON 복원
    # 예외/실패: 레코드 부재는 None; JSON·DB 오류 전파
    # 부수효과: DB 읽기
    def document(self, *, source=None, id=None):
        with self.lock:
            r = self.db.execute(DOC_SELECT + " WHERE " + ("source=?" if source else "id=?"), (source or id,)).fetchone()
        return self._row_to_doc(r) if r else None

    # [기능명세] Store.documents_by_sources
    # 목적: 여러 원본 URL의 문서를 한 번에 조회해 목록 화면의 N+1 조회를 없앰
    # 입력: (self, sources: 원본 URL 반복 가능 객체; None·빈 문자열·중복은 무시)
    # 출력: {source: 문서 사전} — 문서 사전 형태는 document()와 같고(kind 포함), 저장되지 않은 URL은 키가 없음
    # 처리: 중복 제거→SQL_CHUNK(900)개씩 `WHERE source IN (...)` 조회(900개 이하면 SQL 1회)→JSON 복원
    # 예외/실패: 빈 입력은 DB 접근 없이 {}; DB·JSON 오류 전파
    # 부수효과: DB 읽기
    def documents_by_sources(self, sources):
        keys = list(dict.fromkeys(s for s in sources if s))
        found = {}
        if not keys:
            return found
        with self.lock:
            for start in range(0, len(keys), SQL_CHUNK):
                chunk = keys[start:start + SQL_CHUNK]
                rows = self.db.execute(DOC_SELECT + " WHERE source IN (" + ",".join("?" * len(chunk)) + ")", chunk).fetchall()
                for r in rows:
                    doc = self._row_to_doc(r)
                    found[doc["source"]] = doc
        return found

    # [기능명세] Store._documents
    # 목적: 저장된 모든 문서를 한 번에 조회(저장 위치 이동용)
    # 입력: (self)
    # 출력: 문서 사전 목록(rowid 순)
    # 처리: documents 전체 SELECT 후 JSON 복원
    # 예외/실패: DB·JSON 오류 전파
    # 부수효과: DB 읽기
    def _documents(self):
        with self.lock:
            rows = self.db.execute(DOC_SELECT + " ORDER BY rowid").fetchall()
        return [self._row_to_doc(r) for r in rows]

    # [기능명세] Store.save_document
    # 목적: 문서 경로·해시·추출값·종류 저장
    # 입력: (self, source, name, digest, extraction, disk_path=None, kind=None) — kind는 "invoice"/"contract"(files.KIND_FOLDERS 키)
    # 출력: 저장 후 조회한 문서 사전
    # 처리: 같은 source의 ID 유지 또는 UUID 생성→kind가 None이면 기존 레코드의 kind 유지→열 이름을 명시한 INSERT OR REPLACE
    # 예외/실패: DB·JSON 직렬화 오류 전파; kind 값은 검증하지 않음(알 수 없는 값이면 이동 시 추측 로직 사용)
    # 부수효과: documents 갱신; 실제 PDF 쓰기는 호출자가 담당
    def save_document(self, source, name, digest, extraction, disk_path=None, kind=None):
        old = self.document(source=source)
        docid = old["id"] if old else uuid4().hex
        if kind is None and old:
            kind = old.get("kind")
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO documents(" + ",".join(DOC_COLUMNS) + ") VALUES(?,?,?,?,?,?,?)",
                            (docid, source, name, digest, json.dumps(extraction, ensure_ascii=False), str(disk_path) if disk_path else None, kind))
        return self.document(id=docid)

    # [기능명세] Store.set_document_kind
    # 목적: 종류(kind)가 비어 있는 기존 문서에만 종류를 채움(이미 값이 있으면 건드리지 않음)
    # 입력: (self, id: 문서 ID, kind: "invoice"/"contract")
    # 출력: None
    # 처리: kind 열이 NULL 또는 빈 문자열인 행만 UPDATE
    # 예외/실패: 없는 ID나 이미 값이 있는 문서는 변경 없음; DB 오류 전파
    # 부수효과: documents.kind 갱신
    def set_document_kind(self, id, kind):
        if not kind:
            return
        with self.lock, self.db:
            self.db.execute("UPDATE documents SET kind=? WHERE id=? AND (kind IS NULL OR kind='')", (kind, id))

    # [기능명세] Store.path
    # 목적: 이력 문서의 현재 파일 경로 해석
    # 입력: (self, doc)
    # 출력: Path
    # 처리: 문서 ID의 최신 레코드 우선→disk_path 또는 과거 해시 경로
    # 예외/실패: 경로를 계산할 뿐 존재 여부는 확인하지 않음
    # 부수효과: DB 읽기; 파일·이력 원본 수정 없음
    def path(self, doc):
        # Result history contains snapshots of document metadata. Resolve its
        # current path so a storage migration also works for old results.
        if doc.get("id"):
            doc = self.document(id=doc["id"]) or doc
        return Path(doc["disk_path"]) if doc.get("disk_path") else self.root / "documents" / (doc["hash"] + ".pdf")

    # [기능명세] Store.document_root
    # 목적: 현재 원본 PDF 기본 폴더 조회
    # 입력: (self)
    # 출력: Path
    # 처리: meta.document_root 우선, 없으면 앱 루트/원본PDF
    # 예외/실패: DB 오류 전파
    # 부수효과: DB 읽기
    def document_root(self):
        with self.lock:
            row = self.db.execute("SELECT value FROM meta WHERE key='document_root'").fetchone()
        return Path(row[0]) if row else self.root / "원본PDF"

    # [기능명세] Store._commit_root
    # 목적: 모든 문서의 새 경로와 루트 설정을 한 트랜잭션으로 확정(이동 단계 3)
    # 입력: (self, moves: (ID, 원본, 대상) 목록, root: 새 루트 Path)
    # 출력: None
    # 처리: documents.disk_path 일괄 UPDATE와 meta.document_root 저장을 같은 `with self.db` 트랜잭션에서 수행
    # 예외/실패: DB 오류 시 둘 다 롤백되어 기존 설정 유지; 오류 전파
    # 부수효과: documents/meta 변경
    def _commit_root(self, moves, root):
        with self.db:
            self.db.executemany("UPDATE documents SET disk_path=? WHERE id=?", [(str(t), id) for id, _, t in moves])
            self.db.execute("INSERT OR REPLACE INTO meta VALUES('document_root',?)", (str(root),))

    # [기능명세] Store.set_document_root
    # 목적: 새 PDF 저장 위치 적용과 등록 원본 전체 이동
    # 입력: (self, folder)
    # 출력: 확정된 절대경로 문자열
    # 처리: document_mover.prepare_root(경로·쓰기 검사)→잠금 안에서 모든 문서를 document_mover.copy_document(복사·해시 검증; 현재 경로는 self.path로 해석)→_commit_root(DB 경로·설정 일괄 확정)→document_mover.remove_old_copies(이전 원본 정리)
    # 예외/실패: 누락·변조·내용 충돌은 ValueError; 복사/권한 오류는 OSError; 확정 전 실패 시 이번에 만든 복사본만 지우고 기존 원본·설정 유지
    # 부수효과: 폴더·PDF·documents/meta 변경; 확정 후 잠긴 이전 복사본은 남을 수 있음
    def set_document_root(self, folder):
        path = document_mover.prepare_root(folder)
        created = []
        moves = []
        with self.lock:
            try:
                contracts = {c["file"]["url"] for c in self.items("contracts") if c.get("file")}
                invoices = {a["url"] for m in self.items("mails") for a in m.get("attachments", [])}
                # 모든 복사가 검증되기 전에는 기존 원본을 지우지 않는다.
                for doc in self._documents():
                    moves.append(document_mover.copy_document(doc, self.path(doc).resolve(), path, invoices, contracts, created))
                self._commit_root(moves, path)
            except Exception:
                for target in created:
                    target.unlink(missing_ok=True)
                raise
            document_mover.remove_old_copies(moves)
        return str(path.resolve())

    # [기능명세] Store.save_result
    # 목적: 새 비교 이력을 추가 저장
    # 입력: (self, result)
    # 출력: id/created가 추가된 결과 사전
    # 처리: 새 UUID·시각 생성 후 results에 data(전체 JSON)와 summary(_summarize 요약 JSON)를 함께 INSERT
    # 예외/실패: 직렬화·DB 오류 전파
    # 부수효과: 새 결과 추가; 이전 결과 덮어쓰기 없음
    def save_result(self, result):
        result = {**result, "id": uuid4().hex, "created": now()}
        with self.lock, self.db:
            self.db.execute("INSERT INTO results(id,created,data,summary) VALUES(?,?,?,?)",
                            (result["id"], result["created"], json.dumps(result, ensure_ascii=False), json.dumps(self._summarize(result), ensure_ascii=False)))
        return result

    # [기능명세] Store._summarize
    # 목적: 결과 한 건에서 목록 화면용 요약 계산(save_result와 옛 행 보충이 같은 규칙을 쓰도록 한곳에 둠)
    # 입력: (result: id·created가 있는 결과 사전)
    # 출력: {id, created, parent(없으면 None), count(행 수), mismatch(status=='불일치' 행 수), partners(앞 3개 행의 partner), mail_ids(전체 행의 mail_id, 행 순서),
    #        verdicts([{mail_id, contract_id, status}] 행 순서 — 계약서 목록의 문서비교 판정 표시용)}
    # 처리: rows만 훑어 요약 필드를 계산(문서·추출값·pages 같은 큰 필드는 담지 않음)
    # 예외/실패: id·created 키 부재는 KeyError
    # 부수효과: 없음
    @staticmethod
    def _summarize(result):
        result_rows = result.get("rows") or []
        return {
            "id": result["id"],
            "created": result["created"],
            "parent": result.get("parent"),
            "count": len(result_rows),
            "mismatch": sum(1 for r in result_rows if r.get("status") == "불일치"),
            "partners": [r.get("partner") for r in result_rows[:3]],
            "mail_ids": [r.get("mail_id") for r in result_rows],
            "verdicts": [{"mail_id": r.get("mail_id"), "contract_id": r.get("contract_id"), "status": r.get("status")} for r in result_rows],
        }

    # [기능명세] Store.results
    # 목적: 비교 이력 전체를 최신순 조회
    # 입력: (self)
    # 출력: 결과 사전 목록
    # 처리: created 내림차순 후 rowid 내림차순으로 정렬·JSON 복원
    # 예외/실패: DB·JSON 오류 전파
    # 부수효과: DB 읽기; 페이지네이션 없이 전체 반환. HTTP 목록은 result_summaries를 쓰며 이 메서드는 다른 스크립트 호환용으로 유지
    def results(self):
        with self.lock:
            rows = self.db.execute("SELECT data FROM results ORDER BY created DESC,rowid DESC").fetchall()
        return [json.loads(r[0]) for r in rows]

    # [기능명세] Store.result
    # 목적: 결과 한 건 조회
    # 입력: (self, id: 결과 ID)
    # 출력: 결과 사전 또는 None
    # 처리: results.id로 SELECT 후 JSON 복원(호출마다 새 사전이므로 호출자가 바꿔도 저장본에 영향 없음)
    # 예외/실패: 레코드 부재는 None; DB·JSON 오류 전파
    # 부수효과: DB 읽기
    def result(self, id):
        with self.lock:
            r = self.db.execute("SELECT data FROM results WHERE id=?", (id,)).fetchone()
        return json.loads(r[0]) if r else None

    # [기능명세] Store.result_summaries
    # 목적: 목록·이력 화면용 가벼운 결과 요약을 최신순 조회
    # 입력: (self)
    # 출력: [{id, created, parent(없으면 None), count(행 수), mismatch(status=='불일치' 행 수), partners(앞 3개 행의 partner), mail_ids(전체 행의 mail_id, 행 순서)}]
    # 처리: created 내림차순·rowid 내림차순으로 (id, summary) 조회→summary가 있으면 큰 data를 읽지 않고 JSON 복원만 수행
    #       summary가 NULL이거나 verdicts 키가 없는 옛 행은 같은 잠금·한 트랜잭션에서 data로 _summarize를 계산해 summary에 채운 뒤 사용(이후 조회는 빠름)
    # 예외/실패: DB·JSON 오류 전파(보충 중 오류는 트랜잭션이 취소되어 summary는 이전 값으로 남음)
    # 부수효과: DB 읽기; 첫 조회 때 옛 행의 summary 열 갱신(data·created는 바꾸지 않음)
    def result_summaries(self):
        with self.lock:
            rows = self.db.execute("SELECT id, summary FROM results ORDER BY created DESC,rowid DESC").fetchall()
            missing = [rid for rid, summary in rows if summary is None or '"verdicts"' not in summary]
            filled = {}
            if missing:
                with self.db:
                    for rid in missing:
                        data = self.db.execute("SELECT data FROM results WHERE id=?", (rid,)).fetchone()[0]
                        filled[rid] = self._summarize(json.loads(data))
                        self.db.execute("UPDATE results SET summary=? WHERE id=?", (json.dumps(filled[rid], ensure_ascii=False), rid))
        return [filled[rid] if rid in filled else json.loads(summary) for rid, summary in rows]

    # [기능명세] Store.contract_verdicts
    # 목적: 계약서 목록에 보일 계약별 문서비교 판정 계산
    # 입력: (self)
    # 출력: {계약 관리번호: {status, result_id, mail_id, created, count(비교된 메일 수), counts({판정: 건수})}} — 비교된 적 없는 계약은 키가 없음
    # 처리: result_summaries(최신순)의 verdicts를 훑어 (mail_id, contract_id) 쌍마다 가장 최신 행 1건만 고른다(보정으로 만든 새 결과가 원본 판정을 대체).
    #       계약별로 고른 쌍 중 가장 나쁜 판정(불일치>처리 실패>확인 필요>일치)을 대표값으로 하고 같은 순위면 최신 쌍을 쓴다
    # 예외/실패: contract_id·status가 없는 행은 건너뜀; DB·JSON 오류 전파
    # 부수효과: DB 읽기(옛 요약 보충은 result_summaries와 같음). 데이터 변경 없음
    def contract_verdicts(self):
        rank = {"불일치": 0, "처리 실패": 1, "확인 필요": 2, "일치": 3}
        seen, out = set(), {}
        for summary in self.result_summaries():
            for v in summary.get("verdicts") or []:
                cid, status, mail = v.get("contract_id"), v.get("status"), v.get("mail_id")
                if not cid or status not in rank or (mail, cid) in seen:
                    continue
                seen.add((mail, cid))
                entry = out.setdefault(cid, {"status": status, "result_id": summary["id"], "mail_id": mail, "created": summary["created"], "count": 0, "counts": {}})
                entry["count"] += 1
                entry["counts"][status] = entry["counts"].get(status, 0) + 1
                if rank[status] < rank[entry["status"]]:
                    entry.update(status=status, result_id=summary["id"], mail_id=mail, created=summary["created"])
        return out

    # [기능명세] Store.close
    # 목적: SQLite 연결 닫기
    # 입력: (self)
    # 출력: None
    # 처리: db.close 호출
    # 예외/실패: 이미 닫힌 연결의 이후 사용은 지원하지 않음
    # 부수효과: DB 연결 해제
    def close(self):
        self.db.close()
