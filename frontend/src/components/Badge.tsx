/**
 * [파일 역할] 비교 판정(일치·불일치·확인 필요·처리 실패, 로컬 대조의 계약서 없음·대조 전)을 색상 배지로 보여 주는 컴포넌트.
 */
import {CheckCircle2, CircleHelp, Clock, FileX2, XCircle} from 'lucide-react';
import {LOCAL_STATUS, STATUS} from '../api';

/**
 * [기능명세] Badge
 * 목적: 판정 배지 표시
 * 입력: status 판정 문자열
 * 출력: 아이콘·색상 클래스(badge green/red/amber/gray)를 포함한 JSX
 * 처리/실패: 일치=초록, 불일치/처리 실패=빨강, 대조 전=회색, 그 외(확인 필요·계약서 없음 포함)=확인 계열(amber).
 *   아이콘은 일치=체크, 불일치=X, 계약서 없음=빈 문서, 대조 전=시계, 그 외(처리 실패 포함)=물음표
 * 부수효과: 없음(표시만 수행)
 */
export function Badge({status}: {status: string}) {
  const cls = status === STATUS.MATCH
    ? 'green'
    : status === STATUS.MISMATCH || status === STATUS.FAILED
      ? 'red'
      : status === LOCAL_STATUS.PENDING ? 'gray' : 'amber';
  const icon = status === STATUS.MATCH
    ? <CheckCircle2 size={12}/>
    : status === STATUS.MISMATCH
      ? <XCircle size={12}/>
      : status === LOCAL_STATUS.NONE
        ? <FileX2 size={12}/>
        : status === LOCAL_STATUS.PENDING
          ? <Clock size={12}/>
          : <CircleHelp size={12}/>;
  return <span className={'badge ' + cls}>{icon} {status}</span>;
}
