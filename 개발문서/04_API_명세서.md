# 04. API 명세서

- 기준일: 2026-10-26
- 기준: `api.py`, `api_models.py`, `routes/*.py`, 서비스 실제 반환값
- 관련: [DB 설계서](03_DB_설계서.md), [시퀀스 다이어그램](07_시퀀스_다이어그램.md)

## 1. 공통 규약

기본 주소는 실행마다 할당되는 `http://127.0.0.1:{port}`다. JSON 요청은 `Content-Type: application/json`을 사용한다. 라우트로 등록된 `/api/` 엔드포인트는 **29개**다. `/health`는 미들웨어 응답, `/`는 정적 UI와 최초 토큰 교환이므로 29개에서 제외한다. OpenAPI·Swagger·ReDoc 공개 경로는 비활성이다. 근거: `saebom/api.py:85`, `saebom/api.py:116`.

### 1.1 인증·접근

1. Host의 호스트 부분이 `127.0.0.1`이어야 한다. `localhost`·다른 호스트는 403이다.
2. Origin이 있으면 현재 `http://{Host}`와 정확히 같아야 한다. 불일치는 403이다.
3. `GET /?token={실행토큰}`은 303 `/`로 이동하며 HttpOnly·SameSite=Strict 실행 쿠키 `saebom_session`을 설정한다.
4. 모든 API는 실행 쿠키가 필요하다. `auth/status`, `auth/login`, `activate`만 잠금 해제 쿠키 없이 접근한다.
5. 그 밖의 API는 로그인 후 발급되는 HttpOnly·SameSite=Strict `saebom_unlocked`도 필요하다. 서버 재시작 시 두 실행별 토큰이 바뀐다.

토큰·쿠키 원문은 예제·문서에 기록하지 않는다. 요청 헤더 Authorization/Bearer 방식은 구현하지 않았다. 근거: `saebom/api.py:116`.

### 1.2 공통 응답·오류

| 상태 | 조건·응답 |
|---|---|
| 200 | 모든 정상 API 응답(작업 접수도 202가 아닌 200) |
| 400 | BusinessError 또는 ValueError → `{"detail":"한글 안내"}`; 일반 ValueError는 서버 로그 기록 |
| 401 | 실행 쿠키 없음/틀림, 잠금 미해제, 로그인 비밀번호 불일치 |
| 403 | Host·Origin 거부 |
| 404 | 없는 결과·원본·계약·엑셀 파일; 아래 경로별 조건 참고 |
| 422 | Pydantic 요청 구조·형·길이·범위 검증 오류; `detail`은 오류 목록 |
| 429 | 로그인 잠금 중; 남은 초를 포함한 `detail` |
| 500 | 처리하지 않은 내부 오류(DB·파일·KeyError 등); 404/400으로 모두 감추지 않음 |

이후 경로별 오류 표시는 401·403·500 공통 가능성을 생략한다. 본문 입력이 있는 경로는 공통 422도 적용한다. `ContractNotFound`만 계약 404로 변환하며 내부 `KeyError/IndexError`는 500으로 전파한다. 근거: `saebom/api.py:152`, `saebom/routes/contracts.py:21`.

일반 처리 응답에는 Referrer-Policy, X-Content-Type-Options, CSP를 설정하며 API에 Cache-Control: no-store를 설정한다. 미들웨어가 직접 반환하는 인증 오류·health·최초 이동에는 같은 후처리 헤더 전체가 적용되는 것은 아니다. 근거: `saebom/api.py:116`.

### 1.3 작업 접수와 결과 조회

작업 접수 응답은 `{"id":"작업UUID"}`다. HTTP 200은 실행 성공이 아닌 접수 성공이다. `/api/state.jobs`를 주기 조회해 완료를 확인한다. 별도 `/api/jobs/{id}`·취소 API·WebSocket은 없다.

```json
{"id":"job-example","kind":"오프라인 비교","status":"done","message":"작업 완료","done":1,"total":1,"errors":[],"created":"2026-10-26T10:00:00+09:00","result_id":"result-example"}
```

| 필드 | 형·계약 |
|---|---|
| id | UUID hex 문자열(예제 식별자는 설명용) |
| kind | 화면 표시 작업명 |
| status | `running` / `done` / `failed` |
| message | 현재 진행·완료·실패 안내 |
| done / total | 진행 수·전체 수 정수; 완료 상태가 수치 100%를 강제하지는 않음 |
| errors | 항목별 오류 문자열 목록 |
| created | 시간대 포함 ISO 시각 |
| result_id | 비교 결과가 저장되면 추가; 모든 작업에 존재하지 않음 |

작업은 단일 스레드에서 실행되고 최대 20건을 유지한다. 진행 작업·종료 중·exclusive 구간이면 새 접수는 400이다. 작업 함수 실패는 최초 POST 응답을 바꾸지 않고 `failed`로 남는다. 검토 불일치처럼 업무 결과를 정상 반환하면 job은 `done`일 수 있다. 최종 상태 DB 저장 실패 시 메모리는 종료 상태로 바꾸고 로그를 남긴다. 강제 중단·시간 제한은 없다. 근거: `saebom/jobs.py:78`, `saebom/jobs.py:122`.

## 2. 요청 모델

아래 필드는 별도 표시가 없으면 필수다. 문자열·정수의 일반 Pydantic 변환과 추가 필드 기본 무시 동작을 사용한다. `ExpenseRequest` 금액만 StrictInt이며 문자열·소수·bool을 422로 거절한다. 근거: `saebom/api_models.py:9`.

| 모델 | 필드·검증 |
|---|---|
| Login | `password:str`, 1~128자 |
| Pair | `mail_id:str, contract_id:str, invoice_url:str` |
| Work | `pairs:Pair[]`, 1~500건 |
| Correct | `overrides:{문서ID:{필드:값}}`; 업무 허용 필드는 4절 |
| Settings | `document_root:str`, 1~1000자 |
| ImportContracts | `kind:'전체'|'수입'|'지출'='전체'`, `limit:int|null=null`(1~500), `only_new:bool=false` |
| StatementItem | `name:str, spec:str` 각각 최대 200자, `monthly_amount:int` |
| StatementRequest | `customer:str` 최대 200자, `issue_date/from_month/to_month:str` 각각 최대 20자, `items:StatementItem[]` 최대 100건 |
| LocalFolder | `folder:str`, 1~1000자 |
| ExpenseRequest | `title:str` 최대 500자, `month:str` 최대 20자, `supply/vat/total:StrictInt`, `attachments:str[]=[]` 최대 100건, `note:str=''` 최대 2000자 |

구조가 맞아도 월·금액·빈 품목·경로 같은 업무 검증에서 400이 될 수 있다. 예제의 이름·경로·ID는 설명용이며 실제 사용 시 현재 조회값으로 바꾼다.

## 3. 인증 2개

| 번호 | 메서드·경로 | 요청 예 | 200 응답 예·의미 | 추가 오류 | 근거 |
|---|---|---|---|---|---|
| 01 | GET `/api/auth/status` | 본문 없음 | `{"authenticated":false}` | 없음 | `saebom/api.py:165` |
| 02 | POST `/api/auth/login` | `{"password":"[실제 비밀번호]"}` | `{"authenticated":true}` + 잠금 해제 쿠키 | 401 비밀번호 불일치, 429 잠금, 422 길이/형 | `saebom/api.py:176` |

5번째 연속 실패 요청도 401이고, 이어지는 요청부터 30초 동안 429다. 잠금 중에는 정답도 거절한다. 로그인 실패 횟수·잠금은 앱 인스턴스 메모리이며 재시작하면 초기화된다. 비밀번호 값은 config에서 환경변수로 읽고 응답·DB에 기록하지 않는다. 근거: `saebom/api.py:177`, `saebom/config.py:14`.

## 4. 문서비교 7개

| 번호 | 메서드·경로 | 요청 예 | 200 응답 예·의미 | 추가 오류 | 근거 |
|---|---|---|---|---|---|
| 03 | POST `/api/sync` | 본문 없음 | `{"id":"job-example"}`; 사이트 목록 동기화 예약 | 400 작업 충돌 | `saebom/routes/compare.py:24` |
| 04 | POST `/api/download` | `{"pairs":[{"mail_id":"N01","contract_id":"C-2026-001","invoice_url":"https://sbgw.vercel.app/example.pdf"}]}` | `{"id":"job-example"}`; PDF 확보 예약 | 400 현재 목록과 연결 불일치·충돌, 422 | `saebom/routes/compare.py:36` |
| 05 | POST `/api/compare` | 04와 같은 Work | `{"id":"job-example"}`; 저장된 문서 비교 예약 | 400 연결·충돌, 422; 다운로드 미완료는 비동기 failed 가능 | `saebom/routes/compare.py:50` |
| 06 | GET `/api/results` | 본문 없음 | `[{"id":"result-example","created":"2026-10-26T10:00:00+09:00","parent":null,"count":1,"mismatch":0,"partners":["예시업체"],"mail_ids":["N01"]}]` | 없음 | `saebom/routes/compare.py:64` |
| 07 | GET `/api/results/{id}` | `id=result-example` | Result 상세(아래) | 404 결과 없음 | `saebom/routes/compare.py:76` |
| 08 | POST `/api/results/{id}/correct` | `{"overrides":{"invoice-example":{"supply":100000,"month":"2026-09"}}}` | `{"id":"job-example"}`; 부모 결과를 연결한 새 비교 예약 | 404 결과 없음, 400 보정·충돌, 422 | `saebom/routes/compare.py:91` |
| 09 | GET `/api/results/{id}/csv` | `id=result-example` | UTF-8 BOM CSV; 예: `업체,메일,계약번호,전체판정,...` | 404 결과 없음 | `saebom/routes/compare.py:108` |

연결은 현재 스냅샷의 메일·계약·첨부 PDF URL·계약 PDF 링크를 확인하며 같은 메일 중복을 거절한다. 추천 후보는 지출 계약이지만 validate_pairs 자체는 계약 구분을 제한하지 않는다. URL 예제가 실제 존재하는 다운로드 주소라는 뜻은 아니다. 근거: `saebom/services/compare_service.py:109`.

보정 대상은 결과 행의 계산서 문서 ID다. 허용 필드는 `supply,vat,total,month,biz,percent,installment,partner`이며 금액·차수는 정확한 정수 0~10^12, percent는 0~100, bool은 거절한다. 나머지는 200자 이하 문자열, month는 실제 달력상 YYYY-MM이어야 한다. 기존 보정과 새 보정을 합치되 같은 필드는 새 값이 우선한다. 원본·이전 결과는 유지한다. 근거: `saebom/overrides.py:25`, `saebom/overrides.py:47`.

Result 예시(행 없음도 표현 가능한 응답 구조 예시):

```json
{"id":"result-example","created":"2026-10-26T10:00:00+09:00","parent":null,"rows":[],"pairs":[],"overrides":{}}
```

실제 `rows[]`는 `{mail_id,contract_id,subject,partner,invoice,contract,effective_invoice,status,checks,error}`다. 문서와 effective_invoice의 pages는 응답에서 빈 배열이다. `checks[]`는 `{key,label,actual,expected,status,difference,note,invoice_source,contract_source}`이고 문서 판정은 `일치/불일치/확인 필요/처리 실패`다. 총액 계약의 `period`(분할 지급 이행 조건)는 의도적으로 `확인 필요`를 유지한다. 근거: `saebom/services/compare_service.py:167`, `saebom/compare.py:186`, `saebom/views.py:31`.

CSV는 `text/csv; charset=utf-8`, `Content-Disposition: attachment; filename="saebom-{id 앞8자리}.csv"`다. 헤더는 `업체,메일,계약번호,전체판정,항목,계산서,계약·기준,차이(계산서-기준),항목판정,설명,계산서 근거,계약 근거`다. 수식 시작 문자 `=,+,-,@,탭,CR`는 공용 이스케이프로 방어한다. 근거: `saebom/export.py:23`.

## 5. 계약·거래명세서·지출결의서 7개

| 번호 | 메서드·경로 | 요청 예 | 200 응답 예·의미 | 추가 오류 | 근거 |
|---|---|---|---|---|---|
| 10 | POST `/api/contracts/import` | `{"kind":"지출","limit":3,"only_new":true}` | `{"id":"job-example"}`; 관리번호 큰 순 가져오기 예약 | 400 충돌, 422 구분/개수 | `saebom/routes/contracts.py:46` |
| 11 | GET `/api/contracts` | 본문 없음 | `[]` 또는 ImportedContract[] | 없음 | `saebom/routes/contracts.py:58` |
| 12 | GET `/api/contracts/{id}/statement` | `id=C-2026-001` | StatementDraft(아래) | 404 계약 없음, 400 원문 없음 | `saebom/routes/contracts.py:71` |
| 13 | POST `/api/contracts/{id}/statement` | StatementRequest(아래) | `{"file":"예시.xlsx","path":"D:\\자료\\거래명세서\\예시.xlsx","rows":1,"supply":100000,"vat":10000,"total":110000,"warnings":[]}` | 404 계약 없음, 400 지출 계약·원문·업무 검증·12줄 초과·충돌, 422 | `saebom/routes/contracts.py:86` |
| 14 | GET `/api/statements/{file}` | `file=예시.xlsx` | xlsx 바이너리, attachment | 404 경로 거부·파일 없음 | `saebom/routes/contracts.py:101` |
| 15 | GET `/api/contracts/{id}/expense` | `id=C-2026-031` | ExpenseDraft(아래) | 404 계약 없음, 400 원문 없음 | `saebom/routes/contracts.py:21` |
| 16 | POST `/api/contracts/{id}/expense` | ExpenseRequest(아래) | `{"id":"job-example"}`; 실제 사이트 상신 예약 | 404 계약 없음, 400 부적격·월·검산·충돌, 422 | `saebom/routes/contracts.py:32` |

가져오기 목록이 비었을 때 `kind='전체'`는 작업 failed와 로그인 확인 안내를 남긴다. 수입·지출 필터에 해당 계약이 없거나 only_new로 남은 계약이 없으면 정상 done이다. PDF 저장 실패 계약은 contract_imports에 기록하지 않아 다음 가져오기에서 재시도한다. 근거: `saebom/services/contracts_service.py:25`.

ImportedContract는 `{id,kind,partner,title,period,amount_text,file,imported,document,status,approval}`다. `document`는 문서 또는 null, 문서에는 `available`이 붙으며 pages는 빈 배열이다. 상태 행이 없으면 `status='없음',approval=null`이다. 관리번호 큰 순이다. 근거: `saebom/services/contracts_service.py:61`.

StatementDraft 예시(미판독 값은 사람 확인 대상):

```json
{"contract_id":"C-2026-001","eligible":true,"reason":"","customer":"예시업체","customer_biz":null,"contract_date":"2026-01-01","issue_date":"2026-01-01","period_start":"2026-01-01","period_end":"2026-12-31","from_month":"2026-01","to_month":"2026-12","items":[{"name":"서비스","spec":"월정액","monthly_amount":100000}],"notes":[],"missing":[],"folder":"D:\\자료\\거래명세서"}
```

지출 계약 초안도 200과 `eligible:false,reason`을 반환한다. 생성은 수입 계약만 허용한다. 월 금액은 공급가액 기준이다. 총액 계약은 월 금액을 추정하지 않고 null·안내를 반환한다. 생성 시 품목·월별 작성 행이 최대 12줄을 넘으면 400이다. 근거: `saebom/statement.py:160`, `saebom/statement.py:234`, `saebom/statement.py:288`.

StatementRequest 예시:

```json
{"customer":"예시업체","issue_date":"2026-09-30","from_month":"2026-09","to_month":"2026-09","items":[{"name":"서비스","spec":"월정액","monthly_amount":100000}]}
```

xlsx 응답 MIME은 `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`다. 파일명은 한 경로 구간만 허용하고 `/`, `\`, `..`를 거부하며 `.xlsx` 확장자와 resolve한 상위 폴더를 검사한다. 저장 위치를 변경해도 기존 xlsx는 자동 이동하지 않는다. 근거: `saebom/routes/contracts.py:102`, `saebom/files.py:12`.

ExpenseDraft 예시:

```json
{"contract_id":"C-2026-031","eligible":true,"reason":"","title":"예시업체 서비스 지출의 건","month":"2026-09","supply":100000,"vat":10000,"total":110000,"attachments":["계약서.pdf","세금계산서.pdf"],"note":"","warnings":[],"approval":null,"partner":"예시업체","period_start":"2026-01-01","period_end":"2026-12-31"}
```

ExpenseRequest 예시:

```json
{"title":"예시업체 서비스 지출의 건","month":"2026-09","supply":100000,"vat":10000,"total":110000,"attachments":["계약서.pdf"],"note":""}
```

공급가액·합계는 양수, 세 금액은 0~10^12 정수, 공급가액+세액=합계여야 한다. 첨부는 이름을 지정하며 바이너리 업로드 API가 아니다. 사이트에 있는 첨부 후보만 선택하고 없는 이름은 경고한다. `partner`는 클라이언트 입력을 받지 않고 계약에서 강제로 넣는다. 근거: `saebom/expense.py:59`, `saebom/services/contracts_service.py:152`, `saebom/site.py:195`.

상신 결과는 `/api/contracts`의 `approval`로 조회한다. 검토 불일치면 job done이어도 계약은 `없음`, `approval.site_draft=true`다. 클릭 이후 결과 읽기 오류는 job failed와 `없음/site_draft=true/error`다. 시작 시 기존 `품의완료`를 초기화하며 자동 재상신하지 않는다. `site_draft`가 있으면 사이트에 기안이 있을 수 있으므로 확인 뒤 재상신한다. 상세 approval 필드는 [DB 설계서](03_DB_설계서.md) 3.6절을 따른다. 근거: `saebom/services/contracts_service.py:171`.

## 6. 로컬 세금계산서 대조 4개

| 번호 | 메서드·경로 | 요청 예 | 200 응답 예·의미 | 추가 오류 | 근거 |
|---|---|---|---|---|---|
| 17 | GET `/api/local-audit` | 본문 없음 | LocalAuditState(아래) | 폴더 문제는 folder_error로 200 | `saebom/routes/local_audit.py:22` |
| 18 | PUT `/api/local-audit/folder` | `{"folder":"D:\\자료\\세금계산서"}` | LocalAuditState | 400 상대경로·UNC·없는 폴더, 422 길이 | `saebom/routes/local_audit.py:34` |
| 19 | POST `/api/local-audit/pick-folder` | 본문 없음 | `{"folder":"D:\\자료\\세금계산서"}` 또는 `{"folder":null}`(취소) | 네이티브 창 오류 전파 | `saebom/routes/local_audit.py:46` |
| 20 | POST `/api/local-audit/run` | 본문 없음 | `{"id":"job-example"}` | 400 충돌; 폴더 미설정·목록 없음 등은 비동기 failed | `saebom/routes/local_audit.py:59` |

LocalAuditState 예시:

```json
{"folder":null,"folder_error":null,"files":[],"warnings":[],"last":null}
```

`files[] = {file,path,type,size,partner,partner_source,invoice:{fields,error}}`다. `last = {folder,ran_at,contracts_total,counts,warnings,rows}`이며 `rows[]`는 [DB 설계서](03_DB_설계서.md) 3.4절 구조다. 저장된 마지막 결과의 계약 문서는 조회할 때 최신 레코드·파일 존재 상태로 보강한다. PNG는 OCR 없이 확인 필요로 표시한다. 원본 로컬 파일은 수정하지 않는다. 근거: `saebom/services/local_audit_service.py:60`, `saebom/services/local_audit_service.py:108`.

선택창 응답은 폴더 설정을 저장하지 않는다. 화면이 선택값으로 PUT을 다시 호출해야 한다. 폴더 대조는 계약서 다운로드 때문에 네트워크를 사용한다. `/api/compare`의 오프라인 동작과 구별한다.

## 7. 시스템 9개

| 번호 | 메서드·경로 | 요청 예 | 200 응답 예·의미 | 추가 오류 | 근거 |
|---|---|---|---|---|---|
| 21 | GET `/api/state` | 본문 없음 | State(아래) | 이동 중 Store 잠금으로 지연 가능 | `saebom/routes/system.py:25` |
| 22 | PUT `/api/settings` | `{"document_root":"D:\\자료\\원본PDF"}` | `{"document_root":"D:\\자료\\원본PDF"}` | 400 경로·쓰기·이동·작업 충돌, 422 길이 | `saebom/routes/system.py:37` |
| 23 | POST `/api/settings/pick-folder` | 본문 없음 | `{"folder":"D:\\자료"}` 또는 `{"folder":null}` | 네이티브 창 오류 전파 | `saebom/routes/system.py:57` |
| 24 | POST `/api/browser` | 본문 없음 | `{"id":"job-example"}`; 사이트 전용 브라우저 작업 예약 | 400 충돌 | `saebom/routes/system.py:69` |
| 25 | GET `/api/documents/{id}` | `id=invoice-example` | inline application/pdf 바이너리. `?download=1`이면 `Content-Disposition: attachment`(한글 이름은 `filename*=utf-8''…`) | 404 레코드·실제 파일 없음 | `saebom/routes/system.py:81` |
| 26 | POST `/api/shutdown` | 본문 없음 | `{"ok":true}`; shutdown 콜백 요청 | 콜백 오류 전파 | `saebom/routes/system.py:97` |
| 27 | POST `/api/activate` | 본문 없음 | `{"ok":true}`; 기존 창 활성화 콜백 요청 | 잠금 해제 전 허용, 실행 쿠키 필수 | `saebom/routes/system.py:111` |
| 28 | GET `/api/devdocs` | 본문 없음 | `{"docs":[{"name":"00_문서목록.md","title":"새봄 문서비교 개발문서 목록","size":4161}]}`; 파일명이 `NN_*.md`인 문서만 이름순, 하위 폴더 제외 | 잠금 해제 필요 | `saebom/routes/devdocs.py:60` |
| 29 | GET `/api/devdocs/{name}` | `name=02_아키텍처_설계서.md` | text/markdown(UTF-8) 본문 | 404 이름 규칙 불일치·`..`·경로 구분자·인코딩 우회·없는 파일 | `saebom/routes/devdocs.py:79` |

State 예시:

```json
{"mails":[],"contracts":[],"synced":null,"jobs":[],"data_dir":"D:\\앱자료","document_root":"D:\\앱자료\\원본PDF","site":"https://sbgw.vercel.app/"}
```

`mails[]`는 사이트 메일에 `pdfs`, `documents:{URL:Document|null}`, `candidates:계약ID[]`를 추가한다. `contracts[]`는 사이트 계약에 `document`를 추가한다. 문서는 `{id,source,name,hash,extraction,disk_path,kind,available}`이고 extraction.pages는 빈 배열이다. `/api/contracts`와 달리 `/api/state.contracts`는 사이트 스냅샷이고 가져온 계약 목록이 아니다. 근거: `saebom/services/compare_service.py:46`.

폴더 선택창은 UI 스레드가 아닌 FastAPI 스레드풀에서 Tk를 호출한다. 교착·창 미표시 등은 알려진 한계이며 두 선택창 동시 실행 방지는 구현하지 않았다. 근거: `saebom/api.py:66`.

## 8. 라우트 밖 보조 경로

| 경로 | 요청·응답 |
|---|---|
| GET `/health` | Host·Origin 검사 통과 후 실행 쿠키 없이 `{"ok":true,"app":"SaebomCompare"}`; 미들웨어가 경로를 검사하므로 메서드를 별도로 한정하지 않음 |
| GET `/?token=...` | 실행 쿠키 발급 후 303 `/` |
| `/` 및 UI 정적 자원 | 실행 쿠키 검사 후 StaticFiles 제공; 정적 자원 부재는 404 |

전용 로그인은 로컬 앱 잠금이다. 그룹웨어 인증 상태는 별도 브라우저 프로필에서 사람이 확인한다. 이 API는 그룹웨어 로그인 API·실제 전자결재 최종 승인까지 제공하지 않는다.
