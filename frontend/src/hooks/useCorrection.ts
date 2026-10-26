/**
 * [파일 역할] 비교 결과의 계산서 추출값 보정 폼 상태와 동작(열기·입력·재비교 요청·닫기)을 담은 훅.
 * App.tsx에서 분리했다. 작업 요청 자체(act)는 호출자가 넘긴다.
 */
import {useEffect, useState} from 'react';
import {EDIT_FIELDS, NUMERIC_EDIT_FIELDS} from '../api';
import type {Result, Row} from '../types';
import {parseCorrectionValue} from '../utils/correction';

/**
 * [기능명세] useCorrection
 * 목적: 현재 행의 계산서 보정 폼(열림 여부·입력값)과 보정 재비교 요청을 관리한다.
 * 입력: current(현재 결과 상세 또는 null), currentRow(현재 행 또는 undefined), resultId·rowIndex(바뀌면 폼을 초기화하는 신호),
 *   act(작업 요청 공통 함수 — 성공하면 true, 실패하면 false를 돌려준다)
 * 출력: {editing, edits, editErrors, openEdits, closeEdits, changeEdit, correct}
 *   (editErrors: 필드 키별 한글 입력 오류. 비어 있으면 오류 없음)
 * 처리/실패:
 *   - resultId 또는 rowIndex가 바뀌면 폼을 닫고 입력값을 비운다.
 *   - openEdits: EDIT_FIELDS 항목을 문자열 입력값으로 채워 연다(값 없으면 빈 문자열, 현재 행이 없으면 무시).
 *   - correct: 빈 값과 기존값과 같은 값은 제외, NUMERIC_EDIT_FIELDS는 쉼표·공백을 허용하는 0 이상 정수로 변환한다(utils/correction).
 *     변환할 수 없는 입력이 하나라도 있으면 서버로 보내지 않고 해당 필드의 editErrors에 한글 오류를 채운 채 폼을 유지한다. 변경이 없으면 폼만 닫는다.
 *     있으면 results/{id}/correct에 {overrides:{계산서 문서 ID: 변경값}}을 보낸다.
 *     요청이 실패하면 폼을 닫지 않고 입력값을 유지한다(오류는 상단 배너). 성공했을 때만 닫는다.
 * 부수효과: 새 비교 작업 요청(act), editing·edits 변경. 원본 PDF 수정 없음. 범위 검증과 새 이력 저장은 서버 담당
 */
export function useCorrection(
  current: Result | null,
  currentRow: Row | undefined,
  resultId: string,
  rowIndex: number,
  act: (path: string, body?: unknown) => Promise<boolean>,
) {
  const [editing, setEditing] = useState(false);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [editErrors, setEditErrors] = useState<Record<string, string>>({});

  /**
   * [효과 명세] 결과 전환 시 보정 초기화
   * 처리: resultId 또는 rowIndex가 바뀌면 보정 모달을 닫고 입력값을 비운다.
   * 부수효과: editing=false, edits 비우기
   */
  useEffect(() => {
    setEditing(false);
    setEdits({});
    setEditErrors({});
  }, [resultId, rowIndex]);

  /**
   * [기능명세] openEdits
   * 목적: 현재 행의 계산서 보정 폼 열기
   * 입력: 현재 행의 effective_invoice.fields
   * 출력: void
   * 처리/실패: EDIT_FIELDS 항목을 문자열 입력값으로 변환(값 없으면 빈 문자열). 현재 행이 없으면 무시
   * 부수효과: edits·editing 상태 변경, editErrors 비움. 원본 PDF 수정 없음
   */
  const openEdits = () => {
    const d = currentRow?.effective_invoice?.fields;
    if (!d) return;
    setEdits(Object.fromEntries(Object.keys(EDIT_FIELDS).map(k => [k, d[k]?.value === undefined ? '' : String(d[k].value)])));
    setEditErrors({});
    setEditing(true);
  };

  /** [기능명세] closeEdits: 입력/출력 없음. 보정 폼을 닫는다(입력값은 다음 열기·결과 전환 때 다시 채워지거나 비워진다). 부수효과 editing 변경. */
  const closeEdits = () => setEditing(false);

  /** [기능명세] changeEdit: 입력 key(필드 키)·value(입력 문자열), 출력 없음. 해당 필드의 입력값만 바꾼 새 객체로 교체하고 그 필드의 입력 오류를 지운다. 부수효과 edits·editErrors 변경. */
  const changeEdit = (key: string, value: string) => {
    setEdits(s => ({...s, [key]: value}));
    setEditErrors(({[key]: _removed, ...rest}) => rest);
  };

  /**
   * [기능명세] correct
   * 목적: 변경된 추출값만 보내 보정 재비교 요청
   * 입력: edits·current·currentRow
   * 출력: Promise<void>
   * 처리/실패: 빈 값과 기존값과 같은 값은 제외, NUMERIC_EDIT_FIELDS는 parseCorrectionValue로 변환
   *   ("1,000,000"→1000000). 변환 불가 입력이 있으면 요청 없이 editErrors에 필드별 한글 오류를 담고 폼을 유지한다.
   *   변경이 없으면 폼만 닫는다. 있으면 results/{id}/correct에 {overrides:{계산서 문서 ID: 변경값}} 전송
   *   요청이 실패하면 폼을 닫지 않고 입력값을 유지한다(오류는 상단 배너). 성공하면 폼을 닫는다
   * 부수효과: 새 비교 작업 요청·성공 시 폼 닫기. 범위 검증과 새 이력 저장은 서버 담당
   */
  const correct = async () => {
    if (!current || !currentRow) return;
    const changed: Record<string, unknown> = {};
    const errors: Record<string, string> = {};
    for (const [k, v] of Object.entries(edits)) {
      const old = currentRow.effective_invoice.fields[k]?.value;
      if (v === '' || v === String(old ?? '')) continue;
      const parsed = parseCorrectionValue(k, v, NUMERIC_EDIT_FIELDS);
      if (parsed.ok) changed[k] = parsed.value;
      else errors[k] = (EDIT_FIELDS[k] ?? k) + ': ' + parsed.error;
    }
    setEditErrors(errors);
    if (Object.keys(errors).length) return;
    if (!Object.keys(changed).length) {
      setEditing(false);
      return;
    }
    // 성공했을 때만 폼을 닫는다. 실패하면 입력값을 유지하고 오류 배너만 보인다.
    if (await act('results/' + current.id + '/correct', {overrides: {[currentRow.invoice.id]: changed}})) setEditing(false);
  };

  return {editing, edits, editErrors, openEdits, closeEdits, changeEdit, correct};
}
