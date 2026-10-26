/**
 * [파일 역할] '로컬 세금계산서 대조' 화면이 쓰는 순수 함수·상수·자료형(LocalAuditScreen에서 분리).
 * 서버 상태(LocalAuditState)를 표 행(ViewRow)으로 바꾸는 buildRows, 표시용 수치·문자열 변환, 판정 탭 상수를 둔다.
 * React·네트워크·전역 상태를 쓰지 않으므로 같은 입력에는 항상 같은 출력을 낸다.
 */
import {display, LOCAL_STATUS, STATUS} from '../../api';
import type {Field, LocalAuditRow, LocalAuditState, LocalJudgement} from '../../types';

/** [상수 명세] TABS — 판정 필터 탭. '전체'는 '처리 실패'·'대조 전'을 포함한 모든 행이다. */
export const TABS = ['전체', STATUS.MATCH, STATUS.MISMATCH, STATUS.CHECK, LOCAL_STATUS.NONE] as const;
export type Tab = typeof TABS[number];

/**
 * [자료형 명세] ViewRow
 * 표·상세가 쓰는 한 행. 대조 결과 행(LocalAuditRow)에 audited(대조 결과에서 왔는지)를 더하고,
 * status에 화면 전용 '대조 전'을 허용한 것이다.
 * 대조 전 파일은 contract·contract_doc·expected를 null, candidates·checks를 빈 배열, status를 '대조 전'으로 채운다.
 */
export type ViewRow = Omit<LocalAuditRow, 'status'> & {status: LocalJudgement | typeof LOCAL_STATUS.PENDING; audited: boolean};

/** [상수 명세] INVOICE_FIELDS — 상세에 보여 줄 세금계산서 판독 필드(키·라벨) 순서. */
export const INVOICE_FIELDS: [string, string][] = [
  ['partner', '상호'],
  ['biz', '사업자등록번호'],
  ['issued', '작성일자'],
  ['month', '청구월'],
  ['supply', '공급가액'],
  ['vat', '세액'],
  ['total', '합계'],
];

/**
 * [기능명세] buildRows
 * 목적: 서버 상태를 표에 쓸 행 목록으로 변환
 * 입력: data(GET /api/local-audit 응답, 아직 없으면 null)
 * 출력: ViewRow 배열
 * 처리/실패: last가 있고 last.folder가 현재 folder와 같으면 last.rows를 audited=true로 쓰고,
 *   files 중 그 행들에 없는 파일명은 '대조 전' 행으로 덧붙인다. 그 밖(결과 없음·폴더 변경)에는 files 전체를 '대조 전'으로 만든다
 * 부수효과: 없음
 */
export function buildRows(data: LocalAuditState | null): ViewRow[] {
  if (!data) return [];
  const pending = (f: LocalAuditState['files'][number]): ViewRow => ({
    ...f,
    contract: null,
    contract_doc: null,
    candidates: [],
    expected: null,
    status: LOCAL_STATUS.PENDING,
    checks: [],
    note: '',
    audited: false,
  });
  const last = data.last;
  if (!last || !data.folder || last.folder !== data.folder) return data.files.map(pending);
  const rows: ViewRow[] = last.rows.map(r => ({...r, audited: true}));
  const seen = new Set(rows.map(r => r.file));
  return rows.concat(data.files.filter(f => !seen.has(f.file)).map(pending));
}

/**
 * [기능명세] num
 * 목적: 판독 필드 값을 숫자로 꺼내기(차이 계산용)
 * 입력: v(필드 값 unknown)
 * 출력: 유한한 number면 그 값, 아니면 null
 * 처리/실패: 문자열·null·NaN은 null로 본다(서버가 숫자로 주는 것을 전제로 함)
 * 부수효과: 없음
 */
export function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

/**
 * [기능명세] fieldValue
 * 목적: 세금계산서 판독 필드 하나의 값 꺼내기
 * 입력: row(행), key(필드 키)
 * 출력: 값(unknown). 없으면 undefined
 * 처리/실패: invoice나 fields가 없어도 오류 없이 undefined를 돌려준다
 * 부수효과: 없음
 */
export function fieldValue(row: ViewRow, key: string): unknown {
  return row.invoice?.fields?.[key]?.value;
}

/**
 * [기능명세] supplyDiff
 * 목적: 표의 '차이' 열 값 계산
 * 입력: row(행)
 * 출력: 세금계산서 공급가액 − 기대 공급가액(원). 둘 중 하나라도 숫자가 아니면 null
 * 처리/실패: 대조 전 행은 expected가 null이라 항상 null
 * 부수효과: 없음
 */
export function supplyDiff(row: ViewRow): number | null {
  const actual = num(fieldValue(row, 'supply'));
  const expected = num(row.expected?.supply);
  return actual === null || expected === null ? null : actual - expected;
}

/**
 * [기능명세] fileSize
 * 목적: 파일 크기를 사람이 읽는 문자열로 변환
 * 입력: bytes(바이트 수)
 * 출력: 'N KB' 또는 'N.N MB'. 숫자가 아니면 '미확인'
 * 처리/실패: 1 MiB 미만은 KB(올림), 이상은 MB 소수 한 자리
 * 부수효과: 없음
 */
export function fileSize(bytes: number): string {
  if (typeof bytes !== 'number' || !Number.isFinite(bytes)) return '미확인';
  return bytes < 1024 * 1024 ? Math.ceil(bytes / 1024).toLocaleString('ko-KR') + ' KB' : (bytes / 1024 / 1024).toFixed(1) + ' MB';
}

/**
 * [기능명세] runBlock
 * 목적: [웹 계약서와 대조] 버튼을 끌지와 그 이유 결정
 * 입력: folder(저장된 폴더 또는 null), busy(App의 다른 요청·작업 진행 중), saving(이 화면의 폴더 선택·저장 중)
 * 출력: 끌 이유 문구. 켤 수 있으면 빈 문자열
 * 처리/실패: 우선순위는 폴더 없음 → 폴더 저장 중 → 다른 작업 중
 * 부수효과: 없음
 */
export function runBlock(folder: string | null, busy: boolean, saving: boolean): string {
  if (!folder) return '먼저 세금계산서 폴더를 선택하세요';
  if (saving) return '폴더를 저장하는 중입니다';
  if (busy) return '다른 작업이 끝난 뒤 실행할 수 있습니다';
  return '';
}

/**
 * [기능명세] invoiceText
 * 목적: 세금계산서 판독 필드 하나를 상세 화면 문자열로 변환
 * 입력: fields(판독 필드 사전, 없을 수 있음), key(필드 키)
 * 출력: 표시 문자열. 값이 없거나 빈 문자열이면 '미확인'
 * 처리/실패: display()로 숫자 천 단위·배열 쉼표 연결 처리
 * 부수효과: 없음
 */
export function invoiceText(fields: Record<string, Field> | undefined, key: string): string {
  const v = fields?.[key]?.value;
  return v === '' ? '미확인' : display(v);
}
