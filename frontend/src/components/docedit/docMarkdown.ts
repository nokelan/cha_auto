/**
 * [파일 역할] 전송 전 문서 편집 3단 화면의 "변환 모듈".
 * 거래명세서·지출결의서 입력 필드(문자열 기반)와 고정 서식 마크다운 문서를 서로 바꾼다(계획서 4.2절).
 * - 정변환(XxxToMarkdown): 필드 → 마크다운. 값의 줄바꿈은 공백으로, 표 셀의 `|`·`\`는 이스케이프한다.
 * - 역변환(markdownToXxx): 마크다운 → 필드 + 형식 문제 목록. 라벨(`수신:` 등)로 값을 읽고 순서는 따지지 않으며
 *   한글 콜론(：)도 허용한다. 코드 펜스(```) 안의 줄은 라벨·섹션·표로 해석하지 않는다.
 * - 요청 변환(toXxxRequest): 문제가 없을 때 서버 요청 본문(src/types.ts)으로 바꾼다. 금액은 정수.
 * 이 모듈은 형식 문제(필수 라벨·표 머리글 누락, 숫자 아님, 표 열 수 불일치, 월·날짜 형식 오류)만 problems로 돌려준다.
 * 합계 검산·월 범위 같은 의미 검증은 각 확인 창과 서버가 계속 맡는다. 모든 함수는 순수 함수이며 부수효과가 없다.
 */
import type {ExpenseRequest, StatementRequest} from '../../types';
import {parseNonNegativeAmount} from '../../utils/amount';

/** [자료형 명세] 거래명세서 편집 필드. 금액은 문자열로 들고 있다가 요청 변환 때 정수로 해석한다. */
export type StatementFields = {customer: string; issueDate: string; fromMonth: string; toMonth: string; items: {name: string; spec: string; amount: string}[]};
/** [자료형 명세] 지출결의서 편집 필드. note는 특이사항 원문(마크다운 포함 가능)이다. */
export type ExpenseFields = {title: string; month: string; supply: string; vat: string; total: string; attachments: string[]; note: string};
/** [자료형 명세] 역변환 결과: 읽어 낸 필드와 형식 문제 문구 목록(비어 있으면 형식상 정상). */
export type ParseResult<T> = {fields: T; problems: string[]};

const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const NOTE_HEADING = '특이사항';

/**
 * [기능명세] oneLine
 * 목적: 목록·표에 들어갈 값을 한 줄로 만든다.
 * 입력: value — 임의 문자열. 출력: 줄바꿈이 공백 하나로 바뀌고 앞뒤 공백이 제거된 문자열.
 * 부수효과/예외: 없음.
 */
function oneLine(value: string): string {
  return value.replace(/\s*[\r\n]+\s*/g, ' ').trim();
}

/**
 * [기능명세] escapeCell / splitRow
 * 목적: 표 셀의 `|`·`\`를 `\|`·`\\`로 이스케이프(escapeCell)하고, 표 행 한 줄을 셀 배열로 쪼개 복원한다(splitRow).
 * 입력: escapeCell — 셀 값 / splitRow — `|`로 시작하는 한 줄.
 * 출력: 이스케이프된 문자열 / 앞뒤 공백이 제거된 셀 문자열 배열(양끝 파이프는 버림).
 * 처리 규칙: `\|`와 `\\`만 복원하고 다른 `\x`는 그대로 둔다. 이스케이프되지 않은 `|`가 셀 경계다.
 * 부수효과/예외: 없음.
 */
function escapeCell(value: string): string {
  return oneLine(value).replace(/\\/g, '\\\\').replace(/\|/g, '\\|');
}
function splitRow(line: string): string[] {
  let text = line.trim();
  if (text.startsWith('|')) text = text.slice(1);
  const cells: string[] = [];
  let cur = '';
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    const next = text[i + 1];
    if (ch === '\\' && (next === '|' || next === '\\')) {
      cur += next;
      i++;
    } else if (ch === '|') {
      cells.push(cur.trim());
      cur = '';
    } else {
      cur += ch;
    }
  }
  // 마지막 파이프 뒤에 내용이 남아 있을 때만(닫는 파이프가 없는 행) 마지막 셀로 추가한다.
  if (cur.trim() !== '') cells.push(cur.trim());
  return cells;
}

/**
 * [기능명세] stripAmount
 * 목적: 금액 표기에서 쉼표·공백·`원`을 지워 숫자만 남긴다.
 * 입력: text — 금액 문자열. 출력: 정리된 문자열(숫자가 아닌 글자가 남으면 그대로 두어 호출자가 문제로 보고).
 * 부수효과/예외: 없음.
 */
function stripAmount(text: string): string {
  return text.replace(/[,\s]/g, '').replace(/원$/, '');
}

/**
 * [기능명세] Scan / scan
 * 목적: 마크다운을 줄로 나누고 코드 펜스 안팎을 표시한다.
 * 입력: md — 마크다운 원문(CRLF 허용). 출력: 줄 배열과 각 줄의 펜스 여부(펜스 여는·닫는 줄 포함).
 * 부수효과/예외: 없음.
 */
function scan(md: string): {lines: string[]; fenced: boolean[]} {
  const lines = md.replace(/\r\n?/g, '\n').split('\n');
  const fenced: boolean[] = [];
  let open = false;
  for (const line of lines) {
    const isFence = /^\s*(```|~~~)/.test(line);
    if (isFence) {
      fenced.push(true);
      open = !open;
    } else {
      fenced.push(open);
    }
  }
  return {lines, fenced};
}

/**
 * [기능명세] readDoc
 * 목적: 역변환 공통 해석. 라벨 값, `##` 섹션별 줄, 표 행을 한 번에 모은다.
 * 입력: md — 마크다운; stopAtNote — true이면 `## 특이사항` 제목 이후를 해석하지 않고 note 원문으로 돌려준다.
 * 출력: labels(라벨→첫 값), attachments(`## 첨부` 목록), tableLines(`## 품목` 섹션의 `|` 줄), note(원문, 앞뒤 빈 줄 정리).
 * 처리 규칙: 코드 펜스 안은 무시. 라벨은 `- 라벨: 값`(`*`·`+` 도 허용, 한글 콜론 허용)이며 `## 첨부`·`## 품목` 안에서는 라벨로 읽지 않는다.
 *   같은 라벨이 여러 번이면 처음 것만 쓴다.
 * 부수효과/예외: 없음(던지지 않음).
 */
function readDoc(md: string, stopAtNote: boolean) {
  const {lines, fenced} = scan(md);
  const labels = new Map<string, string>();
  const attachments: string[] = [];
  const tableLines: string[] = [];
  let section = '';
  let note = '';
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (fenced[i]) continue;
    const heading = /^##\s+(.+?)\s*$/.exec(line);
    if (heading) {
      section = heading[1];
      if (stopAtNote && section === NOTE_HEADING) {
        note = lines.slice(i + 1).join('\n').replace(/^(?:[ \t]*\n)+/, '').replace(/(?:\n[ \t]*)+$/, '');
        break;
      }
      continue;
    }
    if (/^#\s/.test(line)) {
      section = '';
      continue;
    }
    const item = /^\s*[-*+]\s+(.*?)\s*$/.exec(line);
    if (section === '첨부') {
      if (item && item[1]) attachments.push(item[1]);
    } else if (section === '품목') {
      if (/^\s*\|/.test(line)) tableLines.push(line);
    } else {
      const label = /^\s*[-*+]\s*([^:：]+?)\s*[:：]\s*(.*?)\s*$/.exec(line);
      if (label && !labels.has(label[1])) labels.set(label[1], oneLine(label[2]));
    }
  }
  return {labels, attachments, tableLines, note};
}

/**
 * [기능명세] label
 * 목적: 필수 라벨 값을 꺼내고 없으면 문제 문구를 추가한다.
 * 입력: labels — readDoc 결과; name — 라벨 이름; problems — 문제 목록(변경됨).
 * 출력: 값 또는 빈 문자열. 부수효과: 라벨이 없으면 problems에 "'이름' 항목이 없습니다." 추가.
 */
function label(labels: Map<string, string>, name: string, problems: string[]): string {
  const value = labels.get(name);
  if (value === undefined) {
    problems.push("'" + name + "' 항목이 없습니다.");
    return '';
  }
  return value;
}

/**
 * [기능명세] amountLabel
 * 목적: 금액 라벨을 읽어 쉼표·`원`을 지운 문자열로 돌려주고, 값이 있는데 숫자가 아니면 문제로 보고한다.
 * 입력: labels, name, problems(변경됨). 출력: 정리된 금액 문자열(숫자 아님이면 정리 전 값 유지).
 * 부수효과: 라벨 누락·숫자 아님 문구를 problems에 추가.
 */
function amountLabel(labels: Map<string, string>, name: string, problems: string[]): string {
  const raw = label(labels, name, problems);
  if (!raw) return '';
  const value = stripAmount(raw);
  if (parseNonNegativeAmount(value) === null) {
    problems.push(name + '은(는) 숫자만 입력하세요.');
    return raw;
  }
  return value;
}

/**
 * [기능명세] statementToMarkdown
 * 목적: 거래명세서 필드를 고정 서식 마크다운으로 만든다(계획서 4.2절).
 * 입력: f — 거래명세서 필드. 출력: 마크다운 문자열(끝에 줄바꿈 하나).
 * 처리 규칙: 목록 값은 한 줄로(줄바꿈→공백), 표 셀은 `|`·`\` 이스케이프. 품목이 없으면 머리글·구분선만 출력한다.
 * 부수효과/예외: 없음.
 */
export function statementToMarkdown(f: StatementFields): string {
  const out = [
    '# 거래명세서', '', '## 기본 정보', '',
    '- 수신: ' + oneLine(f.customer),
    '- 작성 일자: ' + oneLine(f.issueDate),
    '- 청구 시작 월: ' + oneLine(f.fromMonth),
    '- 청구 끝 월: ' + oneLine(f.toMonth),
    '', '## 품목', '',
    '| 품목명 | 규격 | 월 금액 |', '| --- | --- | --- |',
  ];
  for (const it of f.items) out.push('| ' + escapeCell(it.name) + ' | ' + escapeCell(it.spec) + ' | ' + escapeCell(it.amount) + ' |');
  return out.join('\n') + '\n';
}

/**
 * [기능명세] markdownToStatement
 * 목적: 거래명세서 마크다운을 필드로 읽는다.
 * 입력: md — 마크다운 원문. 출력: {fields, problems}.
 * 처리 규칙: 필수 라벨(수신·작성 일자·청구 시작 월·청구 끝 월)이 없으면 "'수신' 항목이 없습니다." 등을 추가하고 빈 문자열로 둔다.
 *   작성 일자는 YYYY-MM-DD, 월은 YYYY-MM이 아니면(값이 있을 때) 문제. 품목 표는 `| 품목명 | 규격 | 월 금액 |` 머리글이 필요하며
 *   구분선 행은 건너뛰고 데이터 행은 열이 3개여야 한다(아니면 해당 행은 문제로 보고하고 가능한 만큼만 채워 포함).
 *   월 금액 셀은 쉼표·`원`을 제거하며, 숫자가 아니면 문제(값은 원문 유지).
 * 부수효과/예외: 없음(던지지 않음).
 */
export function markdownToStatement(md: string): ParseResult<StatementFields> {
  const problems: string[] = [];
  const {labels, tableLines} = readDoc(md, false);
  const customer = label(labels, '수신', problems);
  const issueDate = label(labels, '작성 일자', problems);
  const fromMonth = label(labels, '청구 시작 월', problems);
  const toMonth = label(labels, '청구 끝 월', problems);
  if (issueDate && !DATE_RE.test(issueDate)) problems.push('작성 일자는 YYYY-MM-DD 형식으로 입력하세요.');
  if (fromMonth && !MONTH_RE.test(fromMonth)) problems.push('청구 시작 월은 YYYY-MM 형식으로 입력하세요.');
  if (toMonth && !MONTH_RE.test(toMonth)) problems.push('청구 끝 월은 YYYY-MM 형식으로 입력하세요.');

  const items: StatementFields['items'] = [];
  if (!tableLines.length) {
    problems.push('품목 표가 없습니다.');
  } else {
    const head = splitRow(tableLines[0]);
    if (head.length !== 3 || head[0] !== '품목명' || head[1] !== '규격' || head[2] !== '월 금액') {
      problems.push("품목 표의 머리글은 '품목명 | 규격 | 월 금액'이어야 합니다.");
    }
    let dataNo = 0;
    for (const line of tableLines.slice(1)) {
      const cells = splitRow(line);
      if (cells.length > 0 && cells.every((c) => /^:?-+:?$/.test(c))) continue;
      dataNo++;
      if (cells.length !== 3) {
        problems.push('품목 ' + dataNo + ': 열이 ' + cells.length + '개입니다. 품목명·규격·월 금액 3개여야 합니다.');
      }
      const amountRaw = cells[2] ?? '';
      const amount = stripAmount(amountRaw);
      if (amountRaw && parseNonNegativeAmount(amount) === null) {
        problems.push('품목 ' + dataNo + ': 월 금액은 숫자만 입력하세요.');
      }
      items.push({name: cells[0] ?? '', spec: cells[1] ?? '', amount: amountRaw && parseNonNegativeAmount(amount) === null ? amountRaw : amount});
    }
    if (!items.length) problems.push('품목 표에 품목 행이 없습니다.');
  }
  return {fields: {customer, issueDate, fromMonth, toMonth, items}, problems};
}

/**
 * [기능명세] expenseToMarkdown
 * 목적: 지출결의서 필드를 고정 서식 마크다운으로 만든다(계획서 4.2절).
 * 입력: f — 지출결의서 필드. 출력: 마크다운 문자열(끝에 줄바꿈 하나).
 * 처리 규칙: 목록 값은 한 줄로, 빈 첨부 항목은 제외. `## 특이사항` 제목은 note가 비어도 항상 출력하고 note는 원문 그대로 붙인다.
 * 부수효과/예외: 없음.
 */
export function expenseToMarkdown(f: ExpenseFields): string {
  const out = [
    '# 지출결의서', '', '## 기본 정보', '',
    '- 제목: ' + oneLine(f.title),
    '- 청구·사용 월: ' + oneLine(f.month),
    '', '## 금액', '',
    '- 공급가액: ' + oneLine(f.supply),
    '- 세액: ' + oneLine(f.vat),
    '- 합계: ' + oneLine(f.total),
    '', '## 첨부', '',
  ];
  for (const a of f.attachments) {
    const name = oneLine(a);
    if (name) out.push('- ' + name);
  }
  out.push('', '## ' + NOTE_HEADING, '');
  return out.join('\n') + '\n' + f.note.replace(/\r\n?/g, '\n') + (f.note ? '\n' : '');
}

/**
 * [기능명세] markdownToExpense
 * 목적: 지출결의서 마크다운을 필드로 읽는다.
 * 입력: md — 마크다운 원문. 출력: {fields, problems}.
 * 처리 규칙: 필수 라벨(제목·청구·사용 월·공급가액·세액·합계)이 없으면 "'제목' 항목이 없습니다." 등을 추가한다.
 *   월은 YYYY-MM(값이 있을 때), 금액은 쉼표·`원` 제거 후 숫자만 허용(아니면 문제). 첨부는 `## 첨부`의 `- ` 항목(빈 항목 제외).
 *   `## 특이사항` 이후 나머지 전부(그 안의 `#` 제목·코드 펜스 포함)를 앞뒤 빈 줄만 정리해 note로 쓴다.
 *   특이사항 제목이 없으면 note는 빈 문자열이며 문제로 보지 않는다.
 * 부수효과/예외: 없음(던지지 않음).
 */
export function markdownToExpense(md: string): ParseResult<ExpenseFields> {
  const problems: string[] = [];
  const {labels, attachments, note} = readDoc(md, true);
  const title = label(labels, '제목', problems);
  const month = label(labels, '청구·사용 월', problems);
  if (month && !MONTH_RE.test(month)) problems.push('청구·사용 월은 YYYY-MM 형식으로 입력하세요.');
  const supply = amountLabel(labels, '공급가액', problems);
  const vat = amountLabel(labels, '세액', problems);
  const total = amountLabel(labels, '합계', problems);
  return {fields: {title, month, supply, vat, total, attachments, note}, problems};
}

/**
 * [기능명세] toStatementRequest
 * 목적: 형식 문제가 없는 거래명세서 필드를 서버 요청 본문으로 바꾼다.
 * 입력: f. 출력: StatementRequest(monthly_amount는 정수).
 * 처리 규칙: 쉼표·`원`을 지운 뒤 정수로 해석하며 해석할 수 없으면 0(서버 검증이 거부한다). 문제가 있는 필드에는 쓰지 않는다.
 * 부수효과/예외: 없음.
 */
export function toStatementRequest(f: StatementFields): StatementRequest {
  return {
    customer: f.customer,
    issue_date: f.issueDate,
    from_month: f.fromMonth,
    to_month: f.toMonth,
    items: f.items.map((it) => ({name: it.name, spec: it.spec, monthly_amount: parseNonNegativeAmount(stripAmount(it.amount)) ?? 0})),
  };
}

/**
 * [기능명세] toExpenseRequest
 * 목적: 형식 문제가 없는 지출결의서 필드를 서버 요청 본문으로 바꾼다.
 * 입력: f. 출력: ExpenseRequest(supply·vat·total은 정수, 해석 불가면 0이며 서버 검증이 거부한다).
 * 부수효과/예외: 없음.
 */
export function toExpenseRequest(f: ExpenseFields): ExpenseRequest {
  const num = (s: string) => parseNonNegativeAmount(stripAmount(s)) ?? 0;
  return {
    title: f.title, month: f.month, supply: num(f.supply), vat: num(f.vat), total: num(f.total),
    attachments: [...f.attachments], note: f.note,
  };
}
