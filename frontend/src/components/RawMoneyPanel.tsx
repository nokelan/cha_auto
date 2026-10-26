/**
 * [파일 역할] 비교 결과 상세에서 PDF 최초 추출 금액(보정 전 원 추출값)을 보여 주는 읽기 전용 패널.
 * 계산서 공급가액·부가세·합계액과 계약서 환산 전 계약금액·기준(월정액/총액)·부가세 조건을 표시한다.
 */
import type {Field, Row} from '../types';

/**
 * [기능명세] rawMoneyText
 * 입력: PDF에서 저장한 원 추출 필드의 value(unknown).
 * 출력: 유한한 숫자는 천 단위와 원 단위 문자열, 그 외는 '미추출'.
 * 처리/실패: 0원은 유효한 원 추출값이며, 누락·비숫자를 0원으로 대체하지 않는다.
 * 부수효과: 없음. 계약 부가세·분할 비율을 계산하거나 추출값을 변경하지 않는다.
 */
function rawMoneyText(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toLocaleString('ko-KR')}원` : '미추출';
}

/**
 * [기능명세] RawMoneyField
 * 입력: sourceLabel(계산서/계약서), label(금액 항목), 원본 field, 선택적 effective(보정 적용 필드).
 * 출력: 원 추출 금액·변경된 비교 적용값·원문과 페이지를 확인하는 읽기 전용 JSX.
 * 처리/실패: 최초 추출값을 우선 표시하고 effective와 다르면 별도 표시한다. 원문·값 누락은 명시한다.
 * 부수효과: 사용자가 details를 펼치는 표시 동작만 제공한다. 원본·보정값·DB는 수정하지 않는다.
 */
function RawMoneyField({sourceLabel, label, field, effective}: {sourceLabel: string; label: string; field?: Field; effective?: Field}) {
  const changed = effective?.value !== undefined && effective.value !== field?.value;
  return (
    <div className="raw-money-field" role="group" aria-label={`${sourceLabel} ${label} 원 추출값`}>
      <small>{label}</small>
      <strong className={typeof field?.value === 'number' ? '' : 'raw-money-missing'}>{rawMoneyText(field?.value)}</strong>
      {changed && <span className="raw-money-corrected">비교 적용값 {rawMoneyText(effective?.value)} <b>수동 보정</b></span>}
      {field?.quote
        ? <details><summary>추출 원문{field.page ? ` · ${field.page}페이지` : ''}</summary><pre>{field.quote}</pre></details>
        : <span className="raw-money-no-source">원문 근거 없음</span>}
    </div>
  );
}

/**
 * [기능명세] RawMoneyPanel
 * 입력: 현재 비교 행 row. invoice.extraction은 최초 추출, effective_invoice는 보정 후 비교 입력이다.
 * 출력: 계산서 공급가액·부가세·합계, 계약 환산 전 금액·월/총액·부가세 조건의 원 추출 패널.
 * 처리/실패: 각 문서의 원본 extraction.fields만 읽으며(pages는 쓰지 않음),
 *   필드 없는 과거 이력도 미추출로 안전하게 표시한다.
 * 부수효과: 없음. 비교 계산 결과나 계약금액을 역산해 원 추출값으로 표시하지 않는다.
 */
export function RawMoneyPanel({row}: {row: Row}) {
  const invoice = row.invoice?.extraction?.fields || {};
  const contract = row.contract?.extraction?.fields || {};
  const effective = row.effective_invoice?.fields || {};
  const basis = contract.basis?.value === 'monthly' ? '월정액' : contract.basis?.value === 'total' ? '총액' : '미추출';
  const vat = contract.vat_mode?.value === 'included'
    ? '부가세 포함'
    : contract.vat_mode?.value === 'excluded'
      ? '부가세 별도'
      : '부가세 조건 미추출';
  return (
    <section className="raw-money-panel" aria-label="금액 원 추출값">
      <header><h3>금액 원 추출값</h3><span>PDF 최초 추출 · 보정 전</span></header>
      <div className="raw-money-grid">
        <section className="raw-money-document" aria-label="세금계산서 원 추출 금액">
          <h4>세금계산서</h4>
          <div className="raw-money-values">
            <RawMoneyField sourceLabel="세금계산서" label="공급가액" field={invoice.supply} effective={effective.supply}/>
            <RawMoneyField sourceLabel="세금계산서" label="부가세" field={invoice.vat} effective={effective.vat}/>
            <RawMoneyField sourceLabel="세금계산서" label="합계액" field={invoice.total} effective={effective.total}/>
          </div>
        </section>
        <section className="raw-money-document" aria-label="계약서 원 추출 금액">
          <h4>계약서 <span>환산 전</span></h4>
          <div className="raw-money-conditions"><span>{basis}</span><span>{vat}</span></div>
          <RawMoneyField sourceLabel="계약서" label="계약금액" field={contract.amount}/>
        </section>
      </div>
      <p className="raw-money-help">계약금액은 부가세·분할 계산 전 값이므로 아래 비교 기준과 다를 수 있습니다.</p>
    </section>
  );
}
