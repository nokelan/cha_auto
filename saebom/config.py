# [파일 기능명세]
# 앱 공통 설정값. 대상 사이트 주소, 시작 비밀번호, 자사 사업자번호, 지출결의서 제목 접두어, 파일·요청 크기 제한, 로그인 잠금 정책을 한곳에 모은다.
# 다른 모듈은 값을 직접 쓰지 않고 이 모듈을 참조한다. 값은 모듈을 불러올 때 한 번 결정되며(환경변수 SAEBOM_PASSWORD·SAEBOM_OWN_BIZ·SAEBOM_EXPENSE_PREFIX로 덮어쓸 수 있음), 사용하는 쪽은 `config.이름`으로 호출 시점에 읽는다.
# 유지보수: 값이나 의미가 바뀌면 이 주석과 사용방법.md·프로그램_기술설계서.md를 함께 갱신한다.

import os

# 그룹웨어 사이트. SITE_URL은 화면 이동 기준 주소, SITE_HOST는 다운로드 URL 도메인 검사에 쓴다.
SITE_URL = "https://sbgw.vercel.app/"
SITE_HOST = "sbgw.vercel.app"

# 시작 비밀번호. 환경변수 SAEBOM_PASSWORD가 비어 있지 않으면 그 값을, 없거나 빈 값이면 기본값 0000을 쓴다.
# 빈 값을 허용하면 로그인 입력(1자 이상)으로 잠금을 풀 수 없게 되므로 기본값으로 대체한다. 문서·로그에 값을 적지 않는다.
APP_PASSWORD = os.environ.get("SAEBOM_PASSWORD") or "0000"

# 자사 사업자번호. 환경변수 SAEBOM_OWN_BIZ가 비어 있지 않으면 그 값, 아니면 기본값(APP_PASSWORD와 같은 패턴).
# 쓰임 1) compare.py: 계약서 서명표에서 자사 번호가 먼저(갑)이면 을(거래처) 번호로 마지막 번호를 고르는 판별 기준.
# 쓰임 2) statement.py: 서명란의 을 번호가 자사이고 행 구분이 '수입'인 계약만 거래명세서 대상으로 판별하는 기준(갑 번호가 자사이면 지출 안내).
# 두 모듈 모두 호출 시점에 config.OWN_BIZ를 읽으므로 테스트가 monkeypatch로 바꿀 수 있다.
OWN_BIZ = os.environ.get("SAEBOM_OWN_BIZ") or "000-81-00001"

# 지출결의서 제목 접두어. 환경변수 SAEBOM_EXPENSE_PREFIX가 비어 있지 않으면 그 값, 아니면 기본값. expense.draft가 호출 시점에 읽는다.
EXPENSE_PREFIX = os.environ.get("SAEBOM_EXPENSE_PREFIX") or "[IT기획팀]"

# 처리 한도: PDF 한 건 최대 크기(50MiB), 자동 판독 최대 페이지 수, 한 번에 처리할 비교 연결 최대 건수.
MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_PDF_PAGES = 100
MAX_PAIRS = 500

# 로그인 잠금: 연속 실패 허용 횟수와 초과 시 잠금 시간(초). 실행 중 메모리에서만 관리한다.
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_SECONDS = 30
