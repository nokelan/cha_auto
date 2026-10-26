/**
 * [파일 역할] 서버 상태 조회 훅.
 * - 폴링: /api/state와 /api/results(결과 요약 목록)를 함께 읽는다. 작업 중 1초, 아니면 8초 간격.
 * - 결과 상세: 선택한 결과(resultId, 없거나 목록에 없으면 최신 요약)의 상세를 /api/results/{id}로
 *   대상 ID가 바뀔 때만 불러온다. 폴링마다 상세를 다시 받지 않되, 상세 조회가 실패했으면 다음 폴링 때 다시 시도한다.
 *   대상과 다른(이전) 상세는 화면에 넘기지 않아, 전환 중에 이전 결과로 보정·CSV를 실행하지 않게 한다.
 * - 새 완료 결과 감지: 앱을 연 뒤 끝난 작업이 result_id를 만들면 그 결과를 선택하고 호출자에게 알린다(useJobDone 사용).
 */
import {useEffect, useRef, useState} from 'react';
import {api, EMPTY_STATE} from '../api';
import type {Result, ResultSummary, State} from '../types';
import {errorMessage} from '../utils/error';
import {useJobDone} from './useJobDone';

/**
 * [기능명세] useAppState
 * 목적: 서버 상태·결과 요약·선택 결과 상세와 조회 오류를 한곳에서 관리
 * 입력: stopped: 프로그램 종료 후면 true(폴링 중단),
 *   onNewResult: 새로 완료된 작업의 결과 ID를 받는 콜백(행·포커스·화면 초기화는 호출자 담당)
 * 출력: {state, results(요약), resultId, setResultId, current(대상 결과의 상세 또는 null),
 *   detailPending(대상 결과가 있는데 상세가 아직 없음), loading, error, setError, reload, running(진행 중 작업 존재)}
 * 처리/실패: 상태·요약 조회 실패 메시지는 다음 성공 조회 때 비운다. 상세 조회 실패 메시지는 상세가
 *   성공하거나 사용자가 닫을 때까지 유지하며, 실패한 상세는 다음 폴링 때 다시 요청한다
 * 부수효과: 주기적 HTTP GET, 타이머 등록·해제
 */
export function useAppState(stopped: boolean, onNewResult: (id: string) => void) {
  const [state, setState] = useState<State>(EMPTY_STATE);
  const [results, setResults] = useState<ResultSummary[]>([]);
  const [resultId, setResultId] = useState('');
  const [detail, setDetail] = useState<Result | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  /** 상세 조회 오류 문구. 폴링 성공으로 지워지지 않도록 error와 따로 둔다. */
  const [detailError, setDetailError] = useState('');
  /** 증가할 때마다 상세 조회 효과를 다시 실행하게 하는 재시도 신호. */
  const [retryTick, setRetryTick] = useState(0);
  /** 마지막 상세 조회가 실패했는지(다음 폴링에서 재시도할지) 표시. */
  const detailFailed = useRef(false);
  /** 최신 onNewResult 콜백(효과 의존성에 넣지 않기 위해 ref로 보관, 렌더마다 갱신). */
  const onNewResultRef = useRef(onNewResult);
  onNewResultRef.current = onNewResult;

  const running = state.jobs.some(j => j.status === 'running');
  /** 상세를 불러올 결과 ID: resultId가 요약 목록에 있으면 그것, 아니면 최신 요약(없으면 ''). */
  const targetId = results.some(r => r.id === resultId) ? resultId : (results[0]?.id ?? '');
  /** 화면에 넘길 상세: 대상 결과와 ID가 같을 때만. 전환 중 이전 결과는 넘기지 않는다. */
  const current = detail && detail.id === targetId ? detail : null;
  const detailPending = !!targetId && !current;

  /**
   * [기능명세] setErrorAll
   * 목적: 화면의 오류 닫기·작업 요청 전 초기화에서 두 종류의 오류 문구를 함께 다룸
   * 입력: message: 표시할 문구('' 이면 모두 지움)
   * 출력: void
   * 처리/실패: 일반 오류를 바꾸고, 빈 문구면 상세 오류도 지운다(상세 재시도는 계속된다)
   * 부수효과: error·detailError 상태 변경
   */
  const setErrorAll = (message: string) => {
    setError(message);
    if (!message) setDetailError('');
  };

  /**
   * [기능명세] reload
   * 목적: 서버 상태와 결과 요약 동시 갱신
   * 입력: 인자 없음
   * 출력: Promise<State|null> — 성공 시 새 상태, 실패 시 null
   * 처리/실패: state·results 병렬 조회. 성공하면 오류 문구를 지우고, 실패하면 메시지를 표시한다.
   *   성공·실패와 관계없이 최초 로딩 표시를 해제한다
   * 부수효과: HTTP 읽기와 state/results/error/loading 변경
   */
  const reload = async (): Promise<State | null> => {
    try {
      const [s, r] = await Promise.all([api<State>('state'), api<ResultSummary[]>('results')]);
      setState(s);
      setResults(r);
      setError('');
      return s;
    } catch (e) {
      setError(errorMessage(e));
      return null;
    } finally {
      setLoading(false);
    }
  };

  /**
   * [효과 명세] 초기 목록 조회
   * 처리: 마운트 시 reload를 한 번 실행한다.
   * 부수효과: 서버 조회와 최초 화면 상태 갱신
   */
  useEffect(() => {
    void reload();
  }, []);

  /**
   * [효과 명세] 작업 진행 주기 조회(폴링)
   * 입력: running·stopped
   * 처리: 진행 중 작업이 있으면 1초, 없으면 8초마다 reload. stopped면 예약하지 않는다.
   * 부수효과/정리: setInterval 생성, 의존성 변경·언마운트 시 clearInterval
   */
  useEffect(() => {
    if (stopped) return;
    const timer = setInterval(() => {
      void reload();
    }, running ? 1000 : 8000);
    return () => clearInterval(timer);
  }, [running, stopped]);

  /**
   * [효과 명세] 결과 상세 조회
   * 입력: targetId(선택 결과), retryTick(재시도 신호)
   * 처리: 대상이 없으면 상세를 비우고, 있으면 /api/results/{id}를 읽어 detail로 둔다.
   *   detail이 대상과 다른 동안 화면에는 current=null(detailPending)로 전달된다.
   * 실패: 상세 오류 문구를 표시하고 detailFailed를 세워 다음 폴링에서 다시 시도한다.
   * 부수효과/정리: HTTP GET, detail·detailError 변경. 정리 시 늦게 도착한 응답을 무시한다(경쟁 방지).
   */
  useEffect(() => {
    if (!targetId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    api<Result>('results/' + targetId)
      .then(r => {
        if (cancelled) return;
        detailFailed.current = false;
        setDetail(r);
        setDetailError('');
      })
      .catch(e => {
        if (cancelled) return;
        detailFailed.current = true;
        setDetailError(errorMessage(e));
      });
    return () => {
      cancelled = true;
    };
  }, [targetId, retryTick]);

  /**
   * [효과 명세] 실패한 상세 재시도
   * 입력: results(폴링마다 새 배열)
   * 처리: 직전 상세 조회가 실패했으면 retryTick을 올려 상세 조회 효과를 다시 실행한다.
   * 부수효과: retryTick 변경
   */
  useEffect(() => {
    if (detailFailed.current) {
      detailFailed.current = false;
      setRetryTick(t => t + 1);
    }
  }, [results]);

  /**
   * [효과 명세] 새 완료 결과 선택 (useJobDone)
   * 입력: state.jobs·loading
   * 처리: 최초 조회가 끝난 뒤(loading=false) 처음 보이는 목록에서 이미 끝나 있던 작업은 기억만 한다.
   *   이후 새로 끝난 작업이 result_id를 가지면 그 결과를 resultId로 정하고 onNewResult(result_id)를 호출한다.
   * 부수효과: resultId 변경, 호출자 콜백 실행(행·포커스·화면 전환)
   */
  useJobDone(state.jobs, null, fresh => {
    for (const j of fresh) {
      if (j.result_id) {
        setResultId(j.result_id);
        onNewResultRef.current(j.result_id);
      }
    }
  }, !loading);

  return {state, results, resultId, setResultId, current, detailPending, loading, error: error || detailError,
    setError: setErrorAll, reload, running};
}
