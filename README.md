# AI 멀티에이전트 아키텍처 정합성 셀프체크

Gottweis et al. (2026) **「Accelerating scientific discovery with Co-Scientist」**의 전체 논문, 특히 Figure 1 및 Methods에서 확인되는 멀티에이전트 구조 원칙을 기준으로 교수님별 제출 패키지를 점검하는 Streamlit 도구임.

이 버전은 **여러 아키텍처 이미지/PDF와 여러 기능별 MD 파일을 한 번에 분석**하며, 평가 완료 후 파일 목록·점수·파일 간 불일치·내부 정합성·종합 의견을 포함한 결과 PDF를 다운로드할 수 있음.

## 1. 점검 기준

본 도구는 논문 그림의 외형 복제를 평가하지 않음. 아래 구조 원칙이 각 연구의 실제 설계와 다중 파일 설명에 일관되게 반영되었는지 점검함.

| 평가영역 | 배점 | 핵심 확인 내용 |
|---|---:|---|
| Actor · Input · System Boundary | 10 | 사용자·입력·시스템·외부자원 경계 |
| Orchestration · Execution | 20 | Supervisor/Workflow/Task 조정 |
| Specialized Agents | 20 | 역할 분리, Agent별 입력·출력 |
| Information · Control Flow | 15 | 방향성·전달 객체·호출 흐름 |
| Memory · Tools · Evidence | 10 | Memory·DB·RAG·API·검색의 목적과 연결 |
| Feedback · Validation | 10 | 검토·재작업·검증·종료 조건 |
| Output · Cross-file Consistency | 15 | 최종 산출물과 이미지·MD 간 일치 |
| **합계** | **100** | |

## 2. 업로드 파일

### 아키텍처 구성도 원본

여러 개의 `PNG`, `JPG/JPEG`, `PDF` 파일을 업로드할 수 있음.

- 개요도, 세부 Agent 구성도, 데이터 흐름도, Tool/API 연계도 등을 함께 업로드함.
- PDF는 페이지별로 이미지화하여 평가에 반영함.
- 여러 그림은 상호 보완 자료로 해석함. 동일한 Agent·Tool·Output의 이름 또는 흐름이 서로 충돌할 때만 파일 간 불일치로 지적함.

### 기능별 설명 파일

여러 개의 `MD`, `TXT` 파일을 업로드할 수 있음.

- 시스템 개요, Supervisor/Workflow, Agent별 기능, Memory·Tool, 검증·피드백 설명을 각각 분리해 업로드해도 됨.
- 각 파일의 이름·내용 경계가 유지된 채 AI 분석에 전달됨.
- 이미지 속 Agent/Tool/Memory/Output의 이름 또는 ID가 MD 파일과 대응되어야 함.

## 3. 실행 방법

### 의존성 설치

```bash
pip install -r requirements.txt
```

### API 키 설정

아래 두 방법 중 하나를 사용함.

1. 앱 사이드바의 `Anthropic API Key`에 입력함.
2. 프로젝트 루트에 `.streamlit/secrets.toml`을 만들고 아래와 같이 설정함.

```toml
ANTHROPIC_API_KEY = "sk-ant-..."
```

### 실행

```bash
streamlit run app.py
```

## 4. 결과 PDF 구성

평가 완료 뒤 내려받는 `architecture_consistency_report_교수님성함.pdf`에는 아래 내용이 포함됨.

1. 제출 교수·소속·평가일시·모델 정보
2. 전체 점수와 최종 판정
3. 실제 업로드한 다중 이미지/PDF·MD 파일 목록
4. 7개 평가영역별 점수 및 AI 판단 근거
5. 이미지·MD 파일 간 불일치 또는 보완 권고
6. 내부 정합성 체크 결과
7. 파일별 분석 메모
8. 종합 의견 및 논문 기반 평가 방법론

## 5. 운영 유의사항

- 실제 구현하지 않은 Agent, Memory, API, Feedback Loop를 점수 목적만으로 추가하지 않음.
- 외부 Tool이나 persistent memory를 사용하지 않는 경우, 해당 미사용 사실 또는 대체 검증·종료 방식을 MD에 설명함.
- 원본 아키텍처 구성도는 보존하고, 수정본에서만 도식 표기·용어·화살표·범례를 통일함.
- AI 자동 점수는 1차 보조 결과임. 최종 점수와 총평은 멘토 또는 담당자가 화면에서 검토·수정한 후 확정함.

## 6. 기준 논문

Gottweis, J. et al. (2026). *Accelerating scientific discovery with Co-Scientist*. Nature, 655, 487–496. DOI: [10.1038/s41586-026-10644-y](https://doi.org/10.1038/s41586-026-10644-y).

자세한 논문 기반 기준은 `co_scientist_full_paper_reference.md`를 참고함.
