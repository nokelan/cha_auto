/**
 * [파일 역할] 마크다운 원문에서 목차(# ~ ### 제목)를 뽑는 순수 함수 모듈(React·DOM 비의존).
 * 처리 흐름: 줄 단위 순회 → 코드 펜스(``` / ~~~) 안과 4칸 이상 들여쓴 코드 줄 건너뛰기 → 제목 줄만 골라
 *   끝 `#` 장식과 인라인 기호를 정리 → {level, text, index, line} 목록으로 돌려준다.
 * 좌 편집기는 line(0부터 시작하는 줄 번호), 중 편집기는 index(제목들 중 n번째)로 해당 위치를 찾는다.
 */

/** [타입 명세] TocItem — level: 제목 단계(1~3), text: 정리된 제목 글자, index: #~### 제목 중 n번째(0부터), line: 마크다운의 0부터 시작하는 줄 번호. */
export type TocItem = {level: 1 | 2 | 3; text: string; index: number; line: number};

/** [상수 명세] HEADING — 제목 줄(0~3칸 들여쓰기 + `#` 1~3개 + 공백 + 내용). `####` 이상은 4번째 `#` 뒤에 공백이 없어 걸러진다. */
const HEADING = /^ {0,3}(#{1,3})[ \t]+(\S.*)$/;
/** [상수 명세] FENCE_OPEN — 코드 펜스 시작/끝 줄(0~3칸 들여쓰기 + 백틱 또는 물결표 3개 이상). */
const FENCE = /^ {0,3}(`{3,}|~{3,})/;

/**
 * [기능명세] cleanHeadingText
 * 목적: 제목 줄의 내용에서 장식을 걷어 목차에 보여 줄 글자를 만든다.
 * 입력: raw(`#` 기호 뒤의 원문). 출력: 정리된 글자(공백 정리됨, 비어 있을 수 있음).
 * 처리 규칙: 끝의 닫는 `#` 장식(앞에 공백이 있는 경우) 제거, 링크 `[글](주소)`는 글만, 이미지 `![대체](주소)`는 대체 글,
 *   `**` `__` `~~` `` ` `` `*` 기호 제거, 역슬래시 이스케이프 해제. 예외 없음. 부수효과 없음.
 */
function cleanHeadingText(raw: string): string {
  let t = raw.trim();
  t = t.replace(/(^|[ \t]+)#+[ \t]*$/, '').trim();
  t = t.replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1');
  t = t.replace(/(\*\*|__|~~|`|\*)/g, '');
  t = t.replace(/\\([\\`*_{}[\]()#+\-.!|~>])/g, '$1');
  return t.replace(/\s+/g, ' ').trim();
}

/**
 * [기능명세] extractToc
 * 목적: 마크다운에서 #, ##, ### 제목만 순서대로 추출한다.
 * 입력: md(마크다운 원문, 줄바꿈 \n 또는 \r\n).
 * 출력: TocItem[] (제목이 없거나 빈 문서면 빈 배열).
 * 처리 규칙: 코드 펜스 안(같은 문자로 같거나 더 긴 펜스로 닫힘, 닫히지 않으면 끝까지)과 4칸 이상·탭 들여쓴 줄은 제외.
 *   표·목록·인용 줄(`|`, `-`, `>` 시작)은 제목 정규식에 걸리지 않아 무시된다. index는 걸러진 뒤 센 순번이다.
 * 예외: 없음. 부수효과: 없음.
 */
export function extractToc(md: string): TocItem[] {
  const items: TocItem[] = [];
  let fence: string | null = null;
  md.split(/\r?\n/).forEach((line, lineNo) => {
    const f = FENCE.exec(line);
    if (fence) {
      if (f && f[1][0] === fence[0] && f[1].length >= fence.length && line.trim() === f[1]) fence = null;
      return;
    }
    if (f) { fence = f[1]; return; }
    if (/^(\t| {4})/.test(line)) return;
    const m = HEADING.exec(line);
    if (!m) return;
    items.push({level: m[1].length as 1 | 2 | 3, text: cleanHeadingText(m[2]), index: items.length, line: lineNo});
  });
  return items;
}
