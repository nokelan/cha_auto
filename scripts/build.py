# [파일 기능명세]
# Windows 배포 생성 도구. npm 잠금 설치·화면 빌드·PDF.js 자산 복사·PyInstaller(거래명세서 템플릿 포함)·라이선스 수집·ZIP을 순서대로 수행한다. dist와 build 산출물을 갱신하므로 실행 중인 배포 앱을 먼저 닫는다.
# 유지보수: 함수·데이터 계약이 바뀌면 해당 기능명세와 실제 회귀 검사를 함께 갱신한다.

"""Reproducible Windows folder distribution. Run with .venv/Scripts/python."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


# [기능명세] find_npm
# 목적: PATH에서 현재 운영체제에 맞는 npm 실행 파일 탐색
# 입력: 없음. 출력: npm 실행 파일 절대경로 문자열.
# 처리: Windows는 npm.cmd, 그 외는 npm을 먼저 찾고 대체 이름도 확인한다.
# 예외/실패: 둘 다 없으면 RuntimeError로 Node.js 설치 안내. 부수효과: 없음.
def find_npm():
    names = ("npm.cmd", "npm") if os.name == "nt" else ("npm", "npm.cmd")
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError("npm을 찾을 수 없습니다. Node.js를 설치하고 PATH를 확인해 주세요.")


# [기능명세] build
# 목적: Windows 폴더형 EXE와 배포 ZIP 생성
# 입력: ()
# 출력: None; READY/ZIP 경로를 표준 출력에 표시
# 처리: npm ci→화면 빌드→PDF 자산→Chromium 확인→PyInstaller(정적 화면·saebom/assets 거래명세서 템플릿·Chromium 포함)→문서·라이선스→ZIP
# 예외/실패: npm 없음·브라우저 미설치 RuntimeError; 하위 명령 실패 CalledProcessError; saebom/assets 폴더가 없으면 PyInstaller 실패; 파일 오류 전파
# 부수효과: 작업 디렉터리·node_modules·frontend/dist·build·dist 갱신
def build():
    os.chdir(ROOT)
    # 단계 1: package-lock.json 기준 설치·타입 검사·정적 빌드. JSON 설정은 주석을 넣지 않고 여기서 역할을 설명한다.
    npm = find_npm()
    subprocess.run([npm, "ci"], cwd=ROOT / "frontend", check=True)
    subprocess.run([npm, "run", "build"], cwd=ROOT / "frontend", check=True)
    subprocess.run([sys.executable, "scripts/copy_pdf_assets.py"], check=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = Path(p.chromium.executable_path).parents[1]
    if not browser.exists():
        raise RuntimeError("python -m playwright install chromium 명령으로 브라우저를 먼저 설치해 주세요.")
    # 단계 2: 폴더형(--onedir)·콘솔 없는(--windowed) EXE. Chromium과 정적 화면을 _internal 쪽 번들에 포함한다.
    # saebom/assets(거래명세서_템플릿.xlsx)는 statement.template_path()가 _MEIPASS/saebom/assets에서 찾는다. openpyxl은 순수 Python이라 import 분석으로 포함된다.
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed", "--name", "SaebomCompare",
                    "--collect-all", "pdfplumber", "--collect-all", "pdfminer", "--collect-all", "pypdfium2", "--collect-all", "playwright",
                    "--hidden-import", "tkinter", "--hidden-import", "tkinter.filedialog",
                    "--add-data", f"{ROOT / 'frontend' / 'dist'};frontend/dist", "--add-data", f"{ROOT / 'saebom' / 'assets'};saebom/assets", "--add-data", f"{ROOT / '개발문서'};개발문서", "--add-data", f"{browser};browser/{browser.name}", "launcher.py"], check=True)
    target = ROOT / "dist" / "SaebomCompare"
    shutil.copy2(ROOT / "사용방법.md", target / "사용방법.md")
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", target / "THIRD_PARTY_NOTICES.md")
    # Include package license files that accompany the installed distributions.
    licenses = target / "licenses"
    licenses.mkdir(exist_ok=True)
    import importlib.metadata
    for dist in importlib.metadata.distributions():
        for f in dist.files or []:
            if f.name.lower().startswith(('license', 'copying', 'notice')) and not f.is_absolute():
                source = Path(dist.locate_file(f))
                if source.is_file():
                    out = licenses / dist.metadata['Name'] / str(f).replace('../', '_')
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, out)
    for name in ("LICENSE", "LICENSE.chromium.html"):
        for source in browser.rglob(name):
            shutil.copy2(source, licenses / ("chromium-" + source.name))
    # 단계 3: 실행에 필요한 폴더 전체를 ZIP에 넣는다. EXE만 단독 복사해서 배포하면 안 된다.
    archive = ROOT / "dist" / "SaebomCompare-Windows.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in target.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(target.parent))
    print(f"READY: {target / 'SaebomCompare.exe'}")
    print(f"ZIP: {archive}")


if __name__ == '__main__':
    build()
