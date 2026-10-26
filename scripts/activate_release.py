# [파일 기능명세] 검증한 배포 EXE를 기존 사용자 데이터로 실행하고 적용 상태를 읽어 확인한다.
# 시작 전 SQLite backup을 만들고, 실행 후 기존 업무 행·설정의 내용이 유지되는지 비교한다.
# 비밀번호·실행 토큰은 출력/보고하지 않는다. 사이트 작업·비교·상신은 실행하지 않는다.
import argparse
from http.cookiejar import CookieJar
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


# [기능명세] fingerprint
# 목적: 업무 테이블의 행과 설정을 내용 노출 없이 SHA256으로 요약한다.
# 입력: SQLite 경로. 출력: 테이블별 count/hash. 읽기 전용 연결만 사용한다.
# results.summary는 승인된 마이그레이션 대상이므로 기존 값 보존 비교에서 제외한다.
def fingerprint(path):
    result = {}
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        for name in ['items','documents','results','meta','contract_imports','contract_status']:
            columns = [r[1] for r in db.execute(f'PRAGMA table_info({name})') if r[1] != 'summary']
            rows = db.execute(f'SELECT {",".join(columns)} FROM {name} ORDER BY rowid').fetchall()
            payload = json.dumps(rows,ensure_ascii=False,sort_keys=True).encode('utf-8')
            result[name] = {'count':len(rows),'sha256':hashlib.sha256(payload).hexdigest()}
    return result


# [기능명세] main
# 목적: 운영 DB 백업→배포 앱 일반 실행→인증된 읽기 API·원본 데이터 보존 확인.
# 입력: --out 출력폴더. 출력: activation.json, 백업DB, 실행로그. 정상 앱은 종료하지 않는다.
# 실패: 기존 인스턴스 정보가 남거나 실행 준비/데이터 보존 검사 실패 시 예외.
# 부수효과: 정상 앱 실행 및 승인된 DB 마이그레이션·프로필 갱신. 업무 데이터 쓰기 API는 호출하지 않는다.
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out',required=True,type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    data = Path(os.environ.get('SAEBOM_DATA_DIR') or Path(os.environ['LOCALAPPDATA'])/'SaebomCompare').resolve()
    instance = data/'instance.json'
    assert not instance.exists(), '기존 실행 정보가 있습니다. 실행 중 앱 상태를 먼저 확인하세요.'
    source = data/'saebom.sqlite3'
    before = fingerprint(source)
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as db, sqlite3.connect(out/'user-db-before.sqlite3') as backup:
        db.backup(backup)
    env = dict(os.environ)
    env.pop('SAEBOM_NO_OPEN',None)
    env.pop('SAEBOM_VERIFY_EXE',None)
    exe = ROOT/'dist/SaebomCompare/SaebomCompare.exe'
    log = (out/'live-launch.log').open('w',encoding='utf-8')
    app = subprocess.Popen([str(exe)],cwd=ROOT,env=env,stdout=log,stderr=log)
    try:
        for _ in range(200):
            try:
                info = json.loads(instance.read_text(encoding='utf-8'))
                base = f'http://127.0.0.1:{info["port"]}'
                with urllib.request.urlopen(base+'/health',timeout=1) as r:
                    assert r.status == 200
                break
            except Exception:
                if app.poll() is not None:
                    raise RuntimeError('배포 앱이 시작 중 종료되었습니다.')
                time.sleep(.1)
        else:
            raise RuntimeError('앱 시작 대기 시간 초과')
        client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        client.open(base+'/?token='+info['token'],timeout=5).close()
        body = json.dumps({'password':os.environ.get('SAEBOM_PASSWORD') or '0000'}).encode('utf-8')
        client.open(urllib.request.Request(base+'/api/auth/login',data=body,headers={'Content-Type':'application/json'}),timeout=5).close()
        state = json.load(client.open(base+'/api/state',timeout=10))
        results = json.load(client.open(base+'/api/results',timeout=10))
        after = fingerprint(source)
        assert before == after, '기존 업무 행 또는 설정이 변경되었습니다.'
        report = {'exe':str(exe),'pid':app.pid,'health':200,'state_access':200,'results_access':200,
                  'data_preserved':True,'tables':after,'mails':len(state['mails']),'contracts':len(state['contracts']),
                  'results':len(results),'backup':str(out/'user-db-before.sqlite3'),'app_left_running':True}
        (out/'activation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k not in {'tables','backup'}},ensure_ascii=False,indent=2))
    finally:
        log.close()


if __name__ == '__main__':
    main()
