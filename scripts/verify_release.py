# [파일 기능명세] 실제 Windows 배포 EXE의 오프라인 회귀·번들·ZIP 검사.
# 사용자 원본은 verify_ui에서 읽기 전용 사본으로 사용하며 상신·실사이트 접속은 하지 않는다.
# 입력은 배포 EXE 경로와 출력 폴더. 출력은 검사 로그·JSON이며 EXE를 다시 만들지는 않는다.
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


# [기능명세] digest
# 목적: 파일 SHA256을 계산한다. 입력 Path, 출력 hex 문자열. 파일 읽기만 수행한다.
def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


# [기능명세] main
# 목적: 실제 배포 실행 파일로 다섯 화면 검증을 순차 실행하고 번들·ZIP 일치를 확인한다.
# 입력: --exe, --out. 출력: report.json·단계별 로그, 성공0/실패1.
# 처리: 정적파일 해시·필수 템플릿·Chromium·ZIP CRC 및 파일 크기 비교→실제EXE 격리 회귀.
# 예외/실패: 파일·검사 실패는 예외 또는 종료1. 부수효과: 출력폴더와 각 verify의 격리 데이터 생성.
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, default=ROOT/'dist/SaebomCompare/SaebomCompare.exe')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    exe, out = args.exe.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    bundle = exe.parent
    archive = ROOT/'dist/SaebomCompare-Windows.zip'
    assert exe.is_file(), exe
    static = bundle/'_internal/frontend/dist'
    assets = list((ROOT/'frontend/dist').rglob('*'))
    matched = []
    for source in assets:
        if source.is_file():
            dest = static/source.relative_to(ROOT/'frontend/dist')
            assert dest.is_file() and digest(source) == digest(dest), f'정적 자산 불일치: {source.name}'
            matched.append(source.relative_to(ROOT/'frontend/dist').as_posix())
    assert matched, '정적 자산이 없습니다.'
    template = bundle/'_internal/saebom/assets/거래명세서_템플릿.xlsx'
    assert template.is_file() and digest(template) == digest(ROOT/'saebom/assets/거래명세서_템플릿.xlsx')
    assert list((bundle/'_internal/browser').rglob('chrome.exe')), '번들 Chromium 없음'
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None, 'ZIP CRC 오류'
        zipped = {i.filename: i.file_size for i in z.infolist() if not i.is_dir()}
        files = {p.relative_to(bundle.parent).as_posix(): p.stat().st_size for p in bundle.rglob('*') if p.is_file()}
        assert zipped == files, '배포 폴더·ZIP 목록 또는 크기 불일치'
    report = {'exe':str(exe),'exe_sha256':digest(exe),'zip':str(archive),'zip_sha256':digest(archive),
              'static_assets':len(matched),'bundle_files':len(files),'template_equal':True,'zip_valid':True,'steps':[]}
    env = dict(os.environ, SAEBOM_VERIFY_EXE=str(exe))
    env.pop('SAEBOM_PASSWORD', None)
    for name in ['verify_ui','verify_statement','verify_raw_amounts','verify_auth_recovery','verify_workspace_layout']:
        with (out/f'{name}.log').open('w', encoding='utf-8') as log:
            result = subprocess.run([sys.executable,'-X','utf8',f'scripts/{name}.py'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        report['steps'].append({'name':name,'exit_code':result.returncode})
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'{name}: {result.returncode}',flush=True)
        if result.returncode:
            print((out/f'{name}.log').read_text(encoding='utf-8')[-3000:])
            return 1
    print(json.dumps({k:v for k,v in report.items() if k not in {'exe','zip'}},ensure_ascii=False,indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
