# [파일 기능명세]
# 계약 관리번호(예: C-2026-040) 정렬 규칙. store.py와 services/*가 함께 쓰므로 서로 import하지 않도록 따로 둔 중립 모듈이다
# (이전에는 services/common.py에 있어 store.py가 지연 import로 순환 의존을 만들었다).
# 처리 흐름: 관리번호 문자열 → contract_sort_key → 오름차순 정렬 키(관리번호 큰 순으로 정렬하려면 그대로 sorted의 key로 사용).
# 유지보수: 관리번호 형식이 바뀌면 CONTRACT_ID와 contract_sort_key의 기능명세, 계약서 목록 정렬 테스트를 함께 갱신한다.

import re

# 계약 관리번호 형식. 예: C-2026-040 → (2026, 40)
CONTRACT_ID = re.compile(r"C-(\d+)-(\d+)")


# [기능명세] contract_sort_key
# 목적: 계약 관리번호를 '큰 순'으로 정렬하기 위한 오름차순 정렬 키 생성
# 입력: (id: 관리번호 문자열 또는 None)
# 출력: 튜플 — 형식이 맞으면 (0, -연도, -번호, ""), 맞지 않으면 (1, 0, 0, 문자열)
# 처리: 전체가 C-(\d+)-(\d+)에 맞으면 숫자로 비교(C-2026-040 > 039 > 015 > 003, 자리수와 무관),
#       맞지 않거나 None이면 형식 맞는 ID 뒤로 보내고 그들끼리는 문자열 오름차순
# 예외/실패: 없음(None·비문자열은 문자열로 바꿔 뒤로 보냄)
# 부수효과: 없음
# 사용: sorted(items, key=lambda x: contract_sort_key(x["id"]))가 관리번호 내림차순이 된다.
def contract_sort_key(id):
    m = CONTRACT_ID.fullmatch(id) if isinstance(id, str) else None
    if m:
        return (0, -int(m.group(1)), -int(m.group(2)), "")
    return (1, 0, 0, "" if id is None else str(id))
