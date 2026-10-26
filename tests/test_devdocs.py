# [파일 기능명세] 개발문서 열람 API(saebom/routes/devdocs.py) 검사. 임시 폴더를 SAEBOM_DEVDOCS_DIR로 지정해 실제 문서를 건드리지 않는다.
# 목록 필터·정렬·제목 추출, 본문 UTF-8 응답, 잠금 미해제 401, 경로 우회 404를 검증한다.
from fastapi.testclient import TestClient

from tests.test_hardening_api import make_app, unlocked_client


# [기능명세] docs_dir
# 목적: 시험용 문서 폴더 구성. 입력: (tmp_path, monkeypatch). 출력: Path
# 처리: 정상 문서 2건(한글 파일명 포함)·제목 없는 문서·패턴 불일치 파일·하위 폴더 문서를 만들고 환경변수 지정
# 예외/실패: 없음. 부수효과: tmp_path 파일 생성, 환경변수 설정(monkeypatch가 복원)
def docs_dir(tmp_path, monkeypatch):
    folder = tmp_path / "docs"
    (folder / "_초안_리팩토링전").mkdir(parents=True)
    (folder / "00_문서목록.md").write_text("# 문서 목록\n본문 한글", encoding="utf-8")
    (folder / "01_notes.md").write_text("제목 없음", encoding="utf-8")
    (folder / "readme.md").write_text("# 제외", encoding="utf-8")
    (folder / "02_x.txt").write_text("제외", encoding="utf-8")
    (folder / "_초안_리팩토링전" / "03_old.md").write_text("# 제외", encoding="utf-8")
    monkeypatch.setenv("SAEBOM_DEVDOCS_DIR", str(folder))
    return folder


# [기능명세] test_list_and_read
# 목적: 목록(필터·정렬·제목·크기)과 한글 파일명 본문 조회 검증. 입력: (tmp_path, monkeypatch). 출력: None
# 처리: 목록 호출 후 본문 호출. 예외/실패: 조건 위반 시 AssertionError. 부수효과: 임시 파일
def test_list_and_read(tmp_path, monkeypatch):
    folder = docs_dir(tmp_path, monkeypatch)
    app, _ = make_app(tmp_path)
    with unlocked_client(app) as client:
        docs = client.get("/api/devdocs").json()["docs"]
        assert [d["name"] for d in docs] == ["00_문서목록.md", "01_notes.md"]
        assert docs[0]["title"] == "문서 목록"
        assert docs[1]["title"] == "01_notes.md"
        assert docs[0]["size"] == (folder / "00_문서목록.md").stat().st_size
        r = client.get("/api/devdocs/00_문서목록.md")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/markdown")
        assert "charset=utf-8" in r.headers["content-type"]
        assert r.content.decode("utf-8") == "# 문서 목록\n본문 한글"


# [기능명세] test_requires_unlock
# 목적: 잠금 해제 쿠키가 없으면 401인지 검증. 입력: (tmp_path, monkeypatch). 출력: None
# 처리: 실행 토큰만 진입하고 로그인하지 않은 클라이언트로 두 경로 호출. 부수효과: 임시 파일
def test_requires_unlock(tmp_path, monkeypatch):
    docs_dir(tmp_path, monkeypatch)
    app, _ = make_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:12345") as client:
        client.get("/?token=test-secret")
        assert client.get("/api/devdocs").status_code == 401
        assert client.get("/api/devdocs/00_문서목록.md").status_code == 401


# [기능명세] test_bad_names_404
# 목적: 경로 우회·확장자 불일치·하위 폴더·없는 이름이 모두 404인지 검증. 입력: (tmp_path, monkeypatch). 출력: None
# 처리: 우회 문자열을 순서대로 호출. 예외/실패: 200이 하나라도 있으면 AssertionError. 부수효과: 임시 파일
def test_bad_names_404(tmp_path, monkeypatch):
    docs_dir(tmp_path, monkeypatch)
    (tmp_path / "x").write_text("비밀", encoding="utf-8")
    app, _ = make_app(tmp_path)
    with unlocked_client(app) as client:
        for name in ["../x", "%2e%2e%2fx", "..%5Cx", "..%2F..%2Fx.md", "02_x.txt", "readme.md",
                     "99_없음.md", "_초안_리팩토링전/03_old.md", "_초안_리팩토링전%2F03_old.md", "03_old.md"]:
            r = client.get(f"/api/devdocs/{name}")
            assert r.status_code == 404, name
            assert "비밀" not in r.text
