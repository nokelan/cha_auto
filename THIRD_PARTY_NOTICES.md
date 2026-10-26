# 외부 구성요소

이 프로그램은 외부 AI 서비스나 모델을 사용하지 않습니다.

- React, Vite, TypeScript: MIT
- Lucide: ISC
- PDF.js: Apache-2.0
- FastAPI, pdfplumber, pdfminer.six: MIT
- openpyxl, et-xmlfile: MIT (거래명세서 엑셀 생성)
- Uvicorn, SQLite, Python: 각 BSD 계열 / public domain / PSF 라이선스
- Playwright: Apache-2.0. 포함된 Chromium 및 관련 구성요소에는 별도 오픈소스 라이선스가 적용됩니다.
- PyInstaller: GPL 및 배포물에 대한 부트로더 예외

2026-10-26 설치 패키지 메타데이터와 번들 구성 기준의 추가 고지:

| 구성요소 | 라이선스·범위 |
| --- | --- |
| React DOM, Pydantic, pydantic-core, annotated-types, typing-inspection | MIT |
| Starlette, AnyIO, Click, h11 | Starlette·Click은 BSD-3-Clause, AnyIO·h11은 MIT |
| typing-extensions | PSF-2.0 |
| Pillow | MIT-CMU |
| pypdfium2 및 PDFium | BSD-3-Clause·Apache-2.0 및 별도 의존 구성요소 라이선스 |
| cryptography | Apache-2.0 또는 BSD-3-Clause |
| cffi, pycparser | 각각 MIT-0, BSD-3-Clause |
| charset-normalizer | MIT |
| certifi | MPL-2.0 |
| greenlet, pyee | 각각 MIT 및 PSF-2.0, MIT |
| HTTPX, httpcore, idna | BSD-3-Clause (개발·검증 도구) |
| pytest, pluggy, iniconfig | MIT (개발·검증 도구) |
| altgraph, pefile, pywin32-ctypes | 각각 MIT, MIT, BSD-3-Clause (빌드 도구) |
| packaging, Pygments | 각각 Apache-2.0 또는 BSD-2-Clause, BSD-2-Clause (개발·빌드 의존) |
| marked 18.1.1 | MIT (개발문서 화면의 Markdown 변환, 화면 번들에 포함) |
| DOMPurify 3.4.17 | MPL-2.0 또는 Apache-2.0 (개발문서 HTML 정화, 화면 번들에 포함) |
| Mermaid 11.12.0 | MIT (개발문서 다이어그램 렌더링, 화면 번들에 포함. katex·cytoscape·d3 등 하위 구성요소는 번들의 라이선스 원문이 기준) |

런타임 직접 의존성은 `requirements.txt`, 개발·검증·패키징 의존성은 `requirements-dev.txt`에 구분한다. 잠금 파일은 기존 버전을 유지한다. 실제 배포에 포함되는 전이 의존성과 Chromium·PDFium의 제3자 고지는 배포본의 라이선스 원문이 기준이다.

상세 라이선스는 배포본의 licenses 폴더 및 _internal/browser 내부 라이선스를 확인하세요.
