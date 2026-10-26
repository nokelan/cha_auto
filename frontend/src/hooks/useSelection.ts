/**
 * [파일 역할] 3단 화면에서 사용자가 고른 메일과 연결 정보(Pair: 메일·계약서·세금계산서 PDF) 상태 훅.
 * 선택은 메일 ID를 키로 하는 객체이며 화면 상태일 뿐 서버에 저장하지 않는다.
 */
import {useState} from 'react';
import type {Mail, Pair} from '../types';

/**
 * [기능명세] makePair
 * 목적: 메일 한 건을 처음 선택할 때의 기본 연결 생성(toggle·setAll 공통)
 * 입력: m: PDF 첨부가 1개 이상 있는 Mail
 * 출력: Pair. invoice_url은 첫 PDF, contract_id는 추천 후보가 정확히 1건일 때만 그 ID(아니면 '')
 * 처리/실패: PDF가 없는 메일은 호출자가 미리 제외해야 한다(m.pdfs[0] 접근)
 * 부수효과: 없음
 */
export function makePair(m: Mail): Pair {
  return {
    mail_id: m.id,
    contract_id: m.candidates.length === 1 ? m.candidates[0] : '',
    invoice_url: m.pdfs[0].url,
  };
}

/**
 * [기능명세] useSelection
 * 목적: 선택 메일·연결 상태와 갱신 함수 제공
 * 입력: 없음
 * 출력: {selected(메일ID→Pair), pairs(선택 Pair 배열), toggle, setAll, updatePair, clear}
 * 처리/실패: 아래 각 함수 명세 참조
 * 부수효과: selected 상태 변경
 */
export function useSelection() {
  const [selected, setSelected] = useState<Record<string, Pair>>({});

  /**
   * [기능명세] toggle
   * 목적: 메일 한 건 선택 토글
   * 입력: m: PDF 첨부가 있는 Mail
   * 출력: void
   * 처리/실패: 이미 선택됐으면 제거, 아니면 makePair로 기본 연결 추가
   * 부수효과: selected 갱신
   */
  const toggle = (m: Mail) => setSelected(s => {
    const n = {...s};
    if (n[m.id]) delete n[m.id];
    else n[m.id] = makePair(m);
    return n;
  });

  /**
   * [기능명세] setAll
   * 목적: 표시 중인(필터된) 메일 전체 선택·해제
   * 입력: mails: 현재 필터 결과 중 PDF가 있는 메일 목록
   * 출력: void
   * 처리/실패: 목록이 모두 선택돼 있으면 목록 항목만 해제, 아니면 선택되지 않은 항목만 makePair로 추가
   *   (이미 선택된 항목의 사용자 연결은 유지)
   * 부수효과: selected 갱신. 목록 밖 선택은 유지
   */
  const setAll = (mails: Mail[]) => {
    const all = mails.every(m => !!selected[m.id]);
    setSelected(s => {
      const n = {...s};
      for (const m of mails) {
        if (all) delete n[m.id];
        else n[m.id] ??= makePair(m);
      }
      return n;
    });
  };

  /**
   * [기능명세] updatePair
   * 목적: 선택된 메일의 연결 일부(세금계산서 PDF 또는 계약서) 변경
   * 입력: mailId, patch: Pair 일부 필드
   * 출력: void
   * 처리/실패: 기존 Pair에 patch를 덮어쓴다
   * 부수효과: selected 갱신
   */
  const updatePair = (mailId: string, patch: Partial<Pair>) =>
    setSelected(s => ({...s, [mailId]: {...s[mailId], ...patch}}));

  /** [기능명세] clear — 모든 선택 해제. 부수효과: selected를 빈 객체로. */
  const clear = () => setSelected({});

  return {selected, pairs: Object.values(selected), toggle, setAll, updatePair, clear};
}

/** [자료형 명세] Selection — useSelection 반환값(화면 컴포넌트 props용). */
export type Selection = ReturnType<typeof useSelection>;
