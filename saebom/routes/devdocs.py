# [파일 기능명세] 개발문서(개발문서/NN_*.md)를 화면에서 열람하기 위한 읽기 전용 경로를 등록한다. 인증은 api.create_app이 적용한다(/api/ 이하라 잠금 해제 쿠키 필요).
# 처리 흐름: 문서 폴더 해석(devdocs_dir) → 목록(/api/devdocs) 또는 본문(/api/devdocs/{name}) 응답. 쓰기·삭제 기능은 없다.
# 보안: 파일명은 정규식 ^\d\d_.+\.md$ 와 경로 구분자·'..' 금지·상위 폴더 일치로 이중 검증하며, 하위 폴더(`_초안_리팩토링전` 등)는 노출하지 않는다.
import os
import re
import sys
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import Response

DOC_NAME = re.compile(r"^\d\d_.+\.md$")


# [기능명세] devdocs_dir
# 목적: 개발문서 폴더 경로 계산
# 입력: ()
# 출력: Path
# 처리: 환경변수 SAEBOM_DEVDOCS_DIR가 있으면 그 경로(테스트용), 없으면 EXE(sys._MEIPASS)는 _MEIPASS/개발문서, 소스 실행은 프로젝트루트/개발문서
# 예외/실패: 존재 여부는 확인하지 않음(호출 측에서 처리)
# 부수효과: 없음
def devdocs_dir():
    override = os.environ.get("SAEBOM_DEVDOCS_DIR")
    if override:
        return Path(override)
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
    return root / "개발문서"


# [기능명세] doc_title
# 목적: 마크다운 파일의 제목 추출
# 입력: (path: 문서 경로, fallback: 제목이 없을 때 쓸 이름)
# 출력: 첫 '# ' 줄의 제목 문자열 또는 fallback
# 처리: UTF-8로 읽어 '# '로 시작하는 첫 줄(코드펜스 안은 구분하지 않음)의 앞 '# '를 떼고 공백 제거
# 예외/실패: 읽기·디코딩 오류는 fallback 반환(목록 전체가 실패하지 않게 함)
# 부수효과: 파일 읽기
def doc_title(path, fallback):
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                return line[2:].strip() or fallback
    except (OSError, UnicodeDecodeError):
        pass
    return fallback


# [기능명세] register
# 목적: 개발문서 열람 경로 등록. 경로: GET /api/devdocs, GET /api/devdocs/{name}.
# 입력: app(FastAPI), service, store와 키워드 전용 공용 인자(다른 라우트 모듈과 시그니처 통일, 이 모듈은 쓰지 않음)
# 출력: 없음. 처리: 핸들러를 클로저로 등록. 예외/실패: 각 핸들러 명세를 따른다. 부수효과: 앱 라우팅 표 변경.
def register(app, service, store, *, ask_folder=None, strip_pages=None, shutdown=None, activate=None):

    # [기능명세] register.devdocs_list
    # 목적: 열람 가능한 개발문서 목록 조회
    # 입력: ()
    # 출력: {"docs":[{name, title, size(바이트)}]} 이름 오름차순
    # 처리: 문서 폴더 바로 아래 파일 중 이름이 DOC_NAME 정규식에 맞는 것만 포함(하위 폴더 제외)
    # 예외/실패: 폴더가 없거나 읽을 수 없으면 빈 목록(200). 잠금 미해제는 미들웨어가 401
    # 부수효과: 파일 목록·첫 줄 읽기
    @app.get("/api/devdocs")
    def devdocs_list():
        folder = devdocs_dir()
        docs = []
        try:
            for path in sorted(folder.iterdir(), key=lambda p: p.name):
                if DOC_NAME.match(path.name) and path.is_file():
                    docs.append({"name": path.name, "title": doc_title(path, path.name), "size": path.stat().st_size})
        except OSError:
            return {"docs": []}
        return {"docs": docs}

    # [기능명세] register.devdocs_read
    # 목적: 개발문서 한 건의 본문 조회
    # 입력: (name: 파일명 한 구간. 퍼센트 인코딩은 서버가 이미 해제한 값)
    # 출력: text/markdown; charset=utf-8 본문(UTF-8)
    # 처리: 정규식·'/'·'\'·'..' 검사 → 문서 폴더 아래 경로 계산 → resolve한 상위 폴더가 문서 폴더인지·파일인지 확인
    # 예외/실패: 검사 실패·파일 없음·OSError·디코딩 오류는 모두 HTTP 404. 잠금 미해제는 미들웨어가 401
    # 부수효과: 파일 읽기만 수행, 폴더 밖 경로는 열지 않음
    @app.get("/api/devdocs/{name}")
    def devdocs_read(name: str):
        missing = HTTPException(404, "개발문서를 찾을 수 없습니다.")
        if "/" in name or "\\" in name or ".." in name or not DOC_NAME.match(name):
            raise missing
        folder = devdocs_dir()
        path = folder / name
        try:
            if path.resolve().parent != folder.resolve() or not path.is_file():
                raise missing
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            raise missing
        return Response(text, media_type="text/markdown; charset=utf-8")
