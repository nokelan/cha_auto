# [파일 기능명세]
# 2026-10-26 리팩토링의 로컬 회귀 검사를 순서대로 재현한다.
# 사용자 DB는 verify_ui·css_shots가 읽기 전용 사본으로 사용하고 실사이트에는 접속하지 않는다.
# EXE 교체·상신·커밋은 수행하지 않는다. 로그와 결과는 tmp/refactor-review에 저장한다.
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


# [기능명세] main
# 목적: pytest→판정 스냅샷→빌드→4종 UI 회귀→2단 구성 검사→72장 캡처를 순차 수행한다.
# 입력 없음, 출력은 report.json·단계별 로그. 실패 시 즉시 종료코드 1을 반환한다.
# 처리: 검증용 자식 프로세스에서는 비밀번호·EXE 경로 덮어쓰기를 제거하여 기본 테스트 조건을 사용한다.
# 승인된 2단 UI는 과거 화면과 달라야 하므로 픽셀 동일 검사는 --compare-legacy-css를 준 경우에만 합격 조건으로 쓴다.
# 부수효과: frontend/dist 갱신·격리 서버/브라우저 실행·tmp 산출물 생성. 사용자 원본은 변경하지 않는다.
def main():
    out = ROOT / 'tmp/refactor-review'
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.pop('SAEBOM_PASSWORD', None)
    env.pop('SAEBOM_VERIFY_EXE', None)
    npm = shutil.which('npm.cmd') or shutil.which('npm')
    if not npm:
        raise RuntimeError('npm을 찾을 수 없습니다.')
    py = sys.executable
    steps = [
        ('pytest', [py, '-X', 'utf8', '-m', 'pytest', '-q'], ROOT),
        ('snapshot', [py, '-X', 'utf8', 'tmp/refactor-tools/judgement_snapshot.py', str(out/'snapshot.json')], ROOT),
        ('build', [npm, 'run', 'build'], ROOT/'frontend'),
        ('pdf_assets', [py, '-X', 'utf8', 'scripts/copy_pdf_assets.py'], ROOT),
        *[(name, [py, '-X', 'utf8', f'scripts/{name}.py'], ROOT) for name in ['verify_ui', 'verify_statement', 'verify_raw_amounts', 'verify_auth_recovery']],
        ('verify_workspace_layout', [py, '-X', 'utf8', 'scripts/verify_workspace_layout.py'], ROOT),
        ('css_shots', [py, '-X', 'utf8', 'tmp/refactor-tools/css_shots.py', str(out/'css-after')], ROOT),
    ]
    report = {'steps': [], 'snapshot_equal': False, 'css': {}}
    for name, cmd, cwd in steps:
        with (out/f'{name}.log').open('w', encoding='utf-8') as log:
            result = subprocess.run(cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
        report['steps'].append({'name': name, 'exit_code': result.returncode})
        print(f'{name}: {result.returncode}', flush=True)
        (out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        if result.returncode:
            print((out/f'{name}.log').read_text(encoding='utf-8')[-3500:])
            return 1
        if name == 'snapshot':
            report['snapshot_equal'] = (out/'snapshot.json').read_bytes() == (ROOT/'tmp/refactor-tools/snapshot-before.json').read_bytes()
            if not report['snapshot_equal']:
                print('판정 스냅샷 불일치')
                return 1
    from PIL import Image, ImageChops
    baseline = ROOT/'tmp/refactor-tools/css-before/shots'
    after = out/'css-after'
    same, changed, missing = [], [], []
    for before in sorted(baseline.glob('*.png')):
        current = after/before.name
        if not current.is_file():
            missing.append(before.name)
            continue
        with Image.open(before) as a, Image.open(current) as b:
            equal = a.size == b.size and ImageChops.difference(a.convert('RGB'), b.convert('RGB')).getbbox() is None
        (same if equal else changed).append(before.name)
    report['css'] = {'equal': same, 'changed': changed, 'missing': missing}
    metrics_equal = json.loads((baseline/'metrics.json').read_text(encoding='utf-8')) == json.loads((after/'metrics.json').read_text(encoding='utf-8'))
    report['css']['metrics_equal'] = metrics_equal
    report['css']['legacy_comparison_required'] = '--compare-legacy-css' in sys.argv
    report['css']['note'] = '사용자가 승인한 앱 전체 2단 UI 변경으로 과거 PNG·계산 스타일과 차이가 있는 것이 정상입니다.'
    (out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'snapshot_equal': report['snapshot_equal'], 'css_equal': len(same), 'css_changed': changed, 'css_missing': missing, 'metrics_equal': metrics_equal}, ensure_ascii=False, indent=2))
    if '--compare-legacy-css' in sys.argv:
        return bool(changed or missing or not same or not metrics_equal)
    return bool(missing or len(same)+len(changed) != 72)


if __name__ == '__main__':
    sys.exit(main())
