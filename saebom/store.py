# [파일 기능명세]
# 영속 저장 계층. SQLite의 items/documents/results/meta를 RLock으로 보호하며 원본 경로를 문서 ID로 조회한다. PDF 이동은 복사 검증→DB 확정→이전 파일 정리 순서다.
# 유지보수: 함수·데이터 계약이 바뀌면 해당 기능명세와 실제 회귀 검사를 함께 갱신한다.

import json
import hashlib
import os
import re
import shutil
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from uuid import uuid4


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
    # 처리: 명시 root→환경변수→기본 루트 선택, 폴더·RLock·WAL DB·테이블 생성
    # 예외/실패: 폴더 권한·DB 오류 전파; 과거 문서 테이블에 disk_path 없으면 추가
    # 부수효과: 폴더·DB·스키마 생성/변경
    def __init__(self, root=None):
        self.root = Path(root or os.environ.get("SAEBOM_DATA_DIR") or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SaebomCompare")
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "documents").mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / "saebom.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        # 저장 계약: items=최신 목록, documents=현재 경로·추출값, results=변경하지 않는 결과 JSON, meta=설정·작업.
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS items(kind TEXT, id TEXT, data TEXT, PRIMARY KEY(kind,id));
        CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, source TEXT UNIQUE, name TEXT, hash TEXT, extraction TEXT, disk_path TEXT);
        CREATE TABLE IF NOT EXISTS results(id TEXT PRIMARY KEY, created TEXT, data TEXT);
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        """)
        if "disk_path" not in {r[1] for r in self.db.execute("PRAGMA table_info(documents)")}:
            self.db.execute("ALTER TABLE documents ADD COLUMN disk_path TEXT")
        self.db.commit()

    # [기능명세] Store.snapshot
    # 목적: 메일·계약 스냅샷을 함께 교체
    # 입력: (self, mails, contracts)
    # 출력: None
    # 처리: 단일 트랜잭션에서 items 전체 삭제 후 두 목록 삽입·동기화 시각 저장
    # 예외/실패: 삽입 실패 시 DB 트랜잭션 취소
    # 부수효과: items/meta 갱신; PDF와 과거 비교 이력은 유지
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

    # [기능명세] Store.document
    # 목적: 문서 ID 또는 원본 URL로 문서 조회
    # 입력: (self, *, source=None, id=None)
    # 출력: 문서 사전 또는 None
    # 처리: source가 있으면 URL 우선, 없으면 ID로 검색하고 extraction JSON 복원
    # 예외/실패: 레코드 부재는 None; JSON·DB 오류 전파
    # 부수효과: DB 읽기
    def document(self, *, source=None, id=None):
        with self.lock:
            r = self.db.execute("SELECT id,source,name,hash,extraction,disk_path FROM documents WHERE " + ("source=?" if source else "id=?"), (source or id,)).fetchone()
        if not r:
            return None
        return dict(zip(("id", "source", "name", "hash", "extraction", "disk_path"), (*r[:4], json.loads(r[4]), r[5])))

    # [기능명세] Store.save_document
    # 목적: 문서 경로·해시·추출값 저장
    # 입력: (self, source, name, digest, extraction, disk_path=None)
    # 출력: 저장 후 조회한 문서 사전
    # 처리: 같은 source의 ID 유지 또는 UUID 생성 후 레코드 교체
    # 예외/실패: DB·JSON 직렬화 오류 전파
    # 부수효과: documents 갱신; 실제 PDF 쓰기는 호출자가 담당
    def save_document(self, source, name, digest, extraction, disk_path=None):
        old = self.document(source=source)
        docid = old["id"] if old else uuid4().hex
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO documents VALUES(?,?,?,?,?,?)", (docid, source, name, digest, json.dumps(extraction, ensure_ascii=False), str(disk_path) if disk_path else None))
        return self.document(id=docid)

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

    # [기능명세] Store.set_document_root
    # 목적: 새 PDF 저장 위치 적용과 등록 원본 전체 이동
    # 입력: (self, folder)
    # 출력: 확정된 절대경로 문자열
    # 처리: 로컬 절대경로·쓰기 검사→원본/복사본 해시 확인→DB 경로·설정 일괄 확정→이전 원본 정리
    # 예외/실패: 누락·변조·내용 충돌은 ValueError; 복사/권한 오류는 OSError; 확정 전 실패 시 복사본 정리와 기존 설정 유지
    # 부수효과: 폴더·PDF·documents/meta 변경; 확정 후 잠긴 이전 복사본은 남을 수 있음
    def set_document_root(self, folder):
        path = Path(folder).expanduser()
        if not path.is_absolute() or str(path).startswith("\\\\"):
            raise ValueError("PC의 절대 폴더 경로를 선택해 주세요. 네트워크 공유 폴더는 지원하지 않습니다.")
        path.mkdir(parents=True, exist_ok=True)
        # Verify actual write access before changing the setting.
        probe = path / (".saebom-write-" + uuid4().hex)
        try:
            probe.write_bytes(b"")
            for name in ("세금계산서", "계약서"):
                (path / name).mkdir(exist_ok=True)
        finally:
            probe.unlink(missing_ok=True)
        # 이동 단계 1: 대상 폴더만 먼저 준비한다. 등록하지 않은 임의 사용자 파일은 이동 대상이 아니다.
        path = path.resolve()
        created = []
        moves = []
        # First copy and verify every document. Commit paths and the setting
        # together only after all copies succeed, then remove old originals.
        with self.lock:
            try:
                contracts = {c["file"]["url"] for c in self.items("contracts") if c.get("file")}
                invoices = {a["url"] for m in self.items("mails") for a in m.get("attachments", [])}
                # 이동 단계 2: 원본 존재·해시 확인 후 종류별 복사. 전체 성공 전에는 기존 원본을 지우지 않는다.
                for row in self.db.execute("SELECT id FROM documents").fetchall():
                    doc = self.document(id=row[0])
                    source = self.path(doc).resolve()
                    if not source.is_file():
                        raise ValueError(f"원본 파일을 찾을 수 없어 저장 위치를 유지합니다: {doc['name']}. 문서를 다시 다운로드한 뒤 시도해 주세요.")
                    with source.open("rb") as original:
                        if hashlib.file_digest(original, "sha256").hexdigest() != doc["hash"]:
                            raise ValueError(f"원본 파일 내용이 달라 저장 위치를 유지합니다: {doc['name']}")
                    kind = "세금계산서" if doc["source"] in invoices or doc["name"].startswith("세금계산서") else "계약서" if doc["source"] in contracts else source.parent.name
                    if kind not in {"세금계산서", "계약서"}:
                        kind = "계약서"
                    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', doc["name"])[:160].rstrip(". ")
                    target = path / kind / (doc["hash"][:12] + "_" + name)
                    if source == target:
                        moves.append((doc["id"], source, target))
                        continue
                    if target.exists():
                        with target.open("rb") as existing:
                            identical = hashlib.file_digest(existing, "sha256").hexdigest() == doc["hash"]
                        if not identical:
                            raise ValueError(f"새 폴더에 내용이 다른 같은 이름의 파일이 있습니다: {target.name}. 기존 파일을 보존하며 저장 위치를 유지합니다.")
                    else:
                        with target.open("xb") as out:
                            created.append(target)
                            with source.open("rb") as original:
                                shutil.copyfileobj(original, out)
                        with target.open("rb") as copied:
                            if hashlib.file_digest(copied, "sha256").hexdigest() != doc["hash"]:
                                raise OSError("복사한 PDF의 내용이 일치하지 않습니다.")
                    moves.append((doc["id"], source, target))
                # 이동 단계 3: 모든 복사 검증 뒤 현재 경로와 루트 설정을 같은 DB 트랜잭션으로 확정한다.
                with self.db:
                    self.db.executemany("UPDATE documents SET disk_path=? WHERE id=?", [(str(t), id) for id, _, t in moves])
                    self.db.execute("INSERT OR REPLACE INTO meta VALUES('document_root',?)", (str(path),))
            except Exception:
                for target in created:
                    target.unlink(missing_ok=True)
                raise
            # 이동 단계 4: 확정된 대상 경로는 보호하고 이전 원본을 정리한다. 잠긴 파일은 중복으로 남을 수 있다.
            destinations = {target for _, _, target in moves}
            for _, source, target in moves:
                if source != target and source not in destinations:
                    try:
                        source.unlink(missing_ok=True)
                    except OSError:
                        # The verified new copy is committed. A locked old file
                        # may remain, but must not invalidate the new paths.
                        pass
        return str(path.resolve())

    # [기능명세] Store.save_result
    # 목적: 새 비교 이력을 추가 저장
    # 입력: (self, result)
    # 출력: id/created가 추가된 결과 사전
    # 처리: 새 UUID·시각 생성 후 results에 JSON INSERT
    # 예외/실패: 직렬화·DB 오류 전파
    # 부수효과: 새 결과 추가; 이전 결과 덮어쓰기 없음
    def save_result(self, result):
        result = {**result, "id": uuid4().hex, "created": now()}
        with self.lock, self.db:
            self.db.execute("INSERT INTO results VALUES(?,?,?)", (result["id"], result["created"], json.dumps(result, ensure_ascii=False)))
        return result

    # [기능명세] Store.results
    # 목적: 비교 이력을 최신순 조회
    # 입력: (self)
    # 출력: 결과 사전 목록
    # 처리: created 내림차순 후 rowid 내림차순으로 정렬·JSON 복원
    # 예외/실패: DB·JSON 오류 전파
    # 부수효과: DB 읽기; 페이지네이션 없이 전체 반환
    def results(self):
        with self.lock:
            rows = self.db.execute("SELECT data FROM results ORDER BY created DESC,rowid DESC").fetchall()
        return [json.loads(r[0]) for r in rows]

    # [기능명세] Store.close
    # 목적: SQLite 연결 닫기
    # 입력: (self)
    # 출력: None
    # 처리: db.close 호출
    # 예외/실패: 이미 닫힌 연결의 이후 사용은 지원하지 않음
    # 부수효과: DB 연결 해제
    def close(self):
        self.db.close()
