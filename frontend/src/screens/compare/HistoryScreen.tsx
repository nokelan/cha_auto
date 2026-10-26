/**
 * [파일 역할] '작업 이력' 화면. 결과 요약 목록(/api/results)만으로 저장된 비교 작업을 최신순으로 보여 준다.
 */
import {ChevronRight, FileCheck2, History} from 'lucide-react';
import {stamp} from '../../api';
import type {ResultSummary} from '../../types';

/**
 * [기능명세] HistoryScreen
 * 목적: 저장된 비교 작업 목록 표시와 결과 열기
 * 입력: results(결과 요약, 최신순), onOpen(선택한 결과 ID로 '비교 결과' 화면 열기)
 * 출력: 이력 행 목록 또는 '저장된 작업 이력이 없습니다.' 빈 화면 JSX
 * 처리/실패: 행마다 count건 비교, 보정 결과면 '· 수동 보정', 시각, 앞 3개 거래처(count>3이면 ' 외'),
 *   mismatch건 불일치를 표시한다
 * 부수효과: 없음(onOpen 호출만)
 */
export function HistoryScreen({results, onOpen}: {results: ResultSummary[]; onOpen: (id: string) => void}) {
  return (
    <section className="panel">
      <div className="panel-heading"><h2>저장된 비교 작업 <span>{results.length}</span></h2></div>
      {results.length
        ? results.map(r => (
          <button key={r.id} className="history-row" onClick={() => onOpen(r.id)}>
            <span className="history-icon"><FileCheck2 size={22}/></span>
            <div>
              <strong>{r.count}건 비교 {r.parent && '· 수동 보정'}</strong>
              <small>{stamp(r.created)} · {r.partners.join(', ')}{r.count > 3 ? ' 외' : ''}</small>
            </div>
            <span>{r.mismatch}건 불일치</span>
            <ChevronRight size={18}/>
          </button>
        ))
        : <div className="empty"><History size={30}/><h3>저장된 작업 이력이 없습니다.</h3></div>}
    </section>
  );
}
