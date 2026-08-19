# AI 멀티에이전트 아키텍처 정합성 셀프체크 (Streamlit 앱)

Gottweis et al. (2026), *Nature* "Co-Scientist" 구조를 준용한 산출물 사전 점검 도구입니다.
기존에 만든 세 파일(Word 가이드 / Excel 평가표 / Python 콘솔 스크립트)의 **평가 기준을 그대로 이어받아**,
교수님이 파일을 업로드하면 Claude API가 6개 항목을 1차 자동 채점하고, 화면에서 확인·수정 후 PDF로 받을 수 있습니다.

## 동작 방식
1. 교수님이 ① 아키텍처 구성도 원본(필수, 이미지/PDF 1개) ② 기능별 MD 파일(필수)을 업로드
2. "평가 시작" 클릭 → Claude(Vision)가 이미지+MD를 분석해 6개 항목 점수·근거, 내부 정합성 점검 결과, 총평을 1차 산출
3. 화면에서 항목별로 AI 채점 결과를 확인하고, 필요하면 슬라이더로 점수를 직접 수정해 확정
4. 총점·판정 자동 계산 (90↑ 적합 / 80↑ 조건부 적합 / 70↑ 수정 권고 / 그 미만 재검토 권고)
5. "PDF 다운로드" 버튼으로 결과 리포트 저장

> **AI 채점은 참고용 1차 안입니다.** 최종 점수는 반드시 화면에서 교수님/멘토가 확인 후 확정해 주세요.

## 설치

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## API 키 설정 (택 1)

**방법 A — secrets.toml (로컬 실행 권장)**
```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# secrets.toml을 열어 ANTHROPIC_API_KEY 값을 실제 키로 교체
```

**방법 B — 앱 실행 후 사이드바에 직접 입력**
키를 저장하지 않고 그때그때 입력해서 테스트할 때 사용하세요. (세션 종료 시 사라짐)

API 키는 https://console.anthropic.com 에서 발급받습니다. 호출마다 소액의 API 비용이 발생합니다
(이미지 2장 + 텍스트 기준 요청 1건당 대략 수백 원 이내 — 정확한 단가는 Anthropic 요금 페이지 참고).

## 실행

```bash
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 접속.

## 배포 (교수님들께 공유하려면)

- **Streamlit Community Cloud**(무료): GitHub 저장소에 이 폴더를 올린 뒤 streamlit.io에서 연결 → Settings의
  "Secrets"에 `ANTHROPIC_API_KEY`를 등록하면 됩니다. `.streamlit/secrets.toml`은 커밋하지 마세요(.gitignore 처리됨).
- 사내/교내 서버가 있다면 `streamlit run app.py --server.port 8501 --server.address 0.0.0.0` 로 상시 구동 후 방화벽/리버스프록시로 노출.

## 폴더 구성
```
streamlit_app/
├── app.py                          # 메인 앱
├── requirements.txt
├── fonts/
│   └── NanumGothic-Regular.ttf     # PDF 한글 출력용 임베드 폰트 (Regular/Bold)
│   └── NanumGothic-Bold.ttf
├── .streamlit/
│   └── secrets.toml.example        # API 키 템플릿 (복사해서 secrets.toml로 사용)
└── README.md
```

## 평가 기준 (기존 Word/Excel 문서와 동일하게 통일)

| 항목 | 배점 |
|---|---|
| ① Actor / User | 10 |
| ② Orchestrator | 20 |
| ③ Specialized Agents | 20 |
| ④ Agent 관계·정보 흐름 | 20 |
| ⑤ Feedback / Iteration | 15 |
| ⑥ Memory / Context / Output | 15 |

기준 문구는 기존 Excel "정합성 평가표" 시트를 기준으로 통일했고(Word 가이드와 표현이 다소 다르던 부분 정리),
Word 가이드 9장의 셀프체크 마지막 항목("Gottweis 핵심 개념을 준용하되 연구 고유 구조가 훼손되지 않았는가")은
"내부 정합성 점검" 목록 7번째 항목으로 포함했습니다.

## 알려진 제한사항
- 아키텍처 구성도가 PDF로 여러 페이지일 경우 전체 페이지를 이미지로 변환해 함께 전송합니다(페이지가 많으면 API 비용·처리 시간 증가).
- AI 채점은 이미지 해상도·글자 크기에 따라 인식 품질이 달라질 수 있습니다. 너무 작은 텍스트가 많은 구성도는 결과 신뢰도가 낮아질 수 있으니, 항목별 "AI 판단 근거"를 꼭 확인하세요.
- 현재 PDF 리포트는 텍스트 위주입니다(업로드한 구성도 이미지 자체는 리포트에 포함되지 않음). 필요하시면 이미지 삽입 기능을 추가해드릴 수 있습니다.
