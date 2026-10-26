/**
 * [파일 역할] 사이드바 메뉴와 화면별 제목 문구를 담은 상수 모음(App.tsx에서 분리).
 * 화면 ID는 App의 screen 상태 값과 같다. 런타임 부수효과는 없다.
 */
import {BookOpen, FileCheck2, FileText, FolderSearch, History, Inbox, Settings} from 'lucide-react';

/** [상수 명세] NAV — 사이드바 메뉴(화면 ID·라벨·아이콘). 상단바 경로 표시에도 쓴다. */
export const NAV = [
  {id: 'mails', label: '메일 · 문서 선택', icon: Inbox},
  {id: 'results', label: '비교 결과', icon: FileCheck2},
  {id: 'contracts', label: '계약서 목록', icon: FileText},
  {id: 'local', label: '로컬 세금계산서 대조', icon: FolderSearch},
  {id: 'history', label: '작업 이력', icon: History},
  {id: 'settings', label: '설정', icon: Settings},
  {id: 'docs', label: '개발문서', icon: BookOpen},
];

/** [상수 명세] HEADINGS — 화면별 페이지 제목과 설명. 목록에 없는 화면은 settings 문구를 쓴다. */
export const HEADINGS: Record<string, {title: string; desc: string}> = {
  mails: {title: '문서 비교를 시작하세요', desc: '받은 세금계산서를 선택하고, 계약서와 나란히 확인하세요.'},
  results: {title: '비교 결과', desc: '금액부터 지급 조건까지, 원문에 근거해 확인합니다.'},
  contracts: {title: '계약서 목록', desc: '그룹웨어 계약 문서함에서 계약서를 가져와 원문과 추출값을 확인합니다.'},
  local: {title: '로컬 세금계산서 대조', desc: '내 PC 폴더의 세금계산서를 웹 계약서와 대조합니다.'},
  history: {title: '작업 이력', desc: '이전에 비교한 문서와 결과를 다시 확인하세요.'},
  docs: {title: '개발문서', desc: '설계·API·검증 문서를 앱 안에서 읽습니다.'},
  settings: {title: '앱 설정', desc: '원본 PDF 저장 위치와 사이트 접속을 관리합니다.'},
};
