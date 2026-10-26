/**
 * [파일 역할] docMarkdown.ts(문서 편집 변환 모듈) 단위 시험(vitest).
 * 왕복 동일성, 표 `|` 이스케이프, 쉼표 금액, 라벨 순서·한글 콜론 허용, 필수 항목 누락·표 열 수 오류 문구,
 * 특이사항의 `#` 제목·코드 펜스 보존, 빈 특이사항, 요청 본문 정수 변환을 확인한다.
 * 부수효과 없음(순수 함수만 호출).
 */
import {describe, expect, it} from 'vitest';
import {
  expenseToMarkdown, markdownToExpense, markdownToStatement, statementToMarkdown,
  toExpenseRequest, toStatementRequest,
  type ExpenseFields, type StatementFields,
} from './docMarkdown';

const statement: StatementFields = {
  customer: '(주)한울정보', issueDate: '2026-09-30', fromMonth: '2026-01', toMonth: '2026-12',
  items: [
    {name: '유지보수', spec: '월 1회', amount: '190000'},
    {name: 'A|B 서비스', spec: 'x\\y', amount: '50000'},
  ],
};
const expense: ExpenseFields = {
  title: '[IT기획팀] 한울정보 지출의 건 (26.09월)', month: '2026-09',
  supply: '2100000', vat: '210000', total: '2310000',
  attachments: ['계약서_a.pdf', '세금계산서_b.pdf', '메모 3.pdf'],
  note: '첫 줄\n\n## 소제목\n```\n# 펜스 안 제목\n- 합계: 1\n```\n끝',
};

describe('거래명세서', () => {
  it('다품목 왕복이 동일하다', () => {
    const r = markdownToStatement(statementToMarkdown(statement));
    expect(r.problems).toEqual([]);
    expect(r.fields).toEqual(statement);
  });
  it('표 셀의 | 는 이스케이프되고 복원된다', () => {
    const md = statementToMarkdown(statement);
    expect(md).toContain('A\\|B 서비스');
    expect(markdownToStatement(md).fields.items[1].name).toBe('A|B 서비스');
  });
  it('값의 줄바꿈은 공백으로 바뀐다', () => {
    const md = statementToMarkdown({...statement, customer: '가\n나'});
    expect(markdownToStatement(md).fields.customer).toBe('가 나');
  });
  it('쉼표·원이 있는 금액은 숫자만 남긴다', () => {
    const md = statementToMarkdown(statement).replace('190000', '1,900,000원');
    const r = markdownToStatement(md);
    expect(r.problems).toEqual([]);
    expect(r.fields.items[0].amount).toBe('1900000');
  });
  it('라벨 순서가 바뀌고 한글 콜론이어도 읽는다', () => {
    const md = [
      '## 기본 정보', '- 청구 끝 월： 2026-12', '- 청구 시작 월:2026-01', '- 작성 일자 : 2026-09-30', '- 수신：  (주)순서',
      '## 품목', '| 품목명 | 규격 | 월 금액 |', '|---|---|---|', '| 가 | 나 | 100 |',
    ].join('\n');
    const r = markdownToStatement(md);
    expect(r.problems).toEqual([]);
    expect(r.fields).toMatchObject({customer: '(주)순서', fromMonth: '2026-01', toMonth: '2026-12', issueDate: '2026-09-30'});
  });
  it('필수 라벨·표가 없으면 한글 문제 문구를 돌려준다', () => {
    const r = markdownToStatement('# 거래명세서\n- 작성 일자: 2026-09-30\n');
    expect(r.problems).toContain("'수신' 항목이 없습니다.");
    expect(r.problems).toContain("'청구 시작 월' 항목이 없습니다.");
    expect(r.problems).toContain('품목 표가 없습니다.');
    expect(r.fields.customer).toBe('');
  });
  it('표 열 수 오류와 숫자 아님을 알린다', () => {
    const md = statementToMarkdown({...statement, items: []}) + '| 가 | 나 |\n| 다 | 라 | 열두개 |\n';
    const r = markdownToStatement(md);
    expect(r.problems.some((p) => p.includes('품목 1') && p.includes('열'))).toBe(true);
    expect(r.problems.some((p) => p.includes('품목 2') && p.includes('숫자'))).toBe(true);
  });
  it('잘못된 월 형식과 머리글을 알린다', () => {
    const md = statementToMarkdown(statement).replace('2026-01', '26년 1월').replace('월 금액', '금액');
    const r = markdownToStatement(md);
    expect(r.problems.some((p) => p.includes('청구 시작 월'))).toBe(true);
    expect(r.problems.some((p) => p.includes('머리글'))).toBe(true);
  });
  it('코드 펜스 안의 라벨은 무시한다', () => {
    const md = '```\n- 수신: 가짜\n```\n' + statementToMarkdown(statement);
    expect(markdownToStatement(md).fields.customer).toBe('(주)한울정보');
  });
  it('요청 변환은 정수 금액을 만든다', () => {
    const req = toStatementRequest({...statement, items: [{name: 'a', spec: 'b', amount: '1,900,000'}]});
    expect(req.items[0].monthly_amount).toBe(1900000);
    expect(Number.isInteger(req.items[0].monthly_amount)).toBe(true);
    expect(req).toMatchObject({customer: '(주)한울정보', issue_date: '2026-09-30', from_month: '2026-01', to_month: '2026-12'});
  });
});

describe('지출결의서', () => {
  it('첨부 여러 개와 특이사항 왕복이 동일하다', () => {
    const r = markdownToExpense(expenseToMarkdown(expense));
    expect(r.problems).toEqual([]);
    expect(r.fields).toEqual(expense);
  });
  it('특이사항 안의 # 제목·코드 펜스는 섹션 분리에 쓰지 않고 보존한다', () => {
    const note = '# 최상위\n## 첨부\n- 가짜.pdf\n```\n## 특이사항\n```';
    const r = markdownToExpense(expenseToMarkdown({...expense, note}));
    expect(r.fields.note).toBe(note);
    expect(r.fields.attachments).toEqual(expense.attachments);
  });
  it('빈 note도 특이사항 제목을 출력하고 왕복된다', () => {
    const md = expenseToMarkdown({...expense, note: ''});
    expect(md).toContain('## 특이사항');
    expect(markdownToExpense(md).fields.note).toBe('');
  });
  it('쉼표 금액·라벨 순서·한글 콜론을 허용한다', () => {
    const md = ['## 금액', '- 합계： 2,310,000원', '- 세액: 210,000', '- 공급가액: 2,100,000',
      '## 기본 정보', '- 청구·사용 월: 2026-09', '- 제목: 제목입니다', '## 첨부', '- a.pdf', '-', '## 특이사항', '', '메모', ''].join('\n');
    const r = markdownToExpense(md);
    expect(r.problems).toEqual([]);
    expect(r.fields).toEqual({title: '제목입니다', month: '2026-09', supply: '2100000', vat: '210000', total: '2310000', attachments: ['a.pdf'], note: '메모'});
  });
  it('필수 라벨 누락과 숫자 아님을 알린다', () => {
    const r = markdownToExpense('# 지출결의서\n## 금액\n- 공급가액: 열 만\n');
    expect(r.problems).toContain("'제목' 항목이 없습니다.");
    expect(r.problems).toContain("'세액' 항목이 없습니다.");
    expect(r.problems.some((p) => p.includes('공급가액'))).toBe(true);
    expect(r.fields.title).toBe('');
  });
  it('요청 변환은 정수 금액과 note를 그대로 전달한다', () => {
    const req = toExpenseRequest(expense);
    expect(req).toMatchObject({supply: 2100000, vat: 210000, total: 2310000, month: '2026-09'});
    expect(req.note).toBe(expense.note);
    expect(req.attachments).toEqual(expense.attachments);
  });
});
