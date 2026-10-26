# CLAUDE.md

이 폴더(`07_auto`)는 업무 자동화 기능 실습 폴더입니다. 상위 `../CLAUDE.md`의 지침도 함께 따릅니다.

## 메모리

사용자가 준 지침은 이 폴더의 `MEMORY.md`에 기록하며, 아래 줄로 불러옵니다. 새 지침이 생기면 `MEMORY.md`에 추가하세요.

@MEMORY.md

## 큰 기능은 plan 모드로

- 범위가 큰 기능(여러 파일·여러 단계·설계 결정이 필요한 작업)을 구현하려 하면, 구현 전에 사용자에게 plan 모드(Shift+Tab)로 시작하라고 먼저 안내합니다.
- 작은 수정에는 적용하지 않습니다.

## 기획 문서 저장

- plan 모드로 기획하면 항상 이 폴더 안에 `기획/` 폴더를 만들고, 기획 내용을 md 파일로 저장합니다.
- 기획 문서는 별도 요청이 없으면 한글로 작성합니다.

## 소스코드 주석과 함수 기능명세

- 이 프로젝트에서 직접 작성한 모든 소스코드에 파일 역할과 주요 처리 흐름을 한글 주석으로 설명합니다.
- 각 함수·메서드·주요 콜백에는 목적, 입력, 출력, 처리 규칙, 예외·실패 조건, 파일·DB·네트워크·화면 상태 변경 등 부수효과를 코드 내부에 기능명세로 기록합니다.
- 새 소스를 추가하거나 기존 함수를 수정하면 관련 주석과 기능명세도 실제 구현에 맞게 함께 갱신합니다. 별도 설계문서만으로 코드 내부 명세를 대신하지 않습니다.
- 외부 라이브러리, 가상환경, 자동 생성 파일과 빌드 산출물은 주석 작성 대상에서 제외합니다. 주석 문법을 지원하지 않는 설정 파일은 관련 소스의 주석에서 역할을 설명합니다.
- 주석만 보완하는 작업에서는 실행 로직을 변경하지 않습니다.

## 구현된 앱 (2026-10-19)

- 리팩토링 후 개발문서(2026-10-26): 현재 소스 기준 설계·API·DB/ERD·UML·검증·운영 문서15종의 시작점은 `개발문서/00_문서목록.md`입니다. EXE/ZIP 재빌드·배포본검사5종·기존데이터 보존·새 앱 실행까지 완료했으며 증거와 실사이트 미검증 범위는 `개발문서/14_리팩토링_결과보고서.md`에 있습니다.
- 개발문서 열람(2026-10-26): 사이드바 7번째 메뉴 '개발문서'에서 `개발문서/*.md` 16종(Mermaid 25개 포함)을 앱 안에서 봅니다. 서버 `saebom/routes/devdocs.py`(`/api/devdocs`, 읽기 전용), 화면 `frontend/src/screens/docs/`(marked·DOMPurify·mermaid 오프라인 렌더), 검증 `scripts/verify_devdocs.py`입니다. `15_코드_색인.md`는 `scripts/gen_code_index.py`가 소스 주석에서 생성하므로 직접 고치지 말고 스크립트를 다시 실행합니다(`--check`로 최신 여부 확인). 계획은 `기획/개발문서_열람_및_미구현기능_구현계획.md`입니다.
- 같은 날 결함 수정: 상신 이전 승인 월 보존(`prior_approval`), 작성본 수신 뒤 오류의 `site_draft` 표시, 계약 목록 필터 후 표 안정화 대기, 보정 재비교 저장본 폴백, 빈 거래처 매칭 제외, 쉼표 금액 보정, 원문 `?download=1` 내려받기. 기본 비밀번호·원격 변경 감지·결과 문서 사본 중복·작업 제한시간 등은 사용자 결정 대기 항목으로 남아 있습니다.
- 전체 업무 화면(2026-10-26 추가 요청): 한 viewport 안에서 왼쪽 본문·오른쪽 관련 링크가 독립 스크롤하며, 760px 이하에서는 위아래로 배치합니다. 관련 원문·CSV·메뉴 연결은 `RelatedLinks.tsx`, 검증은 `scripts/verify_workspace_layout.py`입니다.

- 새봄 그룹웨어의 세금계산서·계약서를 대조하는 로컬 WebUI 앱입니다. AI·OCR을 사용하지 않습니다.
- Python 서버: `saebom/`, 실행 진입점: `launcher.py`. React 화면: `frontend/`.
- 실행: `.venv/Scripts/python launcher.py` (프런트 빌드 필요). 테스트: `.venv/Scripts/python -m pytest -q`.
- Windows 패키징: `.venv/Scripts/python scripts/build.py`. 배포 EXE는 `dist/SaebomCompare/SaebomCompare.exe`입니다.
- 원본 PDF는 설정한 폴더의 `세금계산서/`, `계약서/`에 보관합니다. 설정·목록·이력은 LOCALAPPDATA의 SaebomCompare에 저장합니다.
- 거래명세서 생성(2026-10-21): 계약서 목록에서 수입 계약을 골라 확인 창에서 값을 고친 뒤 거래명세서 엑셀을 PDF 저장 폴더의 `거래명세서/`에 만듭니다(`saebom/statement.py`, `StatementModal.tsx`, 화면 검증 `scripts/verify_statement.py`). 계획은 `기획/거래명세서_생성_구축계획.md`입니다.
- 로컬 세금계산서 대조(2026-10-21): 사이드바 메뉴에서 PC 폴더의 세금계산서 PDF·PNG를 웹 계약 문서함 계약서와 대조합니다(`saebom/local_audit.py`, `LocalAuditScreen.tsx`, 판정 목록은 `components/CheckList.tsx`로 비교 결과와 공용, 검증 `scripts/verify_local_audit.py`). 알고리즘은 `로컬세금계산서_대조_알고리즘.md`, 계획은 `기획/로컬세금계산서_대조_구축계획.md`, 시험 폴더는 `로컬세금계산서_샘플/`입니다.
- 기능별 분리·지출결의서 자동 상신(2026-10-21): 서버는 `services/` 믹스인·`routes/` 등록 함수, 화면은 `screens/compare/`·`screens/contracts/`로 분리했습니다. 계약 행·상세에 구분별 작업 버튼과 상태 배지를 표시하며, 지출 계약은 `ExpenseModal.tsx`에서 확인 후 `expense.py`·`SiteClient.submit_expense`로 상신·작성본 검토하고 전 항목 일치 시 '품의완료'를 저장합니다. pytest 74건·회귀 4종·실제 C-2026-031/037 상신 검증 통과. 계획과 구현 결과는 `기획/지출결의서_상신_구축계획.md`, 검증은 `scripts/verify_expense.py`입니다. 실제 기안은 앱 전용 브라우저 프로필 localStorage에 남습니다.
- 자세한 실행·빌드 방법은 `사용방법.md`, 확정 계획은 `기획/세금계산서_계약서_비교앱_구축계획.md`를 확인하세요.

## LLM Wiki

이 프로젝트의 지식, 결정, 작업 교훈은 `D:\LLMwiki`의 LLM Wiki에 쌓습니다. 규칙은 `D:\LLMwiki\wiki\CLAUDE.md`에 있습니다.

- 첫 작업 전에 `D:\LLMwiki\wiki\CLAUDE.md`, `index.md`와 이 프로젝트의 `projects/` 페이지를 읽습니다. 페이지가 아직 없으면 첫 위키 반영 때 `project-07-auto`로 만듭니다.
- 주요 결정은 `projects/` 페이지에, 사용자의 성향·교정은 `harness/`에 남깁니다. 이 폴더의 `MEMORY.md`에 지침을 추가할 때도 같은 내용을 위키에 남깁니다.
- 위키 훅은 전역 설정(`~/.claude/settings.json`)에 있습니다. Stop 시점에 반영 요청이 오면 위키 규칙의 "자동 축적" 절차를 따릅니다.
