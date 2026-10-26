/**
 * [파일 기능명세] 새봄 문서비교 React 화면의 진입점.
 * 책임: 전역 스타일을 불러오고 #root에 AccessGate(비밀번호 화면 → App)를 마운트한다.
 * 통신: 동일 출처 /api JSON(api.ts), PDF.js worker와 글꼴·CMap·WASM은 로컬 자산(components/Pdf.tsx).
 * 상태 계약: 서버 데이터는 재조회, 선택·배율·단 너비는 화면 상태이며 자동 영속화하지 않는다.
 * 설정 연계: package.json은 실행/빌드 의존성, package-lock.json은 정확 버전,
 * tsconfig.json은 ES2022·엄격 타입·React JSX·번들 해석·noEmit의 타입 검사 범위를 정의한다.
 * 파일 구성: types.ts(자료형), api.ts(호출·상수), AccessGate.tsx, App.tsx,
 *   screens/(화면), components/(배지·PDF·모달), hooks/(조회·선택·단 너비).
 * 주석 유지: 함수·이벤트 규칙을 변경하면 해당 파일의 명세도 실제 코드와 함께 고친다.
 */
import {createRoot} from 'react-dom/client';
import {AccessGate} from './AccessGate';
import './style.css';

createRoot(document.getElementById('root')!).render(<AccessGate/>);
