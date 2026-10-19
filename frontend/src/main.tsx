/**
 * [파일 기능명세] 새봄 문서비교 React 화면.
 * 책임: AccessGate 인증 → 기업·문서 3단 선택 → 작업 조회 → 비교·원문·보정·저장 위치 UI.
 * 통신: 동일 출처 /api JSON, PDF.js worker와 글꼴·CMap·WASM은 로컬 자산 사용.
 * 상태 계약: 서버 데이터는 재조회, 선택·배율·단 너비는 화면 상태이며 자동 영속화하지 않는다.
 * 설정 연계: package.json은 실행/빌드 의존성, package-lock.json은 정확 버전,
 * tsconfig.json은 ES2022·엄격 타입·React JSX·번들 해석·noEmit의 타입 검사 범위를 정의한다.
 * 주석 유지: 함수·이벤트 규칙을 변경하면 바로 아래 명세도 실제 코드와 함께 고친다.
 */
import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowRight, Check, CheckCircle2, ChevronLeft, ChevronRight, CircleHelp, Download, FileCheck2, Files, FolderOpen, History, Inbox, Leaf, LoaderCircle, Power, RefreshCw, Search, Settings, ShieldCheck, Wifi, X, XCircle } from 'lucide-react';
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import './style.css';

GlobalWorkerOptions.workerSrc = workerUrl;
/**
 * [자료형 명세] Field
 * 추출 필드: value·원문 quote·1부터 시작하는 page·method, 보정 전 previous.
 */
type Field = {value: unknown; quote: string; page: number|null; method: string; previous?: Field};
/**
 * [자료형 명세] Extraction
 * 문서 추출: 필드 사전·페이지 텍스트·판독 error.
 */
type Extraction = {fields: Record<string,Field>; pages: {page:number;text:string}[]; error: string|null};
/**
 * [자료형 명세] Doc
 * 문서 레코드: 식별 ID·파일 이름·추출값·현재 경로·실제 파일 available.
 */
type Doc = {id:string; name:string; extraction:Extraction; available?:boolean; disk_path:string};
/**
 * [자료형 명세] Attachment
 * 사이트 첨부의 원본 이름과 다운로드 URL.
 */
type Attachment = {name:string;url:string};
/**
 * [자료형 명세] Mail
 * 메일과 PDF 첨부·저장 문서·추천 계약 ID 목록.
 */
type Mail = {id:string;sender:string;subject:string;received:string;pdfs:Attachment[];documents:Record<string,Doc|null>;candidates:string[];attachments:Attachment[]};
/**
 * [자료형 명세] Contract
 * 계약의 관리번호·종류·거래처·기간·표시 금액·PDF 문서.
 */
type Contract = {id:string;kind:string;partner:string;title:string;period:string;amount_text:string;file:Attachment|null;document:Doc|null};
/**
 * [자료형 명세] Pair
 * 사용자 확정 연결: mail_id·contract_id·invoice_url.
 */
type Pair = {mail_id:string;contract_id:string;invoice_url:string};
/**
 * [자료형 명세] Job
 * 비동기 작업: 종류·상태·완료/전체 수·오류·생성 결과 ID.
 */
type Job = {id:string;kind:string;status:string;message:string;done:number;total:number;errors:string[];result_id?:string};
/**
 * [자료형 명세] State
 * 서버 상태: 목록·작업·동기화 시각·앱 데이터 루트·PDF 루트.
 */
type State = {mails:Mail[];contracts:Contract[];jobs:Job[];synced:string|null;data_dir:string;document_root:string};
/**
 * [자료형 명세] CheckItem
 * 항목별 실제값·기준값·판정·차이·설명·양쪽 근거.
 */
type CheckItem = {key:string;label:string;actual:unknown;expected:unknown;status:string;note:string;difference?:number|null;invoice_source?:Field;contract_source?:Field};
/**
 * [자료형 명세] Row
 * 메일/계약 한 쌍의 비교 결과와 원본·유효 계산서 추출값.
 */
type Row = {mail_id:string;contract_id:string;subject:string;partner:string;status:string;checks:CheckItem[];invoice:Doc;contract:Doc;effective_invoice:Extraction;error:string|null};
/**
 * [자료형 명세] Result
 * 비교 작업 이력: ID·시각·행 목록·보정 전 부모 ID.
 */
type Result = {id:string;created:string;rows:Row[];parent?:string};
const empty:State={mails:[],contracts:[],jobs:[],synced:null,data_dir:'',document_root:''};

/**
 * [기능명세] api
 * 목적: 로컬 API JSON 호출 공통 함수
 * 입력: path: /api/ 뒤 경로, body: 선택 JSON, method: 본문이 있을 때 사용할 HTTP 메서드
 * 출력: Promise<T>; 응답 JSON
 * 처리/실패: 본문이 없으면 GET, 있으면 JSON 요청; 실패 detail을 Error로 변환
 * 부수효과: fetch 네트워크 요청; 상태 변경·오류 표시는 호출자가 담당
 */
async function api<T>(path:string,body?:unknown,method='POST'):Promise<T>{
 const r=await fetch('/api/'+path,body===undefined?{}:{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 if(!r.ok){const e=await r.json().catch(/* [콜백 명세] api / catch 콜백 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 실패 상태·오류 메시지 처리 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ ()=>({detail:'요청을 완료하지 못했습니다.'}));throw Error(typeof e.detail==='string'?e.detail:'입력값을 확인해 주세요.');}
 return r.json();
}
const stamp=/**
 * [기능명세] stamp
 * 목적: 동기화·결과 시각 표시
 * 입력: ISO 시각 또는 null
 * 출력: 한국어 월·일·시·분 문자열 또는 미동기화 안내
 * 처리/실패: Date와 ko-KR 로캘로 변환
 * 부수효과: 없음
 */
(s:string|null)=>s?new Date(s).toLocaleString('ko-KR',{month:'long',day:'numeric',hour:'2-digit',minute:'2-digit'}):'아직 동기화하지 않음';
const display=/**
 * [기능명세] display
 * 목적: 비교값 화면 표시
 * 입력: unknown 값
 * 출력: 표시 문자열
 * 처리/실패: null은 미확인, 숫자는 천 단위, 배열은 쉼표 연결
 * 부수효과: 없음
 */
(v:unknown):string=>v===null||v===undefined?'미확인':typeof v==='number'?v.toLocaleString('ko-KR'):Array.isArray(v)?v.join(', '):String(v);
/**
 * [기능명세] Badge
 * 목적: 판정 배지 컴포넌트
 * 입력: status 판정 문자열
 * 출력: 아이콘·색상을 포함한 JSX
 * 처리/실패: 일치=초록, 불일치/처리 실패=빨강, 그 외=확인 계열
 * 부수효과: 표시만 수행
 */
function Badge({status}:{status:string}){const cls=status==='일치'?'green':status==='불일치'||status==='처리 실패'?'red':'amber';return <span className={'badge '+cls}>{status==='일치'?<CheckCircle2 size={12}/>:status==='불일치'?<XCircle size={12}/>:<CircleHelp size={12}/>} {status}</span>}

/**
 * [기능명세] Pdf
 * 목적: 문서별 페이지·확대 상태를 갖는 PDF 뷰어
 * 입력: doc: 문서 ID/이름, initialPage: 기본 1
 * 출력: PDF 도구와 Canvas JSX
 * 처리/실패: 영역 너비 측정→인증된 문서 URL→PDF.js 렌더→스크롤 보정
 * 부수효과: PDF 요청·worker·Canvas·ResizeObserver 사용; 효과 정리에서 렌더 취소와 문서 해제
 */
function Pdf({doc,initialPage=1}:{doc:Doc;initialPage?:number}){
 const [page,setPage]=useState(initialPage),[count,setCount]=useState(0),[err,setErr]=useState(''),[loading,setLoading]=useState(true);
 const [zoom,setZoom]=useState(1),[fitWidth,setFitWidth]=useState(600);
 const canvas=useRef<HTMLCanvasElement>(null),body=useRef<HTMLDivElement>(null);
 const anchor=useRef<{x:number;y:number}|null>(null);
 useEffect(/**
 * [효과 콜백 명세] Pdf.effect1 표시 영역 크기 관찰
 * 입력: 의존성 배열의 상태; 출력: void 또는 자원 정리 함수
 * 처리: 마운트 시 ResizeObserver 등록, clientWidth에서 좌우 여백 32px를 빼 맞춤 너비 설정
 * 부수효과/정리: 정리 함수에서 observer.disconnect; fitWidth 변경
 */
()=>{const el=body.current;if(!el)return;const observer=new ResizeObserver(/* [콜백 명세] Pdf / 상태/비동기 콜백 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 본문에 명시된 비동기·조회·렌더 처리 / 영향: 상태 갱신 setFitWidth */ ()=>setFitWidth(Math.max(100,el.clientWidth-32)));observer.observe(el);return/* [콜백 명세] Pdf / 상태/비동기 콜백 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 본문에 명시된 비동기·조회·렌더 처리 / 영향: DOM 이벤트·스크롤 또는 자원 정리; 본문 참조 */ ()=>observer.disconnect();},[]);
 const changeZoom=/**
 * [기능명세] changeZoom
 * 목적: 버튼 배율 변경
 * 입력: value: 화면 맞춤 기준 배율
 * 출력: void
 * 처리/실패: 클릭 앵커를 비우고 1~3으로 제한하며 소수 두 자리 정리
 * 부수효과: zoom 상태 변경으로 재렌더링 요청
 */
(value:number)=>{anchor.current=null;setZoom(Math.max(1,Math.min(3,Math.round(value*100)/100)));};
 const toggleZoom=/**
 * [기능명세] toggleZoom
 * 목적: 클릭·키보드 확대 전환
 * 입력: 선택적 Canvas 마우스 이벤트
 * 출력: void
 * 처리/실패: 로딩/오류 중 무시; 맞춤→2배, 그 외→맞춤; 클릭 상대 좌표 보관
 * 부수효과: zoom·anchor 변경; 실제 스크롤은 완료 효과가 담당
 */
(e?:React.MouseEvent<HTMLCanvasElement>)=>{if(loading||err)return;if(zoom===1&&e){const rect=e.currentTarget.getBoundingClientRect();anchor.current={x:(e.clientX-rect.left)/rect.width,y:(e.clientY-rect.top)/rect.height};}else anchor.current=null;setZoom(zoom===1?2:1);};
 useEffect(/**
 * [효과 콜백 명세] Pdf.effect2 PDF 페이지 렌더 수명
 * 입력: 의존성 배열의 상태; 출력: void 또는 자원 정리 함수
 * 처리: doc.id/page/zoom/fitWidth가 바뀌면 문서와 페이지를 읽어 배율·최대 2배 DPR로 Canvas 렌더
 * 부수효과/정리: 로딩·오류·페이지 수 변경; 정리 시 disposed 표시·렌더 취소·문서 해제
 */
()=>{let disposed=false;let task:ReturnType<typeof getDocument>|undefined;let renderTask:{cancel:()=>void}|undefined;setLoading(true);setErr('');
  task=getDocument({url:'/api/documents/'+doc.id,cMapUrl:'/pdfjs/cmaps/',cMapPacked:true,standardFontDataUrl:'/pdfjs/standard_fonts/',wasmUrl:'/pdfjs/wasm/'});
  task.promise.then(/* [콜백 명세] Pdf / then 콜백 / 입력: (pdf) / 출력: Promise; 본문의 return/예외를 따름 / 처리: 본문에 명시된 비동기·조회·렌더 처리 / 영향: 상태 갱신 setCount, setLoading */ async pdf=>{if(disposed)return;setCount(pdf.numPages);const p=await pdf.getPage(Math.min(page,pdf.numPages));if(disposed||!canvas.current)return;const scale=fitWidth*zoom/p.getViewport({scale:1}).width*Math.min(window.devicePixelRatio||1,2);const viewport=p.getViewport({scale});const el=canvas.current;el.width=viewport.width;el.height=viewport.height;const r=p.render({canvas:el,viewport});renderTask=r;await r.promise;if(!disposed)setLoading(false);}).catch(/* [콜백 명세] Pdf / catch 콜백 / 입력: (e) / 출력: 본문 return 값 또는 void / 처리: 실패 상태·오류 메시지 처리 / 영향: 상태 갱신 setErr, setLoading */ e=>{if(!disposed){setErr('PDF를 표시할 수 없습니다. 저장 경로와 파일을 확인해 주세요. '+e.message);setLoading(false);}});
  return/* [콜백 명세] Pdf / 상태/비동기 콜백 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 본문에 명시된 비동기·조회·렌더 처리 / 영향: DOM 이벤트·스크롤 또는 자원 정리; 본문 참조 */ ()=>{disposed=true;renderTask?.cancel();void task?.destroy();};
 },[doc.id,page,zoom,fitWidth]);
 useEffect(/**
 * [효과 콜백 명세] Pdf.effect3 렌더 완료 후 스크롤 보정
 * 입력: 의존성 배열의 상태; 출력: void 또는 자원 정리 함수
 * 처리: 로딩 종료 뒤 맞춤이면 좌상단, 클릭 확대면 저장한 상대 좌표가 가운데 오도록 이동
 * 부수효과/정리: PDF 본문 scrollLeft/scrollTop과 anchor 참조 변경
 */
()=>{if(loading||!body.current||!canvas.current)return;if(zoom===1){body.current.scrollTo(0,0);}else if(anchor.current){const point=anchor.current;body.current.scrollTo(point.x*canvas.current.clientWidth-body.current.clientWidth/2,point.y*canvas.current.clientHeight-body.current.clientHeight/2);anchor.current=null;}},[loading,zoom]);
 return <div className="pdf"><div className="pdf-tools"><span title={doc.name}>{doc.name}</span><div><button aria-label="이전 페이지" disabled={page<=1} onClick={/* [콜백 명세] Pdf / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 상태 갱신 setPage */ ()=>setPage(page-1)}><ChevronLeft size={16}/></button><b>{page} / {count||'…'}</b><button aria-label="다음 페이지" disabled={page>=count} onClick={/* [콜백 명세] Pdf / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 상태 갱신 setPage */ ()=>setPage(page+1)}><ChevronRight size={16}/></button></div><a href={'/api/documents/'+doc.id} target="_blank" rel="noreferrer">원본 열기</a></div><div className="pdf-zoom-tools"><span>클릭해서 {zoom===1?'확대':'화면 맞춤'}</span><button aria-label="문서 축소" disabled={zoom<=1||loading||!!err} onClick={/* [콜백 명세] Pdf / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ ()=>changeZoom(zoom-.25)}>−</button><output aria-label="문서 확대 비율" title="화면 맞춤 크기 기준">{Math.round(zoom*100)}%</output><button aria-label="문서 확대" disabled={zoom>=3||loading||!!err} onClick={/* [콜백 명세] Pdf / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ ()=>changeZoom(zoom+.25)}>+</button><button className="fit-button" disabled={zoom===1} onClick={/* [콜백 명세] Pdf / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ ()=>changeZoom(1)}>화면 맞춤</button></div><div className="pdf-body" ref={body} aria-busy={loading}>{loading&&<p><LoaderCircle className="spin" size={16}/> 문서 불러오는 중</p>}{err&&<p className="error">{err}</p>}<canvas ref={canvas} hidden={loading||!!err} style={{width:fitWidth*zoom,maxWidth:'none',cursor:zoom===1?'zoom-in':'zoom-out'}} role="button" tabIndex={loading||err?-1:0} aria-label={zoom===1?'문서 이미지 클릭하여 확대':'문서 이미지 클릭하여 화면 맞춤'} aria-pressed={zoom>1} onClick={toggleZoom} onKeyDown={/* [콜백 명세] Pdf / onKeyDown 이벤트 / 입력: (e) / 출력: 본문 return 값 또는 void / 처리: 키 조건을 확인하고 본문 동작 실행 / 영향: DOM 이벤트·스크롤 또는 자원 정리; 본문 참조 */ e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();toggleZoom();}}}/></div></div>
}

/**
 * [기능명세] AccessGate
 * 목적: 프로그램 시작 비밀번호 화면
 * 입력: 컴포넌트 인자 없음
 * 출력: 준비 화면·로그인 폼 또는 App JSX
 * 처리/실패: auth/status 조회 후 서버 확인 성공에만 App 마운트
 * 부수효과: 비밀번호 입력·인증 상태와 요청 관리; 입력값은 영속 저장하지 않음
 */
function AccessGate(){
 const [checking,setChecking]=useState(true),[unlocked,setUnlocked]=useState(false),[password,setPassword]=useState(''),[error,setError]=useState(''),[submitting,setSubmitting]=useState(false);
 const input=useRef<HTMLInputElement>(null);
 useEffect(/**
 * [효과 콜백 명세] AccessGate.effect1 최초 인증 조회
 * 입력: 의존성 배열의 상태; 출력: void 또는 자원 정리 함수
 * 처리: 마운트 때 auth/status를 읽고 authenticated로 UI 분기; 실패 오류 표시
 * 부수효과/정리: checking 종료·인증 상태 변경; 실패 시 App을 열지 않음
 */
()=>{api<{authenticated:boolean}>('auth/status').then(/* [콜백 명세] AccessGate / then 콜백 / 입력: (r) / 출력: 본문 return 값 또는 void / 처리: 본문에 명시된 비동기·조회·렌더 처리 / 영향: 상태 갱신 setUnlocked */ r=>setUnlocked(r.authenticated)).catch(/* [콜백 명세] AccessGate / catch 콜백 / 입력: (e) / 출력: 본문 return 값 또는 void / 처리: 실패 상태·오류 메시지 처리 / 영향: 상태 갱신 setError */ e=>setError(e.message)).finally(/* [콜백 명세] AccessGate / finally 콜백 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 요청 종료 후 상태·자원 정리 / 영향: 상태 갱신 setChecking */ ()=>setChecking(false));},[]);
 const login=/**
 * [기능명세] login
 * 목적: 비밀번호 폼 제출
 * 입력: React.FormEvent
 * 출력: Promise<void>
 * 처리/실패: 기본 제출 방지→중복/빈 값 검사→auth/login→성공 시 잠금 해제, 실패 시 오류·포커스
 * 부수효과: 입력값 비우기·로그인 상태/요청 상태 변경; 쿠키 발급은 서버 담당
 */
async(e:React.FormEvent)=>{e.preventDefault();if(submitting||!password)return;setSubmitting(true);setError('');try{await api('auth/login',{password});setPassword('');setUnlocked(true);}catch(e){setError((e as Error).message);setPassword('');input.current?.focus();}finally{setSubmitting(false);}};
 if(checking)return <div className="access-screen"><LoaderCircle className="spin" size={28}/><p>프로그램을 준비하고 있습니다.</p></div>;
 if(unlocked)return <App/>;
 return <div className="access-screen"><section className="access-card"><div className="access-logo"><Leaf size={30}/></div><h1>새봄 문서비교</h1><p>프로그램을 시작하려면 비밀번호를 입력해 주세요.</p><form onSubmit={/* [콜백 명세] AccessGate / onSubmit 이벤트 / 입력: (e) / 출력: 본문 return 값 또는 void / 처리: 본문에 명시된 비동기·조회·렌더 처리 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ e=>void login(e)}><label htmlFor="app-password">비밀번호</label><input ref={input} id="app-password" type="password" inputMode="numeric" autoComplete="current-password" autoFocus maxLength={128} value={password} disabled={submitting} onChange={/* [콜백 명세] AccessGate / onChange 이벤트 / 입력: (e) / 출력: 본문 return 값 또는 void / 처리: 입력·선택 값을 해당 화면 상태에 반영 / 영향: 상태 갱신 setPassword */ e=>setPassword(e.target.value)} aria-describedby={error?'login-error':undefined}/>{error&&<p id="login-error" role="alert">{error}</p>}<button className="primary" type="submit" disabled={!password||submitting}>{submitting?<LoaderCircle className="spin" size={16}/>:<ShieldCheck size={16}/>}시작하기</button></form><small>저장된 문서와 비교 이력은 잠금 해제 후 확인할 수 있습니다.</small></section></div>;
}

/**
 * [기능명세] App
 * 목적: 기업 선택·비교·이력·설정 화면 컨테이너
 * 입력: 컴포넌트 인자 없음
 * 출력: 메인 화면·모달 또는 종료 안내 JSX
 * 처리/실패: 서버 상태 조회와 사용자 선택을 합쳐 버튼·결과·모달 구성
 * 부수효과: 주기 요청·작업 API·선택/설정/미리보기 상태 관리
 */
function App(){
 const [state,setState]=useState<State>(empty),[screen,setScreen]=useState('mails'),[selected,setSelected]=useState<Record<string,Pair>>({}),[q,setQ]=useState(''),[from,setFrom]=useState(''),[to,setTo]=useState('');
 const [results,setResults]=useState<Result[]>([]),[resultId,setResultId]=useState(''),[rowIndex,setRowIndex]=useState(0),[notice,setNotice]=useState(''),[error,setError]=useState(''),[loading,setLoading]=useState(true),[requesting,setRequesting]=useState(false),[stopped,setStopped]=useState(false);
 const [folder,setFolder]=useState(''),[picking,setPicking]=useState(false),[preview,setPreview]=useState<{invoice:Doc;contract:Doc;invoicePage?:number;contractPage?:number}|null>(null),[editing,setEditing]=useState(false),[edits,setEdits]=useState<Record<string,string>>({});
 const [widths,setWidths]=useState([27,32]);
 const [moving,setMoving]=useState(false);
 const [focusedMail,setFocusedMail]=useState('');
 const jobsLoaded=useRef(false);
 const workspaceRef=useRef<HTMLDivElement>(null);
 const drag=useRef<{index:number;x:number;widths:number[]}|null>(null);
 const resize=/**
 * [기능명세] resize
 * 목적: 3단 화면 비율 변경
 * 입력: index: 경계 0/1, delta: 퍼센트 변화량, base: 기준 비율
 * 출력: void
 * 처리/실패: 최소 너비 제약 안에서 인접 열 비율 조정
 * 부수효과: widths 상태 변경; DB 저장하지 않음
 */
(index:number,delta:number,base=widths)=>{const next=[...base];if(index===0){const d=Math.max(20-base[0],Math.min(base[1]-22,delta));next[0]+=d;next[1]-=d;}else{next[1]=Math.max(22,Math.min(100-base[0]-27,base[1]+delta));}setWidths(next);};
 const divider=/**
 * [기능명세] divider
 * 목적: 키보드·포인터로 조절 가능한 경계 렌더
 * 입력: index: 경계 번호
 * 출력: separator JSX
 * 처리/실패: 방향키는 2단위, 포인터 이동은 전체 폭 대비 비율; 드래그 끝에 참조 해제
 * 부수효과: 포인터 캡처·drag 참조·widths 변경
 */
(index:number)=><div className="column-divider" role="separator" tabIndex={0} aria-label={index===0?'기업 목록 너비 조정':'비교 영역 너비 조정'} aria-orientation="vertical" aria-valuemin={index===0?20:22} aria-valuemax={index===0?widths[0]+widths[1]-22:100-widths[0]-27} aria-valuenow={Math.round(widths[index])} onKeyDown={/* [콜백 명세] divider / onKeyDown 이벤트 / 입력: (e) / 출력: 본문 return 값 또는 void / 처리: 키 조건을 확인하고 본문 동작 실행 / 영향: DOM 이벤트·스크롤 또는 자원 정리; 본문 참조 */ e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();resize(index,e.key==='ArrowLeft'?-2:2);}}} onPointerDown={/* [콜백 명세] divider / onPointerDown 이벤트 / 입력: (e) / 출력: 본문 return 값 또는 void / 처리: 본문에 명시된 비동기·조회·렌더 처리 / 영향: 상태 갱신 setPointerCapture */ e=>{e.currentTarget.setPointerCapture(e.pointerId);drag.current={index,x:e.clientX,widths:[...widths]};}} onPointerMove={/* [콜백 명세] divider / onPointerMove 이벤트 / 입력: (e) / 출력: 본문 return 값 또는 void / 처리: 본문에 명시된 비동기·조회·렌더 처리 / 영향: 참조 상태 변경; 본문 참조 */ e=>{if(drag.current&&workspaceRef.current)resize(index,(e.clientX-drag.current.x)/workspaceRef.current.clientWidth*100,drag.current.widths);}} onPointerUp={/* [콜백 명세] divider / onPointerUp 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 본문에 명시된 비동기·조회·렌더 처리 / 영향: 참조 상태 변경; 본문 참조 */ ()=>{drag.current=null;}} onPointerCancel={/* [콜백 명세] divider / onPointerCancel 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 본문에 명시된 비동기·조회·렌더 처리 / 영향: 참조 상태 변경; 본문 참조 */ ()=>{drag.current=null;}}><span/></div>;
 const seen=useRef(new Set<string>());
 const reload=/**
 * [기능명세] reload
 * 목적: 서버 상태와 비교 이력 동시 갱신
 * 입력: 인자 없음
 * 출력: Promise<State|null>
 * 처리/실패: state/results 병렬 조회; 실패 메시지 표시; 최초 로딩 해제
 * 부수효과: HTTP 읽기와 state/results/error/loading 변경
 */
async()=>{try{const [s,r]=await Promise.all([api<State>('state'),api<Result[]>('results')]);setState(s);setResults(r);setError('');return s;}catch(e){setError((e as Error).message);return null;}finally{setLoading(false);}};
 useEffect(/**
 * [효과 콜백 명세] App.effect1 초기 목록 조회
 * 입력: 의존성 배열의 상태; 출력: void 또는 자원 정리 함수
 * 처리: 마운트 시 reload 한 번 실행
 * 부수효과/정리: 서버 조회와 최초 화면 상태 갱신
 */
()=>{void reload();},[]);
 const busy=requesting||moving||state.jobs.some(/* [콜백 명세] App / some 콜백 / 입력: (j) / 출력: 조건 판정값 / 처리: 준비 조건·선택 조건·작업 상태 검사 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ j=>j.status==='running');
 useEffect(/**
 * [효과 콜백 명세] App.effect2 작업 진행 주기 조회
 * 입력: 의존성 배열의 상태; 출력: void 또는 자원 정리 함수
 * 처리: 진행 작업이 있으면 1초, 없으면 8초; stopped이면 예약하지 않음
 * 부수효과/정리: 타이머 생성, 정리 시 clearInterval
 */
()=>{if(stopped)return;const timer=setInterval(/* [콜백 명세] App / setInterval 콜백 / 입력: () / 출력: 다음 상태값 / 처리: 직전 상태를 사용해 불변 갱신값 계산 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ ()=>{void reload();},state.jobs.some(/* [콜백 명세] App / some 콜백 / 입력: (j) / 출력: 조건 판정값 / 처리: 준비 조건·선택 조건·작업 상태 검사 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ j=>j.status==='running')?1000:8000);return/* [콜백 명세] App / 상태/비동기 콜백 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 본문에 명시된 비동기·조회·렌더 처리 / 영향: DOM 이벤트·스크롤 또는 자원 정리; 본문 참조 */ ()=>clearInterval(timer);},[state.jobs.some(/* [콜백 명세] App / some 콜백 / 입력: (j) / 출력: 조건 판정값 / 처리: 준비 조건·선택 조건·작업 상태 검사 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ j=>j.status==='running'),stopped]);
 useEffect(/**
 * [효과 콜백 명세] App.effect3 새 완료 결과 선택
 * 입력: 의존성 배열의 상태; 출력: void 또는 자원 정리 함수
 * 처리: 최초 완료 이력은 seen에 등록만 하고 새 완료 작업의 result_id를 선택
 * 부수효과/정리: 결과 ID·행·포커스·현재 화면 변경; 3단 화면은 유지
 */
()=>{if(loading)return;if(!jobsLoaded.current){state.jobs.forEach(/* [콜백 명세] App / forEach 콜백 / 입력: (j) / 출력: void / 처리: 본문에 명시된 비동기·조회·렌더 처리 / 영향: 참조 상태 변경; 본문 참조 */ j=>{if(j.status!=='running')seen.current.add(j.id);});jobsLoaded.current=true;return;}for(const j of state.jobs){if(j.status!=='running'&&!seen.current.has(j.id)){seen.current.add(j.id);if(j.result_id){setResultId(j.result_id);setRowIndex(0);setFocusedMail('');setScreen(/* [콜백 명세] App / setScreen 콜백 / 입력: (s) / 출력: 다음 상태값 / 처리: 직전 상태를 사용해 불변 갱신값 계산 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ s=>s==='mails'?'mails':'results');} }}},[state.jobs,loading]);
 useEffect(/**
 * [효과 콜백 명세] App.effect4 서버 저장 위치 반영
 * 입력: 의존성 배열의 상태; 출력: void 또는 자원 정리 함수
 * 처리: document_root 변경을 폴더 입력 상태에 동기화
 * 부수효과/정리: folder 상태 변경
 */
()=>{if(state.document_root)setFolder(state.document_root);},[state.document_root]);
 useEffect(/**
 * [효과 콜백 명세] App.effect5 결과 전환 시 보정 초기화
 * 입력: 의존성 배열의 상태; 출력: void 또는 자원 정리 함수
 * 처리: resultId 또는 rowIndex 변경 시 보정창과 입력값 초기화
 * 부수효과/정리: editing=false 및 edits 비우기
 */
()=>{setEditing(false);setEdits({});},[resultId,rowIndex]);
 const act=/**
 * [기능명세] act
 * 목적: 작업 요청 공통 실행
 * 입력: path, body 기본 {}, method 기본 POST
 * 출력: Promise<void>
 * 처리/실패: 요청 중 설정→API 호출→reload; 오류를 화면에 표시
 * 부수효과: 작업 API 호출·안내 및 요청 상태 변경
 */
async(path:string,body:unknown={},method='POST')=>{setRequesting(true);setError('');setNotice('');try{await api(path,body,method);await reload();}catch(e){setError((e as Error).message);}finally{setRequesting(false);}};
 const toggle=/**
 * [기능명세] toggle
 * 목적: 메일 한 건 선택 토글
 * 입력: m: PDF 첨부가 있는 Mail
 * 출력: void
 * 처리/실패: 기존 선택 제거 또는 첫 PDF와 단일 후보 계약으로 Pair 생성
 * 부수효과: selected 갱신; PDF가 없는 항목은 호출자가 제외
 */
(m:Mail)=>setSelected(/* [콜백 명세] toggle / setSelected 콜백 / 입력: (s) / 출력: 다음 상태값 / 처리: 직전 상태를 사용해 불변 갱신값 계산 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ s=>{const n={...s};if(n[m.id])delete n[m.id];else n[m.id]={mail_id:m.id,contract_id:m.candidates.length===1?m.candidates[0]:'',invoice_url:m.pdfs[0].url};return n;});
 const pairs=Object.values(selected),selectedMails=state.mails.filter(/* [콜백 명세] App / filter 콜백 / 입력: (m) / 출력: 조건 판정값 / 처리: 현재 항목의 포함 여부 판정 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ m=>!!selected[m.id]);
 const connected=pairs.length>0&&pairs.every(/* [콜백 명세] App / every 콜백 / 입력: (p) / 출력: 조건 판정값 / 처리: 준비 조건·선택 조건·작업 상태 검사 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ p=>p.contract_id);
 const ready=connected&&pairs.every(/* [콜백 명세] App / every 콜백 / 입력: (p) / 출력: 조건 판정값 / 처리: 준비 조건·선택 조건·작업 상태 검사 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ p=>{const m=state.mails.find(/* [콜백 명세] App / find 콜백 / 입력: (x) / 출력: 조건 판정값 / 처리: 현재 항목이 조회 대상인지 판정 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ x=>x.id===p.mail_id);const c=state.contracts.find(/* [콜백 명세] App / find 콜백 / 입력: (x) / 출력: 조건 판정값 / 처리: 현재 항목이 조회 대상인지 판정 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ x=>x.id===p.contract_id);return m?.documents[p.invoice_url]?.available&&c?.document?.available;});
 const filtered=state.mails.filter(/* [콜백 명세] App / filter 콜백 / 입력: (m) / 출력: 조건 판정값 / 처리: 현재 항목의 포함 여부 판정 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ m=>(m.sender+' '+m.subject).toLowerCase().includes(q.toLowerCase())&&(!from||m.received.slice(0,10)>=from)&&(!to||m.received.slice(0,10)<=to));
 const pdfCount=state.mails.filter(/* [콜백 명세] App / filter 콜백 / 입력: (m) / 출력: 조건 판정값 / 처리: 현재 항목의 포함 여부 판정 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ m=>m.pdfs.length).length;
 const current=results.find(/* [콜백 명세] App / find 콜백 / 입력: (r) / 출력: 조건 판정값 / 처리: 현재 항목이 조회 대상인지 판정 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ r=>r.id===resultId)||results[0];const currentRow=screen==='mails'&&focusedMail?current?.rows.find(/* [콜백 명세] App / find 콜백 / 입력: (r) / 출력: 조건 판정값 / 처리: 현재 항목이 조회 대상인지 판정 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ r=>r.mail_id===focusedMail):current?.rows[rowIndex]||current?.rows[0];
 const nav=[{id:'mails',label:'메일 · 문서 선택',icon:Inbox},{id:'results',label:'비교 결과',icon:FileCheck2},{id:'history',label:'작업 이력',icon:History},{id:'settings',label:'설정',icon:Settings}];
 const latestJob=state.jobs[0];
 const allFiltered=filtered.filter(/* [콜백 명세] App / filter 콜백 / 입력: (m) / 출력: 조건 판정값 / 처리: 현재 항목의 포함 여부 판정 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ m=>m.pdfs.length);
 const setAll=/**
 * [기능명세] setAll
 * 목적: 필터 결과 전체 선택·해제
 * 입력: 인자 없음; allFiltered 참조
 * 출력: void
 * 처리/실패: 전부 선택됐으면 해제, 아니면 없는 선택만 추가; 첫 PDF·단일 후보 사용
 * 부수효과: selected 갱신; 필터 밖 선택은 유지
 */
()=>{const all=allFiltered.every(/* [콜백 명세] setAll / every 콜백 / 입력: (m) / 출력: 조건 판정값 / 처리: 준비 조건·선택 조건·작업 상태 검사 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ m=>selected[m.id]);setSelected(/* [콜백 명세] setAll / setSelected 콜백 / 입력: (s) / 출력: 다음 상태값 / 처리: 직전 상태를 사용해 불변 갱신값 계산 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ s=>{const n={...s};for(const m of allFiltered){if(all)delete n[m.id];else n[m.id]??={mail_id:m.id,contract_id:m.candidates.length===1?m.candidates[0]:'',invoice_url:m.pdfs[0].url};}return n;});};
 const saveFolder=/**
 * [기능명세] saveFolder
 * 목적: 저장 위치 적용
 * 입력: 입력 상태 folder
 * 출력: Promise<void>
 * 처리/실패: 이동 중 잠금→settings PUT→상태 재조회→완료 안내; 실패 오류 표시
 * 부수효과: 등록 PDF·경로의 실제 이동은 서버, 화면은 moving·folder·안내 변경
 */
async()=>{setMoving(true);setError('');setNotice('');try{await api('settings',{document_root:folder},'PUT');await reload();setNotice('저장 위치를 변경하고 기존 PDF도 함께 옮겼습니다. 이전 비교 이력에서도 원문을 볼 수 있습니다.');}catch(e){setError((e as Error).message);}finally{setMoving(false);}};
 const pickFolder=/**
 * [기능명세] pickFolder
 * 목적: Windows 폴더 선택 요청
 * 입력: 인자 없음
 * 출력: Promise<void>
 * 처리/실패: pick-folder 호출 후 취소가 아니면 folder 입력값 변경
 * 부수효과: 네이티브 대화상자 요청·선택 중 상태 변경; 자동 적용 없음
 */
async()=>{setPicking(true);setError('');try{const r=await api<{folder:string|null}>('settings/pick-folder',{});if(r.folder)setFolder(r.folder);}catch(e){setError((e as Error).message);}finally{setPicking(false);}};
 const openEdits=/**
 * [기능명세] openEdits
 * 목적: 현재 계산서 보정 폼 열기
 * 입력: 현재 행의 effective_invoice 참조
 * 출력: void
 * 처리/실패: 허용 필드를 문자열 입력값으로 변환; 값이 없으면 빈 문자열
 * 부수효과: edits·editing 상태 변경; 원본 PDF 수정 없음
 */
()=>{const d=currentRow?.effective_invoice?.fields;if(!d)return;setEdits(Object.fromEntries(['partner','biz','supply','vat','total','month','percent','installment'].map(/* [콜백 명세] openEdits / map 콜백 / 입력: (k) / 출력: 항목별 파생값 또는 JSX / 처리: 현재 항목을 표시 요소 또는 데이터 값으로 변환 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ k=>[k,d[k]?.value===undefined?'':String(d[k].value)])));setEditing(true);};
 const correct=/**
 * [기능명세] correct
 * 목적: 변경된 추출값만 보정 재비교 요청
 * 입력: edits/current/currentRow 참조
 * 출력: Promise<void>
 * 처리/실패: 기존값과 비교→숫자 필드 Number 변환→변경 없으면 닫기→correct API
 * 부수효과: 새 비교 작업 요청·폼 닫기; 서버가 범위 검증 및 새 이력 저장
 */
async()=>{if(!current||!currentRow)return;const changed:Record<string,unknown>={};for(const [k,v] of Object.entries(edits)){const old=currentRow.effective_invoice.fields[k]?.value;if(v!==''&&v!==String(old??''))changed[k]=['supply','vat','total','percent','installment'].includes(k)?Number(v):v;}if(!Object.keys(changed).length){setEditing(false);return;}await act('results/'+current.id+'/correct',{overrides:{[currentRow.invoice.id]:changed}});setEditing(false);};
 const resultView=(current&&currentRow?<><div className="result-summary"><div><span className="eyebrow">REVIEW COMPLETE</span><h2>{current.rows.length}건의 비교 결과</h2><p>{stamp(current.created)} {current.parent?'· 수동 보정 후 재비교':''}</p></div><div className="result-counts">{['일치','불일치','확인 필요','처리 실패'].map(/* [콜백 명세] App / map 콜백 / 입력: (s) / 출력: 항목별 파생값 또는 JSX / 처리: 현재 항목을 표시 요소 또는 데이터 값으로 변환 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ s=><div key={s}><Badge status={s}/><strong>{current.rows.filter(/* [콜백 명세] App / filter 콜백 / 입력: (r) / 출력: 조건 판정값 / 처리: 현재 항목의 포함 여부 판정 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ r=>r.status===s).length}</strong></div>)}</div><a className="secondary" href={'/api/results/'+current.id+'/csv'}><Download size={16}/>CSV 저장</a></div><div className="review-layout"><section className="panel result-list"><div className="panel-heading"><h2>문서 목록</h2></div>{current.rows.map(/* [콜백 명세] App / map 콜백 / 입력: (r, i) / 출력: 항목별 파생값 또는 JSX / 처리: 현재 항목을 표시 요소 또는 데이터 값으로 변환 / 영향: 상태 갱신 setRowIndex, setFocusedMail */ (r,i)=><button className={i===rowIndex?'active':''} key={r.mail_id} onClick={/* [콜백 명세] App / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 상태 갱신 setRowIndex, setFocusedMail */ ()=>{setRowIndex(i);setFocusedMail(r.mail_id);}}><strong>{r.partner}</strong><small>{r.subject}</small><Badge status={r.status}/></button>)}</section><section className="panel review"><div className="panel-heading"><div><h2>{currentRow.partner}</h2><p>{currentRow.contract_id} · {currentRow.subject}</p></div><Badge status={currentRow.status}/></div><div className="review-actions"><button className="secondary" onClick={/* [콜백 명세] App / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 상태 갱신 setPreview */ ()=>setPreview({invoice:currentRow.invoice,contract:currentRow.contract})}><Files size={16}/>원문 나란히 보기</button><button className="text-btn" onClick={openEdits}>계산서 추출값 보정</button></div>{currentRow.error&&<div className="alert error">{currentRow.error}</div>}{currentRow.checks.map(/* [콜백 명세] App / map 콜백 / 입력: (c) / 출력: 항목별 파생값 또는 JSX / 처리: 현재 항목을 표시 요소 또는 데이터 값으로 변환 / 영향: 상태 갱신 setPreview */ c=><div className="check-item" key={c.key}><div className="check-title"><h3>{c.label}</h3><Badge status={c.status}/></div><div className="check-values"><div><small>세금계산서 / 실제값</small><strong>{display(c.actual)}</strong></div><ArrowRight size={16}/><div><small>계약서 / 비교 기준</small><strong>{display(c.expected)}</strong></div></div>{typeof c.difference === 'number' && c.difference !== 0 && <p className="difference">차이 {c.difference > 0 ? '+' : ''}{c.difference.toLocaleString('ko-KR')}원 (계산서 − 기준)</p>}{c.note&&<p className="check-note">{c.note}</p>}<details><summary>원문 근거 확인</summary><div className="evidence">{[['계산서',c.invoice_source],['계약서',c.contract_source]].map(/* [콜백 명세] App / map 콜백 / 입력: ([label,source]) / 출력: 항목별 파생값 또는 JSX / 처리: 현재 항목을 표시 요소 또는 데이터 값으로 변환 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ ([label,source])=>{const f=source as Field|undefined;return <blockquote key={String(label)}><small>{String(label)} {f?.page?`· ${f.page}페이지`:''} · {f?.method||'추출 근거 없음'}</small><p>{f?.quote||'관련 항목을 읽지 못했습니다.'}</p>{f?.previous&&<p>보정 전: {display(f.previous.value)} · {f.previous.quote}</p>}</blockquote>})}</div><button className="text-btn" onClick={/* [콜백 명세] App / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 상태 갱신 setPreview */ ()=>setPreview({invoice:currentRow.invoice,contract:currentRow.contract,invoicePage:c.invoice_source?.page||1,contractPage:c.contract_source?.page||1})}>해당 페이지 보기</button></details></div>)}</section></div></>:<div className="panel empty"><span className="empty-icon"><FileCheck2 size={30}/></span><h3>아직 비교한 문서가 없어요</h3><p>메일을 선택하고 PDF를 저장한 뒤 비교를 실행하세요.</p><button className="primary" onClick={/* [콜백 명세] App / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 상태 갱신 setScreen */ ()=>setScreen('mails')}>메일 선택하기<ArrowRight size={16}/></button></div>);
 if(stopped)return <div className="closed"><Leaf size={40}/><h1>새봄 문서비교를 종료했습니다.</h1><p>저장한 문서와 비교 이력은 유지됩니다. 다시 사용하려면 EXE를 실행해 주세요.</p></div>;
 return <div className="shell"><aside className="sidebar"><a className="brand" onClick={/* [콜백 명세] App / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 상태 갱신 setScreen */ ()=>setScreen('mails')}><span className="brand-icon"><Leaf size={23}/></span><div>새봄<span>문서비교</span></div></a><div className="workspace-label">DOCUMENT WORKSPACE</div><nav>{nav.map(/* [콜백 명세] App / map 콜백 / 입력: (n) / 출력: 항목별 파생값 또는 JSX / 처리: 현재 항목을 표시 요소 또는 데이터 값으로 변환 / 영향: 상태 갱신 setScreen */ n=><button key={n.id} className={screen===n.id?'active':''} onClick={/* [콜백 명세] App / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 상태 갱신 setScreen */ ()=>setScreen(n.id)}><n.icon size={18}/>{n.label}{n.id==='mails'&&state.mails.length>0&&<span>{state.mails.length}</span>}</button>)}</nav><div className="sidebar-bottom"><div className="privacy"><ShieldCheck size={18}/><div><strong>내 PC에서 안전하게</strong><p>AI 없이, 저장 문서는 오프라인 비교</p></div></div><button className="exit" disabled={busy} onClick={/* [콜백 명세] App / onClick 이벤트 / 입력: () / 출력: Promise; 본문의 return/예외를 따름 / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 상태 갱신 setStopped, setError */ async()=>{try{await api('shutdown',{});setStopped(true);}catch(e){setError((e as Error).message);}}}><Power size={16}/>프로그램 종료</button><small>SAEBOM COMPARE · v1.0</small></div></aside>
 <main><header className="topbar"><span>내 작업 공간 <ChevronRight size={13}/> {nav.find(/* [콜백 명세] App / find 콜백 / 입력: (n) / 출력: 조건 판정값 / 처리: 현재 항목이 조회 대상인지 판정 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ n=>n.id===screen)?.label}</span><div><span className="local-dot"/> 로컬 실행 중 <i/> <ShieldCheck size={14}/> AI 미사용</div></header><div className="content">
 <div className="page-heading"><div className="eyebrow">SAEBOM DOCUMENT REVIEW</div><div className="heading-line"><div><h1>{screen==='mails'?'문서 비교를 시작하세요':screen==='results'?'비교 결과':screen==='history'?'작업 이력':'앱 설정'}</h1><p>{screen==='mails'?'받은 세금계산서를 선택하고, 계약서와 나란히 확인하세요.':screen==='results'?'금액부터 지급 조건까지, 원문에 근거해 확인합니다.':screen==='history'?'이전에 비교한 문서와 결과를 다시 확인하세요.':'원본 PDF 저장 위치와 사이트 접속을 관리합니다.'}</p></div>{screen==='mails'&&<button className="primary" disabled={busy} onClick={/* [콜백 명세] App / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ ()=>void act('sync')}><RefreshCw size={16} className={busy?'spin':''}/>목록 새로고침</button>}</div></div>
 {error&&<div role="alert" className="alert error"><XCircle size={17}/>{error}<button onClick={/* [콜백 명세] App / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 상태 갱신 setError */ ()=>setError('')} aria-label="오류 닫기"><X size={16}/></button></div>}{notice&&<div role="status" className="alert success"><CheckCircle2 size={17}/>{notice}</div>}
 {latestJob&&<div className={'job '+(latestJob.status==='failed'?'job-failed':'')}><div>{latestJob.status==='running'?<LoaderCircle size={17} className="spin"/>:latestJob.status==='failed'?<XCircle size={17}/>:<CheckCircle2 size={17}/>}<b>{latestJob.kind}</b><span>{latestJob.message}</span><small>{latestJob.done} / {latestJob.total}</small></div>{latestJob.status==='running'&&<progress value={latestJob.done} max={latestJob.total}/ >}{latestJob.errors?.length>0&&<details><summary>실패 파일 {latestJob.errors.length}건 보기</summary>{latestJob.errors.map(/* [콜백 명세] App / map 콜백 / 입력: (e, i) / 출력: 항목별 파생값 또는 JSX / 처리: 현재 항목을 표시 요소 또는 데이터 값으로 변환 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ (e,i)=><p key={i}>{e}</p>)}</details>}</div>}

 {screen==='mails'&&<>
 <div className="workspace-info"><span>PDF 메일 <b>{pdfCount}건</b> · 계약 <b>{state.contracts.length}건</b></span><span>최근 동기화 {stamp(state.synced)}</span><button className="text-btn" onClick={/* [콜백 명세] App / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 상태 갱신 setWidths */ ()=>setWidths([27,32])}>단 너비 초기화</button></div>
 <div className="compare-workspace" ref={workspaceRef} style={{'--first':widths[0]+'fr','--second':widths[1]+'fr','--third':(100-widths[0]-widths[1])+'fr'} as React.CSSProperties}>
 <section className="panel company-panel"><div className="panel-heading"><div><h2><b className="stage">1</b>비교할 기업 <span>{allFiltered.length}</span></h2><p>기업을 누르면 PDF와 추천 계약이 선택됩니다.</p></div></div>
 <div className="filters"><div className="search"><Search size={16}/><input aria-label="업체 또는 메일 제목 검색" placeholder="기업명 또는 메일 검색" value={q} onChange={/* [콜백 명세] App / onChange 이벤트 / 입력: (e) / 출력: 본문 return 값 또는 void / 처리: 입력·선택 값을 해당 화면 상태에 반영 / 영향: 상태 갱신 setQ */ e=>setQ(e.target.value)}/></div><label>수신일 <input aria-label="수신일 시작" type="date" value={from} onChange={/* [콜백 명세] App / onChange 이벤트 / 입력: (e) / 출력: 본문 return 값 또는 void / 처리: 입력·선택 값을 해당 화면 상태에 반영 / 영향: 상태 갱신 setFrom */ e=>setFrom(e.target.value)}/><input aria-label="수신일 종료" type="date" value={to} onChange={/* [콜백 명세] App / onChange 이벤트 / 입력: (e) / 출력: 본문 return 값 또는 void / 처리: 입력·선택 값을 해당 화면 상태에 반영 / 영향: 상태 갱신 setTo */ e=>setTo(e.target.value)}/></label>{(q||from||to)&&<button className="text-btn" onClick={/* [콜백 명세] App / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 상태 갱신 setQ, setFrom, setTo */ ()=>{setQ('');setFrom('');setTo('');}}>검색 초기화</button>}</div>
 <div className="list-actions"><label><input type="checkbox" aria-label="표시된 PDF 메일 전체 선택" disabled={!allFiltered.length||busy} checked={allFiltered.length>0&&allFiltered.every(/* [콜백 명세] App / every 콜백 / 입력: (m) / 출력: 조건 판정값 / 처리: 준비 조건·선택 조건·작업 상태 검사 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ m=>!!selected[m.id])} onChange={setAll}/> 전체 선택</label><button className="text-btn" disabled={busy} onClick={/* [콜백 명세] App / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 상태 갱신 setSelected */ ()=>setSelected({})}>선택 해제</button></div>
 <div className="company-list">{allFiltered.map(/* [콜백 명세] App / map 콜백 / 입력: (m) / 출력: 항목별 파생값 또는 JSX / 처리: 현재 항목을 표시 요소 또는 데이터 값으로 변환 / 영향: 상태 갱신 setFocusedMail, setResultId, setRowIndex */ m=>{const c=state.contracts.find(/* [콜백 명세] App / find 콜백 / 입력: (c) / 출력: 조건 판정값 / 처리: 현재 항목이 조회 대상인지 판정 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ c=>c.id===m.candidates[0]);const saved=m.pdfs.some(/* [콜백 명세] App / some 콜백 / 입력: (a) / 출력: 조건 판정값 / 처리: 준비 조건·선택 조건·작업 상태 검사 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ a=>m.documents[a.url]?.available);return <button className={'company-card '+(selected[m.id]?'selected':'')} key={m.id} disabled={busy} aria-pressed={!!selected[m.id]} onClick={/* [콜백 명세] App / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 상태 갱신 setFocusedMail, setResultId, setRowIndex */ ()=>{toggle(m);setFocusedMail(m.id);const r=results.find(/* [콜백 명세] App / find 콜백 / 입력: (r) / 출력: 조건 판정값 / 처리: 현재 항목이 조회 대상인지 판정 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ r=>r.rows.some(/* [콜백 명세] App / some 콜백 / 입력: (x) / 출력: 조건 판정값 / 처리: 준비 조건·선택 조건·작업 상태 검사 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ x=>x.mail_id===m.id));if(r){setResultId(r.id);setRowIndex(r.rows.findIndex(/* [콜백 명세] App / findIndex 콜백 / 입력: (x) / 출력: 본문 return 값 또는 void / 처리: 본문에 명시된 비동기·조회·렌더 처리 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ x=>x.mail_id===m.id));}}}><span className="company-title"><strong>{m.sender}</strong>{selected[m.id]?<CheckCircle2 size={18}/>:<span className="select-circle"/>}</span><span className="company-subject">{m.subject}</span><span className="company-meta">{m.received.slice(0,10)} · PDF {m.pdfs.length}개 · {saved?'저장됨':'저장 필요'}</span><span className="contract-hint">{m.candidates.length===1?'추천 계약 · '+c?.title:m.candidates.length>1?'계약 후보 여러 건 · 직접 선택':'연결할 계약 직접 선택'}</span></button>})}</div>
 {!allFiltered.length&&<div className="empty"><Inbox size={28}/><h3>{loading?'목록 불러오는 중':state.synced?'검색 결과 없음':'목록을 가져와 주세요'}</h3><p>목록 새로고침으로 PDF 메일을 불러옵니다.</p></div>}
 <div className="panel-footer">PDF 없는 메일 {state.mails.length-pdfCount}건 제외</div></section>
 {divider(0)}
 <section className="panel connections"><div className="panel-heading"><div><h2><b className="stage">2</b>문서 연결 · 비교 <span>{pairs.length}</span></h2><p>연결된 계약을 확인한 뒤 비교하세요.</p></div></div>
 {selectedMails.length?selectedMails.map(/* [콜백 명세] App / map 콜백 / 입력: (m) / 출력: 항목별 파생값 또는 JSX / 처리: 현재 항목을 표시 요소 또는 데이터 값으로 변환 / 영향: 상태 갱신 setSelected */ m=>{const pair=selected[m.id];const c=state.contracts.find(/* [콜백 명세] App / find 콜백 / 입력: (c) / 출력: 조건 판정값 / 처리: 현재 항목이 조회 대상인지 판정 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ c=>c.id===pair.contract_id);return <div className="connection" key={m.id}><div><strong>{m.sender}</strong><small>{m.subject}</small><label className="field-label">세금계산서 PDF<select aria-label={m.sender+' 첨부 PDF 선택'} value={pair.invoice_url} disabled={busy} onChange={/* [콜백 명세] App / onChange 이벤트 / 입력: (e) / 출력: 본문 return 값 또는 void / 처리: 입력·선택 값을 해당 화면 상태에 반영 / 영향: 상태 갱신 setSelected */ e=>setSelected(/* [콜백 명세] App / setSelected 콜백 / 입력: (s) / 출력: 다음 상태값 / 처리: 직전 상태를 사용해 불변 갱신값 계산 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ s=>({...s,[m.id]:{...s[m.id],invoice_url:e.target.value}}))}>{m.pdfs.map(/* [콜백 명세] App / map 콜백 / 입력: (a) / 출력: 항목별 파생값 또는 JSX / 처리: 현재 항목을 표시 요소 또는 데이터 값으로 변환 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ a=><option key={a.url} value={a.url}>{a.name}</option>)}</select></label></div><ArrowRight size={17}/><div><label className="field-label">비교할 계약서<select aria-label={m.sender+' 연결 계약'} value={pair.contract_id} disabled={busy} onChange={/* [콜백 명세] App / onChange 이벤트 / 입력: (e) / 출력: 본문 return 값 또는 void / 처리: 입력·선택 값을 해당 화면 상태에 반영 / 영향: 상태 갱신 setSelected */ e=>setSelected(/* [콜백 명세] App / setSelected 콜백 / 입력: (s) / 출력: 다음 상태값 / 처리: 직전 상태를 사용해 불변 갱신값 계산 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ s=>({...s,[m.id]:{...s[m.id],contract_id:e.target.value}}))}><option value="">계약서를 선택하세요</option>{['지출','수입'].map(/* [콜백 명세] App / map 콜백 / 입력: (kind) / 출력: 항목별 파생값 또는 JSX / 처리: 현재 항목을 표시 요소 또는 데이터 값으로 변환 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ kind=><optgroup key={kind} label={kind+' 계약'}>{state.contracts.filter(/* [콜백 명세] App / filter 콜백 / 입력: (c) / 출력: 조건 판정값 / 처리: 현재 항목의 포함 여부 판정 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ c=>c.kind===kind&&c.file).map(/* [콜백 명세] App / map 콜백 / 입력: (c) / 출력: 항목별 파생값 또는 JSX / 처리: 현재 항목을 표시 요소 또는 데이터 값으로 변환 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ c=><option key={c.id} value={c.id}>{c.partner} · {c.title} · {c.id}</option>)}</optgroup>)}</select></label><small>{c?`${c.period} · ${c.amount_text}`:m.candidates.length>1?'후보가 여러 건입니다. 직접 선택해 주세요.':'연결할 계약을 선택해 주세요.'}</small></div></div>}) : <div className="empty"><FileCheck2 size={28}/><h3>기업을 선택해 주세요</h3><p>왼쪽 목록에서 한 건 또는 여러 건을 선택할 수 있습니다.</p></div>}
 <div className="action-bar"><span><b>{pairs.length}건</b> 선택됨 {ready?'· 비교 준비 완료':connected?'· PDF를 먼저 저장해 주세요':'· 기업과 계약을 선택해 주세요'}</span><div><button className="secondary" disabled={!connected||busy} onClick={/* [콜백 명세] App / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ ()=>void act('download',{pairs})}><Download size={16}/>선택 문서 다운로드</button><button className="primary" disabled={!ready||busy} onClick={/* [콜백 명세] App / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ ()=>void act('compare',{pairs})}><FileCheck2 size={16}/>비교 실행</button></div></div></section>
 {divider(1)}
 <section className="workspace-results"><div className="panel-heading"><div><h2><b className="stage">3</b>비교 결과 · 원문</h2><p>항목별 차이와 PDF 근거를 확인하세요.</p></div></div>{resultView}</section>
 </div><p className="workspace-help">단 사이의 경계선을 드래그하면 좌우 너비를 조정할 수 있습니다. 화면이 좁으면 세로로 배치됩니다.</p>
 </>}

 {screen==='results'&&resultView}

 {screen==='history'&&<section className="panel"><div className="panel-heading"><h2>저장된 비교 작업 <span>{results.length}</span></h2></div>{results.length?results.map(/* [콜백 명세] App / map 콜백 / 입력: (r) / 출력: 항목별 파생값 또는 JSX / 처리: 현재 항목을 표시 요소 또는 데이터 값으로 변환 / 영향: 상태 갱신 setResultId, setRowIndex, setScreen */ r=><button key={r.id} className="history-row" onClick={/* [콜백 명세] App / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 상태 갱신 setResultId, setRowIndex, setScreen */ ()=>{setResultId(r.id);setRowIndex(0);setScreen('results');}}><span className="history-icon"><FileCheck2 size={22}/></span><div><strong>{r.rows.length}건 비교 {r.parent&&'· 수동 보정'}</strong><small>{stamp(r.created)} · {r.rows.map(/* [콜백 명세] App / map 콜백 / 입력: (x) / 출력: 항목별 파생값 또는 JSX / 처리: 현재 항목을 표시 요소 또는 데이터 값으로 변환 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ x=>x.partner).slice(0,3).join(', ')}{r.rows.length>3?' 외':''}</small></div><span>{r.rows.filter(/* [콜백 명세] App / filter 콜백 / 입력: (x) / 출력: 조건 판정값 / 처리: 현재 항목의 포함 여부 판정 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ x=>x.status==='불일치').length}건 불일치</span><ChevronRight size={18}/></button>):<div className="empty"><History size={30}/><h3>저장된 작업 이력이 없습니다.</h3></div>}</section>}

 {screen==='settings'&&<div className="settings-grid"><section className="panel"><div className="panel-heading"><div><h2><FolderOpen size={19}/>원본 PDF 저장 위치</h2><p>내 PC의 원하는 폴더에 문서 종류별로 보관합니다.</p></div></div><div className="settings-body"><label className="field-label" htmlFor="folder">저장할 기본 폴더</label><div className="folder-input"><input id="folder" disabled={busy} value={folder} onChange={/* [콜백 명세] App / onChange 이벤트 / 입력: (e) / 출력: 본문 return 값 또는 void / 처리: 입력·선택 값을 해당 화면 상태에 반영 / 영향: 상태 갱신 setFolder */ e=>setFolder(e.target.value)} placeholder="예: D:\새봄문서"/><button className="secondary" disabled={picking||busy} onClick={/* [콜백 명세] App / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ ()=>void pickFolder()}><FolderOpen size={16}/>{picking?'선택 중…':'폴더 선택'}</button></div><div className="folder-tree"><FolderOpen size={17}/><strong>{folder||'지정 폴더'}</strong><div>└ 세금계산서 <span>세금계산서 원본 PDF</span></div><div>└ 계약서 <span>계약서 원본 PDF</span></div></div><p className="help">저장 위치를 적용하면 기존 세금계산서·계약서 PDF도 새 폴더로 함께 이동합니다. 이전 비교 이력의 원문 연결도 유지됩니다. 파일 이동이 끝날 때까지 기다려 주세요.</p><button className="primary" disabled={busy||!folder||folder===state.document_root} onClick={/* [콜백 명세] App / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ ()=>void saveFolder()}>{moving?<LoaderCircle size={16} className="spin"/>:<Check size={16}/>}저장 위치 적용</button></div></section><section className="panel"><div className="panel-heading"><h2>사이트 연결</h2></div><div className="settings-body"><div className="site-address"><Wifi size={18}/><div><strong>새봄 그룹웨어</strong><p>https://sbgw.vercel.app/</p></div></div><p className="help">앱 전용 브라우저로 접속합니다. 로그인이 필요한 경우 열린 창에서 직접 로그인한 후 목록을 새로고침하세요.</p><button className="secondary" disabled={busy} onClick={/* [콜백 명세] App / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ ()=>void act('browser')}><FolderOpen size={16}/>전용 브라우저 열기</button></div></section><section className="panel"><div className="panel-heading"><h2>로컬 데이터와 처리 방식</h2></div><div className="settings-body"><div className="setting-note"><ShieldCheck size={23}/><div><strong>AI 없이 규칙으로 비교</strong><p>텍스트가 포함된 PDF를 읽고 금액·기간·지급조건을 대조합니다. 이미지 PDF와 모호한 조건은 확인 필요로 표시합니다.</p></div></div><label className="field-label">설정·목록·이력 저장 위치</label><code>{state.data_dir}</code><p className="help">인터넷은 목록 동기화와 다운로드에만 사용합니다. 저장된 PDF의 비교·원문 보기·CSV 저장은 오프라인에서 가능합니다.</p></div></section></div>}
 <footer className="footer">새봄 문서비교 <span>문서가 머무는 곳, 내 PC</span></footer></div></main>

 {preview&&<div className="modal-backdrop"><section className="modal pdf-modal"><header><div><h2>원문 나란히 보기</h2><p>왼쪽 세금계산서 · 오른쪽 계약서</p></div><button className="icon-btn" aria-label="원문 보기 닫기" onClick={/* [콜백 명세] App / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 상태 갱신 setPreview */ ()=>setPreview(null)}><X size={22}/></button></header><div className="pdf-pair"><Pdf doc={preview.invoice} initialPage={preview.invoicePage}/><Pdf doc={preview.contract} initialPage={preview.contractPage}/></div></section></div>}
 {editing&&currentRow&&<div className="modal-backdrop"><section className="modal edit-modal"><header><div><h2>계산서 추출값 보정</h2><p>수정값은 새 비교 이력으로 저장되며 원본 PDF는 변경되지 않습니다.</p></div><button className="icon-btn" aria-label="보정 닫기" onClick={/* [콜백 명세] App / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 상태 갱신 setEditing */ ()=>setEditing(false)}><X size={20}/></button></header><div className="edit-fields">{Object.entries({partner:'업체명',biz:'사업자등록번호',supply:'공급가액',vat:'부가세',total:'합계액',month:'청구 월 (YYYY-MM)',percent:'분할 비율 (%)',installment:'분할 차수'}).map(/* [콜백 명세] App / map 콜백 / 입력: ([k,label]) / 출력: 항목별 파생값 또는 JSX / 처리: 현재 항목을 표시 요소 또는 데이터 값으로 변환 / 영향: 상태 갱신 setEdits */ ([k,label])=><label key={k}>{label}<input value={edits[k]||''} onChange={/* [콜백 명세] App / onChange 이벤트 / 입력: (e) / 출력: 본문 return 값 또는 void / 처리: 입력·선택 값을 해당 화면 상태에 반영 / 영향: 상태 갱신 setEdits */ e=>setEdits(/* [콜백 명세] App / setEdits 콜백 / 입력: (s) / 출력: 다음 상태값 / 처리: 직전 상태를 사용해 불변 갱신값 계산 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ s=>({...s,[k]:e.target.value}))}/></label>)}</div><div className="modal-actions"><button className="secondary" onClick={/* [콜백 명세] App / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 상태 갱신 setEditing */ ()=>setEditing(false)}>취소</button><button className="primary" disabled={busy} onClick={/* [콜백 명세] App / onClick 이벤트 / 입력: () / 출력: 본문 return 값 또는 void / 처리: 해당 요소의 선택·작업·모달 동작 실행 / 영향: 명시된 조회·변환 수행; 별도 저장 동작은 본문에 있을 때만 실행 */ ()=>void correct()}>보정값으로 재비교</button></div></section></div>}
 </div>
}
createRoot(document.getElementById('root')!).render(<AccessGate/>);
