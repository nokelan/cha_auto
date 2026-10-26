/** [파일 역할] toc.ts 의 extractToc 단위시험(vitest): 레벨 필터, 코드 펜스, 줄·순번, 장식 정리, 빈 문서, 표·목록. */
import {describe, expect, it} from 'vitest';
import {extractToc} from './toc';

describe('extractToc', () => {
  it('#~### 만 뽑고 ####·#없는 줄은 제외한다', () => {
    const t = extractToc('# 가\n## 나\n### 다\n#### 라\n#마\n본문 # 바');
    expect(t.map(x => [x.level, x.text])).toEqual([[1, '가'], [2, '나'], [3, '다']]);
  });
  it('line 과 index 가 정확하다', () => {
    const t = extractToc('글\n\n# A\n내용\n## B\n\n### C');
    expect(t.map(x => [x.index, x.line])).toEqual([[0, 2], [1, 4], [2, 6]]);
  });
  it('코드 펜스 안의 제목은 제외하고 펜스 뒤는 다시 센다', () => {
    const t = extractToc('# A\n```\n# 코드\n```\n## B\n~~~md\n## 물결\n~~~\n### C');
    expect(t.map(x => [x.text, x.index, x.line])).toEqual([['A', 0, 0], ['B', 1, 4], ['C', 2, 8]]);
  });
  it('닫히지 않은 펜스는 끝까지 코드로 본다', () => {
    expect(extractToc('# A\n```\n## 안\n## 안2')).toHaveLength(1);
  });
  it('4칸 들여쓴 코드 줄은 제외한다', () => {
    expect(extractToc('    # 코드\n\t# 탭\n   # 세칸')).toHaveLength(1);
  });
  it('끝 # 장식과 인라인 기호를 정리한다', () => {
    const t = extractToc('# 제목 #\n## **굵게** `코드` ##\n### [링크](http://x) C#');
    expect(t.map(x => x.text)).toEqual(['제목', '굵게 코드', '링크 C#']);
  });
  it('빈 문서와 제목 없는 문서는 빈 배열', () => {
    expect(extractToc('')).toEqual([]);
    expect(extractToc('그냥 글\n- 목록')).toEqual([]);
  });
  it('표·목록 속 # 는 무시한다', () => {
    expect(extractToc('| # | 이름 |\n| --- | --- |\n| # 1 | a |\n- # 항목\n> # 인용')).toEqual([]);
  });
  it('CRLF 줄바꿈도 처리한다', () => {
    expect(extractToc('# A\r\n## B\r\n').map(x => x.line)).toEqual([0, 1]);
  });
});
