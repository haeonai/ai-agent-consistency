# Gottweis et al. (2026) 전체 논문 기반 정합성 평가 참조 프레임

## 1. 적용 범위

이 프레임은 Gottweis et al. (2026), *Accelerating scientific discovery with Co-Scientist*의 Figure 1뿐 아니라 Methods의 `Overview of Co-Scientist architecture`, `From research goal to research plan configuration`, `The specialized agents underpinning Co-Scientist`, `Tool use in Co-Scientist` 설명을 종합하여 정리한 평가 기준이다.

평가 목적은 논문 그림의 외형을 복제했는지 판단하는 것이 아니다. 개별 연구가 실제 설계에 맞는 역할 분담, 실행 흐름, 상태·근거 관리, 검증 및 결과 반환 구조를 갖추고 있고, 아키텍처 이미지와 기능 설명 문서가 서로 모순되지 않는지 점검하는 것이다.

## 2. 논문에서 확인되는 핵심 구조

1. **Human/Scientist-in-the-loop**: 연구자는 자연어로 연구목표, 제약, 선호, 초기 아이디어를 입력하고, 생성된 결과를 검토하거나 추가 피드백으로 시스템을 조정한다.
2. **Input-to-plan configuration**: 연구목표는 작업의 목적, 평가 기준, 제약, 선호를 담은 계획 또는 실행 설정으로 해석된다.
3. **Supervisor/Orchestration**: Supervisor는 계획을 바탕으로 task queue 또는 workflow를 만들고, 전문 Agent/worker에 작업과 자원을 배정하며, 전체 상태와 종료 조건을 판단한다.
4. **Specialized agents**: 생성, 검토, 순위화, 개선, 유사도 분석, 메타검토처럼 서로 다른 전문 역할을 수행하는 Agent가 협업한다. 개별 Agent는 독자적 역할과 논리를 갖는다.
5. **Execution framework**: 전문 Agent는 비동기 task execution framework 또는 명시적 workflow 안에서 실행된다. 실제 시스템이 순차형이라면 순차 workflow로 정직하게 표시할 수 있다.
6. **Memory/Context**: 장기 또는 세션 컨텍스트에는 Agent 상태, 진행 현황, 중간 결과, 지식·문서 등이 저장되고 이후 실행·피드백에 재활용된다.
7. **Tools and evidence**: 웹 검색, 데이터베이스, 사설 문서 저장소, API, 특화 AI 모델 등은 근거 확보, 검색, 계산, 실행을 위해 Agent에 연결될 수 있다.
8. **Feedback and validation**: 검토·랭킹·메타리뷰의 결과는 다음 생성·개선·재검토 단계로 전달되며, 반복 과정에서 품질을 높인다. 단발성 workflow라면 품질 검증·종료 조건을 명확히 해야 한다.
9. **Output**: 최종 결과는 연구자 또는 사용자에게 연구 개요, 가설, 제안, 보고서, 예측 등의 형태로 반환된다.

## 3. 도식 표기 원칙

- 연구자/사용자, AI 시스템, 외부 도구·DB의 **경계**를 구분한다.
- 주 정보·작업 흐름은 **방향 화살표와 전달 객체 라벨**로 표현한다.
- Supervisor의 **작업 배정·조정**과 Agent의 **데이터 전달**을 구분한다.
- 실제 반복 구조가 있으면 평가/검토 결과의 **발생지·재진입지·개선 목적**을 표시한다.
- Memory·Tool은 실제 사용할 때만 표시하며, 연결된 Agent와 사용 목적을 함께 적는다.
- Agent 박스에는 이름만 쓰지 않고 **이름 + 역할**을 함께 적는다.
- 출력에는 결과 형식과 수용자 또는 검토 주체를 표시한다.

## 4. 적용 유의사항

- Co-Scientist의 Agent 명칭, Agent 수, Gemini 사용, 비동기 worker 구현은 의무 사항이 아니다.
- 외부 Tool, persistent memory, feedback loop를 실제로 사용하지 않는다면 억지로 추가하지 않는다. 대신 미사용 또는 단발성 검증 방식을 설명해야 한다.
- 여러 아키텍처 이미지가 제출된 경우, 개요도·세부도·데이터 흐름도 사이의 명칭·방향·역할·입출력은 서로 일치해야 한다.
- 여러 MD 파일이 제출된 경우, 모든 Agent·Tool·Memory·Output의 이름 또는 ID가 이미지 파일과 대응되어야 한다.

## 5. 출처

Gottweis, J. et al. (2026). *Accelerating scientific discovery with Co-Scientist*. Nature, 655, 487–496. DOI: 10.1038/s41586-026-10644-y. Figure 1 및 Methods.
