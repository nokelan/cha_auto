/**
 * [파일 역할] 비교 결과 상세 화면 조각.
 * 3단 화면의 셋째 단과 '비교 결과' 메뉴 화면에서 같은 내용을 보여 준다.
 * 결과 요약 카운트·CSV 저장, 문서 목록, 선택 행의 항목별 판정과 원문 근거를 표시한다.
 * 항목별 판정 목록(check-item + 근거)은 components/CheckList가 그린다(로컬 세금계산서 대조 화면과 공용, DOM은 분리 전과 같다).
 */
import {ArrowRight, Download, FileCheck2, Files, LoaderCircle} from 'lucide-react';
import {stamp, STATUS_ORDER} from '../../api';
import {Badge} from '../../components/Badge';
import {CheckList} from '../../components/CheckList';
import {RawMoneyPanel} from '../../components/RawMoneyPanel';
import type {Preview, Result, Row} from '../../types';

type Props = {
  current: Result | null;
  pending: boolean;
  currentRow: Row | undefined;
  rowIndex: number;
  onSelectRow: (index: number, mailId: string) => void;
  onPreview: (preview: Preview) => void;
  onEdit: () => void;
  onStart: () => void;
};

/**
 * [기능명세] ResultView
 * 목적: 선택된 결과 상세와 현재 행 표시
 * 입력: current(결과 상세 또는 null), pending(결과는 있는데 상세를 불러오는 중), currentRow(표시할 행),
 *   rowIndex(목록 강조 행), onSelectRow(문서 목록 클릭: 행 번호·메일 ID), onPreview(원문 모달 열기),
 *   onEdit(보정 폼 열기), onStart(빈 화면에서 '메일 선택하기')
 * 출력: 결과 JSX. 상세를 불러오는 중이면 로딩 표시, 결과 자체가 없으면 '아직 비교한 문서가 없어요' 빈 화면,
 *   결과는 있는데 표시할 행이 없으면(비교하지 않은 기업을 고른 경우) '선택한 기업은 이 결과에 없어요' 안내
 * 처리/실패: 행 오류(error)는 경고로 표시. 항목별 판정은 CheckList에 맡긴다(근거 없음 문구·0이 아닌 차이만 표시 규칙 포함).
 *   CheckList의 '해당 페이지 보기'는 그 항목 근거 페이지로 원문 나란히 보기(onPreview)를 연다
 * 부수효과: 없음(콜백 호출만). CSV 저장은 /api/results/{id}/csv 링크
 */
export function ResultView({current, pending, currentRow, rowIndex, onSelectRow, onPreview, onEdit, onStart}: Props) {
  if (pending) {
    return (
      <div className="panel empty" aria-busy="true">
        <span className="empty-icon"><LoaderCircle className="spin" size={30}/></span>
        <h3>비교 결과를 불러오는 중</h3>
      </div>
    );
  }
  if (current && !currentRow) {
    // 3단 화면에서 이 결과에 포함되지 않은 기업(비교한 적 없음)을 눌렀거나 행 번호가 범위를 벗어난 경우.
    // 저장된 결과는 있으므로 '비교한 문서가 없다'고 하지 않고 상황에 맞게 안내한다.
    return (
      <div className="panel empty">
        <span className="empty-icon"><FileCheck2 size={30}/></span>
        <h3>선택한 기업은 이 결과에 없어요</h3>
        <p>이 기업은 아직 비교하지 않았습니다. 비교를 실행하면 결과가 표시됩니다. 이전 결과는 '작업 이력'에서 볼 수 있습니다.</p>
      </div>
    );
  }
  if (!current || !currentRow) {
    return (
      <div className="panel empty">
        <span className="empty-icon"><FileCheck2 size={30}/></span>
        <h3>아직 비교한 문서가 없어요</h3>
        <p>메일을 선택하고 PDF를 저장한 뒤 비교를 실행하세요.</p>
        <button className="primary" onClick={onStart}>메일 선택하기<ArrowRight size={16}/></button>
      </div>
    );
  }
  return (
    <>
      <div className="result-summary">
        <div>
          <span className="eyebrow">REVIEW COMPLETE</span>
          <h2>{current.rows.length}건의 비교 결과</h2>
          <p>{stamp(current.created)} {current.parent ? '· 수동 보정 후 재비교' : ''}</p>
        </div>
        <div className="result-counts">
          {STATUS_ORDER.map(s => (
            <div key={s}>
              <Badge status={s}/>
              <strong>{current.rows.filter(r => r.status === s).length}</strong>
            </div>
          ))}
        </div>
        <a className="secondary" href={'/api/results/' + current.id + '/csv'}><Download size={16}/>CSV 저장</a>
      </div>
      <div className="review-layout">
        <section className="panel result-list">
          <div className="panel-heading"><h2>문서 목록</h2></div>
          {current.rows.map((r, i) => (
            <button className={i === rowIndex ? 'active' : ''} key={r.mail_id} onClick={() => onSelectRow(i, r.mail_id)}>
              <strong>{r.partner}</strong>
              <small>{r.subject}</small>
              <Badge status={r.status}/>
            </button>
          ))}
        </section>
        <section className="panel review">
          <div className="panel-heading">
            <div>
              <h2>{currentRow.partner}</h2>
              <p>{currentRow.contract_id} · {currentRow.subject}</p>
            </div>
            <Badge status={currentRow.status}/>
          </div>
          <div className="review-actions">
            <button className="secondary" onClick={() => onPreview({invoice: currentRow.invoice, contract: currentRow.contract})}>
              <Files size={16}/>원문 나란히 보기
            </button>
            <button className="text-btn" onClick={onEdit}>계산서 추출값 보정</button>
          </div>
          <RawMoneyPanel row={currentRow}/>
          {currentRow.error && <div className="alert error">{currentRow.error}</div>}
          <CheckList
            checks={currentRow.checks}
            onPage={c => onPreview({
              invoice: currentRow.invoice,
              contract: currentRow.contract,
              invoicePage: c.invoice_source?.page || 1,
              contractPage: c.contract_source?.page || 1,
            })}
          />
        </section>
      </div>
    </>
  );
}
