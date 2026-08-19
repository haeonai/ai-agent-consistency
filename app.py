"""
AI 멀티에이전트 아키텍처 정합성 셀프체크 — Streamlit 앱
Reference: Gottweis et al. (2026), Nature, Co-Scientist

교수님이 ① 아키텍처 구성도 1식 ② 기능별 MD 파일을 업로드하면
Claude API(Vision)가 6개 평가항목을 1차 자동 채점하고, 교수님이 화면에서 직접 확인·수정한 뒤
결과를 PDF로 다운로드할 수 있는 도구입니다.

실행 방법: streamlit run app.py
API 키 설정: .streamlit/secrets.toml 에 ANTHROPIC_API_KEY = "sk-ant-..." 를 넣거나,
            앱 사이드바에 직접 입력합니다. (자세한 내용은 README.md 참고)
"""

import base64
import io
import json
import textwrap
from datetime import datetime

import os

import fitz  # PyMuPDF
import streamlit as st
from anthropic import Anthropic
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
FONT_REGULAR_PATH = os.path.join(FONTS_DIR, "NanumGothic-Regular.ttf")
FONT_BOLD_PATH = os.path.join(FONTS_DIR, "NanumGothic-Bold.ttf")
FONT_NAME = "NanumGothic"
FONT_NAME_BOLD = "NanumGothic-Bold"

# --------------------------------------------------------------------------
# 평가 기준 (Word 가이드 6장 / Excel "정합성 평가표" 시트와 동일하게 통일)
# --------------------------------------------------------------------------
CRITERIA = [
    {
        "id": "actor",
        "name": "① Actor / User",
        "max": 10,
        "question": "Human/User/Researcher와 시스템의 경계 및 상호작용이 명확한가?",
    },
    {
        "id": "orchestrator",
        "name": "② Orchestrator",
        "max": 20,
        "question": "Supervisor/Orchestrator/Coordinator 등 총괄 조정 역할이 명확한가?",
    },
    {
        "id": "agents",
        "name": "③ Specialized Agents",
        "max": 20,
        "question": "2개 이상의 전문 Agent가 역할별로 구분되어 있는가?",
    },
    {
        "id": "flow",
        "name": "④ Agent 관계·정보 흐름",
        "max": 20,
        "question": "Agent 간 호출·협업·정보 전달 방향이 명확한가?",
    },
    {
        "id": "feedback",
        "name": "⑤ Feedback / Iteration",
        "max": 15,
        "question": "검토·평가·개선 등 반복 구조가 필요한 경우 표현되어 있는가?",
    },
    {
        "id": "memory_output",
        "name": "⑥ Memory / Context / Output",
        "max": 15,
        "question": "Memory/Context 및 최종 Output의 위치와 흐름이 명확한가?",
    },
]

# Word 가이드 7장 "내부 정합성 점검" + 9장 체크리스트 11번 항목 통합
INTERNAL_CHECKS_PROMPT = [
    "그림에 있는 Agent 이름과 MD 설명의 Agent 이름이 동일한가?",
    "그림에서 표현한 입력·처리·출력 흐름과 MD 설명이 일치하는가?",
    "각 Agent의 역할이 중복되거나 서로 모순되지 않는가?",
    "화살표 방향이 실제 시스템 실행/정보 흐름과 일치한다고 볼 수 있는가?",
    "Memory/DB/API 등 외부 자원을 사용하는 경우 그림과 설명에 모두 반영되어 있는가?",
    "반복/피드백 구조가 있다고 설명하면서 그림에서는 단방향으로만 표현되어 있지는 않은가?",
    "Gottweis et al. (2026)의 핵심 개념(Supervisor-Specialized Agent-Task-Memory-Feedback)을 "
    "준용하되 연구 고유 구조가 훼손되지 않았는가?",
]

MODEL_OPTIONS = ["claude-sonnet-4-6", "claude-opus-4-6"]


def verdict_from_score(total: int) -> str:
    if total >= 90:
        return "적합 — 공지사항 게시 전 제출 가능"
    if total >= 80:
        return "조건부 적합 — 경미한 수정 권고"
    if total >= 70:
        return "수정 권고 — 구조 또는 표기 보완 필요"
    return "재검토 권고 — 핵심 구성요소/흐름 보완 필요"


def file_to_png_b64_list(uploaded_file) -> list[str]:
    """업로드된 파일(png/jpg/pdf)을 base64 PNG 이미지 리스트로 변환. PDF는 페이지별로 렌더링."""
    name = uploaded_file.name.lower()
    data = uploaded_file.read()
    images = []
    if name.endswith(".pdf"):
        doc = fitz.open(stream=data, filetype="pdf")
        for page in doc:
            pix = page.get_pixmap(dpi=150)
            images.append(base64.b64encode(pix.tobytes("png")).decode())
        doc.close()
    else:
        images.append(base64.b64encode(data).decode())
    return images


def build_prompt(md_text: str) -> str:
    criteria_text = "\n".join(
        f"- id=\"{c['id']}\" | {c['name']} (배점 {c['max']}점): {c['question']}"
        for c in CRITERIA
    )
    internal_text = "\n".join(f"- {q}" for q in INTERNAL_CHECKS_PROMPT)

    return f"""당신은 대학 AI 멀티에이전트 연구 산출물의 시스템 구성도를 평가하는 채점 보조자입니다.
Gottweis et al. (2026), Nature "Co-Scientist" 논문의 Supervisor - Specialized Agent - Task - Memory - Feedback
구조를 참조 기준으로 삼되, "논문 그림과 똑같이 그렸는가"가 아니라
"각 연구의 아키텍처가 이 구조에 논리적으로 대응되고, 그림·설명 사이에 모순이 없는가"를 평가합니다.
연구자가 정의한 Agent 명칭은 자유롭게 사용할 수 있습니다.

첨부된 이미지는 [아키텍처 구성도 원본]입니다 (PDF인 경우 페이지별로 나뉘어 첨부되었을 수 있습니다).
아래는 [기능별 MD 파일] 내용입니다.

--- MD 파일 내용 시작 ---
{md_text if md_text.strip() else "(MD 파일 없음 또는 비어 있음)"}
--- MD 파일 내용 끝 ---

## 채점 지침
- 이미지·MD에서 실제로 확인되는 내용만 근거로 삼고, 확인되지 않으면 감점하세요.
- 각 항목 점수는 0 이상 배점 이하의 정수여야 합니다.

## 평가 항목 (6개, 총 100점)
{criteria_text}

## 내부 정합성 점검 (7개, 참고용 — 점수에 직접 반영하지 않고 pass/fail과 코멘트만)
{internal_text}

다른 설명 없이 아래 JSON 형식으로만 응답하세요:
{{
  "scores": [
    {{"id": "actor", "score": 0, "reason": "근거 한 문장"}},
    {{"id": "orchestrator", "score": 0, "reason": "..."}},
    {{"id": "agents", "score": 0, "reason": "..."}},
    {{"id": "flow", "score": 0, "reason": "..."}},
    {{"id": "feedback", "score": 0, "reason": "..."}},
    {{"id": "memory_output", "score": 0, "reason": "..."}}
  ],
  "internal_checks": [
    {{"question": "...", "pass": true, "comment": "짧은 코멘트"}}
  ],
  "overall_comment": "전체 총평 2~3문장 (강점과 보완점 위주)"
}}
"""


class AIResponseParseError(Exception):
    """AI 응답에서 JSON을 파싱하지 못했을 때 원본 텍스트를 함께 담아 전달하기 위한 예외."""

    def __init__(self, raw_text: str):
        self.raw_text = raw_text
        super().__init__("AI 응답을 JSON으로 해석하지 못했습니다.")


def _extract_json(text: str) -> dict:
    text = text.strip()
    # 마크다운 코드펜스 제거 (```json ... ``` 또는 ``` ... ```)
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 앞뒤에 설명 문구가 섞여 있을 경우, 첫 '{'부터 마지막 '}'까지만 추출해 재시도
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    raise AIResponseParseError(text)


def call_claude(api_key: str, model: str, prompt: str, image_b64_list: list[str]) -> dict:
    client = Anthropic(api_key=api_key)
    content = [{"type": "text", "text": prompt}]
    for img in image_b64_list:
        content.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": img},
            }
        )
    resp = client.messages.create(
        model=model,
        max_tokens=4000,
        system=(
            "너는 채점 보조 AI다. 사용자가 요청한 JSON 형식 그대로만 응답하라. "
            "인사말, 설명, 마크다운 코드펜스(```) 없이 순수 JSON 객체 하나만 출력하라."
        ),
        messages=[{"role": "user", "content": content}],
    )
    text = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")
    return _extract_json(text)


# --------------------------------------------------------------------------
# PDF 생성 (ReportLab 내장 한글 CID 폰트 사용 — 별도 폰트 파일 불필요)
# --------------------------------------------------------------------------
def _wrap(text: str, width: int = 42) -> list[str]:
    out = []
    for para in (text or "").split("\n"):
        wrapped = textwrap.wrap(para, width)
        out.extend(wrapped if wrapped else [""])
    return out


def generate_pdf(
    prof_name: str,
    dept: str,
    final_scores: list[dict],
    total: int,
    verdict: str,
    internal_checks: list[dict],
    overall_comment: str,
) -> io.BytesIO:
    if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_REGULAR_PATH))
    if FONT_NAME_BOLD not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT_NAME_BOLD, FONT_BOLD_PATH))
    FONT = FONT_NAME

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    margin = 20 * mm
    y = height - margin

    def ensure_space(dy):
        nonlocal y
        if y - dy < margin:
            c.showPage()
            y = height - margin

    def line(text, size=11, dy=7 * mm, gray=0, bold=False):
        nonlocal y
        ensure_space(dy)
        c.setFont(FONT_NAME_BOLD if bold else FONT, size)
        c.setFillGray(gray)
        c.drawString(margin, y, text)
        y -= dy

    def rule():
        nonlocal y
        ensure_space(4 * mm)
        c.setStrokeGray(0.7)
        c.line(margin, y, width - margin, y)
        y -= 6 * mm

    # 헤더
    line("AI 멀티에이전트 아키텍처 정합성 평가 결과", size=16, dy=10 * mm, bold=True)
    line("Reference: Gottweis et al. (2026), Nature, Co-Scientist", size=9, dy=6 * mm, gray=0.4)
    line(f"평가일시: {datetime.now().strftime('%Y-%m-%d %H:%M')}", size=10)
    line(f"제출 교수: {prof_name or '-'}      소속/전공: {dept or '-'}", size=10)
    rule()

    # 총점/판정
    line(f"총점: {total} / 100", size=14, dy=8 * mm, bold=True)
    line(f"판정: {verdict}", size=14, dy=9 * mm, bold=True)
    rule()

    # 항목별 결과
    line("항목별 평가 결과", size=13, dy=8 * mm, bold=True)
    for item in final_scores:
        line(f"{item['name']}   —   {item['score']} / {item['max']}점", size=11, dy=6 * mm)
        for chunk in _wrap(f"근거: {item['reason']}", 48):
            line(chunk, size=9, dy=5 * mm, gray=0.25)
        y -= 1.5 * mm
    rule()

    # 내부 정합성 점검
    line("내부 정합성 점검", size=13, dy=8 * mm, bold=True)
    for chk in internal_checks:
        mark = "O" if chk.get("pass") else "X"
        for chunk in _wrap(f"[{mark}] {chk.get('question','')}", 46):
            line(chunk, size=10, dy=5.5 * mm)
        if chk.get("comment"):
            for chunk in _wrap(f"코멘트: {chk['comment']}", 48):
                line(chunk, size=9, dy=5 * mm, gray=0.25)
        y -= 1.5 * mm
    rule()

    # 총평
    line("총평", size=13, dy=8 * mm, bold=True)
    for chunk in _wrap(overall_comment, 48):
        line(chunk, size=10, dy=5.5 * mm)

    c.save()
    buf.seek(0)
    return buf


# --------------------------------------------------------------------------
# Streamlit UI
# --------------------------------------------------------------------------
st.set_page_config(page_title="AI 아키텍처 정합성 셀프체크", layout="wide")
st.title("AI 멀티에이전트 아키텍처 정합성 셀프체크")
st.caption("Gottweis et al. (2026), Nature Co-Scientist 구조를 준용한 산출물 사전 점검 도구")

with st.sidebar:
    st.header("설정")
    default_key = ""
    try:
        default_key = st.secrets.get("ANTHROPIC_API_KEY", "")
    except Exception:
        pass
    api_key = st.text_input("Anthropic API Key", type="password", value=default_key)
    model = st.selectbox("모델", MODEL_OPTIONS, index=0)
    st.caption("API 키는 저장되지 않으며 이 세션에서만 사용됩니다.")
    st.markdown("---")
    st.caption("문의: 김진숙 멘토(haeonverse@gmail.com)")

col1, col2 = st.columns(2)
prof_name = col1.text_input("교수님 성함")
dept = col2.text_input("소속/전공")

st.subheader("파일 업로드")
c1, c2 = st.columns(2)
diagram_file = c1.file_uploader(
    "① 아키텍처 구성도 원본 (필수)",
    type=["png", "jpg", "jpeg", "pdf"],
    accept_multiple_files=False,
    help="이미지 또는 PDF 1개 파일을 업로드하세요.",
)
md_file = c2.file_uploader("② 기능별 MD 파일 (필수)", type=["md", "txt"])

ready = bool(api_key) and bool(diagram_file) and bool(md_file)
if not ready:
    missing = []
    if not api_key:
        missing.append("API 키(사이드바)")
    if not diagram_file:
        missing.append("아키텍처 구성도")
    if not md_file:
        missing.append("기능별 MD 파일")
    if missing:
        st.info("평가를 시작하려면 다음이 필요합니다: " + ", ".join(missing))

if st.button("평가 시작", type="primary", disabled=not ready):
    with st.spinner("AI가 구성도와 MD 파일을 분석하고 있습니다... (약 10~30초 소요)"):
        diagram_file.seek(0)
        images = file_to_png_b64_list(diagram_file)
        md_text = md_file.read().decode("utf-8", errors="ignore")

        prompt = build_prompt(md_text)
        try:
            ai_result = call_claude(api_key, model, prompt, images)
            st.session_state["ai_result"] = ai_result
            st.session_state["prof_name"] = prof_name
            st.session_state["dept"] = dept
        except AIResponseParseError as e:
            st.error("AI 응답을 JSON으로 해석하지 못했습니다. '평가 시작'을 한 번 더 눌러 다시 시도해 주세요.")
            with st.expander("AI 원본 응답 보기 (문제가 계속되면 이 내용을 멘토에게 공유해 주세요)"):
                st.code(e.raw_text)
        except Exception as e:
            st.error(f"평가 중 오류가 발생했습니다: {e}")

if "ai_result" in st.session_state:
    ai_result = st.session_state["ai_result"]
    score_map = {s["id"]: s for s in ai_result.get("scores", [])}

    st.markdown("---")
    st.subheader("항목별 평가 결과 (AI 1차 채점 — 필요 시 직접 수정해 확정하세요)")

    final_scores = []
    total = 0
    for c in CRITERIA:
        ai_item = score_map.get(c["id"], {})
        ai_score = int(ai_item.get("score", 0) or 0)
        ai_score = max(0, min(ai_score, c["max"]))
        reason = ai_item.get("reason", "")

        with st.expander(f"{c['name']}  (배점 {c['max']}점)  —  AI 채점: {ai_score}점", expanded=True):
            st.write(f"**질문:** {c['question']}")
            st.write(f"**AI 판단 근거:** {reason}")
            edited = st.slider(
                "최종 점수 (직접 수정 가능)",
                min_value=0,
                max_value=c["max"],
                value=ai_score,
                key=f"score_{c['id']}",
            )
        total += edited
        final_scores.append(
            {"id": c["id"], "name": c["name"], "max": c["max"], "score": edited, "reason": reason}
        )

    verdict = verdict_from_score(total)

    st.markdown("---")
    m1, m2 = st.columns(2)
    m1.metric("총점", f"{total} / 100")
    m2.metric("판정", verdict)

    st.subheader("내부 정합성 점검 (AI 자동 확인 · 참고용)")
    internal_checks = ai_result.get("internal_checks", [])
    for chk in internal_checks:
        icon = "✅" if chk.get("pass") else "⚠️"
        st.write(f"{icon} **{chk.get('question','')}** — {chk.get('comment','')}")

    st.subheader("총평")
    overall_comment = st.text_area(
        "AI 총평 (필요 시 수정 가능)", ai_result.get("overall_comment", ""), height=100
    )

    st.markdown("---")
    pdf_buf = generate_pdf(
        st.session_state.get("prof_name", ""),
        st.session_state.get("dept", ""),
        final_scores,
        total,
        verdict,
        internal_checks,
        overall_comment,
    )
    file_label = st.session_state.get("prof_name") or "result"
    st.download_button(
        "📄 평가 결과 PDF 다운로드",
        data=pdf_buf,
        file_name=f"architecture_check_{file_label}.pdf",
        mime="application/pdf",
        type="primary",
    )
