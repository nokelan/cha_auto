# [파일 기능명세]
# PDF.js 오프라인 자산 복사 스크립트. node_modules의 cmaps/standard_fonts/wasm을 frontend/dist/pdfjs로 복사한다. 모듈 실행 즉시 처리하며 원본 폴더 누락·권한 오류는 호출자에게 전파한다.
# 유지보수: 함수·데이터 계약이 바뀌면 해당 기능명세와 실제 회귀 검사를 함께 갱신한다.

from pathlib import Path
import shutil

# [실행 블록 명세]
# 입력: 프로젝트 frontend/node_modules/pdfjs-dist의 cmaps·standard_fonts·wasm 디렉터리.
# 출력: frontend/dist/pdfjs 아래의 동일 자산 트리. 반환값 없이 파일을 복사한다.
# 처리: 세 디렉터리를 copytree(dirs_exist_ok=True)로 순서대로 복사한다.
# 실패: 미설치 의존성·권한·디스크 오류를 전파한다. 브라우저가 CDN 없이 PDF를 표시하도록 배포에 포함한다.
root = Path(__file__).resolve().parents[1] / "frontend"
for name in ("cmaps", "standard_fonts", "wasm"):
    shutil.copytree(root / "node_modules" / "pdfjs-dist" / name, root / "dist" / "pdfjs" / name, dirs_exist_ok=True)
