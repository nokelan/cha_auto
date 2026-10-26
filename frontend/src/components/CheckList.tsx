/**
 * [파일 역할] 항목별 판정 목록(check-item) 공용 컴포넌트.
 * '비교 결과'(ResultView)와 '로컬 세금계산서 대조'(LocalAuditScreen) 상세가 함께 쓴다.
 * 항목마다 제목·판정 배지·실제값/기준값·차이·설명·원문 근거(계산서/계약서 인용)를 보여 준다.
 * DOM 계약: 원래 ResultView 안에 있던 마크업을 그대로 옮긴 것이다. check-item 들을 부모 요소의 직계 자식으로
 *   내보내도록 Fragment로 감싸며, 클래스·문구·순서를 바꾸면 회귀 검사(scripts/verify_ui.py)와 CSS가 깨질 수 있다.
 */
import {ArrowRight} from 'lucide-react';
import {display} from '../api';
import {Badge} from './Badge';
import type {CheckItem, Field} from '../types';

/**
 * [기능명세] CheckList
 * 목적: 비교 판정 항목 목록 표시
 * 입력: checks(판정 항목 배열), onPage(선택: 근거 펼침 안의 페이지 이동 버튼을 눌렀을 때 부를 콜백, 인자는 그 항목),
 *   pageLabel(선택: 페이지 이동 버튼 문구, 기본 '해당 페이지 보기')
 * 출력: check-item div 목록 Fragment. checks가 비면 아무것도 그리지 않는다
 * 처리/실패: 값 표시는 display()(없으면 '미확인'). 차이(difference)는 0이 아닌 숫자일 때만 '차이 ±N원'으로 표시.
 *   근거가 없으면 '추출 근거 없음'·'관련 항목을 읽지 못했습니다.', 보정 전 값(previous)이 있으면 함께 보인다.
 *   onPage가 없으면 페이지 이동 버튼을 그리지 않는다
 * 부수효과: 없음(onPage 콜백 호출만)
 */
export function CheckList({checks, onPage, pageLabel = '해당 페이지 보기'}: {
  checks: CheckItem[];
  onPage?: (check: CheckItem) => void;
  pageLabel?: string;
}) {
  return (
    <>
      {checks.map(c => (
        <div className="check-item" key={c.key}>
          <div className="check-title">
            <h3>{c.label}</h3>
            <Badge status={c.status}/>
          </div>
          <div className="check-values">
            <div><small>세금계산서 / 실제값</small><strong>{display(c.actual)}</strong></div>
            <ArrowRight size={16}/>
            <div><small>계약서 / 비교 기준</small><strong>{display(c.expected)}</strong></div>
          </div>
          {typeof c.difference === 'number' && c.difference !== 0 && (
            <p className="difference">차이 {c.difference > 0 ? '+' : ''}{c.difference.toLocaleString('ko-KR')}원 (계산서 − 기준)</p>
          )}
          {c.note && <p className="check-note">{c.note}</p>}
          <details>
            <summary>원문 근거 확인</summary>
            <div className="evidence">
              {([['계산서', c.invoice_source], ['계약서', c.contract_source]] as [string, Field | undefined][]).map(([label, f]) => (
                <blockquote key={label}>
                  <small>{label} {f?.page ? `· ${f.page}페이지` : ''} · {f?.method || '추출 근거 없음'}</small>
                  <p>{f?.quote || '관련 항목을 읽지 못했습니다.'}</p>
                  {f?.previous && <p>보정 전: {display(f.previous.value)} · {f.previous.quote}</p>}
                </blockquote>
              ))}
            </div>
            {onPage && (
              <button className="text-btn" onClick={() => onPage(c)}>
                {pageLabel}
              </button>
            )}
          </details>
        </div>
      ))}
    </>
  );
}
