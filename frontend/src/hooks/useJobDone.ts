/**
 * [파일 역할] App의 state 폴링으로 들어오는 작업 목록에서 "작업이 새로 끝났는지"를 감지하는 훅.
 * useAppState·ContractsScreen·LocalAuditScreen에 복붙돼 있던 seenJobs ref 패턴을 한곳에 모은 것이다.
 * 이 훅은 자체 타이머를 만들지 않는다(폴링은 useAppState 담당).
 */
import {useEffect, useRef} from 'react';
import type {Job} from '../types';

/**
 * [기능명세] useJobDone
 * 목적: running이 아닌 상태로 새로 보이는 작업(완료·실패)을 한 번씩만 콜백에 알린다.
 * 입력: jobs(폴링으로 갱신되는 작업 목록), kinds(감시할 작업 종류. null이면 모든 종류),
 *   onDone(새로 끝난 작업 배열을 받는 콜백. 최신 콜백이 쓰이며 의존성에 넣을 필요 없음),
 *   ready(기본 true. false인 동안은 첫 기준 등록도 미룬다 — 최초 조회 전의 빈 목록을 기준으로 삼지 않기 위함)
 * 출력: 없음.
 * 처리/실패: ready가 처음 true가 되는 첫 실행에서는 이미 끝나 있던 작업 ID만 기억하고 콜백은 부르지 않는다
 *   (마운트·최초 조회가 그 결과를 이미 반영하므로). 이후 jobs가 바뀔 때 기억하지 않은 끝난 작업이 있으면
 *   ID를 기억하고 onDone(fresh)를 한 번 호출한다. 같은 작업은 다시 알리지 않는다.
 * 부수효과: seen ID 집합 갱신, 콜백 실행(콜백이 하는 일은 호출자 몫).
 */
export function useJobDone(
  jobs: Job[],
  kinds: readonly string[] | null,
  onDone: (fresh: Job[]) => void,
  ready = true,
) {
  /** 이미 확인한(끝난) 작업 ID. null이면 아직 첫 목록을 기준으로 등록하지 않은 상태. */
  const seen = useRef<Set<string> | null>(null);
  /** 최신 콜백(효과 의존성에 넣지 않으려고 ref로 보관, 렌더마다 갱신). */
  const callback = useRef(onDone);
  callback.current = onDone;

  useEffect(() => {
    if (!ready) return;
    const done = jobs.filter(j => (kinds === null || kinds.includes(j.kind)) && j.status !== 'running');
    if (seen.current === null) {
      seen.current = new Set(done.map(j => j.id));
      return;
    }
    const known = seen.current;
    const fresh = done.filter(j => !known.has(j.id));
    if (!fresh.length) return;
    fresh.forEach(j => known.add(j.id));
    callback.current(fresh);
  }, [jobs, ready]);
}
