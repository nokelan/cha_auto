/**
 * [파일 역할] 개발문서 마크다운 → 안전한 DOM 변환 유틸(DocsScreen 전용, React 비의존).
 * 처리 흐름: marked(GFM) → DOMPurify.sanitize → 컨테이너 innerHTML → DOM 후처리
 *   (제목 id 부여·표 스크롤 래핑·링크 분류·이미지 대체·mermaid 코드블록을 자리표시 요소로 교체).
 * 원칙: eval·외부 요청 없음. 앱 CSP(script-src 'self')를 위반하지 않는다.
 */
import DOMPurify from 'dompurify';
import {marked} from 'marked';
import type {DocToc} from '../../types';

/** [타입 명세] MermaidJob — 렌더해야 할 mermaid 자리표시 요소와 원문 코드. */
export type MermaidJob = {el: HTMLElement; source: string};

/** [상수 명세] DOC_LINK — 앱 안 문서 전환 대상 링크 형식 `NN_이름.md` + 선택적 `#앵커`. */
const DOC_LINK = /^(\d{2}_[^/\\#?]*\.md)(#.*)?$/;

/**
 * [기능명세] slugify
 * 목적: 제목 글자를 앵커용 슬러그로 변환(GitHub 방식과 유사: 소문자, 한글·영숫자 유지, 공백은 하이픈).
 * 입력: text 제목 글자. 출력: 슬러그 문자열(빈 값 가능). 부수효과: 없음
 */
export function slugify(text: string): string {
  return text.trim().toLowerCase().replace(/[^\p{L}\p{N}\s_-]/gu, '').replace(/\s+/g, '-');
}

/**
 * [기능명세] decodeSafe
 * 목적: URI 구성요소를 예외 없이 디코딩. 입력: s. 출력: 디코딩 문자열(실패 시 원문). 부수효과: 없음
 */
export function decodeSafe(s: string): string {
  try { return decodeURIComponent(s); } catch { return s; }
}

/**
 * [기능명세] renderMarkdownInto
 * 목적: 마크다운 본문을 정화해 컨테이너에 삽입하고 후처리 결과(목차·mermaid 작업)를 돌려준다.
 * 입력: container(내용이 교체될 대상 요소), markdown(원문 문자열)
 * 출력: {toc: 목차 항목[], mermaid: 렌더 대기 작업[]}
 * 처리 규칙:
 *   - 제목(h1~h4)에 id `doc-<순번>-<슬러그>`와 data-slug(GitHub식 중복 번호 포함) 부여.
 *   - `#앵커` 링크는 data-anchor, `NN_*.md[#앵커]` 링크는 data-doc/data-anchor를 달고 href="#"로 바꿔 앱 안 이동 대상으로 표시.
 *   - http(s) 링크는 새 탭·noopener. 그 외(`../`·절대경로·기타 상대·mailto 등)는 span.docs-link-off(title=원래 경로).
 *   - 상대 경로 이미지는 대체 글자 span으로 바꾸고 data: 이미지만 유지. 표는 div.docs-scroll로 감싼다.
 *   - ```mermaid 블록은 div.docs-mermaid로 교체하고 작업 목록에 넣는다.
 * 예외: marked/DOMPurify 예외는 호출자(DocsScreen)가 잡는다.
 * 부수효과: container.innerHTML 교체·DOM 조작(스크롤 위치는 건드리지 않음)
 */
export function renderMarkdownInto(container: HTMLElement, markdown: string): {toc: DocToc[]; mermaid: MermaidJob[]} {
  const html = marked.parse(markdown, {gfm: true, async: false}) as string;
  container.innerHTML = DOMPurify.sanitize(html);

  const toc: DocToc[] = [];
  const seen = new Map<string, number>();
  container.querySelectorAll<HTMLElement>('h1,h2,h3,h4').forEach((h, i) => {
    const text = (h.textContent ?? '').trim();
    const slug = slugify(text);
    const n = seen.get(slug) ?? 0;
    seen.set(slug, n + 1);
    h.dataset.slug = n ? slug + '-' + n : slug;
    h.id = `doc-${i + 1}-${slug || 'section'}`;
    toc.push({id: h.id, level: Number(h.tagName[1]), text});
  });

  container.querySelectorAll<HTMLAnchorElement>('a').forEach(a => {
    const href = a.getAttribute('href') ?? '';
    const m = DOC_LINK.exec(decodeSafe(href));
    if (/^https?:\/\//i.test(href)) {
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
    } else if (href.startsWith('#')) {
      a.dataset.anchor = decodeSafe(href.slice(1));
      a.setAttribute('href', '#');
    } else if (m) {
      a.dataset.doc = m[1];
      if (m[2]) a.dataset.anchor = m[2].slice(1);
      a.setAttribute('href', '#');
    } else {
      const off = document.createElement('span');
      off.className = 'docs-link-off';
      off.title = href;
      off.append(...Array.from(a.childNodes));
      a.replaceWith(off);
    }
  });

  container.querySelectorAll<HTMLImageElement>('img').forEach(img => {
    if (/^data:image\//i.test(img.getAttribute('src') ?? '')) return;
    const off = document.createElement('span');
    off.className = 'docs-link-off';
    off.title = img.getAttribute('src') ?? '';
    off.textContent = `[이미지: ${img.alt || '표시 불가'}]`;
    img.replaceWith(off);
  });

  container.querySelectorAll('table').forEach(t => {
    const wrap = document.createElement('div');
    wrap.className = 'docs-scroll';
    t.replaceWith(wrap);
    wrap.append(t);
  });

  const mermaid: MermaidJob[] = [];
  container.querySelectorAll<HTMLElement>('pre > code.language-mermaid').forEach(code => {
    const el = document.createElement('div');
    el.className = 'docs-mermaid';
    el.textContent = '도형을 그리는 중입니다…';
    code.parentElement!.replaceWith(el);
    mermaid.push({el, source: code.textContent ?? ''});
  });
  return {toc, mermaid};
}

/** [상태 명세] mermaidReady — mermaid 동적 import·initialize를 한 번만 하기 위한 Promise 캐시. */
let mermaidReady: Promise<typeof import('mermaid').default> | null = null;
let mermaidSeq = 0;

/**
 * [기능명세] renderMermaidJobs
 * 목적: 자리표시 요소마다 mermaid SVG를 그린다. mermaid는 첫 호출 때만 동적 import(별도 청크).
 * 입력: jobs(renderMarkdownInto 결과), cancelled(문서 전환 시 중단 여부를 알려 주는 함수)
 * 출력: Promise<void>
 * 처리 규칙: initialize({startOnLoad:false, securityLevel:'strict'}) 후 render. 도형 하나가 실패해도 나머지는 계속 그린다.
 *   실패하면 한글 오류 문구와 원문 코드를 표시한다. cancelled()가 true면 DOM을 더 건드리지 않는다.
 * 부수효과: job.el 내용 교체, 같은 출처 정적 청크 동적 로딩. mermaid가 임시 요소를 body에 잠시 추가한다
 */
export async function renderMermaidJobs(jobs: MermaidJob[], cancelled: () => boolean): Promise<void> {
  if (!jobs.length) return;
  try {
    mermaidReady ??= import('mermaid').then(mod => {
      mod.default.initialize({startOnLoad: false, securityLevel: 'strict'});
      return mod.default;
    });
    const mermaid = await mermaidReady;
    for (const job of jobs) {
      if (cancelled()) return;
      try {
        const {svg} = await mermaid.render(`docs-mermaid-${++mermaidSeq}`, job.source);
        if (cancelled()) return;
        job.el.innerHTML = svg;
      } catch {
        if (!cancelled()) showMermaidError(job);
      }
    }
  } catch {
    mermaidReady = null;
    jobs.forEach(j => { if (!cancelled()) showMermaidError(j); });
  }
}

/**
 * [기능명세] showMermaidError
 * 목적: 렌더 실패 도형에 오류 문구와 원문 코드를 표시. 입력: job. 출력: 없음.
 * 부수효과: job.el 내용 교체(textContent 사용, HTML 삽입 없음)
 */
function showMermaidError(job: MermaidJob) {
  job.el.replaceChildren();
  const msg = document.createElement('div');
  msg.className = 'docs-mermaid-error';
  msg.textContent = '도형을 그리지 못했습니다. 아래 원문 코드를 확인해 주세요.';
  const pre = document.createElement('pre');
  const code = document.createElement('code');
  code.textContent = job.source;
  pre.append(code);
  job.el.append(msg, pre);
}
