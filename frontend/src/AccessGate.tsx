/**
 * [파일 역할] 프로그램 시작 비밀번호 화면.
 * 서버 인증 상태(/api/auth/status)를 확인해 잠금 해제된 경우에만 App을 띄운다.
 * 비밀번호를 연속으로 틀려 서버가 잠그면(HTTP 429) 서버 안내 문구("…초 후 다시 시도해 주세요.")를 그대로 표시한다.
 * 잠금 해제 뒤 어느 API가 401을 받으면(api()가 'saebom:unauthorized' 이벤트 발송) 비밀번호 화면으로 되돌아간다.
 */
import {useEffect, useRef, useState, type FormEvent} from 'react';
import {LoaderCircle, Leaf, ShieldCheck} from 'lucide-react';
import {api} from './api';
import {App} from './App';
import {errorMessage} from './utils/error';

/**
 * [기능명세] AccessGate
 * 목적: 프로그램 시작 비밀번호 화면
 * 입력: 컴포넌트 인자 없음
 * 출력: 준비 화면·로그인 폼 또는 App JSX
 * 처리/실패: auth/status 조회 후 서버 확인 성공에만 App 마운트. 조회 실패는 폼 아래 오류로 표시
 * 부수효과: 비밀번호 입력·인증 상태와 요청 관리. 입력값은 영속 저장하지 않음
 */
export function AccessGate() {
  const [checking, setChecking] = useState(true);
  const [unlocked, setUnlocked] = useState(false);
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  /**
   * [효과 명세] 최초 인증 조회
   * 처리: 마운트 때 auth/status를 읽어 authenticated로 화면을 나눈다. 실패하면 오류를 표시한다.
   * 부수효과: checking 종료·unlocked·error 변경. 실패 시 App을 열지 않음
   */
  useEffect(() => {
    api<{authenticated: boolean}>('auth/status')
      .then(r => setUnlocked(r.authenticated))
      .catch((e: unknown) => setError(errorMessage(e)))
      .finally(() => setChecking(false));
  }, []);

  /**
   * [효과 명세] 인증 만료 처리
   * 처리: api()가 보내는 'saebom:unauthorized' 이벤트(401)를 받으면 잠금 해제를 풀어 비밀번호 화면을 다시 보이고 안내 문구를 둔다.
   * 부수효과: unlocked=false·error 변경, App 언마운트(진행 중 폴링 중단). 리스너는 언마운트 때 해제
   */
  useEffect(() => {
    const onUnauthorized = () => {
      setUnlocked(false);
      setError('로그인이 만료되었습니다. 비밀번호를 다시 입력해 주세요.');
    };
    window.addEventListener('saebom:unauthorized', onUnauthorized);
    return () => window.removeEventListener('saebom:unauthorized', onUnauthorized);
  }, []);

  /**
   * [기능명세] login
   * 목적: 비밀번호 폼 제출
   * 입력: FormEvent
   * 출력: Promise<void>
   * 처리/실패: 기본 제출 방지 → 중복/빈 값 검사 → auth/login → 성공 시 잠금 해제.
   *   실패(틀린 비밀번호, 5회 연속 실패 잠금 429 등)면 서버 detail을 오류로 표시하고 입력을 비운 뒤 포커스
   * 부수효과: 입력값 비우기·로그인 상태/요청 상태 변경. 쿠키 발급과 실패 횟수 관리는 서버 담당
   */
  const login = async (e: FormEvent) => {
    e.preventDefault();
    if (submitting || !password) return;
    setSubmitting(true);
    setError('');
    try {
      await api('auth/login', {password});
      setPassword('');
      setUnlocked(true);
    } catch (err) {
      setError(errorMessage(err));
      setPassword('');
      input.current?.focus();
    } finally {
      setSubmitting(false);
    }
  };

  if (checking) {
    return (
      <div className="access-screen">
        <LoaderCircle className="spin" size={28}/>
        <p>프로그램을 준비하고 있습니다.</p>
      </div>
    );
  }
  if (unlocked) return <App/>;
  return (
    <div className="access-screen">
      <section className="access-card">
        <div className="access-logo"><Leaf size={30}/></div>
        <h1>새봄 문서비교</h1>
        <p>프로그램을 시작하려면 비밀번호를 입력해 주세요.</p>
        <form onSubmit={e => void login(e)}>
          <label htmlFor="app-password">비밀번호</label>
          <input
            ref={input}
            id="app-password"
            type="password"
            inputMode="numeric"
            autoComplete="current-password"
            autoFocus
            maxLength={128}
            value={password}
            disabled={submitting}
            onChange={e => setPassword(e.target.value)}
            aria-describedby={error ? 'login-error' : undefined}
          />
          {error && <p id="login-error" role="alert">{error}</p>}
          <button className="primary" type="submit" disabled={!password || submitting}>
            {submitting ? <LoaderCircle className="spin" size={16}/> : <ShieldCheck size={16}/>}시작하기
          </button>
        </form>
        <small>저장된 문서와 비교 이력은 잠금 해제 후 확인할 수 있습니다.</small>
      </section>
    </div>
  );
}
