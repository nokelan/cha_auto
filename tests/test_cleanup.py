# [파일 기능명세] 3단계 설정·빌드 탐색 회귀 검사. 자식 Python과 가짜 PATH 조회만 사용하며 실제 빌드·사이트·사용자 DB를 변경하지 않는다.
import json
import os
import subprocess
import sys

import pytest

from scripts import build


# [기능명세] test_config_environment
# 목적: 모듈 로드 시 환경변수 덮어쓰기와 빈 값 기본값을 검증한다.
# 입력: pytest 매개변수. 출력: 없음. 처리: 자식 Python에서 config만 읽는다.
# 예외/실패: 값 불일치 단언 실패. 부수효과: 일시적인 자식 프로세스만 생성.
@pytest.mark.parametrize("biz,prefix,expected", [
    ("111-81-12345", "[운영팀]", ["111-81-12345", "[운영팀]"]),
    ("", "", ["000-81-00001", "[IT기획팀]"]),
])
def test_config_environment(biz, prefix, expected):
    env = dict(os.environ, SAEBOM_OWN_BIZ=biz, SAEBOM_EXPENSE_PREFIX=prefix)
    result = subprocess.check_output([
        sys.executable, "-X", "utf8", "-c",
        "import json; from saebom import config; print(json.dumps([config.OWN_BIZ, config.EXPENSE_PREFIX]))",
    ], env=env, text=True, encoding="utf-8")
    assert json.loads(result) == expected


# [기능명세] test_find_npm
# 목적: 운영체제 기본 이름·대체 이름과 미설치 오류를 검증한다.
# 입력: monkeypatch. 출력: 없음. 처리: shutil.which만 가짜 탐색기로 교체한다.
# 예외/실패: 단언 실패. 부수효과: 테스트 종료 시 자동 복구되는 패치만 사용.
def test_find_npm(monkeypatch):
    preferred = "npm.cmd" if os.name == "nt" else "npm"
    fallback = "npm" if os.name == "nt" else "npm.cmd"
    monkeypatch.setattr(build.shutil, "which", lambda name: "/tools/" + name)
    assert build.find_npm() == "/tools/" + preferred
    monkeypatch.setattr(build.shutil, "which", lambda name: "/tools/" + name if name == fallback else None)
    assert build.find_npm() == "/tools/" + fallback
    monkeypatch.setattr(build.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="npm을 찾을 수 없습니다"):
        build.find_npm()
