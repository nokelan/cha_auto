/**
 * [파일 역할] 설정 화면의 '저장 위치' 상태와 동작(폴더 입력값·폴더 선택 대화상자·저장 위치 적용)을 담은 훅.
 * App.tsx에서 분리했다. 오류·안내 표시와 상태 재조회는 호출자가 넘기는 함수로 위임한다.
 */
import {useEffect, useState} from 'react';
import {api} from '../api';
import {errorMessage} from '../utils/error';

/**
 * [기능명세] useSettings
 * 목적: 저장 위치 입력값과 폴더 선택·적용 동작을 관리한다.
 * 입력: documentRoot(서버가 알려 준 현재 저장 위치), setError(오류 문구 표시/해제 함수),
 *   setNotice(안내 문구 표시/해제 함수), reload(서버 상태 재조회)
 * 출력: {folder, setFolder, picking, moving, saveFolder, pickFolder}
 *   - folder: 입력 상자 값, picking: 폴더 선택 대화상자 요청 중, moving: 저장 위치 이동 중(다른 작업 잠금에 쓰임)
 * 처리/실패: documentRoot가 바뀌면(비어 있지 않을 때) folder를 그 값으로 맞춘다.
 *   saveFolder/pickFolder의 실패는 setError로 표시하고 상태는 finally에서 해제한다(예외를 밖으로 던지지 않음).
 * 부수효과: settings PUT, settings/pick-folder POST(네이티브 대화상자), reload 호출, folder·picking·moving·안내·오류 변경.
 */
export function useSettings(
  documentRoot: string,
  setError: (message: string) => void,
  setNotice: (message: string) => void,
  reload: () => Promise<unknown>,
) {
  const [folder, setFolder] = useState('');
  const [picking, setPicking] = useState(false);
  const [moving, setMoving] = useState(false);

  /**
   * [효과 명세] 서버 저장 위치 반영
   * 처리: 서버 document_root가 바뀌면(비어 있지 않을 때) 폴더 입력값을 그 값으로 맞춘다.
   * 부수효과: folder 상태 변경
   */
  useEffect(() => {
    if (documentRoot) setFolder(documentRoot);
  }, [documentRoot]);

  /**
   * [기능명세] saveFolder
   * 목적: 저장 위치 적용
   * 입력: 입력 상태 folder
   * 출력: Promise<void>
   * 처리/실패: 이동 중 잠금 → settings PUT → 상태 재조회 → 완료 안내. 실패하면 오류 표시
   * 부수효과: 등록 PDF·경로의 실제 이동은 서버, 화면은 moving·안내·오류 변경
   */
  const saveFolder = async () => {
    setMoving(true);
    setError('');
    setNotice('');
    try {
      await api('settings', {document_root: folder}, 'PUT');
      await reload();
      setNotice('저장 위치를 변경하고 기존 PDF도 함께 옮겼습니다. 이전 비교 이력에서도 원문을 볼 수 있습니다.');
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setMoving(false);
    }
  };

  /**
   * [기능명세] pickFolder
   * 목적: Windows 폴더 선택 대화상자 요청
   * 입력: 인자 없음
   * 출력: Promise<void>
   * 처리/실패: settings/pick-folder 호출 후 취소(null)가 아니면 폴더 입력값만 바꾼다. 실패하면 오류 표시
   * 부수효과: 네이티브 대화상자 요청, picking·folder 변경. 자동 적용하지 않음
   */
  const pickFolder = async () => {
    setPicking(true);
    setError('');
    try {
      const r = await api<{folder: string | null}>('settings/pick-folder', {});
      if (r.folder) setFolder(r.folder);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setPicking(false);
    }
  };

  return {folder, setFolder, picking, moving, saveFolder, pickFolder};
}
