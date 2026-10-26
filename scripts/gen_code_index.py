# [파일 기능명세]
# 개발문서/15_코드_색인.md를 소스에서 생성하는 도구. 파일별 역할(머리 주석 첫 문장), 줄 수, 주요 심볼을 표로 만든다.
# 사람이 쓴 설명이 아니라 소스의 한글 주석과 AST·정규식에서 뽑으므로, 소스가 바뀌면 이 스크립트를 다시 실행해 갱신한다.
# 사용: .venv/Scripts/python -X utf8 scripts/gen_code_index.py          (문서 파일을 새로 쓴다)
#       .venv/Scripts/python -X utf8 scripts/gen_code_index.py --check  (파일을 쓰지 않고 최신인지 확인, 다르면 종료코드 1)
# 제외: node_modules, dist, tmp, .venv, __pycache__, 자동 생성 파일, 빌드 산출물.
import argparse
import ast
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / '개발문서' / '15_코드_색인.md'
SKIP_PARTS = {'node_modules', 'dist', 'tmp', '.venv', '__pycache__', 'build'}
# (제목, 디렉터리, 글롭) 순서가 문서의 절 순서가 된다.
GROUPS = [
    ('진입점', '.', '*.py'),
    ('서버 — saebom/', 'saebom', '*.py'),
    ('서버 — saebom/routes/ (HTTP 라우트 등록)', 'saebom/routes', '*.py'),
    ('서버 — saebom/services/ (Service 믹스인)', 'saebom/services', '*.py'),
    ('화면 — frontend/src/ 최상위', 'frontend/src', '*.ts*'),
    ('화면 — screens/', 'frontend/src/screens', '**/*.ts*'),
    ('화면 — components/', 'frontend/src/components', '*.ts*'),
    ('화면 — hooks/', 'frontend/src/hooks', '*.ts*'),
    ('화면 — utils/', 'frontend/src/utils', '*.ts*'),
    ('스크립트 — scripts/', 'scripts', '*.py'),
    ('테스트 — tests/', 'tests', '*.py'),
]


# [기능명세] first_sentence
# 목적: 주석 덩어리에서 파일 역할 한 문장을 뽑는다. 입력은 주석 본문 문자열, 출력은 100자 이내의 한 줄.
# 처리: '[파일 기능명세]'·'[파일 역할]' 표지를 지우고 공백을 합친 뒤 첫 마침표 또는 100자에서 자른다. 부수효과 없음.
def first_sentence(text):
    text = re.sub(r'\[파일\s*(기능명세|역할)\]', '', text)
    text = re.sub(r'\s+', ' ', text).strip(' *#/')
    cut = re.search(r'(?<=[다요음임함됨])\.\s|\.$', text)
    sentence = text[:cut.end()].strip() if cut else text
    return (sentence[:100] + '…') if len(sentence) > 100 else sentence


# [기능명세] header_comment
# 목적: 파일 맨 위 주석을 읽는다. 입력은 파일 경로, 출력은 주석 본문(없으면 빈 문자열).
# 처리: .py는 연속된 '#' 줄, .ts/.tsx는 첫 '/** ... */' 블록, 그 외는 빈 문자열. 읽기만 한다.
def header_comment(path):
    lines = path.read_text(encoding='utf-8-sig').splitlines()
    if path.suffix == '.py':
        body = []
        for line in lines:
            if line.startswith('#'):
                body.append(line.lstrip('# '))
            elif body:
                break
            elif line.strip() and not line.startswith('#!'):
                break
        return ' '.join(body)
    text = '\n'.join(lines[:40])
    block = re.search(r'/\*\*(.*?)\*/', text, re.S)
    return block.group(1) if block else ''


# [기능명세] symbols
# 목적: 파일의 최상위 주요 심볼 이름을 모은다. 입력은 파일 경로, 출력은 최대 8개의 이름 목록.
# 처리: .py는 AST의 최상위 클래스·함수(밑줄로 시작하는 비공개 제외), .ts/.tsx는 export 선언 이름. 구문 오류는 빈 목록으로 대체한다.
def symbols(path):
    source = path.read_text(encoding='utf-8')
    names = []
    if path.suffix == '.py':
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith('_'):
                names.append(node.name)
    else:
        names = re.findall(r'^export\s+(?:default\s+)?(?:async\s+)?(?:function|const|class|type|interface)\s+([A-Za-z0-9_]+)', source, re.M)
    return names[:8]


# [기능명세] collect
# 목적: 한 그룹의 대상 파일을 이름순으로 모은다. 입력은 디렉터리·글롭, 출력은 제외 규칙을 통과한 파일 경로 목록.
# 처리: SKIP_PARTS가 경로에 포함되면 제외하고 '.'(루트) 그룹은 하위 폴더를 보지 않는다. 읽기만 한다.
def collect(directory, pattern):
    base = ROOT / directory
    found = base.glob(pattern) if directory != '.' else base.glob(pattern)
    return sorted(p for p in found if p.is_file() and not (SKIP_PARTS & set(p.relative_to(ROOT).parts)))


# [기능명세] render
# 목적: 색인 문서 전체 Markdown을 만든다. 입력 없음, 출력은 문서 문자열.
# 처리: 그룹별 표(파일, 줄 수, 역할, 주요 심볼)를 만든다. 역할 주석이 없는 파일은 '(머리 주석 없음)'으로 표시한다.
# 날짜는 넣지 않아 소스가 같으면 결과도 같다(--check 비교용).
def render():
    out = ['# 15. 코드 색인', '',
           '- 이 문서는 `scripts/gen_code_index.py`가 소스의 머리 주석에서 생성한다. 직접 고치지 않고 소스 주석을 고친 뒤 스크립트를 다시 실행한다.',
           '- 역할은 각 파일 머리 주석의 첫 문장, 심볼은 최상위 공개 클래스·함수·export 이름(최대 8개)이다.',
           '- 줄 단위 참조(`파일:줄`)는 각 설계 문서에 있으며 `scripts/verify_docs.py`가 존재를 검사한다. 자동 생성 파일·외부 라이브러리·빌드 산출물은 제외했다.', '']
    for title, directory, pattern in GROUPS:
        files = collect(directory, pattern)
        if not files:
            continue
        out += [f'## {title}', '', '| 파일 | 줄 | 역할 | 주요 심볼 |', '|---|---:|---|---|']
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            role = first_sentence(header_comment(path)) or '(머리 주석 없음)'
            role = role.replace('|', '\\|')
            names = ', '.join(f'`{n}`' for n in symbols(path)) or '-'
            lines = len(path.read_text(encoding='utf-8').splitlines())
            out.append(f'| `{rel}` | {lines} | {role} | {names} |')
        out.append('')
    return '\n'.join(out).rstrip() + '\n'


# [기능명세] main
# 목적: 색인 문서를 쓰거나(기본) 최신 여부를 확인한다(--check).
# 입력: 명령행 --check. 출력: 표준 출력 요약. 실패: --check에서 내용이 다르면 종료코드 1.
# 부수효과: 기본 모드는 개발문서/15_코드_색인.md를 새로 쓴다(UTF-8, LF).
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    text = render()
    if args.check:
        current = OUTPUT.read_text(encoding='utf-8') if OUTPUT.is_file() else ''
        if current != text:
            print('15_코드_색인.md가 최신이 아닙니다. gen_code_index.py를 다시 실행하세요.')
            return 1
        print('15_코드_색인.md 최신')
        return 0
    OUTPUT.write_text(text, encoding='utf-8', newline='\n')
    print(f'{OUTPUT.relative_to(ROOT)} 생성: {text.count(chr(10))}줄')
    return 0


if __name__ == '__main__':
    sys.exit(main())
