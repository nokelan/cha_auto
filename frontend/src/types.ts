/**
 * [파일 역할] 새봄 문서비교 화면이 서버(/api)와 주고받는 자료형 정의.
 * 런타임 코드는 없고 TypeScript 타입 검사에만 쓰인다.
 * 서버 응답 형태가 바뀌면 이 파일과 사용하는 화면을 함께 고친다.
 * 서버가 고정된 값만 주는 상태·구분 문자열은 리터럴 유니온(JobStatus·Judgement·LocalJudgement·ContractKind)으로 둔다.
 */

/** [자료형 명세] JobStatus — 서버 작업 상태(saebom/jobs.py): 진행 중·완료·실패. */
export type JobStatus = 'running' | 'done' | 'failed';

/** [자료형 명세] Judgement — 비교 판정(saebom/compare.py)과 같은 문자열. api.ts의 STATUS 값과 같다. */
export type Judgement = '일치' | '불일치' | '확인 필요' | '처리 실패';

/** [자료형 명세] LocalJudgement — 로컬 세금계산서 대조의 판정: 비교 판정 + '계약서 없음'(웹 계약 후보 0건). */
export type LocalJudgement = Judgement | '계약서 없음';

/** [자료형 명세] ContractKind — 계약 구분(수입/지출). */
export type ContractKind = '수입' | '지출';

/**
 * [자료형 명세] Field
 * 추출 필드: value·원문 quote·1부터 시작하는 page·method, 보정 전 previous.
 */
export type Field = {value: unknown; quote: string; page: number | null; method: string; previous?: Field};

/**
 * [자료형 명세] Extraction
 * 문서 추출: 필드 사전·판독 error.
 * pages(페이지 전문)는 결과 상세 API에서 빈 배열이거나 생략되며, 화면은 사용하지 않는다.
 */
export type Extraction = {fields: Record<string, Field>; pages?: {page: number; text: string}[]; error: string | null};

/**
 * [자료형 명세] Doc
 * 문서 레코드: 식별 ID·파일 이름·추출값·현재 경로·실제 파일 available.
 */
export type Doc = {id: string; name: string; extraction: Extraction; available?: boolean; disk_path: string};

/**
 * [자료형 명세] Attachment
 * 사이트 첨부의 원본 이름과 다운로드 URL.
 */
export type Attachment = {name: string; url: string};

/**
 * [자료형 명세] Mail
 * 메일과 PDF 첨부·저장 문서·추천 계약 ID 목록.
 */
export type Mail = {
  id: string;
  sender: string;
  subject: string;
  received: string;
  pdfs: Attachment[];
  documents: Record<string, Doc | null>;
  candidates: string[];
  attachments: Attachment[];
};

/**
 * [자료형 명세] Contract
 * 계약의 관리번호·구분·거래처·기간·표시 금액·PDF 문서. ImportedContract와 로컬 대조 요약(LocalContractRef·LocalCandidate)이 이 형을 재사용한다.
 */
export type Contract = {
  id: string;
  kind: ContractKind;
  partner: string;
  title: string;
  period: string;
  amount_text: string;
  file: Attachment | null;
  document: Doc | null;
};

/**
 * [자료형 명세] ImportedContract
 * '계약서 목록' 화면(GET /api/contracts, 관리번호 큰 순)의 가져온 계약 한 건.
 * 공통 계약 정보(Contract: 관리번호·구분·거래처·계약명·기간·표시 금액·사이트 첨부·저장 문서(추출값 포함))에
 * 가져온 ISO 시각(imported)·품의 상태(status)·마지막 상신 정보(approval)를 더한 것이다.
 * document.extraction.fields의 계약서 키: partner, biz, start, end, basis(monthly|total), amount,
 * vat_mode(included|excluded), ratios, payment, condition.
 */
export type ImportedContract = Contract & {
  imported: string;
  status: '품의완료' | '없음';
  approval: ExpenseApproval | null;
  /** 문서비교 화면의 대표 판정(메일별 최신 결과 중 가장 나쁜 것). 비교된 적 없으면 null. */
  compare: ContractCompare | null;
};

/**
 * [자료형 명세] ContractCompare
 * 계약서 목록의 문서비교 판정. status는 대표 판정, result_id·mail_id는 그 판정을 낸 결과와 메일,
 * count는 비교된 메일 수, counts는 판정별 건수다.
 */
export type ContractCompare = {
  status: Judgement; result_id: string; mail_id: string; created: string; count: number; counts: Partial<Record<Judgement, number>>;
};

/** [자료형 명세] 작성본 검토 한 항목. actual/expected는 작성본과 입력값이고 ok는 일치 여부다. */
export type ExpenseReview = {label: string; ok: boolean; actual: unknown; expected: unknown};
/** [자료형 명세] 계약별 마지막 지출결의서 상신·검토 정보. 상태는 계약 목록의 status를 사용한다. */
export type ExpenseApproval = {
  month: string; doc_id: string; doc_no: string; doc_url: string; title: string;
  supply: number; vat: number; total: number; document_total: number | null;
  review: ExpenseReview[]; warnings: string[]; submitted_at: string;
  /** 상신 클릭 이후 오류 또는 작성본 검토 불일치로 그룹웨어에 기안이 이미 만들어졌을 수 있음(서버 contract_status가 설정). */
  site_draft?: boolean;
  /** 마지막 상신 시도의 오류 문구(있을 때만). */
  error?: string;
};
/** [자료형 명세] 확인 창에서 수정하여 제출하는 지출결의서 값. 첨부는 사이트 파일명이다. */
export type ExpenseRequest = {
  title: string; month: string; supply: number; vat: number; total: number; attachments: string[]; note: string;
};
/** [자료형 명세] 초안 API 응답. 미판독 금액은 null이며 사람이 채워야 상신할 수 있다. */
export type ExpenseDraft = Omit<ExpenseRequest, 'supply' | 'vat' | 'total'> & {
  contract_id: string; eligible: boolean; reason: string | null; partner: string;
  supply: number | null; vat: number | null; total: number | null;
  warnings: string[]; approval: ExpenseApproval | null; period_start: string | null; period_end: string | null;
};

/**
 * [자료형 명세] Pair
 * 사용자 확정 연결: mail_id·contract_id·invoice_url.
 */
export type Pair = {mail_id: string; contract_id: string; invoice_url: string};

/**
 * [자료형 명세] Job
 * 비동기 작업: 종류·상태·완료/전체 수·오류·생성 결과 ID.
 */
export type Job = {
  id: string;
  kind: string;
  status: JobStatus;
  message: string;
  done: number;
  total: number;
  errors: string[];
  result_id?: string;
};

/**
 * [자료형 명세] State
 * 서버 상태(/api/state): 목록·작업·동기화 시각·앱 데이터 루트·PDF 루트·접속 사이트 주소.
 */
export type State = {
  mails: Mail[];
  contracts: Contract[];
  jobs: Job[];
  synced: string | null;
  data_dir: string;
  document_root: string;
  site: string;
};

/**
 * [자료형 명세] CheckItem
 * 항목별 실제값·기준값·판정·차이·설명·양쪽 근거.
 */
export type CheckItem = {
  key: string;
  label: string;
  actual: unknown;
  expected: unknown;
  status: Judgement;
  note: string;
  difference?: number | null;
  invoice_source?: Field;
  contract_source?: Field;
};

/**
 * [자료형 명세] Row
 * 메일/계약 한 쌍의 비교 결과와 원본·유효 계산서 추출값.
 */
export type Row = {
  mail_id: string;
  contract_id: string;
  subject: string;
  partner: string;
  status: Judgement;
  checks: CheckItem[];
  invoice: Doc;
  contract: Doc;
  effective_invoice: Extraction;
  error: string | null;
};

/**
 * [자료형 명세] Result
 * 결과 상세(GET /api/results/{id}): ID·시각·보정 전 부모 ID·행 목록·연결 쌍·보정값.
 */
export type Result = {
  id: string;
  created: string;
  parent?: string | null;
  rows: Row[];
  pairs?: Pair[];
  overrides?: Record<string, Record<string, unknown>>;
};

/**
 * [자료형 명세] ResultSummary
 * 결과 요약(GET /api/results 목록 항목, 최신순): 행 수·불일치 수·앞 3개 거래처·포함 메일 ID.
 */
export type ResultSummary = {
  id: string;
  created: string;
  parent: string | null;
  count: number;
  mismatch: number;
  partners: string[];
  mail_ids: string[];
};

/**
 * [자료형 명세] Preview
 * 원문 나란히 보기 모달의 두 문서와 각각 처음 열 페이지(없으면 1페이지).
 */
export type Preview = {invoice: Doc; contract: Doc; invoicePage?: number; contractPage?: number};

/**
 * [자료형 명세] StatementItem
 * 거래명세서 품목 한 줄: 품목명·규격·월 금액(원, 부가세 별도 공급가액).
 * 초안(GET)에서는 원문에서 금액을 찾지 못하면 monthly_amount가 null이다.
 */
export type StatementItem = {name: string; spec: string; monthly_amount: number | null};

/**
 * [자료형 명세] StatementDraft
 * 거래명세서 확인 창 초기값(GET /api/contracts/{id}/statement).
 * eligible=false면 reason(예: '지출 계약은 거래처가 발행합니다')을 보여 주고 생성하지 않는다.
 * 날짜는 'YYYY-MM-DD', 청구 월은 'YYYY-MM'. issue_date 기본값은 계약체결일(contract_date)이다.
 * notes: 사람이 확인할 안내(총액 계약·부가세 포함 등), missing: 원문에서 찾지 못한 값의 키
 *   (예: 'contract_date', 'items[0].spec'). folder: 생성 파일을 저장할 서버 폴더 경로.
 */
export type StatementDraft = {
  contract_id: string;
  eligible: boolean;
  reason: string | null;
  customer: string;
  customer_biz: string | null;
  contract_date: string | null;
  issue_date: string | null;
  period_start: string | null;
  period_end: string | null;
  from_month: string | null;
  to_month: string | null;
  items: StatementItem[];
  notes: string[];
  missing: string[];
  folder: string;
};

/**
 * [자료형 명세] StatementRequest
 * 거래명세서 생성 요청 본문(POST /api/contracts/{id}/statement). 확인 창에서 사람이 고친 값이다.
 * monthly_amount는 양의 정수여야 한다(서버가 다시 검증).
 */
export type StatementRequest = {
  customer: string;
  issue_date: string;
  from_month: string;
  to_month: string;
  items: {name: string; spec: string; monthly_amount: number}[];
};

/**
 * [자료형 명세] StatementResult
 * 거래명세서 생성 결과: 저장 파일명·전체 경로·채운 줄 수·공급가액·세액·합계·경고 문구.
 * 파일은 GET /api/statements/{file}로 내려받는다.
 */
export type StatementResult = {
  file: string;
  path: string;
  rows: number;
  supply: number;
  vat: number;
  total: number;
  warnings: string[];
};

/**
 * [자료형 명세] LocalInvoice
 * 로컬 세금계산서 판독값: 필드 사전(partner, biz, issued, supply, vat, total, month)·판독 오류.
 * PNG나 텍스트 없는 PDF는 fields가 비고 error에 사유가 들어올 수 있다.
 */
export type LocalInvoice = Omit<Extraction, 'pages'>;

/**
 * [자료형 명세] LocalFile
 * 로컬 폴더(GET /api/local-audit files)의 세금계산서 파일 한 건.
 * file: 파일명, path: 전체 경로, type: 'pdf'|'png', size: 바이트,
 * partner: 상호(없으면 null), partner_source: 상호를 읽은 곳('pdf' 본문 / 'filename' 파일명 규칙 / null), invoice: 판독값.
 */
export type LocalFile = {
  file: string;
  path: string;
  type: 'pdf' | 'png';
  size: number;
  partner: string | null;
  partner_source: 'pdf' | 'filename' | null;
  invoice: LocalInvoice;
};

/**
 * [자료형 명세] LocalContractRef
 * 로컬 대조 행에 연결된 웹 계약 요약: 관리번호·구분·거래처·계약명·기간·표시 금액.
 */
export type LocalContractRef = Pick<Contract, 'id' | 'kind' | 'partner' | 'title' | 'period' | 'amount_text'>;

/**
 * [자료형 명세] LocalCandidate
 * 상호가 맞는 웹 계약 후보 한 건(관리번호·구분·거래처·계약명). 여럿이면 사람이 확인한다.
 */
export type LocalCandidate = Pick<Contract, 'id' | 'kind' | 'partner' | 'title'>;

/**
 * [자료형 명세] LocalAuditRow
 * 로컬 대조 결과 한 행. LocalFile의 file·type·size·partner·partner_source·invoice에 더해
 * contract(고른 계약 또는 null), contract_doc(저장된 계약서 문서 레코드 + available, 없으면 null),
 * candidates(후보 목록), expected(계약 기준 기대 공급가액·세액·합계, 없으면 null),
 * status(LocalJudgement), checks(항목별 판정), note(판정 설명)를 담는다.
 * path는 서버가 넣지 않을 수 있어 선택 항목이다.
 */
export type LocalAuditRow = Omit<LocalFile, 'path'> & {
  path?: string;
  contract: LocalContractRef | null;
  contract_doc: Doc | null;
  candidates: LocalCandidate[];
  expected: {supply: number | null; vat: number | null; total: number | null} | null;
  status: LocalJudgement;
  checks: CheckItem[];
  note: string;
};

/**
 * [자료형 명세] LocalAudit
 * 마지막 로컬 대조 실행 결과: 대조한 폴더·실행 ISO 시각·웹 계약 수·판정별 건수·행 목록.
 */
export type LocalAudit = {
  folder: string;
  ran_at: string;
  contracts_total: number;
  counts: Record<string, number>;
  rows: LocalAuditRow[];
};

/**
 * [자료형 명세] LocalAuditState
 * '로컬 세금계산서 대조' 화면 상태(GET /api/local-audit, PUT /api/local-audit/folder 응답).
 * folder: 저장된 세금계산서 폴더(없으면 null), folder_error: 폴더를 읽지 못한 사유,
 * files: 폴더의 PDF·PNG 목록, last: 마지막 대조 결과(없으면 null).
 */
export type LocalAuditState = {
  folder: string | null;
  folder_error: string | null;
  files: LocalFile[];
  last: LocalAudit | null;
};

/** [타입 명세] DevDocInfo — GET /api/devdocs 의 문서 한 건(파일명·제목·바이트 크기). */
export type DevDocInfo = {name: string; title: string; size: number};

/** [타입 명세] DocToc — 현재 개발문서의 목차 항목(제목 id·레벨·글자). */
export type DocToc = {id: string; level: number; text: string};
