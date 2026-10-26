/**
 * [파일 역할] '설정' 화면. 원본 PDF 저장 위치 변경, 사이트 전용 브라우저 열기, 로컬 데이터 안내를 보여 준다.
 * 폴더 입력값과 저장·선택 요청은 useSettings 훅이 관리하고, 이 화면은 표시와 콜백 호출만 한다.
 */
import {Check, FolderOpen, LoaderCircle, ShieldCheck, Wifi} from 'lucide-react';
import type {State} from '../types';

type Props = {
  state: State;
  folder: string;
  picking: boolean;
  moving: boolean;
  busy: boolean;
  onFolderChange: (folder: string) => void;
  onPickFolder: () => void;
  onSaveFolder: () => void;
  onOpenBrowser: () => void;
};

/**
 * [기능명세] SettingsScreen
 * 목적: 저장 위치·사이트 연결·로컬 데이터 설정 화면
 * 입력: state(document_root·data_dir·site), folder(입력 중인 폴더), picking(폴더 선택 대화상자 중),
 *   moving(PDF 이동 중), busy(작업 중), onFolderChange, onPickFolder, onSaveFolder, onOpenBrowser
 * 출력: 설정 패널 3개 JSX
 * 처리/실패: 폴더가 비었거나 현재 저장 위치와 같거나 작업 중이면 '저장 위치 적용'을 막는다
 * 부수효과: 없음(콜백 호출만). 실제 이동·브라우저 실행은 서버가 담당
 */
export function SettingsScreen({state, folder, picking, moving, busy, onFolderChange, onPickFolder, onSaveFolder, onOpenBrowser}: Props) {
  return (
    <div className="settings-grid">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2><FolderOpen size={19}/>원본 PDF 저장 위치</h2>
            <p>내 PC의 원하는 폴더에 문서 종류별로 보관합니다.</p>
          </div>
        </div>
        <div className="settings-body">
          <label className="field-label" htmlFor="folder">저장할 기본 폴더</label>
          <div className="folder-input">
            <input id="folder" disabled={busy} value={folder} onChange={e => onFolderChange(e.target.value)} placeholder="예: D:\새봄문서"/>
            <button className="secondary" disabled={picking || busy} onClick={onPickFolder}>
              <FolderOpen size={16}/>{picking ? '선택 중…' : '폴더 선택'}
            </button>
          </div>
          <div className="folder-tree">
            <FolderOpen size={17}/>
            <strong>{folder || '지정 폴더'}</strong>
            <div>└ 세금계산서 <span>세금계산서 원본 PDF</span></div>
            <div>└ 계약서 <span>계약서 원본 PDF</span></div>
          </div>
          <p className="help">저장 위치를 적용하면 기존 세금계산서·계약서 PDF도 새 폴더로 함께 이동합니다. 이전 비교 이력의 원문 연결도 유지됩니다. 파일 이동이 끝날 때까지 기다려 주세요.</p>
          <button className="primary" disabled={busy || !folder || folder === state.document_root} onClick={onSaveFolder}>
            {moving ? <LoaderCircle size={16} className="spin"/> : <Check size={16}/>}저장 위치 적용
          </button>
        </div>
      </section>
      <section className="panel">
        <div className="panel-heading"><h2>사이트 연결</h2></div>
        <div className="settings-body">
          <div className="site-address">
            <Wifi size={18}/>
            <div>
              <strong>새봄 그룹웨어</strong>
              <p>{state.site}</p>
            </div>
          </div>
          <p className="help">앱 전용 브라우저로 접속합니다. 로그인이 필요한 경우 열린 창에서 직접 로그인한 후 목록을 새로고침하세요.</p>
          <button className="secondary" disabled={busy} onClick={onOpenBrowser}><FolderOpen size={16}/>전용 브라우저 열기</button>
        </div>
      </section>
      <section className="panel">
        <div className="panel-heading"><h2>로컬 데이터와 처리 방식</h2></div>
        <div className="settings-body">
          <div className="setting-note">
            <ShieldCheck size={23}/>
            <div>
              <strong>AI 없이 규칙으로 비교</strong>
              <p>텍스트가 포함된 PDF를 읽고 금액·기간·지급조건을 대조합니다. 이미지 PDF와 모호한 조건은 확인 필요로 표시합니다.</p>
            </div>
          </div>
          <label className="field-label">설정·목록·이력 저장 위치</label>
          <code>{state.data_dir}</code>
          <p className="help">인터넷은 목록 동기화와 다운로드에만 사용합니다. 저장된 PDF의 비교·원문 보기·CSV 저장은 오프라인에서 가능합니다.</p>
        </div>
      </section>
    </div>
  );
}
