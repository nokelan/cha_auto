# [파일 기능명세]
# 개발문서 00~15의 파일·상대 링크·코드 줄 참조·29개 API·실제 SQLite 스키마와
# 모든 Mermaid 블록을 검사한다. 사용자 DB나 사이트에 접속하지 않는다.
# Mermaid는 tmp/document-tools/node_modules에 설치한 로컬 패키지를 Chromium으로 읽는다.
import ast
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import random
import re
import sys
import tempfile
import threading
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from saebom.store import Store


# [기능명세] QuietHandler.log_message
# 목적: 정적 서버의 요청 로그를 생략한다. 입력은 HTTP 로그 인자, 출력·부수효과 없음.
class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


# [기능명세] source_routes
# 목적: Python AST에서 /api 데코레이터를 추출한다.
# 입력 없음, 출력은 (HTTP 메서드, 경로, 파일, 줄) 목록. 파일 읽기만 하며 구문 오류는 전파한다.
def source_routes():
    routes = []
    for p in [ROOT / 'saebom/api.py', *sorted((ROOT / 'saebom/routes').glob('*.py'))]:
        for node in ast.walk(ast.parse(p.read_text(encoding='utf-8'))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for d in node.decorator_list:
                    if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in {'get', 'post', 'put', 'delete'} and d.args and isinstance(d.args[0], ast.Constant):
                        route = d.args[0].value
                        if isinstance(route, str) and route.startswith('/api/'):
                            routes.append((d.func.attr.upper(), route, p.relative_to(ROOT).as_posix(), d.lineno))
    return sorted(routes)


# [기능명세] main
# 목적: 문서 검증 전체 실행. 입력 없음, 출력은 report.json·Mermaid SVG/PNG와 요약.
# 처리: 번호·링크·줄 참조 검사→라우트·새 임시 DB 스키마 대조→Mermaid parse 및 render.
# 실패: 검사 실패는 보고서에 누적하고 종료코드 1. 패키지 미설치는 실패로 표시한다。
# 부수효과: tmp/docs-review에 검사 산출물·임시 SQLite 생성, 로컬 서버·Chromium 실행 후 정리.
def main():
    docs = sorted((ROOT / '개발문서').glob('[0-9][0-9]_*.md'))
    out = ROOT / 'tmp/docs-review'
    out.mkdir(parents=True, exist_ok=True)
    errors, links, refs, diagrams = [], [], [], []
    if [p.name[:2] for p in docs] != [f'{i:02}' for i in range(16)]:
        errors.append('문서 00~15 누락 또는 번호 중복')
    for doc in docs:
        content = doc.read_text(encoding='utf-8')
        for i, block in enumerate(re.findall(r'```json\s*\n(.*?)```', content, re.S)):
            try:
                json.loads(block)
            except ValueError as e:
                errors.append(f'{doc.name}: JSON 예제 #{i} 오류 {e}')
        for code in re.findall(r'```mermaid\s*\n(.*?)```', content, re.S):
            diagrams.append({'file': doc.name, 'code': code.strip()})
        for path, line in re.findall(r'(?<![\w/])((?:saebom|frontend/src|scripts|tests)/[\w./가-힣-]+\.(?:py|tsx?|css)):(\d+)', content):
            p = ROOT / path
            lines = p.read_text(encoding='utf-8').splitlines() if p.is_file() else []
            valid = 1 <= int(line) <= len(lines)
            refs.append({'document': doc.name, 'ref': f'{path}:{line}', 'valid': valid,
                         'source': lines[int(line)-1] if valid else None})
            if not valid:
                errors.append(f'{doc.name}: 잘못된 코드 참조 {path}:{line}')
        # 외부 URL과 앵커를 제외하고 로컬 Markdown 링크를 검사한다.
        for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', content):
            target = unquote(target.strip('<>').split('#')[0])
            if not target or re.match(r'^[a-zA-Z]+://', target):
                continue
            valid = (doc.parent / target).exists()
            links.append({'document': doc.name, 'target': target, 'valid': valid})
            if not valid:
                errors.append(f'{doc.name}: 없는 링크 {target}')
    routes = source_routes()
    api_text = next((p.read_text(encoding='utf-8') for p in docs if p.name.startswith('04_')), '')
    for method, route, path, line in routes:
        # ID 변수 이름이 다른 경우에도 경로 구조로 비교한다.
        normalized = re.sub(r'\{[^}]+\}', '{id}', route)
        normalized_text = re.sub(r'\{[^}\n]+\}', '{id}', api_text)
        if normalized not in normalized_text:
            errors.append(f'API 문서 누락 {method} {route}')
    if len(routes) != 29:
        errors.append(f'라우트 수 {len(routes)} != 29')
    with tempfile.TemporaryDirectory(dir=out) as folder:
        store = Store(Path(folder))
        tables = {name: [dict(zip(['cid','name','type','notnull','default','pk'], row)) for row in store.db.execute(f'PRAGMA table_info({name})')] for name, in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        store.close()
    db_text = next((p.read_text(encoding='utf-8') for p in docs if p.name.startswith('03_')), '')
    for table, columns in tables.items():
        if table not in db_text:
            errors.append(f'DB 문서 테이블 누락 {table}')
        for c in columns:
            if not re.search(r'\b'+re.escape(c['name'])+r'\b', db_text):
                errors.append(f'DB 문서 열 누락 {table}.{c["name"]}')
    mermaid = ROOT / 'tmp/document-tools/node_modules/mermaid/dist/mermaid.esm.min.mjs'
    if not mermaid.is_file():
        errors.append('Mermaid 로컬 패키지 없음: npm.cmd install --prefix tmp/document-tools --no-save mermaid@11.12.0')
    else:
        from playwright.sync_api import sync_playwright
        handler = partial(QuietHandler, directory=str(mermaid.parent))
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    page = browser.new_page(viewport={'width': 1600, 'height': 1000})
                    page.goto(f'http://127.0.0.1:{server.server_port}/')
                    page.evaluate("async()=>{window.mm=(await import('./mermaid.esm.min.mjs')).default;mm.initialize({startOnLoad:false,securityLevel:'strict',theme:'default'});document.body.innerHTML='<main id=diagram></main>'}")
                    for i, diagram in enumerate(diagrams):
                        try:
                            rendered = page.evaluate("async({code,id})=>{await mm.parse(code);const r=await mm.render(id,code);document.querySelector('#diagram').innerHTML=r.svg;return r.svg}", {'code': diagram['code'], 'id': f'd{i}'})
                            (out / f'diagram-{i:02}.svg').write_text(rendered, encoding='utf-8')
                            page.locator('#diagram').screenshot(path=str(out / f'diagram-{i:02}.png'))
                            diagram['ok'] = True
                        except Exception as e:
                            diagram['ok'] = False
                            errors.append(f'Mermaid {diagram["file"]} #{i}: {str(e)[:1000]}')
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
    unique_refs = list({r['ref']: r for r in refs}.values())
    sampled = random.Random(26).sample(unique_refs, min(30, len(unique_refs)))
    if len(sampled) < 30:
        errors.append('コード参照の標本が30件未満')
    report = {'documents': len(docs), 'routes': routes, 'tables': tables, 'links': links,
              'references': len(refs), 'sampled_references': sampled, 'diagrams': diagrams, 'errors': errors}
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'documents': len(docs), 'routes': len(routes), 'tables': len(tables),
                      'columns': sum(map(len, tables.values())), 'references': len(refs),
                      'diagrams': len(diagrams), 'errors': errors}, ensure_ascii=False, indent=2))
    return bool(errors)


if __name__ == '__main__':
    sys.exit(main())
