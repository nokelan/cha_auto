# [파일 기능명세]
# 원본 PDF 저장 위치 이동의 파일시스템 단계. DB·락을 전혀 다루지 않는 순수 파일 작업만 모았다
# (이전에는 store.py의 Store._prepare_root/_kind_folder/_copy_document/_remove_old_copies였다).
# 이동 순서(복사→해시 검증→DB 반영→이전 사본 삭제) 중 DB 반영은 Store._commit_root가 맡고, 이 모듈은 나머지 세 단계를 제공한다.
#   1) prepare_root: 새 루트의 경로 형식·쓰기 권한·종류별 하위 폴더 준비
#   2) copy_document: 문서 한 건을 새 위치로 복사하고 해시 재검증(이번에 만든 파일은 created에 기록)
#   4) remove_old_copies: DB 확정 후 이전 사본 정리(실패는 무시)
# 호출자(Store.set_document_root)가 락을 잡고 순서를 지키며, 확정 전 실패 시 created 파일을 지우는 롤백도 호출자가 한다.
# 유지보수: 오류 문구·단계 순서를 바꾸면 tests/test_app.py의 저장 위치 이동 시험과 tests/test_refactor_domain.py를 함께 갱신한다.

import hashlib
import shutil
from pathlib import Path
from uuid import uuid4

from .files import KIND_FOLDERS, safe_name


# [기능명세] prepare_root
# 목적: 새 저장 위치의 경로 형식과 실제 쓰기 권한 검사(이동 단계 1)
# 입력: (folder: 경로 문자열)
# 출력: resolve된 절대경로 Path(세금계산서/계약서 하위 폴더 준비 완료)
# 처리: ~ 확장→절대경로·UNC(\\) 검사→폴더 생성→임시 파일 쓰기 시험·종류별 하위 폴더 생성→finally에서 시험 파일 삭제→resolve
# 예외/실패: 상대경로·네트워크 공유는 ValueError; 폴더 생성·쓰기 실패는 OSError 전파
# 부수효과: 대상 폴더와 하위 폴더 생성; 시험 파일은 남기지 않음. 등록하지 않은 사용자 파일은 건드리지 않음
def prepare_root(folder):
    path = Path(folder).expanduser()
    if not path.is_absolute() or str(path).startswith("\\\\"):
        raise ValueError("PC의 절대 폴더 경로를 선택해 주세요. 네트워크 공유 폴더는 지원하지 않습니다.")
    path.mkdir(parents=True, exist_ok=True)
    # 설정을 바꾸기 전에 실제 쓰기 권한을 확인한다.
    probe = path / (".saebom-write-" + uuid4().hex)
    try:
        probe.write_bytes(b"")
        for name in KIND_FOLDERS.values():
            (path / name).mkdir(exist_ok=True)
    finally:
        probe.unlink(missing_ok=True)
    return path.resolve()


# [기능명세] kind_folder
# 목적: 문서를 보관할 종류 폴더 이름 결정
# 입력: (doc: 문서 사전, source: 현재 원본 Path, invoices: 메일 첨부 URL 집합, contracts: 계약 파일 URL 집합)
# 출력: "세금계산서" 또는 "계약서"
# 처리: doc["kind"]가 KIND_FOLDERS 키면 그 폴더를 사용; 없으면 기존 추측(계산서 URL 또는 이름 접두어 '세금계산서'→세금계산서, 계약 URL→계약서, 그 외 현재 상위 폴더 이름, 둘 다 아니면 계약서)
# 예외/실패: 없음(항상 두 값 중 하나)
# 부수효과: 없음
def kind_folder(doc, source, invoices, contracts):
    if doc.get("kind") in KIND_FOLDERS:
        return KIND_FOLDERS[doc["kind"]]
    kind = "세금계산서" if doc["source"] in invoices or doc["name"].startswith("세금계산서") else "계약서" if doc["source"] in contracts else source.parent.name
    return kind if kind in KIND_FOLDERS.values() else "계약서"


# [기능명세] copy_document
# 목적: 문서 하나를 새 위치로 복사하고 해시를 검증(이동 단계 2)
# 입력: (doc: 문서 사전, source: 현재 원본 파일의 resolve된 Path(Store.path(doc).resolve()), root: 새 루트 Path,
#        invoices·contracts: 종류 추측용 URL 집합, created: 이번에 만든 파일을 기록할 리스트)
# 출력: (문서 ID, 현재 원본 Path, 대상 Path) 튜플
# 처리: 원본 존재·해시 확인→대상=root/종류 폴더/해시 앞 12자_safe_name(이름)→같은 경로면 그대로 반환→대상이 이미 있으면 같은 내용일 때만 재사용→없으면 배타 생성(xb)으로 복사 후 복사본 해시 재검증
# 예외/실패: 원본 누락·원본 변조·내용이 다른 동명 파일은 ValueError; 복사 오류·복사본 불일치는 OSError. 원본은 지우지 않음
# 부수효과: 새 대상 파일 생성; 생성 직후 created에 추가해 이후 실패 시 호출자가 정리할 수 있게 함
def copy_document(doc, source, root, invoices, contracts, created):
    if not source.is_file():
        raise ValueError(f"원본 파일을 찾을 수 없어 저장 위치를 유지합니다: {doc['name']}. 문서를 다시 다운로드한 뒤 시도해 주세요.")
    with source.open("rb") as original:
        if hashlib.file_digest(original, "sha256").hexdigest() != doc["hash"]:
            raise ValueError(f"원본 파일 내용이 달라 저장 위치를 유지합니다: {doc['name']}")
    target = root / kind_folder(doc, source, invoices, contracts) / (doc["hash"][:12] + "_" + safe_name(doc["name"]))
    if source == target:
        return doc["id"], source, target
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
    return doc["id"], source, target


# [기능명세] remove_old_copies
# 목적: 확정 후 이전 원본 정리(이동 단계 4)
# 입력: (moves: (ID, 원본, 대상) 목록)
# 출력: None
# 처리: 새 대상 경로 집합은 보호하고, 원본≠대상인 이전 파일만 삭제
# 예외/실패: 잠긴 파일 등 OSError는 무시(확정된 새 경로를 무효화하지 않음)
# 부수효과: 이전 PDF 삭제; 잠긴 이전 파일은 중복으로 남을 수 있음
def remove_old_copies(moves):
    destinations = {target for _, _, target in moves}
    for _, source, target in moves:
        if source != target and source not in destinations:
            try:
                source.unlink(missing_ok=True)
            except OSError:
                # 검증된 새 복사본은 이미 확정됐다. 잠긴 옛 파일이 남아도 새 경로는 유효하다.
                pass
