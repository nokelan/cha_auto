# API 명세서

- 작성일: 2026-10-26
- 대상: 새봄 문서비교 앱 로컬 HTTP API 전체(`saebom/api.py`, `saebom/routes/*.py`가 등록하는 27개 라우트와 미들웨어가 직접 처리하는 경로)
- 문서 기준: 소스코드 직접 확인(`saebom/api.py`, `api_models.py`, `config.py`, `jobs.py`, `routes/`, `services/`, `store.py`, `statement.py`, `expense.py`, `local_audit.py`, `launcher.py`, `frontend/src`)과 `.venv`의 FastAPI 0.115.0·Starlette 0.38.6·Pydantic 2.14.1에서 임시 데이터 폴더로 호출해 본 결과. 확인하지 못한 것은 "(추정)"으로 표시
- 관련 문서: [기술설계서 13~15절](../프로그램_기술설계서.md)(요약), [10_보안설계서](10_보안설계서.md), [사용방법](../사용방법.md)

이 문서는 기술설계서 14절의 표를 필드·오류·예시 수준으로 확장한 것입니다. 요약 수준의 설명은 기술설계서로 대신하고, 여기서는 반복하지 않습니다.

## 1. 공통 사항

### 1.1 기준 URL과 진입

| 항목 | 내용 | 근거 |
|---|---|---|
| 기준 URL | `http://127.0.0.1:{임의 포트}` — 실행마다 OS가 정하는 포트(`bind(("127.0.0.1", 0))`) | `launcher.py:79` |
| 바인딩 | 루프백 한 주소만. Uvicorn은 미리 바인딩한 소켓으로 실행하며 접근 로그는 끄고(`access_log=False`) 로그 설정은 하지 않음 | `launcher.py:94`, `launcher.py:168`(`server.run(sockets=[sock])`) |
| 포트·토큰 전달 | 앱 데이터 폴더(`Store.root`)의 `instance.json`에 `{"port": …, "token": …}` 평문 기록, 종료 시 삭제 | `launcher.py:95`, `launcher.py:172` |
| 문서 | `/docs`·`/redoc`·`/openapi.json` 비활성(`docs_url=None, redoc_url=None, openapi_url=None`). 이 명세가 유일한 API 문서 | `saebom/api.py:103` |
| 본문 형식 | 요청·응답 모두 JSON(UTF-8). 예외는 PDF·CSV·XLSX 응답과 폴더 선택창 응답 | — |
| 요청 본문 형식 제약 | 본문 모델이 있는 라우트에 `Content-Type: text/plain`으로 JSON 문자열을 보내면 422(`model_attributes_type`)로 거절됨(`/api/auth/login`으로 확인) | 실험 |
| 프런트의 호출 함수 | `api(path, body?, method='POST')`: 본문이 없으면 `fetch('/api/'+path)` 즉 GET, 있으면 JSON 본문. 작업성 POST는 본문 `{}`를 보냄 | `frontend/src/api.ts:58` |

### 1.2 두 단계 인증

모든 요청은 `create_app.protect` 미들웨어(`saebom/api.py:114-141`)를 거칩니다. 검사 순서는 아래 표와 같으며 앞 단계에서 걸리면 뒤 단계는 보지 않습니다.

| 순서 | 검사 | 실패 시 응답 | 코드 위치 |
|---|---|---|---|
| 1 | `Host` 헤더의 호스트 부분이 `127.0.0.1`인가 (포트는 무시) | 403 `{"detail":"로컬 접속만 허용됩니다."}` | `api.py:116-118` |
| 2 | `Origin` 헤더가 있으면 `http://{Host 헤더 전체}`와 정확히 같은가 (`Origin: null` 포함 다른 값은 거절) | 403 `{"detail":"다른 사이트의 요청은 허용되지 않습니다."}` | `api.py:119-121` |
| 3 | 경로가 `/health`이면 인증 없이 `{"ok":true,"app":"SaebomCompare"}` 응답 | — | `api.py:122-123` |
| 4 | 경로가 `/`이고 쿼리 `token`이 실행 토큰과 같으면 `saebom_session` 쿠키를 발급하고 `/`로 303 리다이렉트 | — | `api.py:124-128` |
| 5 | 쿠키 `saebom_session`이 실행 토큰과 같은가 | 401 `{"detail":"EXE를 실행해 앱 화면을 다시 열어 주세요."}` | `api.py:129-130` |
| 6 | 경로가 `/api/`로 시작하고 `/api/auth/status`·`/api/auth/login`·`/api/activate`가 아니면 쿠키 `saebom_unlocked`가 실행별 잠금 해제 토큰과 같은가 | 401 `{"detail":"비밀번호를 입력해 프로그램을 잠금 해제해 주세요."}` | `api.py:131-134` |

- 1단계(앱 진입): 실행 토큰은 `secrets.token_urlsafe(32)`이며 `launcher.py:77`이 만들어 `create_app(token=…)`에 넘깁니다. 앱 창이 `/?token=…`으로 한 번 열면 쿠키가 붙고 이후 토큰은 URL에서 사라집니다.
- 2단계(비밀번호): `POST /api/auth/login`이 성공하면 `saebom_unlocked` 쿠키(실행별 무작위 토큰, `api.py:85`)를 발급합니다.
- 두 쿠키 모두 `HttpOnly; Path=/; SameSite=strict`이며 `Max-Age`·`Expires`·`Secure`는 없습니다(`api.py:126`, `api.py:186`, 실험으로 `Set-Cookie` 확인). 즉 세션 쿠키이고 서버 재시작 시 토큰이 바뀌어 무효가 됩니다.
- 표의 "인증" 열에서 **세션**은 1단계 쿠키만, **세션+잠금해제**는 두 쿠키 모두 필요함을 뜻합니다.
- 보안 설계의 근거와 위협 모델은 [10_보안설계서](10_보안설계서.md)를 참고하세요.

### 1.3 공통 응답 헤더

미들웨어가 정상 처리 흐름(`call_next` 이후)의 응답에만 붙입니다(`api.py:135-141`). 실험으로 확인한 적용 범위는 다음과 같습니다.

| 헤더 | 값 | 붙는 응답 |
|---|---|---|
| `Referrer-Policy` | `no-referrer` | 정상 응답 전부, 그리고 토큰 진입 303 응답 |
| `X-Content-Type-Options` | `nosniff` | 정상 응답 전부 |
| `Content-Security-Policy` | `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; worker-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'` | 정상 응답 전부 |
| `Cache-Control` | `no-store` | 경로가 `/api`로 시작하는 정상 응답. 정적 파일(`/`)에는 붙지 않음 |

붙지 않는 경우(실험 확인): 미들웨어가 직접 만든 403·401 응답, `/health` 응답, 토큰 진입 303(Referrer-Policy만 있음), 처리되지 않은 예외로 만들어진 500 응답.

### 1.4 오류 형식과 상태코드

오류 본문은 `{"detail": …}`입니다. `detail`은 대부분 한글 문자열이고, 요청 본문 검증 실패(422)에서만 객체 목록입니다.

| 코드 | 의미 | 발생 위치 |
|---|---|---|
| 400 | 업무 규칙 위반. 코드 어디서든 `ValueError`를 던지면 `bad_input` 핸들러가 `{"detail": 예외 메시지}`로 변환(`api.py:150-152`). 작업 중복 접수("현재 작업이 끝난 뒤 실행해 주세요.")도 400이며 409는 쓰지 않음 | 전 라우트 |
| 401 | 인증 실패. 미들웨어의 앱 진입·잠금 해제 미통과, 또는 로그인 비밀번호 오류(마지막 실패 포함) | `api.py:130`, `134`, `183` |
| 403 | Host·Origin 검사 실패 | `api.py:118`, `121` |
| 404 | 대상 없음(결과·계약·문서·거래명세서 파일). 정의되지 않은 `/api/...` 경로도 정적 파일 마운트가 `{"detail":"Not Found"}` 404로 응답함(실험) | 해당 라우트 |
| 422 | Pydantic 요청 모델 검증 실패. `detail`은 `[{"type","loc","msg","input","ctx"}…]` 목록. 프런트는 문자열이 아닌 `detail`을 "입력값을 확인해 주세요."로 바꿔 보여 줌(`frontend/src/api.ts:65`) | 본문 모델이 있는 라우트 |
| 429 | 로그인 잠금 중(`/api/auth/login`만). 정답이어도 잠금 중이면 429 | `api.py:176-177` |
| 500 | 처리되지 않은 예외. 본문은 JSON이 아닌 텍스트 `Internal Server Error`(실험) | 예: 폴더 선택창(Tk) 오류, SQLite 오류, 토큰·쿠키에 비ASCII 문자 |

422 본문 예시(`POST /api/contracts/import`에 `{"limit":0}`):

```json
{"detail":[{"type":"greater_than_equal","loc":["body","limit"],"msg":"Input should be greater than or equal to 1","input":0,"ctx":{"ge":1}}]}
```

### 1.5 동기 라우트와 스레드풀

27개 라우트 핸들러는 모두 `async def`가 아닌 일반 `def`입니다(`routes/*.py`, `api.py:162`, `api.py:173`). FastAPI는 이를 외부 스레드풀에서 실행하므로 요청 처리 중 DB·파일 접근이 이벤트 루프를 막지 않습니다. 오래 걸리는 업무(사이트 수집, PDF 저장, 비교)는 요청 안에서 하지 않고 단일 작업 스레드(`JobRunner`, `jobs.py:38`)에 넘기며, 요청은 곧바로 작업 ID를 돌려줍니다. 예외로 요청 스레드 안에서 오래 걸릴 수 있는 것은 `PUT /api/settings`(PDF 이동), `POST /api/contracts/{id}/statement`(엑셀 생성), 폴더 선택창 두 개입니다.

### 1.6 작업 접수 응답과 진행 확인

작업성 API는 **접수만** 하고 결과를 돌려주지 않습니다.

1. 클라이언트가 `POST /api/sync` 등을 호출하면 `{"id": "<작업 ID(uuid4 hex 32자)>"}`를 받습니다(`jobs.py:85`, `jobs.py:106`).
2. 진행 상황은 `GET /api/state`의 `jobs` 배열에서 해당 `id`를 찾아 `status`·`message`·`done`/`total`·`errors`로 확인합니다(최신순). 프런트는 작업 중 1초, 아니면 8초 간격으로 `/api/state`와 `/api/results`를 함께 읽습니다(`frontend/src/hooks/useAppState.ts` 머리 설명).
3. `status`가 `done`이면 비교류 작업은 `result_id`로 `GET /api/results/{id}`를 조회하고, 계약 가져오기는 `GET /api/contracts`, 로컬 대조는 `GET /api/local-audit`의 `last`, 지출결의서 상신은 `GET /api/contracts`의 `status`·`approval`을 조회합니다.
4. 실행 중인 작업이 하나라도 있거나 종료 중이거나 배타 구간(저장 위치 변경·거래명세서 생성)이면 새 작업 접수는 400 `현재 작업이 끝난 뒤 실행해 주세요.`로 거절됩니다(`jobs.py:83-84`, `jobs.py:21`). 즉 작업은 동시에 하나만 실행됩니다.

### 1.7 미들웨어와 마운트가 직접 처리하는 경로

데코레이터로 정의된 27개 라우트와 별개로 다음 경로가 있습니다.

| 경로 | 메서드 | 인증 | 동작 | 위치 |
|---|---|---|---|---|
| `/health` | 모든 메서드 | Host·Origin 검사만 | 200 `{"ok":true,"app":"SaebomCompare"}`. 단일 실행 감지·검증 스크립트가 사용 | `api.py:122-123`, `launcher.py:57` |
| `/?token={실행 토큰}` | GET | Host·Origin 검사 후 토큰 비교 | 303 → `/`, `Set-Cookie: saebom_session={토큰}; HttpOnly; Path=/; SameSite=strict`, `Referrer-Policy: no-referrer`. 토큰 불일치면 5단계로 넘어가 401 | `api.py:124-128` |
| `/` 및 그 아래 정적 파일 | GET | **세션**(잠금 해제 불필요) | `frontend/dist`를 `StaticFiles(html=True)`로 제공 | `api.py:196` |

`/health`는 쿠키 없이 응답하므로 Host가 `127.0.0.1`이고 Origin이 없거나 같은 출처일 때만 열립니다.

## 2. 라우트 전체

### 2.0 색인(27개)

코드의 데코레이터를 `grep -nE "@(app|router)\."`로 센 결과: `saebom/api.py` 2개 + `routes/compare.py` 7개 + `routes/contracts.py` 7개 + `routes/local_audit.py` 4개 + `routes/system.py` 7개 = **27개**. 아래 표의 행 수도 27입니다.

| # | 메서드 | 경로 | 인증 | 요청 본문 모델 | 성공 응답 | 정의 위치 | 상세 |
|---|---|---|---|---|---|---|---|
| 1 | GET | `/api/auth/status` | 세션 | 없음 | `{authenticated}` | `saebom/api.py:161` | 2.1 |
| 2 | POST | `/api/auth/login` | 세션 | `Login` | `{authenticated}` + 쿠키 | `saebom/api.py:172` | 2.1 |
| 3 | GET | `/api/state` | 세션+잠금해제 | 없음 | 메일·계약·작업·경로 | `saebom/routes/system.py:24` | 2.2 |
| 4 | PUT | `/api/settings` | 세션+잠금해제 | `Settings` | `{document_root}` | `saebom/routes/system.py:36` | 2.2 |
| 5 | POST | `/api/settings/pick-folder` | 세션+잠금해제 | 없음 | `{folder}` | `saebom/routes/system.py:56` | 2.2 |
| 6 | POST | `/api/browser` | 세션+잠금해제 | 없음 | `{id}` | `saebom/routes/system.py:68` | 2.2 |
| 7 | GET | `/api/documents/{id}` | 세션+잠금해제 | 없음 | PDF(inline) | `saebom/routes/system.py:80` | 2.2 |
| 8 | POST | `/api/shutdown` | 세션+잠금해제 | 없음 | `{ok}` | `saebom/routes/system.py:95` | 2.2 |
| 9 | POST | `/api/activate` | 세션 | 없음 | `{ok}` | `saebom/routes/system.py:109` | 2.2 |
| 10 | POST | `/api/sync` | 세션+잠금해제 | 없음 | `{id}` | `saebom/routes/compare.py:23` | 2.3 |
| 11 | POST | `/api/download` | 세션+잠금해제 | `Work` | `{id}` | `saebom/routes/compare.py:35` | 2.3 |
| 12 | POST | `/api/compare` | 세션+잠금해제 | `Work` | `{id}` | `saebom/routes/compare.py:49` | 2.3 |
| 13 | GET | `/api/results` | 세션+잠금해제 | 없음 | 요약 배열 | `saebom/routes/compare.py:63` | 2.3 |
| 14 | GET | `/api/results/{id}` | 세션+잠금해제 | 없음 | 결과 상세 | `saebom/routes/compare.py:75` | 2.3 |
| 15 | POST | `/api/results/{id}/correct` | 세션+잠금해제 | `Correct` | `{id}` | `saebom/routes/compare.py:90` | 2.3 |
| 16 | GET | `/api/results/{id}/csv` | 세션+잠금해제 | 없음 | CSV(attachment) | `saebom/routes/compare.py:124` | 2.3 |
| 17 | POST | `/api/contracts/import` | 세션+잠금해제 | `ImportContracts` | `{id}` | `saebom/routes/contracts.py:43` | 2.4 |
| 18 | GET | `/api/contracts` | 세션+잠금해제 | 없음 | 가져온 계약 배열 | `saebom/routes/contracts.py:55` | 2.4 |
| 19 | GET | `/api/contracts/{id}/statement` | 세션+잠금해제 | 없음 | 거래명세서 초안 | `saebom/routes/contracts.py:68` | 2.4 |
| 20 | POST | `/api/contracts/{id}/statement` | 세션+잠금해제 | `StatementRequest` | 생성 결과 | `saebom/routes/contracts.py:83` | 2.4 |
| 21 | GET | `/api/statements/{file}` | 세션+잠금해제 | 없음 | XLSX(attachment) | `saebom/routes/contracts.py:98` | 2.4 |
| 22 | GET | `/api/contracts/{id}/expense` | 세션+잠금해제 | 없음 | 지출결의서 초안 | `saebom/routes/contracts.py:18` | 2.4 |
| 23 | POST | `/api/contracts/{id}/expense` | 세션+잠금해제 | `ExpenseRequest` | `{id}` | `saebom/routes/contracts.py:29` | 2.4 |
| 24 | GET | `/api/local-audit` | 세션+잠금해제 | 없음 | 로컬 대조 상태 | `saebom/routes/local_audit.py:21` | 2.5 |
| 25 | PUT | `/api/local-audit/folder` | 세션+잠금해제 | `LocalFolder` | 로컬 대조 상태 | `saebom/routes/local_audit.py:33` | 2.5 |
| 26 | POST | `/api/local-audit/pick-folder` | 세션+잠금해제 | 없음 | `{folder}` | `saebom/routes/local_audit.py:45` | 2.5 |
| 27 | POST | `/api/local-audit/run` | 세션+잠금해제 | 없음 | `{id}` | `saebom/routes/local_audit.py:58` | 2.5 |

### 2.0.1 요청 모델 정의(`saebom/api_models.py`)

`config` 값: `MAX_PAIRS=500`(`config.py:22`), 로그인 길이 등은 모델에 직접 지정.

| 모델 | 필드 | 타입 | 제약 | 위치 |
|---|---|---|---|---|
| `Pair` | `mail_id`, `contract_id`, `invoice_url` | `str` | 제약 없음 | `api_models.py:9` |
| `Work` | `pairs` | `list[Pair]` | 1~500개 | `api_models.py:17-18` |
| `Correct` | `overrides` | `dict[str, dict[str, Any]]` | 모델 제약 없음. 허용 필드·값 범위는 `correct` 핸들러가 검사(2.3 참조) | `api_models.py:23` |
| `Settings` | `document_root` | `str` | 1~1000자 | `api_models.py:29-30` |
| `ImportContracts` | `kind` | `"전체"｜"수입"｜"지출"` | 기본 `"전체"` | `api_models.py:36-37` |
| | `limit` | `int｜null` | 기본 `null`(전체), 1~500 | `api_models.py:38` |
| | `only_new` | `bool` | 기본 `false` | `api_models.py:39` |
| `StatementItem` | `name`, `spec` | `str` | 각 200자 이하(빈 값은 모델이 허용, 업무 검사가 400 처리) | `api_models.py:45-47` |
| | `monthly_amount` | `int` | Pydantic 기본(느슨한) 정수 변환. 범위는 업무 검사 | `api_models.py:48` |
| `StatementRequest` | `customer` | `str` | 200자 이하 | `api_models.py:55` |
| | `issue_date`, `from_month`, `to_month` | `str` | 각 20자 이하 | `api_models.py:56-58` |
| | `items` | `list[StatementItem]` | 100개 이하 | `api_models.py:59` |
| `LocalFolder` | `folder` | `str` | 1~1000자 | `api_models.py:64-65` |
| `Login` | `password` | `str` | 1~128자 | `api_models.py:70-71` |
| `ExpenseRequest` | `title` | `str` | 500자 이하 | `api_models.py:77` |
| | `month` | `str` | 20자 이하 | `api_models.py:78` |
| | `supply`, `vat`, `total` | `StrictInt` | JSON 정수만(문자열·실수 거절) | `api_models.py:79-81` |
| | `attachments` | `list[str]` | 기본 `[]`, 100개 이하 | `api_models.py:82` |
| | `note` | `str` | 기본 `""`, 2000자 이하 | `api_models.py:83` |

본문 모델에 정의되지 않은 필드는 무시됩니다(Pydantic 기본, `extra` 설정 없음 — 모델 정의에서 확인).

### 2.1 인증 API

#### 2.1.1 `GET /api/auth/status`

| 항목 | 내용 |
|---|---|
| 목적 | 현재 실행에서 비밀번호 잠금이 풀렸는지 조회. 앱 시작 시 `AccessGate`가 호출 |
| 인증 | 세션(잠금 해제 불필요) |
| 요청 | 없음 |
| 성공 응답 200 | `{"authenticated": bool}` — `saebom_unlocked` 쿠키가 현재 실행 토큰과 같으면 `true` |
| 오류 | 403(Host·Origin), 401(세션 없음). 잠금 해제 쿠키에 비ASCII 문자가 있으면 500(10_보안설계서 참조) |
| 부수효과 | 없음 |
| 관련 기능 | 비밀번호 잠금 화면(`frontend/src/AccessGate.tsx:33`) |

```
GET /api/auth/status   (쿠키: saebom_session=<토큰>)
→ 200 {"authenticated": false}
```

#### 2.1.2 `POST /api/auth/login`

| 항목 | 내용 |
|---|---|
| 목적 | 시작 비밀번호 확인과 잠금 해제 쿠키 발급 |
| 인증 | 세션(잠금 해제 불필요) |
| 요청 본문 | `Login`: `{"password": str(1~128자)}` |
| 처리 | `login_lock` 안에서 ① 잠금 만료 시각(`time.monotonic()` 기준)이 남았으면 429 ② 비밀번호와 `config.APP_PASSWORD`를 UTF-8 바이트로 `secrets.compare_digest` 비교 ③ 틀리면 실패 횟수 +1, 5회째면 횟수를 0으로 돌리고 30초 잠금 후 401 ④ 맞으면 횟수 0으로 초기화 |
| 성공 응답 200 | `{"authenticated": true}` + `Set-Cookie: saebom_unlocked=<토큰>; HttpOnly; Path=/; SameSite=strict` |
| 오류 | 401 `비밀번호가 올바르지 않습니다.`(잠금을 거는 5번째 실패도 401) / 429 `비밀번호를 여러 번 틀렸습니다. {N}초 후 다시 시도해 주세요.`(N은 남은 초를 올림, 최소 1) / 422(빈 값·129자 이상 — 실패 횟수에 세지 않음) |
| 부수효과 | 메모리의 실패 횟수·잠금 시각 갱신(재시작 시 초기화). 성공 시 쿠키 발급. 입력값을 저장·기록하지 않음 |
| 관련 기능 | 비밀번호 잠금. 비밀번호는 `SAEBOM_PASSWORD` 환경변수, 없거나 빈 값이면 기본값(`config.py:14`) |
| 정의 | `saebom/api.py:172-187`, 모델 `api_models.py:70` |

```
POST /api/auth/login
{"password": "예시-비밀번호"}
→ 401 {"detail": "비밀번호가 올바르지 않습니다."}

(5회 연속 실패 후)
→ 429 {"detail": "비밀번호를 여러 번 틀렸습니다. 30초 후 다시 시도해 주세요."}
```

실험에서 5번째 실패는 401, 6번째부터 429였고 정답을 보내도 429였습니다.

### 2.2 시스템 API

#### 2.2.1 `GET /api/state`

| 항목 | 내용 |
|---|---|
| 목적 | 화면 초기·주기 조회용 전체 상태 |
| 인증 | 세션+잠금해제 |
| 요청 | 없음 |
| 성공 응답 200 | `{mails[], contracts[], synced, jobs[], data_dir, document_root, site}` |
| 필드 | `mails`: 받은 메일 배열(수신일 내림차순, 4절 `메일` 표). `contracts`: 사이트 계약 목록 배열(4절 `사이트 계약`). `synced`: `string｜null` 마지막 동기화 시각(ISO 8601). `jobs`: 작업 객체 배열(최신순, 3절). `data_dir`: `string` 앱 데이터 폴더 절대경로. `document_root`: `string` 원본 PDF 보관 폴더 절대경로. `site`: `string` 그룹웨어 주소(`config.SITE_URL`) |
| 오류 | 401/403, DB 오류는 500 |
| 부수효과 | DB 읽기, 문서 파일 존재 여부 확인(`available`) |
| 관련 기능 | 메일·계약 목록, 작업 진행, 설정 화면 |
| 정의 | `routes/system.py:24`, 합성은 `services/compare_service.py:34`(catalog) |

```json
{"mails":[{"id":"m-0001","sender":"가온데이터","subject":"9월 세금계산서","received":"2026-09-30 10:12",
  "attachments":[{"name":"세금계산서_가온데이터_2026-09.pdf","url":"https://sbgw.vercel.app/files/inv1.pdf"}],
  "pdfs":[{"name":"세금계산서_가온데이터_2026-09.pdf","url":"https://sbgw.vercel.app/files/inv1.pdf"}],
  "documents":{"https://sbgw.vercel.app/files/inv1.pdf":null},"candidates":["C-2026-040"]}],
 "contracts":[],"synced":"2026-10-26T09:00:00+09:00","jobs":[],
 "data_dir":"C:\\Users\\예시\\AppData\\Local\\SaebomCompare","document_root":"D:\\예시\\원본PDF","site":"https://sbgw.vercel.app/"}
```

주의: `mails[].documents`와 `contracts[].document`는 `extraction.pages`(페이지 전문)를 비우지 않습니다(`compare_service.py:61`, `70`, `81`에서 `strip_pages` 같은 처리를 하지 않음). 다운로드한 문서가 많으면 이 응답이 커지며 프런트는 이를 1~8초마다 읽습니다. 다른 목록 API(`/api/contracts`, `/api/results/{id}`)는 `pages`를 빈 배열로 비웁니다.

#### 2.2.2 `PUT /api/settings`

| 항목 | 내용 |
|---|---|
| 목적 | 원본 PDF 보관 폴더 변경과 등록된 PDF 전체 이동 |
| 인증 | 세션+잠금해제 |
| 요청 본문 | `Settings`: `{"document_root": str(1~1000자)}` |
| 처리 | `service.exclusive("저장 위치 변경")` 진입(진행 중 작업이 있으면 거절) → `Store.set_document_root`: 경로·쓰기 검사(`_prepare_root`) → 모든 문서를 새 폴더로 복사하고 SHA-256 검증(`_copy_document`) → DB 경로·설정을 한 트랜잭션으로 확정(`_commit_root`) → 이전 파일 삭제(`_remove_old_copies`). 확정 전 실패하면 이번에 만든 복사본만 지움 |
| 성공 응답 200 | `{"document_root": "<확정된 절대경로>"}` |
| 오류 400 | `진행 중인 작업이 끝난 뒤 저장 위치를 변경해 주세요.` / `PC의 절대 폴더 경로를 선택해 주세요. 네트워크 공유 폴더는 지원하지 않습니다.`(상대경로·`\\` 시작) / `원본 파일을 찾을 수 없어 저장 위치를 유지합니다: {파일명}. 문서를 다시 다운로드한 뒤 시도해 주세요.` / `원본 파일 내용이 달라 저장 위치를 유지합니다: {파일명}` / `새 폴더에 내용이 다른 같은 이름의 파일이 있습니다: {파일명}. 기존 파일을 보존하며 저장 위치를 유지합니다.` / `저장 위치를 바꾸지 못했습니다. 기존 설정과 원본 파일은 유지됩니다. 새 폴더의 쓰기 권한과 여유 공간을 확인해 주세요. ({OSError 종류})` |
| 오류 기타 | 422(빈 값·1001자 이상) |
| 부수효과 | 폴더·하위 폴더(`세금계산서/`, `계약서/`) 생성, PDF 복사·삭제, `documents.disk_path`·`meta.document_root` 변경. 이동 내내 `store.lock`을 쥐므로 `GET /api/state`가 지연될 수 있음 |
| 정의 | `routes/system.py:36-46`, `store.py:400`, `store.py:302` |

```
PUT /api/settings
{"document_root": "D:\\새봄문서\\원본PDF"}
→ 200 {"document_root": "D:\\새봄문서\\원본PDF"}
→ 400 {"detail": "진행 중인 작업이 끝난 뒤 저장 위치를 변경해 주세요."}
```

#### 2.2.3 `POST /api/settings/pick-folder`

| 항목 | 내용 |
|---|---|
| 목적 | 원본 PDF 보관 폴더를 고르는 Windows 폴더 선택창 열기 |
| 인증 | 세션+잠금해제 |
| 요청 | 없음 (프런트는 본문 `{}`를 보냄, 무시됨) |
| 처리 | `ask_folder("원본 PDF 저장 폴더 선택", 현재 저장 위치의 상위 폴더)` — 숨긴 Tk 창을 만들고 `askdirectory` 호출(`api.py:63-72`) |
| 성공 응답 200 | `{"folder": "<선택 경로>"｜null}` — 취소하면 `null` |
| 오류 | Tk·대화상자 오류는 처리되지 않아 500 |
| 부수효과 | 네이티브 대화상자 표시. 설정은 바꾸지 않음(화면이 `PUT /api/settings` 호출) |
| 정의 | `routes/system.py:56-58` |

```
POST /api/settings/pick-folder   {}
→ 200 {"folder": "D:\\새봄문서"}
→ 200 {"folder": null}
```

#### 2.2.4 `POST /api/browser`

| 항목 | 내용 |
|---|---|
| 목적 | 그룹웨어 로그인용 전용 브라우저 열기 작업 접수 |
| 인증 | 세션+잠금해제 |
| 요청 | 없음 |
| 성공 응답 200 | `{"id": "<작업 ID>"}` — 작업 종류 `전용 브라우저` |
| 오류 400 | `현재 작업이 끝난 뒤 실행해 주세요.` |
| 부수효과 | 작업 스레드에서 Chromium 지속 프로필(`browser-profile`)을 열고 `https://sbgw.vercel.app/#/mail`로 이동 |
| 정의 | `routes/system.py:68-70`, `services/core.py:146`, `site.py:132` |

```
POST /api/browser   {}
→ 200 {"id": "3f9c1c0e8b7a4d2f9a6b5c4d3e2f1a0b"}
```

#### 2.2.5 `GET /api/documents/{id}`

| 항목 | 내용 |
|---|---|
| 목적 | 저장된 원본 PDF 제공(화면의 PDF 뷰어와 "원본 열기" 링크) |
| 인증 | 세션+잠금해제 |
| 경로 변수 | `id`: 문서 ID(`documents.id`, uuid hex). 임의 파일 경로는 입력받지 않음 |
| 성공 응답 200 | `Content-Type: application/pdf`, `Content-Disposition: inline; filename=…`(원문 파일명 `doc["name"]`), 본문은 PDF 바이트 |
| 오류 404 | `저장한 PDF를 찾을 수 없습니다. 다시 다운로드해 주세요.`(레코드 없음 또는 파일 없음) |
| 부수효과 | 파일 읽기. 경로는 `Store.path(doc)`가 DB의 `disk_path`(없으면 `documents/{hash}.pdf`)로 계산하며, 그 경로가 보관 폴더 아래인지는 다시 검사하지 않음(`store.py:275-280`) |
| 정의 | `routes/system.py:80-85` |

```
GET /api/documents/9c2e5d7f1a3b4c6d8e0f1a2b3c4d5e6f
→ 200 application/pdf (본문 PDF)
→ 404 {"detail": "저장한 PDF를 찾을 수 없습니다. 다시 다운로드해 주세요."}
```

#### 2.2.6 `POST /api/shutdown`

| 항목 | 내용 |
|---|---|
| 목적 | 프로그램 종료 요청 |
| 인증 | 세션+잠금해제 |
| 요청 | 없음 |
| 성공 응답 200 | `{"ok": true}` |
| 부수효과 | `shutdown` 콜백이 있으면 Uvicorn `should_exit=True`(`launcher.py:90-91`). 서버가 종료 절차(작업 접수 차단, 브라우저·DB 정리, `instance.json` 삭제)에 들어감 |
| 정의 | `routes/system.py:95-98` |

```
POST /api/shutdown   {}
→ 200 {"ok": true}
```

#### 2.2.7 `POST /api/activate`

| 항목 | 내용 |
|---|---|
| 목적 | 이미 실행 중인 앱 창을 앞으로 가져오기. 두 번째 실행이 첫 번째 인스턴스를 깨울 때 사용 |
| 인증 | 세션만(잠금 해제 전에도 호출 가능) |
| 요청 | 없음 |
| 성공 응답 200 | `{"ok": true}` |
| 부수효과 | `activate` 콜백이 있으면 `threading.Event.set()` → 앱 창 스레드가 `page.bring_to_front()`(`launcher.py:124-126`). 비밀번호 잠금은 해제되지 않음 |
| 호출자 | 프런트가 아니라 `launcher.py:53-64`(`_existing_instance`, 요청 구성 58-61)이 `instance.json`의 토큰을 쿠키로 보내 호출 |
| 정의 | `routes/system.py:109-112` |

```
POST /api/activate   (쿠키: saebom_session=<토큰>)  {}
→ 200 {"ok": true}
```

### 2.3 문서비교 API

#### 2.3.1 `POST /api/sync`

| 항목 | 내용 |
|---|---|
| 목적 | 그룹웨어 메일·계약 목록 동기화 작업 접수 |
| 인증 | 세션+잠금해제 |
| 요청 | 없음 |
| 성공 응답 200 | `{"id": "<작업 ID>"}` — 종류 `목록 동기화`, `total`=2 |
| 오류 400 | `현재 작업이 끝난 뒤 실행해 주세요.` |
| 작업 실패 사유(작업 `message`) | `메일·계약 목록이 비어 있습니다. 전용 브라우저의 로그인과 화면을 확인해 주세요.`(둘 중 하나라도 빈 목록) / `계약 목록 양식이 바뀌었습니다. 기존 목록을 유지합니다.`(열 7개가 아님) / 사이트 탐색 오류 |
| 부수효과 | 사이트 접속. 성공 시 `items` 테이블을 통째로 교체하고 `meta.synced` 갱신. 실패하면 기존 목록 유지. `contract_imports`·PDF·비교 이력은 유지 |
| 정의 | `routes/compare.py:23-25`, `services/compare_service.py:14`, `store.py:80` |

```
POST /api/sync   {}
→ 200 {"id": "0a1b2c3d4e5f60718293a4b5c6d7e8f9"}
```

#### 2.3.2 `POST /api/download`

| 항목 | 내용 |
|---|---|
| 목적 | 선택한 연결의 세금계산서·계약서 PDF 저장·판독 작업 접수 |
| 인증 | 세션+잠금해제 |
| 요청 본문 | `Work`: `{"pairs":[{"mail_id","contract_id","invoice_url"}…]}` (1~500개) |
| 처리 | `validate_pairs`로 먼저 검증한 뒤 작업 접수. 작업은 URL 기준으로 파일을 합치고 한 건씩 저장 |
| 성공 응답 200 | `{"id": "<작업 ID>"}` — 종류 `문서 다운로드`, `total`=고유 파일 수 |
| 오류 400 | `메일과 PDF 계약서를 연결해 주세요.`(메일·계약이 없거나 계약에 PDF 없음) / `메일에 실제 첨부된 PDF를 선택해 주세요.`(`invoice_url`이 해당 메일의 `.pdf` 첨부가 아님) / `같은 메일을 중복 선택할 수 없습니다.` / `현재 작업이 끝난 뒤 실행해 주세요.` |
| 오류 422 | `pairs`가 비었거나 501개 이상, 필드 누락 |
| 작업 실패 사유 | `{n}개 파일 저장 실패. 상세 오류를 확인하고 재시도하세요.`(파일별 사유는 작업 `errors`에 `"{파일명}: {사유}"`) / `프로그램 종료 요청으로 중단했습니다. 저장한 파일은 유지됩니다.` |
| 부수효과 | 사이트 접속, `원본PDF/세금계산서/`·`계약서/`에 `{해시12}_{정리된 이름}` 저장, `documents` 갱신. 이미 저장된 URL은 재사용 |
| 정의 | `routes/compare.py:35-40`, `services/compare_service.py:97`, `123`, `services/core.py:170` |

```
POST /api/download
{"pairs":[{"mail_id":"m-0001","contract_id":"C-2026-040","invoice_url":"https://sbgw.vercel.app/files/inv1.pdf"}]}
→ 200 {"id": "7e6d5c4b3a2918070f1e2d3c4b5a6978"}
→ 400 {"detail": "메일에 실제 첨부된 PDF를 선택해 주세요."}
```

#### 2.3.3 `POST /api/compare`

| 항목 | 내용 |
|---|---|
| 목적 | 저장된 추출값으로 문서비교 작업 접수(네트워크·AI 미사용) |
| 인증 | 세션+잠금해제 |
| 요청 본문 | `Work`(2.3.2와 같음) |
| 성공 응답 200 | `{"id": "<작업 ID>"}` — 종류 `오프라인 비교`, 완료 시 작업에 `result_id` 기록 |
| 오류 400·422 | 2.3.2와 같음 |
| 작업 실패 사유 | `선택 문서 다운로드를 먼저 완료해 주세요. 비교는 네트워크를 사용하지 않습니다.`(문서 레코드 또는 파일 없음) |
| 부수효과 | `results` 테이블에 새 결과 INSERT(기존 결과는 덮어쓰지 않음), 작업 상태 저장 |
| 정의 | `routes/compare.py:49-54`, `services/compare_service.py:154` |

```
POST /api/compare
{"pairs":[{"mail_id":"m-0001","contract_id":"C-2026-040","invoice_url":"https://sbgw.vercel.app/files/inv1.pdf"}]}
→ 200 {"id": "5a4b3c2d1e0f9a8b7c6d5e4f3a2b1c0d"}
```

#### 2.3.4 `GET /api/results`

| 항목 | 내용 |
|---|---|
| 목적 | 비교 결과 이력의 요약 목록 |
| 인증 | 세션+잠금해제 |
| 성공 응답 200 | 최신순 배열. 항목 `{id: str, created: str(ISO), parent: str｜null, count: int(행 수), mismatch: int(상태가 '불일치'인 행 수), partners: str[](앞 3개 행의 업체명), mail_ids: str[](전체 행의 메일 ID)}` |
| 오류 | 401/403, DB·JSON 오류는 500 |
| 부수효과 | DB 읽기(행 상세·페이지 전문은 반환하지 않음) |
| 정의 | `routes/compare.py:63-66`, `store.py:463` |

```json
[{"id":"5a4b3c2d1e0f9a8b7c6d5e4f3a2b1c0d","created":"2026-10-26T09:30:00+09:00","parent":null,
  "count":2,"mismatch":1,"partners":["가온데이터","이음소프트"],"mail_ids":["m-0001","m-0002"]}]
```

#### 2.3.5 `GET /api/results/{id}`

| 항목 | 내용 |
|---|---|
| 목적 | 결과 한 건의 상세 |
| 인증 | 세션+잠금해제 |
| 경로 변수 | `id`: 결과 ID(uuid hex) |
| 성공 응답 200 | `{id, created, parent, rows[], pairs[], overrides{}}` — 필드 정의는 4절 `비교 결과`. 각 행의 `invoice`·`contract`의 `extraction.pages`와 `effective_invoice.pages`는 빈 배열로 대체 |
| 오류 404 | `결과를 찾을 수 없습니다.` |
| 부수효과 | DB 읽기. 저장된 결과는 변경하지 않음 |
| 정의 | `routes/compare.py:75-81`, `saebom/api.py:42-53`(`strip_pages`) |

```
GET /api/results/5a4b3c2d1e0f9a8b7c6d5e4f3a2b1c0d
→ 200 {"id":"5a4b…","created":"2026-10-26T09:30:00+09:00","parent":null,"rows":[{…4절 참조…}],
       "pairs":[{"mail_id":"m-0001","contract_id":"C-2026-040","invoice_url":"https://sbgw.vercel.app/files/inv1.pdf"}],
       "overrides":{}}
→ 404 {"detail": "결과를 찾을 수 없습니다."}
```

#### 2.3.6 `POST /api/results/{id}/correct`

| 항목 | 내용 |
|---|---|
| 목적 | 추출값을 수동 보정해 새 결과를 만드는 재비교 작업 접수 |
| 인증 | 세션+잠금해제 |
| 경로 변수 | `id`: 기준 결과 ID |
| 요청 본문 | `Correct`: `{"overrides": {"<세금계산서 문서 ID>": {"<필드>": 값}}}` |
| 허용 필드 | `supply`, `vat`, `total`, `month`, `biz`, `percent`, `installment`, `partner` |
| 값 검사 | `supply`·`vat`·`total`·`percent`·`installment`: `int`(불리언 제외)이며 `0 ≤ v ≤ 10^12`, `percent`는 `≤ 100`. 나머지 필드: 문자열 200자 이하, `month`는 `YYYY-MM`으로 유효한 월 |
| 성공 응답 200 | `{"id": "<작업 ID>"}` — 종류 `보정 후 재비교`. 완료 시 `result_id`는 **새** 결과 ID이며 새 결과의 `parent`가 `id` |
| 오류 404 | `결과를 찾을 수 없습니다.` |
| 오류 400 | `수정할 문서 또는 항목이 잘못되었습니다.`(문서 ID가 그 결과 행의 세금계산서 문서가 아니거나 허용 필드 밖) / `금액·차수·비율은 범위 안의 정수로 입력해 주세요.` / `수정값을 200자 이내 문자열로 입력해 주세요.` / `청구 월은 YYYY-MM 형식으로 입력해 주세요.` / `현재 작업이 끝난 뒤 실행해 주세요.` |
| 오류 422 | `overrides` 누락·형식 오류 |
| 부수효과 | 기존 결과의 `overrides`에 이번 값을 병합해 `run_compare(pairs, 병합값, parent=id)` 작업 예약. 새 결과 INSERT, 원본 PDF·이전 결과·저장된 추출값은 변경하지 않음. 보정된 필드는 `quote="사용자 수동 보정"`, `method="수동 보정"`, 이전 값을 `previous`에 보관 |
| 정의 | `routes/compare.py:90-115`, `services/compare_service.py:154` |

```
POST /api/results/5a4b3c2d1e0f9a8b7c6d5e4f3a2b1c0d/correct
{"overrides":{"9c2e5d7f1a3b4c6d8e0f1a2b3c4d5e6f":{"supply":1000000,"month":"2026-09"}}}
→ 200 {"id": "1122334455667788990011223344aabb"}
→ 400 {"detail": "금액·차수·비율은 범위 안의 정수로 입력해 주세요."}
```

#### 2.3.7 `GET /api/results/{id}/csv`

| 항목 | 내용 |
|---|---|
| 목적 | 결과를 CSV로 내려받기 |
| 인증 | 세션+잠금해제 |
| 성공 응답 200 | `Content-Type: text/csv; charset=utf-8`, `Content-Disposition: attachment; filename="saebom-{id 앞 8자}.csv"`. 본문 앞에 UTF-8 BOM(`\ufeff`) |
| 열(12개) | `업체`, `메일`, `계약번호`, `전체판정`, `항목`, `계산서`, `계약·기준`, `차이(계산서-기준)`, `항목판정`, `설명`, `계산서 근거`, `계약 근거` |
| 행 | 결과 행마다 `checks` 항목 수만큼 한 줄씩. `checks`가 비어 있으면 `항목="문서 처리"`, `항목판정=행 status`, `설명=행 error`인 한 줄 |
| 수식 방지 | 모든 셀을 문자열로 바꾼 뒤 `= + - @`, 탭, 캐리지 리턴으로 시작하면 앞에 `'`를 붙임. 음수 차이값(예: `-100`)도 `'-100`이 됨 |
| 오류 404 | `결과가 없습니다.`(`GET /api/results/{id}`의 404 문구와 다름) |
| 부수효과 | 메모리에서만 생성, 서버 파일로 저장하지 않음 |
| 정의 | `routes/compare.py:124-147`, `safe`는 `routes/compare.py:139-141` |

```
GET /api/results/5a4b3c2d1e0f9a8b7c6d5e4f3a2b1c0d/csv
→ 200 text/csv
\ufeff업체,메일,계약번호,전체판정,항목,계산서,계약·기준,차이(계산서-기준),항목판정,설명,계산서 근거,계약 근거
가온데이터,9월 세금계산서,C-2026-040,불일치,공급가액,1100000,1000000,100000,불일치,,…
```

### 2.4 계약서·거래명세서·지출결의서 API

#### 2.4.1 `POST /api/contracts/import`

| 항목 | 내용 |
|---|---|
| 목적 | "계약서 목록" 메뉴의 계약서 가져오기 작업 접수 |
| 인증 | 세션+잠금해제 |
| 요청 본문 | `ImportContracts`: `{"kind":"전체"｜"수입"｜"지출","limit":1~500｜null,"only_new":bool}` (모두 선택, 기본 `전체`·`null`·`false`) |
| 성공 응답 200 | `{"id": "<작업 ID>"}` — 종류 `계약서 가져오기` |
| 오류 | 422(구분 이름 밖의 값, `limit`이 0 이하 또는 501 이상) / 400 `현재 작업이 끝난 뒤 실행해 주세요.` |
| 작업 처리 | 사이트 계약 목록 수집 → 관리번호 큰 순 정렬 → `only_new`면 이미 가져온 것 제외 → `limit` 앞에서 N개 → 계약마다 PDF 저장·판독 후 `contract_imports`에 기록 |
| 작업 완료 메시지 | `가져올 계약이 없습니다.` 또는 `계약서 {N}건을 가져왔습니다.` |
| 작업 실패 사유 | `{n}개 계약 가져오기 실패. 상세 오류를 확인하고 재시도하세요.`(건별 사유는 `errors`에 `"{관리번호}: {사유}"`, `계약서 PDF가 없습니다.` 포함. 성공한 건은 이미 기록됨) / `프로그램 종료 요청으로 중단했습니다. 가져온 계약은 유지됩니다.` |
| 부수효과 | 사이트 접속, `원본PDF/계약서/` 저장, `documents`·`contract_imports` 갱신 |
| 정의 | `routes/contracts.py:43-45`, `services/contracts_service.py:19` |

```
POST /api/contracts/import
{"kind":"지출","limit":10,"only_new":true}
→ 200 {"id": "aabbccddeeff00112233445566778899"}
→ 422 {"detail":[{"type":"literal_error","loc":["body","kind"],"msg":"Input should be '전체', '수입' or '지출'","input":"기타","ctx":{"expected":"'전체', '수입' or '지출'"}}]}
```

#### 2.4.2 `GET /api/contracts`

| 항목 | 내용 |
|---|---|
| 목적 | 가져온 계약 목록(관리번호 큰 순) |
| 인증 | 세션+잠금해제 |
| 성공 응답 200 | `가져온 계약` 배열. 항목 필드는 4절 표. `document.extraction.pages`는 빈 배열 |
| 오류 | 401/403, DB 오류 500 |
| 부수효과 | DB 읽기, PDF 존재 확인 |
| 정의 | `routes/contracts.py:55-57`, `services/contracts_service.py:53` |

```json
[{"id":"C-2026-040","kind":"지출","partner":"온새미로","title":"보안관제 서비스 계약서","period":"2026-01-01 ~ 2026-12-31",
  "amount_text":"월 1,000,000원","file":{"name":"계약서_C-2026-040_온새미로_보안관제.pdf","url":"https://sbgw.vercel.app/files/c40.pdf"},
  "imported":"2026-10-26T09:10:00+09:00","document":{"id":"…","available":true,"extraction":{"fields":{},"pages":[],"error":null}},
  "status":"없음","approval":null}]
```

#### 2.4.3 `GET /api/contracts/{id}/statement`

| 항목 | 내용 |
|---|---|
| 목적 | 거래명세서 확인 창의 초기값 |
| 인증 | 세션+잠금해제 |
| 경로 변수 | `id`: 계약 관리번호(예: `C-2026-040`) |
| 성공 응답 200 | `거래명세서 초안`(4절). 지출 계약도 200이며 `eligible=false`와 `reason` 문구로 표시 |
| 오류 404 | `가져온 계약을 찾을 수 없습니다.` |
| 오류 400 | `계약서 원문 PDF가 없어 거래명세서를 만들 수 없습니다.`(파일 링크·문서 레코드·PDF 파일 중 하나가 없음) |
| 부수효과 | DB 읽기·파일 존재 확인. 파일·DB를 쓰지 않음 |
| 정의 | `routes/contracts.py:68-73`, `services/contracts_service.py:102`, `statement.py:159` |

```json
{"contract_id":"C-2026-031","eligible":true,"reason":null,"customer":"가온데이터","customer_biz":"123-45-67890",
 "contract_date":"2026-01-02","issue_date":"2026-01-02","period_start":"2026-01-01","period_end":"2026-12-31",
 "from_month":"2026-01","to_month":"2026-12","items":[{"name":"유지보수","spec":"서버 10대","monthly_amount":1000000}],
 "notes":[],"missing":[],"folder":"D:\\예시\\원본PDF\\거래명세서"}
```

#### 2.4.4 `POST /api/contracts/{id}/statement`

| 항목 | 내용 |
|---|---|
| 목적 | 확인한 값으로 거래명세서 엑셀 생성 |
| 인증 | 세션+잠금해제 |
| 요청 본문 | `StatementRequest`: `{"customer","issue_date":"YYYY-MM-DD","from_month":"YYYY-MM","to_month":"YYYY-MM","items":[{"name","spec","monthly_amount":int}]}` |
| 성공 응답 200 | `{file: str, path: str(절대경로), rows: int, supply: int, vat: int｜float, total: int｜float, warnings: str[]}` |
| 처리 | 배타 구간(`거래명세서 생성`) 안에서 수입 계약 여부 재확인 → 계약기간·관리번호를 붙여 `statement.build`: 청구월 × 품목 줄 생성(최대 12줄) → 템플릿 사본 채우기 → 템플릿 수식·고정 칸 변경 여부 검사 → 같은 이름이 있으면 `_2`, `_3`…으로 새 이름을 골라 배타적 생성 |
| 오류 404 | `가져온 계약을 찾을 수 없습니다.` |
| 오류 400 | `계약서 원문 PDF가 없어 거래명세서를 만들 수 없습니다.` / 지출·확인 불가 안내(`지출 계약은 거래처가 발행하는 문서라 거래명세서를 만들지 않습니다.`, `계약서 서명란에서 새봄바이오가 "을"(공급자)인지 확인하지 못해 거래명세서를 만들 수 없습니다.`) / `수신(거래처)을 입력해 주세요.` / `작성 일자를 YYYY-MM-DD 형식으로 입력해 주세요.` / `청구 시작 월을 YYYY-MM 형식으로 입력해 주세요.`·`청구 끝 월을 …` / `청구 시작 월이 끝 월보다 늦습니다.` / `{i}번째 품목의 품목명을 입력해 주세요.`·`…규격을…`·`…월금액을 1원 이상의 정수로 입력해 주세요.`(상한 10^12) / `품목을 1개 이상 입력해 주세요.` / `청구월 {a}개 × 품목 {b}개 = {c}줄입니다. 템플릿은 12줄까지만 넣을 수 있으니 …` / 템플릿 자리표시자·수식 변경 오류(`거래명세서를 저장하지 않았습니다. …`) / `진행 중인 작업이 끝난 뒤 다시 시도해 주세요. (거래명세서 생성)` |
| 오류 422 | 필드 길이 초과(`customer` 200자 등), `items` 101개 이상, `monthly_amount`가 정수로 변환되지 않음 |
| 부수효과 | `{PDF 보관 폴더}/거래명세서/`에 새 `.xlsx` 1개 생성(기존 파일·템플릿은 덮어쓰지 않음, 실패 시 만들던 파일 삭제). 구간 동안 작업 접수 거절 |
| 정의 | `routes/contracts.py:83-88`, `services/contracts_service.py:116`, `statement.py:287` |

```
POST /api/contracts/C-2026-031/statement
{"customer":"가온데이터","issue_date":"2026-01-02","from_month":"2026-01","to_month":"2026-03",
 "items":[{"name":"유지보수","spec":"서버 10대","monthly_amount":1000000}]}
→ 200 {"file":"거래명세서_C-2026-031_가온데이터_202601-202603.xlsx","path":"D:\\예시\\원본PDF\\거래명세서\\거래명세서_C-2026-031_가온데이터_202601-202603.xlsx",
       "rows":3,"supply":3000000,"vat":300000,"total":3300000,
       "warnings":["청구 범위 2026-01~2026-03가 계약기간 2026-01~2026-12와 다릅니다."]}
```

#### 2.4.5 `GET /api/statements/{file}`

| 항목 | 내용 |
|---|---|
| 목적 | 만든 거래명세서 엑셀 내려받기 |
| 인증 | 세션+잠금해제 |
| 경로 변수 | `file`: 파일명 한 구간(`encodeURIComponent` 된 한글 가능) |
| 성공 응답 200 | `Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, `Content-Disposition: attachment`(한글 이름은 `filename*`로 인코딩) |
| 오류 404 | `거래명세서 파일을 찾을 수 없습니다.` — 이름에 `/`·`\`·`..`가 있거나 `.xlsx`로 끝나지 않거나, `resolve()`한 상위 폴더가 거래명세서 폴더가 아니거나, 파일이 아닌 경우, `OSError` |
| 부수효과 | 파일 읽기. 폴더 밖 경로는 열지 않음 |
| 정의 | `routes/contracts.py:98-110` |

```
GET /api/statements/거래명세서_C-2026-031_가온데이터.xlsx
→ 200 (xlsx 본문)
→ 404 {"detail": "거래명세서 파일을 찾을 수 없습니다."}
```

#### 2.4.6 `GET /api/contracts/{id}/expense`

| 항목 | 내용 |
|---|---|
| 목적 | 지출결의서 확인 창의 초기값 |
| 인증 | 세션+잠금해제 |
| 성공 응답 200 | `지출결의서 초안`(4절) |
| 오류 404 | `가져온 계약을 찾을 수 없습니다.` |
| 오류 400 | `계약서 원문 PDF가 없어 지출결의서를 상신할 수 없습니다.` |
| 부수효과 | DB·파일 존재 읽기. 수입 계약은 200에 `eligible=false`와 `reason="지출 계약만 지출결의서를 상신할 수 있습니다."` |
| 정의 | `routes/contracts.py:18-23`, `services/contracts_service.py:130`, `expense.py:16` |

```json
{"contract_id":"C-2026-040","eligible":true,"reason":"","title":"[IT기획팀] 온새미로 보안관제 서비스 지출의 건 (26.09월)",
 "month":"2026-09","supply":1000000,"vat":100000,"total":1100000,
 "attachments":["계약서_C-2026-040_온새미로_보안관제.pdf","세금계산서_온새미로_2026-09.pdf"],"note":"",
 "warnings":[],"approval":null,"partner":"온새미로","period_start":"2026-01-01","period_end":"2026-12-31"}
```

#### 2.4.7 `POST /api/contracts/{id}/expense`

| 항목 | 내용 |
|---|---|
| 목적 | 확인한 값으로 지출결의서 상신 작업 접수 |
| 인증 | 세션+잠금해제 |
| 요청 본문 | `ExpenseRequest`: `{"title","month","supply","vat","total","attachments":[…],"note"}` |
| 업무 검사 | 순서: 계약·원문 확인 → 지출 계약 여부 → `expense.validate`: 제목 공백 제외 1~500자 / `month`는 `YYYY-MM` 형식·유효한 월 / `supply`·`vat`·`total`은 정수 `0..10^12` / `supply>0`, `total>0` / `supply+vat==total` / `attachments` 100개 이하·각 항목 1~500자 문자열 / `note` 2000자 이하 |
| 성공 응답 200 | `{"id": "<작업 ID>"}` — 종류 `지출결의서 상신`, `total`=3 |
| 오류 404 | `가져온 계약을 찾을 수 없습니다.` |
| 오류 400 | `계약서 원문 PDF가 없어 지출결의서를 상신할 수 없습니다.` / `지출 계약만 지출결의서를 상신할 수 있습니다.` / `제목을 1~500자로 입력해 주세요.` / `청구월을 YYYY-MM 형식으로 입력해 주세요.`·`청구월을 올바른 YYYY-MM 형식으로 입력해 주세요.` / `금액은 0~1조 원 범위의 정수로 입력해 주세요.` / `공급가액과 합계는 0보다 커야 합니다.` / `공급가액 + 세액이 합계와 다릅니다.` / `첨부 파일 이름을 올바르게 입력해 주세요.` / `특이사항을 2000자 이내로 입력해 주세요.` / `현재 작업이 끝난 뒤 실행해 주세요.` |
| 오류 422 | 구조·크기 오류(`supply`가 문자열·실수 등) |
| 작업 완료 메시지 | 전 항목 일치: `지출결의서 상신·검토 완료: 품의완료` / 불일치: `지출결의서 작성본 검토 불일치: 상태는 없음입니다.`(작업 `status`는 둘 다 `done`) |
| 작업 실패 | 사이트 오류 등은 작업 `failed`(`작업 실패: …`), 계약 상태는 `없음`과 `error` 문구로 저장. 자동 재상신하지 않음 |
| 부수효과 | 작업 시작 시 이전 상신 상태를 `없음`으로 초기화한 뒤 사이트에서 기안 입력·상신, 작성본 DOM 검토, `contract_status` 저장. 같은 달 품의완료 기록이 있으면 `warnings`에 중복 상신 경고 추가 |
| 정의 | `routes/contracts.py:29-34`, `services/contracts_service.py:144`, `161`, `expense.py:57` |

```
POST /api/contracts/C-2026-040/expense
{"title":"[IT기획팀] 온새미로 보안관제 서비스 지출의 건 (26.09월)","month":"2026-09",
 "supply":1000000,"vat":100000,"total":1100000,
 "attachments":["계약서_C-2026-040_온새미로_보안관제.pdf","세금계산서_온새미로_2026-09.pdf"],"note":""}
→ 200 {"id": "0f1e2d3c4b5a69788796a5b4c3d2e1f0"}
→ 400 {"detail": "공급가액 + 세액이 합계와 다릅니다."}
```

### 2.5 로컬 세금계산서 대조 API

#### 2.5.1 `GET /api/local-audit`

| 항목 | 내용 |
|---|---|
| 목적 | "로컬 세금계산서 대조" 화면 상태: 저장 폴더, 폴더 안 파일과 판독값, 마지막 대조 결과 |
| 인증 | 세션+잠금해제 |
| 성공 응답 200 | `로컬 대조 상태`(4절): `{folder: str｜null, folder_error: str｜null, files[], warnings: str[], last: 객체｜null}` |
| 처리 | `meta.local_invoice_folder`가 있으면 폴더 검사 후 직접 아래 `.pdf`·`.png` 파일을 이름순으로 읽음(판독은 (경로, 수정 시각, 크기) 캐시 재사용, 최대 200개). 마지막 결과의 계약서 문서는 원본 URL로 다시 조회해 `available`을 갱신 |
| 오류 | 폴더 삭제·권한 문제는 오류가 아니라 200과 `folder_error` 문구(`폴더를 찾을 수 없습니다: …`, `폴더를 읽지 못했습니다. ({예외 종류})`) |
| 부수효과 | 로컬 폴더·PDF 읽기, 판독 캐시 갱신, DB 읽기. meta는 바꾸지 않음 |
| 정의 | `routes/local_audit.py:21-23`, `services/local_audit_service.py:51` |

```json
{"folder":"D:\\세금계산서","folder_error":null,
 "files":[{"file":"세금계산서_가온데이터_2026-09.pdf","path":"D:\\세금계산서\\세금계산서_가온데이터_2026-09.pdf","type":"pdf","size":48213,
           "partner":"가온데이터","partner_source":"pdf","invoice":{"fields":{},"error":null}}],
 "warnings":[],"last":null}
```

#### 2.5.2 `PUT /api/local-audit/folder`

| 항목 | 내용 |
|---|---|
| 목적 | 세금계산서 폴더 저장 |
| 인증 | 세션+잠금해제 |
| 요청 본문 | `LocalFolder`: `{"folder": str(1~1000자)}` |
| 성공 응답 200 | `GET /api/local-audit`과 같은 상태 객체(저장 직후 폴더 목록 포함) |
| 오류 400 | `세금계산서 폴더 경로를 입력해 주세요.`(공백뿐) / `네트워크 공유 폴더(UNC)는 지원하지 않습니다. PC의 폴더를 선택해 주세요.`(`\\` 또는 `//` 시작) / `PC의 절대 폴더 경로를 선택해 주세요. (예: D:\세금계산서)` / `폴더를 찾을 수 없습니다: {입력값}` |
| 오류 422 | 빈 문자열, 1001자 이상 |
| 부수효과 | `meta.local_invoice_folder` 갱신(검사 실패 시 기존 값 유지). 마지막 대조 결과는 지우지 않음 |
| 정의 | `routes/local_audit.py:33-35`, `services/local_audit_service.py:80`, `local_audit.py:42` |

```
PUT /api/local-audit/folder   {"folder": "D:\\세금계산서"}
→ 200 {"folder":"D:\\세금계산서","folder_error":null,"files":[…],"warnings":[],"last":null}
→ 400 {"detail": "PC의 절대 폴더 경로를 선택해 주세요. (예: D:\\세금계산서)"}
```

#### 2.5.3 `POST /api/local-audit/pick-folder`

| 항목 | 내용 |
|---|---|
| 목적 | 세금계산서 폴더를 고르는 Windows 폴더 선택창 |
| 인증 | 세션+잠금해제 |
| 성공 응답 200 | `{"folder": "<선택 경로>"｜null}` |
| 처리 | 시작 폴더: 저장된 `meta.local_invoice_folder`, 없으면 PDF 보관 폴더. 제목 `세금계산서 폴더 선택` |
| 오류 | Tk 오류는 500 |
| 부수효과 | 대화상자 표시. 선택만 하고 저장하지 않음(화면이 이어서 PUT 호출, 취소하면 호출하지 않음) |
| 정의 | `routes/local_audit.py:45-48` |

```
POST /api/local-audit/pick-folder   {}
→ 200 {"folder": "D:\\세금계산서"}
```

#### 2.5.4 `POST /api/local-audit/run`

| 항목 | 내용 |
|---|---|
| 목적 | 폴더의 세금계산서와 웹 계약서를 대조하는 작업 접수 |
| 인증 | 세션+잠금해제 |
| 성공 응답 200 | `{"id": "<작업 ID>"}` — 종류 `로컬 세금계산서 대조`, `total`=파일 수+1 |
| 오류 400 | `현재 작업이 끝난 뒤 실행해 주세요.` (폴더 미설정 등은 접수 후 작업 실패로 남음) |
| 작업 실패 사유 | `세금계산서 폴더를 먼저 선택하세요.` / 폴더 검사 실패 문구 / `선택한 폴더에 PDF·PNG 세금계산서가 없습니다.` / `프로그램 종료 요청으로 중단했습니다. 이전 대조 결과는 유지됩니다.` / 사이트 수집 오류. 실패하면 이전 `last`는 유지 |
| 작업 완료 메시지 | 예: `세금계산서 26건 대조: 일치 8 · 불일치 2 · 확인 필요 14 · 계약서 없음 2`(`처리 실패`는 1건 이상일 때만 포함) |
| 부수효과 | 사이트에서 계약 목록 1회 수집, 후보 계약서 PDF 저장(`documents`), 고른 계약을 `contract_imports`에도 기록, 결과를 `meta.local_audit`에 저장. 행 단위 실패는 `처리 실패` 행과 작업 `errors`(`"{파일}: {사유}"`)로 남기고 계속 |
| 정의 | `routes/local_audit.py:58-60`, `services/local_audit_service.py:99` |

```
POST /api/local-audit/run   {}
→ 200 {"id": "c0ffee00c0ffee00c0ffee00c0ffee00"}
```

## 3. 작업(job) 객체

### 3.1 필드

`GET /api/state`의 `jobs[]`와 `meta.jobs`(DB 저장본)가 같은 모양입니다(`jobs.py:87`, `jobs.py:27`).

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | string | `uuid4().hex`(32자) |
| `kind` | string | 작업 종류(3.3 표) |
| `status` | string | `running`｜`done`｜`failed` |
| `message` | string | 진행·완료·실패 문구. 접수 직후 `작업 준비 중`, 실패 시 `작업 실패: {예외 메시지}` |
| `done` | int | 처리한 단위 수 |
| `total` | int | 전체 단위 수(접수 직후 1, 업무가 갱신) |
| `errors` | string[] | 파일·계약·세금계산서 단위 오류. 접수 직후 `[]` |
| `created` | string | 접수 시각(ISO 8601, 초 단위) |
| `result_id` | string | 선택. `오프라인 비교`·`보정 후 재비교`가 완료 직전에 기록하는 새 결과 ID. 다른 종류에는 없음 |

예시:

```json
{"id":"5a4b3c2d1e0f9a8b7c6d5e4f3a2b1c0d","kind":"오프라인 비교","status":"done","message":"작업 완료","done":2,"total":2,
 "errors":[],"created":"2026-10-26T09:30:00+09:00","result_id":"1122334455667788990011223344aabb"}
```

### 3.2 상태 전이

| 전이 | 조건 | 위치 |
|---|---|---|
| (없음) → `running` | `submit` 통과(종료·배타 구간·다른 `running` 작업이 없음). `done=0`, `total=1`, `errors=[]`, `message="작업 준비 중"` | `jobs.py:83-88` |
| `running` → `done` | 작업 함수가 예외 없이 끝남. `message`는 함수가 문자열을 반환하면 그 값, 아니면 `작업 완료` | `jobs.py:100-101` |
| `running` → `failed` | 작업 함수가 예외를 던짐. `message="작업 실패: {예외}"`, 예외는 `app.log`에 기록되고 다시 던지지 않음 | `jobs.py:102-104` |
| `running` → `failed` | 프로그램 재시작 시 DB에서 복원한 `running` 작업. `message="이전 실행이 종료되었습니다. 저장 파일은 유지되며 작업을 다시 실행할 수 있습니다."` | `jobs.py:47-49`, `jobs.py:19` |

- `done`/`failed`는 종결 상태이며 다시 `running`으로 돌아가지 않습니다.
- 작업 목록은 새 작업을 접수할 때마다 최근 19개만 남기고 새 작업을 더해 최대 20개로 유지합니다(`jobs.py:86`). 오래된 작업은 목록에서 사라지며 비교 결과 이력(`results` 테이블)에는 영향이 없습니다.
- 작업 스레드는 하나뿐(`ThreadPoolExecutor(max_workers=1)`, `jobs.py:38`)이라 동시에 실행되는 작업은 없습니다.
- `GET /api/state`의 `jobs`는 생성 역순(최신 먼저)이며 `errors`는 사본입니다(`jobs.py:115-117`).

### 3.3 종류(kind)와 완료 메시지

| kind | 접수 API | 작업 함수 | `total` | 성공 시 최종 `message` | 실패 조건 요약 | `result_id` |
|---|---|---|---|---|---|---|
| `목록 동기화` | `POST /api/sync` | `sync` (`compare_service.py:14`) | 2 | `작업 완료` | 빈 목록, 계약 열 수 불일치, 탐색 오류 | 없음 |
| `전용 브라우저` | `POST /api/browser` | `open_browser` (`core.py:146`) | 1 | `작업 완료`(중간 문구 `전용 브라우저를 열었습니다.`는 덮어써짐) | 브라우저·탐색 오류 | 없음 |
| `문서 다운로드` | `POST /api/download` | `download` (`compare_service.py:123`) | 고유 파일 수 | `작업 완료` | 하나라도 실패하면 `failed` + `errors` | 없음 |
| `오프라인 비교` | `POST /api/compare` | `run_compare` (`compare_service.py:154`) | 비교 행 수 | `작업 완료` | 문서 누락·파일 없음 | 있음 |
| `보정 후 재비교` | `POST /api/results/{id}/correct` | `run_compare`(보정·부모 결과 지정) | 비교 행 수 | `작업 완료` | 위와 같음 | 있음(새 결과) |
| `계약서 가져오기` | `POST /api/contracts/import` | `import_contracts` (`contracts_service.py:19`) | 선택된 계약 수(0건이면 1) | `가져올 계약이 없습니다.` / `계약서 {N}건을 가져왔습니다.` | 일부 실패하면 `failed` + `errors` | 없음 |
| `지출결의서 상신` | `POST /api/contracts/{id}/expense` | `run_expense` (`contracts_service.py:161`) | 3 | `지출결의서 상신·검토 완료: 품의완료` 또는 `지출결의서 작성본 검토 불일치: 상태는 없음입니다.`(둘 다 `done`) | 사이트 상신·DOM 오류 | 없음(결과는 계약의 `status`·`approval`) |
| `로컬 세금계산서 대조` | `POST /api/local-audit/run` | `run_local_audit` (`local_audit_service.py:99`) | 파일 수+1 | `세금계산서 {N}건 대조: 일치 … · 불일치 … · 확인 필요 … · 계약서 없음 …` | 폴더 미설정·파일 0건·사이트 수집 오류 | 없음(결과는 `GET /api/local-audit`의 `last`) |

`sync`와 `open_browser`는 작업 함수가 문자열을 반환하지 않으므로 중간에 `update`로 넣은 완료 문구(`목록 저장 완료` 등)가 마지막에 `작업 완료`로 바뀝니다(`jobs.py:101`).

## 4. 주요 응답 객체

타입 표기에서 `｜null`은 `null`이 올 수 있음을 뜻합니다.

### 4.1 문서(document)

`documents` 테이블 행(`store.py:23`, `store.py:201`)에 응답 가공으로 필드가 더해진 객체입니다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | string | 문서 ID(uuid hex). `GET /api/documents/{id}`의 경로 변수 |
| `source` | string | 원본 다운로드 URL |
| `name` | string | 원본 첨부 파일명 |
| `hash` | string | PDF 바이트의 SHA-256(소문자 hex 64자) |
| `extraction` | object | 4.2 |
| `disk_path` | string｜null | 현재 저장 경로(절대경로). 옛 데이터는 null일 수 있음 |
| `kind` | string｜null | `invoice`｜`contract`. 옛 데이터는 null일 수 있음 |
| `available` | bool | 선택. 파일이 실제로 존재하는지(`/api/state`, `/api/contracts`, 로컬 대조 응답에 있음) |

### 4.2 추출값(extraction)과 필드

| 필드 | 타입 | 설명 |
|---|---|---|
| `fields` | object | 항목 키 → 필드 객체 |
| `pages` | `{page:int, text:string}[]` | 페이지 텍스트 전문. 여러 응답에서 `[]`로 비움 |
| `error` | string｜null | 판독 오류(`텍스트 추출 불가: 이미지 PDF는 지원하지 않습니다. OCR·AI 미사용.`, `PDF 열기 실패 (손상 또는 암호화): {예외 종류}`, `100페이지를 초과해 자동 판독하지 않았습니다.`) |

필드 객체: `{value: 값, quote: string(근거 원문), page: int｜null, method: string}`. 수동 보정 필드는 `quote="사용자 수동 보정"`, `page=null`, `method="수동 보정"`, `previous`(보정 전 필드 객체)를 더 가집니다.

| 문서 | 필드 키(값 타입) |
|---|---|
| 세금계산서 | `biz`(string), `partner`(string), `issued`(string 날짜), `supply`·`vat`·`total`(int), `month`(`YYYY-MM`), `installment`(int), `percent`(int) |
| 계약서 | `partner`(string), `biz`(string), `start`·`end`(ISO 날짜), `basis`(`monthly`｜`total`), `amount`(int), `vat_mode`(`included`｜`excluded`), `ratios`(int[]), `payment`(string), `condition`(string) |

위 키는 `compare.py:95-163`의 `put(...)` 호출에서 확인한 목록입니다. 양식에서 찾지 못한 항목은 키가 없습니다.

### 4.3 비교 결과(result)

`GET /api/results/{id}` 응답(`store.save_result`가 `id`·`created`를 붙인 JSON, `store.py:426`, 행 구성은 `compare_service.py:184-188`).

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | string | 결과 ID |
| `created` | string | 생성 시각 |
| `parent` | string｜null | 보정 재비교의 기준 결과 ID |
| `rows` | object[] | 비교 행(아래) |
| `pairs` | `{mail_id, contract_id, invoice_url}[]` | 비교한 연결 |
| `overrides` | `{문서ID: {필드: 값}}` | 누적 보정값 |

행(row):

| 필드 | 타입 | 설명 |
|---|---|---|
| `mail_id`, `contract_id` | string | 연결 키 |
| `subject` | string | 메일 제목 |
| `partner` | string | 계약 거래처 |
| `invoice`, `contract` | document | 4.1 (`extraction.pages` 비움) |
| `effective_invoice` | object | 보정이 반영된 세금계산서 추출값(`fields`, `pages`=`[]`, `error`) |
| `status` | string | `일치`｜`불일치`｜`확인 필요`｜`처리 실패` |
| `checks` | check[] | 항목 판정. 문서 오류가 있으면 `[]` |
| `error` | string｜null | 문서 오류 문구 |

판정 우선순위: 문서 오류(이미지 PDF는 `확인 필요`, 그 외 `처리 실패`) → 항목 중 불일치가 하나라도 있으면 `불일치` → 확인 필요가 있으면 `확인 필요` → 모두 `일치`(`compare.py:185-187`, `compare.py:259`).

check:

| 필드 | 타입 | 설명 |
|---|---|---|
| `key` | string | `biz`, `partner`, `arithmetic`, `vat_check`, `installment`, `supply`, `vat`, `total`, `period`, `group`, `payment` 중 하나 |
| `label` | string | 화면 항목명(예: `공급가액`, `청구기간 / 계약기간`) |
| `actual`, `expected` | any | 세금계산서 값, 계약·기준 값 |
| `status` | string | `일치`｜`불일치`｜`확인 필요` |
| `difference` | int｜null | 둘 다 int일 때 `actual - expected` |
| `note` | string | 설명 |
| `invoice_source`, `contract_source` | 필드 객체｜null | 근거 원문·페이지 |

### 4.4 메일과 계약

사이트 메일(`GET /api/state`의 `mails[]`, `compare_service.py:34-87`):

| 필드 | 타입 | 설명 |
|---|---|---|
| `id`, `sender`, `subject`, `received` | string | 사이트에서 읽은 값 |
| `attachments` | `{name, url}[]` | 첨부 전체 |
| `pdfs` | `{name, url}[]` | 이름이 `.pdf`로 끝나는 첨부 |
| `documents` | `{url: document｜null}` | PDF별 저장 문서(`available` 포함, `pages` 비우지 않음) |
| `candidates` | string[] | 추천 계약 관리번호. 업체명 부분 일치, 사업자번호 일치가 있으면 그것으로 대체 |

사이트 계약(`GET /api/state`의 `contracts[]`): `{id, kind, partner, title, period, amount_text, file: {name,url}｜null, document: document｜null}`.

가져온 계약(`GET /api/contracts`, `contracts_service.py:53-62`): 위 필드에 더해 `imported`(string, 가져온 시각), `status`(`품의완료`｜`없음`, 기록이 없으면 `없음`), `approval`(4.5｜null)이 있고 `document`의 `extraction.pages`는 `[]`입니다.

### 4.5 상신 기록(approval)

`contract_status.data`(`contracts_service.py:161-182`, `store.py:172`). 상신 시작 시 `{title, month, supply, vat, total, submitted_at, review:[], warnings}`로 초기화하고 완료 시 아래를 채웁니다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `title`, `month` | string | 상신 제목, 청구월 |
| `supply`, `vat`, `total` | int | 금액 |
| `submitted_at` | string | 상신 시작 시각 |
| `doc_id`, `doc_no`, `doc_url` | string｜null | 사이트 작성본 정보 |
| `document_total` | int｜null | 작성본 금액 칸 |
| `review` | `{label, actual, expected, ok}[]` | 8개 항목(`작성본 금액`, `본문 합계`, `본문 공급가액`, `본문 세액`, `공급가액 + 세액 = 합계`, `업체명`, `사용기간`, `제목`, `expense.py:113-120`) |
| `warnings` | string[] | 초안·사이트 경고 |
| `error` | string | 선택. 실패 시 예외 문구 |

`status`는 `review`가 비어 있지 않고 모두 `ok`일 때만 `품의완료`, 그 외 `없음`입니다.

### 4.6 거래명세서 초안과 생성 결과

초안(`GET /api/contracts/{id}/statement`, `statement.py:220-222`, `contracts_service.py:102-104`):

| 필드 | 타입 | 설명 |
|---|---|---|
| `contract_id` | string｜null | 관리번호 |
| `eligible` | bool | 서명란 을 사업자번호가 자사이고 구분이 `수입`일 때 `true` |
| `reason` | string｜null | 적격이면 `null`, 아니면 지출·확인 불가 안내 문구 |
| `customer`, `customer_biz` | string, string｜null | 거래처(갑) 상호, 갑 사업자번호 |
| `contract_date`, `issue_date` | string｜null | 계약체결일 `YYYY-MM-DD`(작성 일자 기본값 동일) |
| `period_start`, `period_end` | string｜null | 계약기간 ISO 날짜 |
| `from_month`, `to_month` | string｜null | 청구 시작·끝 월 `YYYY-MM` |
| `items` | `{name, spec, monthly_amount: int｜null}[]` | 품목 |
| `notes` | string[] | 안내 문구(총액 계약·부가세 포함·품목 여러 개) |
| `missing` | string[] | 찾지 못한 값의 키(예: `contract_date`, `items[0].spec`) |
| `folder` | string | 엑셀이 저장될 폴더 절대경로 |

생성 결과(`POST …/statement`, `statement.py:363`): `{file, path, rows, supply, vat, total, warnings}`(2.4.4). `vat`는 공급가액×0.1이 정수면 `int`, 아니면 `float`, `total`도 같은 규칙입니다.

### 4.7 지출결의서 초안

`GET /api/contracts/{id}/expense`(`expense.py:46-49`): `{contract_id, eligible: bool, reason: string(적격이면 ""), title, month, supply, vat, total: int, attachments: string[], note: string(""), warnings: string[], approval: 4.5｜null, partner, period_start, period_end}`. 직전 달을 계약기간 안으로 맞춰 청구월 기본값으로 쓰고, 금액은 계약 기준 기대값(판독 실패 시 0과 경고)입니다.

### 4.8 로컬 대조 상태

`GET /api/local-audit`·`PUT /api/local-audit/folder`(`local_audit_service.py:70`):

| 필드 | 타입 | 설명 |
|---|---|---|
| `folder` | string｜null | 저장된 폴더 |
| `folder_error` | string｜null | 폴더 검사·읽기 오류 문구 |
| `files` | file[] | `{file, path, type: "pdf"｜"png", size: int｜null, partner: string｜null, partner_source: "pdf"｜"filename"｜null, invoice: {fields, error}}` — PNG는 판독하지 않고 `error="이미지 파일은 판독하지 않습니다(OCR 미사용)."`, 50MiB 초과는 `파일이 50MiB를 넘어 읽지 않았습니다.` |
| `warnings` | string[] | 예: 200개 초과 시 앞 200개만 읽었다는 안내 |
| `last` | object｜null | `{folder, ran_at, contracts_total: int, counts: {일치, 불일치, 확인 필요, 처리 실패, 계약서 없음: int}, warnings, rows}` |

`last.rows[]`(`local_audit.py:239-243`): `{file, type, size, partner, partner_source, invoice, contract: {id, kind, partner, title, period, amount_text}｜null, contract_doc: document｜null, candidates: {id, kind, partner, title}[], expected: {supply, vat, total}｜null, status: 일치｜불일치｜확인 필요｜처리 실패｜계약서 없음, checks: check[], note: string}`. PNG 판정은 항상 `확인 필요`, 수입 계약을 고른 경우 `처리 실패`가 아니면 `확인 필요`로 낮춥니다(`local_audit.py:265-276`).

## 5. 프런트 호출 관계

`frontend/src`를 `api(`·`fetch(`·`href`로 grep하고 호출 지점을 열어 대조했습니다.

| API | 프런트 호출 | 호출 위치 |
|---|---|---|
| `GET /api/auth/status` | 호출함 | `AccessGate.tsx:33` |
| `POST /api/auth/login` | 호출함 | `AccessGate.tsx:54` |
| `GET /api/state` | 호출함(폴링) | `hooks/useAppState.ts:76` |
| `PUT /api/settings` | 호출함 | `App.tsx:199` |
| `POST /api/settings/pick-folder` | 호출함 | `App.tsx:221` |
| `POST /api/browser` | 호출함 | `App.tsx:429` |
| `GET /api/documents/{id}` | 호출함(PDF.js 주소, "원본 열기" 링크) | `components/Pdf.tsx:157`, `Pdf.tsx:225` |
| `POST /api/shutdown` | 호출함 | `App.tsx:279` |
| `POST /api/activate` | **호출하지 않음**. `launcher.py`의 `_existing_instance`만 호출 | `launcher.py:58-61` |
| `POST /api/sync` | 호출함 | `App.tsx:353` |
| `POST /api/download` | 호출함 | `screens/compare/MailsScreen.tsx:215` → `App.tsx:402` → `act`(`App.tsx:138`) |
| `POST /api/compare` | 호출함 | `MailsScreen.tsx:218` → `App.tsx:402` |
| `GET /api/results` | 호출함(폴링) | `hooks/useAppState.ts:76` |
| `GET /api/results/{id}` | 호출함 | `hooks/useAppState.ts:126` |
| `POST /api/results/{id}/correct` | 호출함 | `App.tsx:265` |
| `GET /api/results/{id}/csv` | 링크 이동(`<a href>`) | `screens/compare/ResultView.tsx:71` |
| `POST /api/contracts/import` | 호출함 | `App.tsx:410` |
| `GET /api/contracts` | 호출함 | `screens/contracts/ContractsScreen.tsx:111`, `components/ExpenseModal.tsx:135` |
| `GET /api/contracts/{id}/statement` | 호출함 | `ContractsScreen.tsx:164` |
| `POST /api/contracts/{id}/statement` | 호출함 | `components/StatementModal.tsx:255` |
| `GET /api/statements/{file}` | 링크 이동(`<a href>`) | `StatementModal.tsx:328` |
| `GET /api/contracts/{id}/expense` | 호출함 | `ContractsScreen.tsx:168` |
| `POST /api/contracts/{id}/expense` | 호출함 | `components/ExpenseModal.tsx:181` |
| `GET /api/local-audit` | 호출함 | `screens/LocalAuditScreen.tsx:186` |
| `PUT /api/local-audit/folder` | 호출함 | `LocalAuditScreen.tsx:210` |
| `POST /api/local-audit/pick-folder` | 호출함 | `LocalAuditScreen.tsx:208` |
| `POST /api/local-audit/run` | 호출함 | `App.tsx:414` |
| `GET /health` (라우트 밖) | 프런트는 호출하지 않음. `launcher.py:57`과 `scripts/verify_*.py`가 사용 | — |

27개 라우트 중 프런트가 호출하지 않는 것은 `POST /api/activate` 하나입니다. `GET`으로 쓰는 링크(`csv`, `statements`, `documents`)는 `fetch`가 아니라 브라우저 내비게이션이라 오류 시 JSON 본문을 화면 안내로 바꾸지 못하고 브라우저가 그대로 보여 줍니다(`api()`를 거치지 않음).

## 6. 기존 문서와 어긋난 점, 발견 사항

### 6.1 기존 문서와 어긋난 점

| # | 기존 문서의 서술 | 코드에서 확인한 사실 |
|---|---|---|
| 1 | 기술설계서 14절 `GET /api/local-audit` 응답을 `{folder, folder_error, files[], last}`로 소개 | 응답에 `warnings: string[]`도 있음(`services/local_audit_service.py:70`) |
| 2 | 기술설계서 15절 첫 문장: 시작 비밀번호는 `0000` | 기본값이 `0000`이고 `SAEBOM_PASSWORD` 환경변수가 비어 있지 않으면 그 값을 씀(`config.py:14`). 사용방법.md는 환경변수를 안내함 |
| 3 | 기술설계서 14절은 "인증 누락은 401, 요청 스키마 오류는 422"로만 소개 | 422의 `detail`은 문자열이 아니라 객체 목록이며, 프런트는 이를 "입력값을 확인해 주세요."로 바꿔 보임(`frontend/src/api.ts:65`) |
| 4 | 기술설계서 15절 "API 응답에 `Cache-Control: no-store`" | 경로가 `/api`로 시작하는 정상 응답에만 붙고 미들웨어가 직접 만드는 401·403·`/health` 응답에는 붙지 않음(`api.py:122-141`, 실험) |
| 5 | `saebom/routes/*.py`의 기능명세 주석 제목(`create_app.sync` 등)과 `api.py` 머리 주석의 "(GET /api/…)" 안내 | 라우트 정의는 `routes/*.py`로 옮겨졌고 `api.py`에는 `/api/auth/status`·`/api/auth/login`만 남음. 주석의 `create_app.…` 이름은 실제 함수 위치와 다름 |

### 6.2 발견 사항(코드는 수정하지 않음)

| # | 내용 | 위치 | 영향 |
|---|---|---|---|
| 1 | `GET /api/state`가 `mails[].documents`·`contracts[].document`의 `extraction.pages`를 비우지 않음. 다른 목록 API는 비움 | `services/compare_service.py:61`, `70`, `81` | 문서가 쌓이면 1~8초 주기 폴링 응답이 커질 수 있음(실측하지 않음, 추정) |
| 2 | 토큰·쿠키·쿼리 `token`에 비ASCII 문자가 들어오면 `secrets.compare_digest(str, str)`이 `TypeError`를 던져 JSON이 아닌 500이 됨(실험으로 확인). 비교는 실패하지 않고 예외로 끝나 인증이 뚫리지는 않음 | `saebom/api.py:124`, `129`, `133`, `163` | 오류 응답 형식·헤더 불일치. 로그인 비밀번호 비교만 UTF-8 바이트로 해서 안전(`api.py:178`) |
| 3 | 상태코드 일관성: 작업 충돌이 400(409 아님), 마지막 로그인 실패가 401(429 아님), 같은 "결과 없음"의 메시지가 라우트마다 다름(`결과를 찾을 수 없습니다.` / `결과가 없습니다.`) | `api.py:183`, `jobs.py:84`, `routes/compare.py:80`, `129` | 클라이언트가 문구로 분기하면 취약 |
| 4 | 폴더 선택창(Tk)을 요청 스레드풀의 작업 스레드에서 만듦. Tk는 보통 생성한 스레드에서만 안전하다고 알려져 있음 | `saebom/api.py:63-72`, `routes/system.py:56-58`, `routes/local_audit.py:45-48` | 환경에 따라 오류·교착 가능성(추정). 실제 장애는 확인하지 못함 |
| 5 | `/api/documents/{id}`는 `disk_path`를 그대로 열며 보관 폴더 아래인지 확인하지 않음 | `routes/system.py:80-85`, `store.py:275-280` | DB가 변조된 경우에만 의미(같은 사용자 권한 범위). 정상 동작에서는 앱이 쓴 경로만 들어감 |
| 6 | `PUT /api/settings`와 `PUT /api/local-audit/folder`는 로컬 절대경로를 제한 없이 허용(시스템 폴더 포함) | `store.py:302-315`, `local_audit.py:42-53` | 사용자가 고른 폴더에 하위 폴더·PDF를 쓰거나 읽음. 의도된 동작으로 보임 |
| 7 | `api.py`는 `StatementItem`을 import하지만 사용하지 않음 | `saebom/api.py:23` | 영향 없음(정리 대상) |
