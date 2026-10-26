# [파일 기능명세]
# 원본 PDF 파일 이름·보관 폴더 규칙. 다운로드 저장(service)과 저장 위치 이동(store)이 같은 규칙을 쓰도록 한곳에 둔다.
# 거래명세서 엑셀 저장 폴더 이름(STATEMENT_FOLDER)과 파일 이름 정리(safe_name)도 statement·service·api가 함께 쓴다.
# 유지보수: 규칙을 바꾸면 기존 저장 파일 경로와 호환되는지 확인하고 이 명세를 함께 갱신한다.

import re

# 문서 종류(kind)별 보관 하위 폴더 이름.
KIND_FOLDERS = {"invoice": "세금계산서", "contract": "계약서"}
# 계약서로 만든 거래명세서 엑셀을 저장하는 하위 폴더 이름(PDF 보관 폴더/거래명세서/).
# 저장 위치 변경(store.set_document_root)은 이 폴더를 옮기지 않는다.
STATEMENT_FOLDER = "거래명세서"


# [기능명세] safe_name
# 목적: 사이트가 준 첨부 이름을 Windows에서 쓸 수 있는 파일 이름으로 정리
# 입력: (name: str)
# 출력: 금지 문자를 _로 바꾸고 160자로 자른 뒤 끝의 점·공백을 제거한 문자열
# 처리: <>:"/\|?* 와 제어문자(0x00~0x1f)를 _로 치환
# 예외/실패: 문자열 입력이 전제; 빈 결과가 나올 수 있으며 호출자가 해시 접두어를 붙여 사용
# 부수효과: 없음
def safe_name(name):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)[:160].rstrip(". ")
