"""
AI 멀티에이전트 아키텍처 정합성 셀프체크 — Streamlit 앱
Reference: Gottweis et al. (2026), Nature, Co-Scientist

여러 개의 아키텍처 이미지/PDF와 여러 개의 기능별 MD 파일을 한 번에 업로드하면,
전체 논문(Figure 1 및 Methods) 기반의 공통 기준으로 종합 정합성을 평가합니다.
평가 후에는 파일 목록, 점수, 파일 간 불일치, 내부 점검, 총평을 포함한 PDF를 다운로드할 수 있습니다.

실행: streamlit run app.py
API 키: .streamlit/secrets.toml의 ANTHROPIC_API_KEY 또는 앱 사이드바 입력
"""

import base64
import html
import io
import json
import os
from datetime import datetime
from typing import Any

import fitz  # PyMuPDF
import streamlit as st
from anthropic import Anthropic
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR = os.path.join(BASE_DIR, "fonts")
FONT_REGULAR_PATH = os.path.join(FONTS_DIR, "NanumGothic-Regular.ttf")
FONT_BOLD_PATH = os.path.join(FONTS_DIR, "NanumGothic-Bold.ttf")
REFERENCE_PATH = os.path.join(BASE_DIR, "co_scientist_full_paper_reference.md")
FONT_NAME = "NanumGothic"
FONT_NAME_BOLD = "NanumGothic-Bold"

# 전체 논문(Figure 1 + Methods) 기반 7개 평가항목, 총 100점
CRITERIA = [
    {
        "id": "actor_boundary",
        "name": "① Actor · Input · System Boundary",
        "max": 10,
        "question": "사용자/연구자, 입력, AI 시스템, 외부 자원의 경계와 상호작용이 명확한가?",
    },
    {
        "id": "orchestration",
        "name": "② Orchestration · Execution",
        "max": 20,
        "question": "Supervisor/Orchestrator/Planner가 목표를 해석하고 작업·순서·상태를 조정하는 방식이 명확한가?",
    },
    {
        "id": "specialized_agents",
        "name": "③ Specialized Agents",
        "max": 20,
        "question": "2개 이상의 전문 역할이 중복 없이 구분되고, 각 Agent의 역할·입력·출력이 설명되는가?",
    },
    {
        "id": "information_flow",
        "name": "④ Information · Control Flow",
        "max": 15,
        "question": "Agent 간 호출·협업·정보 전달 방향과 핵심 전달 객체가 화살표·설명으로 명확한가?",
    },
    {
        "id": "tools_evidence",
        "name": "⑤ Memory · Tools · Evidence",
        "max": 10,
        "question": "사용하는 Memory/Context, DB, RAG, Search, API, 외부 모델의 목적·연결 Agent·읽기/기록 또는 호출 관계가 명확한가?",
    },
    {
        "id": "feedback_validation",
        "name": "⑥ Feedback · Validation",
        "max": 10,
        "question": "검토·평가·오류 처리·재작업 또는 단발성 검증·종료 조건이 실제 설계에 맞게 표현되는가?",
    },
    {
        "id": "output_consistency",
        "name": "⑦ Output · Cross-file Consistency",
        "max": 15,
        "question": "최종 산출물과 수용자가 명확하며, 여러 이미지·여러 MD 사이의 명칭·역할·입출력·도구 사용이 일치하는가?",
    },
]

INTERNAL_CHECKS_PROMPT = [
    "모든 아키텍처 이미지에 나타난 동일 구성요소의 이름·역할·방향이 서로 일치하는가?",
    "이미지에 있는 Agent/Tool/Memory/Output 명칭이 MD 설명에 동일하거나 명확히 대응되는가?",
    "이미지에서 표현한 입력·처리·출력 흐름과 MD 설명이 일치하는가?",
    "각 Agent의 역할이 중복되거나 서로 모순되지 않는가?",
    "화살표 방향이 실제 시스템 실행/정보 흐름과 일치한다고 볼 수 있는가?",
    "Memory/DB/API/RAG/외부 모델을 사용하는 경우 이미지와 MD에 모두 반영되어 있는가?",
    "반복·피드백 구조가 있다고 설명하면서 이미지에는 단방향으로만 표현되어 있지는 않은가?",
    "논문 전체에서 확인되는 핵심 원칙(연구자 개입·조정·전문 역할·실행 흐름·상태/근거·검증·결과 반환)을 실제 연구 구조에 맞게 준용했는가?",
]

MODEL_OPTIONS = ["claude-sonnet-4-6", "claude-opus-4-6"]


class AIResponseParseError(Exception):
    """AI 응답에서 JSON을 파싱하지 못했을 때 원문을 포함하는 예외."""

    def __init__(self, raw_text: str):
        self.raw_text = raw_text
        super().__init__("AI 응답을 JSON으로 해석하지 못했습니다.")


def verdict_from_score(total: int) -> str:
    if total >= 90:
        return "적합 — 최종 제출 가능"
    if total >= 80:
        return "조건부 적합 — 경미한 수정 권고"
    if total >= 70:
        return "수정 권고 — 구조 또는 표기 보완 필요"
    return "재검토 권고 — 핵심 구성요소/흐름 보완 필요"


def verdict_color(total: int) -> colors.Color:
    if total >= 90:
        return colors.HexColor("#1F7A4C")
    if total >= 80:
        return colors.HexColor("#9A6B00")
    if total >= 70:
        return colors.HexColor("#B85C00")
    return colors.HexColor("#B42318")


def load_reference() -> str:
    try:
        with open(REFERENCE_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return "참조 요약 파일을 불러오지 못했습니다. Figure 1 및 Methods의 구조 원칙을 기준으로 평가하세요."


def _media_type(file_name: str) -> str:
    lower = file_name.lower()
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    return "image/png"


def diagrams_to_image_assets(uploaded_files) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """여러 이미지/PDF를 Vision 입력용 PNG 리스트와 업로드 목록으로 변환한다."""
    image_assets: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []

    for uploaded_file in uploaded_files:
        name = uploaded_file.name
        lower = name.lower()
        data = uploaded_file.getvalue()
        if lower.endswith(".pdf"):
            doc = fitz.open(stream=data, filetype="pdf")
            page_count = len(doc)
            inventory.append({"kind": "아키텍처 PDF", "name": name, "detail": f"{page_count}쪽"})
            for page_no, page in enumerate(doc, start=1):
                pix = page.get_pixmap(dpi=160, alpha=False)
                image_assets.append(
                    {
                        "name": name,
                        "page": page_no,
                        "media_type": "image/png",
                        "data": base64.b64encode(pix.tobytes("png")).decode(),
                    }
                )
            doc.close()
        else:
            inventory.append({"kind": "아키텍처 이미지", "name": name, "detail": "1장"})
            image_assets.append(
                {
                    "name": name,
                    "page": None,
                    "media_type": _media_type(name),
                    "data": base64.b64encode(data).decode(),
                }
            )

    return image_assets, inventory


def md_files_to_bundle(uploaded_files) -> tuple[str, list[dict[str, Any]]]:
    """여러 MD/TXT 파일을 파일 경계를 보존한 하나의 분석용 본문으로 병합한다."""
    blocks: list[str] = []
    inventory: list[dict[str, Any]] = []
    for uploaded_file in uploaded_files:
        text = uploaded_file.getvalue().decode("utf-8", errors="ignore").strip()
        line_count = len(text.splitlines()) if text else 0
        inventory.append({"kind": "기능 설명 MD", "name": uploaded_file.name, "detail": f"{line_count}줄"})
        blocks.append(
            f"\n===== MD 파일 시작: {uploaded_file.name} =====\n"
            f"{text if text else '(파일이 비어 있음)'}\n"
            f"===== MD 파일 끝: {uploaded_file.name} =====\n"
        )
    return "\n".join(blocks), inventory


def build_prompt(md_bundle: str, image_assets: list[dict[str, Any]], inventory: list[dict[str, Any]]) -> str:
    criteria_text = "\n".join(
        f"- id=\"{c['id']}\" | {c['name']} (배점 {c['max']}점): {c['question']}"
        for c in CRITERIA
    )
    internal_text = "\n".join(f"- {q}" for q in INTERNAL_CHECKS_PROMPT)
    inventory_text = "\n".join(
        f"- {item['kind']}: {item['name']} ({item['detail']})" for item in inventory
    )
    image_lines: list[str] = []
    for idx, asset in enumerate(image_assets, start=1):
        page_label = f" / {asset['page']}쪽" if asset["page"] else ""
        image_lines.append(f"- 이미지 {idx}: {asset['name']}{page_label}")
    image_text = "\n".join(image_lines)
    reference = load_reference()

    return f"""당신은 대학 AI 멀티에이전트 연구 산출물의 정합성을 평가하는 채점 보조자입니다.

## 평가 목적
Gottweis et al. (2026) Co-Scientist의 그림 외형을 복제했는지 평가하지 마세요. 전체 논문, 특히 Figure 1 및 Methods에서 확인되는 연구자 개입·목표/계획 해석·Supervisor 조정·전문 Agent 역할 분담·실행 흐름·Memory/Context·Tools/Evidence·Feedback/Validation·Output 원칙을 기준으로 삼으세요. 각 연구의 고유 Agent 명칭, 구현 방식, 순차형/비동기형 구조는 허용됩니다.

## 전체 논문 기반 참조 프레임
{reference}

## 업로드 범위
아래의 여러 아키텍처 이미지와 여러 MD 파일은 하나의 프로젝트 제출 패키지입니다. 개요도·세부도·데이터 흐름도 등 여러 이미지가 서로 보완 관계일 수 있으므로, 한 파일에 없는 내용을 다른 파일에서 발견했다고 감점하지 마세요. 다만 동일한 구성요소의 명칭·역할·입출력·도구 사용·흐름 방향이 이미지끼리 또는 이미지와 MD 사이에서 모순되면 반드시 지적하세요.

### 업로드 파일 목록
{inventory_text}

### Vision 입력 이미지 목록
{image_text}

### 기능별 MD 파일 내용
{md_bundle if md_bundle.strip() else '(MD 파일 없음 또는 비어 있음)'}

## 채점 지침
- 이미지와 MD에서 실제로 확인되는 내용만 근거로 삼으세요. 확인되지 않는 내용은 추정하지 마세요.
- 각 항목 점수는 0 이상 배점 이하의 정수여야 합니다.
- Memory, Tool, Feedback은 실제 미사용일 수 있습니다. 이 경우 억지로 감점하기보다, 미사용 또는 대체 검증 방식이 명확히 설명되었는지 보세요.
- 여러 파일을 종합했을 때의 구조적 완결성과 파일 간 내부 정합성을 함께 평가하세요.

## 평가 항목 (7개, 총 100점)
{criteria_text}

## 내부 정합성 점검 (참고용 — 점수와 별도로 pass/fail 및 코멘트)
{internal_text}

다른 설명 없이 아래 JSON 형식의 객체 하나만 응답하세요. 모든 배열 항목을 빠짐없이 채우세요.
{{
  "scores": [
    {{"id": "actor_boundary", "score": 0, "reason": "근거 한 문장"}},
    {{"id": "orchestration", "score": 0, "reason": "근거 한 문장"}},
    {{"id": "specialized_agents", "score": 0, "reason": "근거 한 문장"}},
    {{"id": "information_flow", "score": 0, "reason": "근거 한 문장"}},
    {{"id": "tools_evidence", "score": 0, "reason": "근거 한 문장"}},
    {{"id": "feedback_validation", "score": 0, "reason": "근거 한 문장"}},
    {{"id": "output_consistency", "score": 0, "reason": "근거 한 문장"}}
  ],
  "internal_checks": [
    {{"question": "점검 질문", "pass": true, "comment": "짧은 근거"}}
  ],
  "cross_file_issues": [
    {{"severity": "high 또는 medium 또는 low", "related_files": ["파일명"], "issue": "발견된 불일치 또는 보완 필요 사항", "recommendation": "수정 권고"}}
  ],
  "evidence_by_asset": [
    {{"asset": "파일명 또는 파일명/쪽수", "summary": "해당 파일에서 확인된 핵심 구조 또는 역할"}}
  ],
  "overall_comment": "전체 총평 2~3문장. 강점, 핵심 보완점, 제출 준비 상태를 포함"
}}
"""


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise AIResponseParseError(text)


def call_claude(api_key: str, model: str, prompt: str, image_assets: list[dict[str, Any]]) -> dict[str, Any]:
    client = Anthropic(api_key=api_key)
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for idx, asset in enumerate(image_assets, start=1):
        label = f"[아키텍처 이미지 {idx}/{len(image_assets)}] {asset['name']}"
        if asset["page"]:
            label += f" / {asset['page']}쪽"
        content.append({"type": "text", "text": label})
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": asset["media_type"],
                    "data": asset["data"],
                },
            }
        )
    response = client.messages.create(
        model=model,
        max_tokens=6000,
        system=(
            "너는 엄격하지만 건설적인 대학 AI 멀티에이전트 연구 산출물 평가 보조자다. "
            "사용자가 요청한 JSON 객체 하나만 출력하고, JSON 밖의 인사말·설명·마크다운 코드펜스를 출력하지 마라."
        ),
        messages=[{"role": "user", "content": content}],
    )
    text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
    return _extract_json(text)


# --------------------------------------------------------------------------
# PDF 생성: 다중 파일 분석 결과를 포함한 가독성 중심 결과보고서
# --------------------------------------------------------------------------
def _register_fonts() -> None:
    if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_REGULAR_PATH))
    if FONT_NAME_BOLD not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT_NAME_BOLD, FONT_BOLD_PATH))


def _safe(text: Any) -> str:
    return html.escape(str(text or "-")).replace("\n", "<br/>")


def _pdf_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ReportTitle", parent=base["Title"], fontName=FONT_NAME_BOLD, fontSize=20,
            leading=27, textColor=colors.HexColor("#102A43"), spaceAfter=5 * mm,
        ),
        "subtitle": ParagraphStyle(
            "ReportSubtitle", parent=base["Normal"], fontName=FONT_NAME, fontSize=9.5,
            leading=14, textColor=colors.HexColor("#52606D"), spaceAfter=6 * mm,
        ),
        "h1": ParagraphStyle(
            "ReportH1", parent=base["Heading2"], fontName=FONT_NAME_BOLD, fontSize=13,
            leading=18, textColor=colors.HexColor("#102A43"), spaceBefore=5 * mm, spaceAfter=3 * mm,
        ),
        "body": ParagraphStyle(
            "ReportBody", parent=base["BodyText"], fontName=FONT_NAME, fontSize=9.2,
            leading=14, textColor=colors.HexColor("#243B53"), spaceAfter=2.2 * mm,
        ),
        "small": ParagraphStyle(
            "ReportSmall", parent=base["BodyText"], fontName=FONT_NAME, fontSize=7.8,
            leading=10.5, textColor=colors.HexColor("#52606D"),
        ),
        "table": ParagraphStyle(
            "ReportTable", parent=base["BodyText"], fontName=FONT_NAME, fontSize=8.1,
            leading=11.2, textColor=colors.HexColor("#243B53"),
        ),
        "table_bold": ParagraphStyle(
            "ReportTableBold", parent=base["BodyText"], fontName=FONT_NAME_BOLD, fontSize=8.1,
            leading=11.2, textColor=colors.HexColor("#102A43"),
        ),
        "white": ParagraphStyle(
            "ReportWhite", parent=base["BodyText"], fontName=FONT_NAME_BOLD, fontSize=11.5,
            leading=16, textColor=colors.white, alignment=TA_CENTER,
        ),
        "center": ParagraphStyle(
            "ReportCenter", parent=base["BodyText"], fontName=FONT_NAME, fontSize=8.5,
            leading=12, textColor=colors.HexColor("#243B53"), alignment=TA_CENTER,
        ),
    }


def _p(text: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_safe(text), style)


def _header_footer(canvas, doc) -> None:
    canvas.saveState()
    page_width, page_height = A4
    canvas.setStrokeColor(colors.HexColor("#D9E2EC"))
    canvas.setLineWidth(0.4)
    canvas.line(18 * mm, page_height - 13 * mm, page_width - 18 * mm, page_height - 13 * mm)
    canvas.setFont(FONT_NAME, 7.3)
    canvas.setFillColor(colors.HexColor("#627D98"))
    canvas.drawString(18 * mm, page_height - 10 * mm, "AI 멀티에이전트 아키텍처 정합성 평가 결과")
    canvas.drawRightString(page_width - 18 * mm, 10 * mm, f"Page {doc.page}")
    canvas.drawString(18 * mm, 10 * mm, "Reference: Gottweis et al. (2026), Co-Scientist — Figure 1 및 Methods 기반")
    canvas.restoreState()


def _severity_label(value: str) -> tuple[str, colors.Color]:
    normalized = (value or "low").lower()
    if normalized in {"high", "높음", "high-risk"}:
        return "높음", colors.HexColor("#B42318")
    if normalized in {"medium", "mid", "중간"}:
        return "중간", colors.HexColor("#B85C00")
    return "낮음", colors.HexColor("#1F7A4C")


def generate_pdf(
    prof_name: str,
    dept: str,
    model: str,
    final_scores: list[dict[str, Any]],
    total: int,
    verdict: str,
    internal_checks: list[dict[str, Any]],
    cross_file_issues: list[dict[str, Any]],
    evidence_by_asset: list[dict[str, Any]],
    inventory: list[dict[str, Any]],
    overall_comment: str,
) -> io.BytesIO:
    _register_fonts()
    styles = _pdf_styles()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=21 * mm,
        bottomMargin=17 * mm,
        title="AI 멀티에이전트 아키텍처 정합성 평가 결과",
        author="AI MASTER 정합성 셀프체크",
    )

    story: list[Any] = []
    story.append(Paragraph("AI 멀티에이전트 아키텍처<br/>정합성 평가 결과", styles["title"]))
    story.append(
        _p(
            "Gottweis et al. (2026) 전체 논문 기반 — Figure 1 및 Methods의 역할·흐름·상태·근거·검증 원칙 준용",
            styles["subtitle"],
        )
    )

    meta_rows = [
        [_p("제출 교수", styles["table_bold"]), _p(prof_name or "미입력", styles["table"]),
         _p("소속/전공", styles["table_bold"]), _p(dept or "미입력", styles["table"])],
        [_p("평가 일시", styles["table_bold"]), _p(datetime.now().strftime("%Y-%m-%d %H:%M"), styles["table"]),
         _p("평가 모델", styles["table_bold"]), _p(model, styles["table"])],
    ]
    meta = Table(meta_rows, colWidths=[24 * mm, 58 * mm, 24 * mm, 58 * mm])
    meta.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F0F4F8")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#F0F4F8")),
        ("BOX", (0, 0), (-1, -1), 0.45, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D9E2EC")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([meta, Spacer(1, 6 * mm)])

    banner = Table([[_p(f"총점  {total} / 100점    |    {verdict}", styles["white"])]], colWidths=[164 * mm])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), verdict_color(total)),
        ("BOX", (0, 0), (-1, -1), 0.2, verdict_color(total)),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.extend([banner, Spacer(1, 5 * mm)])

    story.append(_p("1. 분석 범위", styles["h1"]))
    story.append(
        _p(
            f"아키텍처 이미지/PDF {sum(1 for x in inventory if '아키텍처' in x['kind'])}개와 "
            f"기능 설명 MD {sum(1 for x in inventory if 'MD' in x['kind'])}개를 하나의 제출 패키지로 종합 분석했음.",
            styles["body"],
        )
    )
    inventory_data = [[_p("구분", styles["table_bold"]), _p("파일명", styles["table_bold"]), _p("상세", styles["table_bold"])]]
    for item in inventory:
        inventory_data.append([_p(item["kind"], styles["table"]), _p(item["name"], styles["table"]), _p(item["detail"], styles["table"])])
    inventory_table = Table(inventory_data, colWidths=[32 * mm, 102 * mm, 30 * mm], repeatRows=1)
    inventory_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6EEF6")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D9E2EC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([inventory_table, Spacer(1, 5 * mm)])

    story.append(_p("2. 항목별 평가", styles["h1"]))
    score_rows = [[_p("평가영역", styles["table_bold"]), _p("점수", styles["table_bold"])]]
    for item in final_scores:
        score_rows.append([
            _p(item["name"], styles["table_bold"]),
            _p(f"{item['score']} / {item['max']}", styles["center"]),
        ])
    score_table = Table(score_rows, colWidths=[132 * mm, 32 * mm], repeatRows=1)
    score_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6EEF6")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D9E2EC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 1), (1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([score_table, Spacer(1, 3 * mm)])
    for item in final_scores:
        story.append(_p(f"{item['name']} — AI 판단 근거: {item.get('reason') or '근거 미제공'}", styles["body"]))
    story.append(Spacer(1, 2 * mm))

    story.append(_p("3. 파일 간 정합성 점검", styles["h1"]))
    if cross_file_issues:
        for issue_no, issue in enumerate(cross_file_issues, start=1):
            label, color = _severity_label(issue.get("severity", "low"))
            related = ", ".join(issue.get("related_files", []) or []) or "관련 파일 미지정"
            issue_title = Paragraph(
                f'<font color="{color.hexval()}"><b>[{_safe(label)}] 확인 사항 {issue_no}</b></font>',
                styles["body"],
            )
            story.append(issue_title)
            story.append(_p(f"관련 파일: {related}", styles["small"]))
            story.append(_p(f"확인 사항: {issue.get('issue') or '미기재'}", styles["body"]))
            story.append(_p(f"수정 권고: {issue.get('recommendation') or '미기재'}", styles["body"]))
            story.append(Spacer(1, 1.5 * mm))
    else:
        story.append(_p("여러 이미지와 MD 파일 간에 명확한 모순 또는 보완 필요 사항이 자동 탐지되지 않았음.", styles["body"]))

    story.append(_p("4. 내부 정합성 체크", styles["h1"]))
    for check_no, check in enumerate(internal_checks, start=1):
        passed = bool(check.get("pass"))
        label = "통과" if passed else "보완 필요"
        color = "#1F7A4C" if passed else "#B42318"
        check_title = Paragraph(
            f'<font color="{color}"><b>[{_safe(label)}] {check_no}. {_safe(check.get("question") or "점검 항목 미기재")}</b></font>',
            styles["body"],
        )
        story.append(check_title)
        story.append(_p(f"판단 근거: {check.get('comment') or '근거 미제공'}", styles["body"]))
        story.append(Spacer(1, 1.2 * mm))
    story.append(Spacer(1, 2 * mm))

    if evidence_by_asset:
        story.append(_p("5. 파일별 분석 메모", styles["h1"]))
        for evidence_no, evidence in enumerate(evidence_by_asset, start=1):
            story.append(_p(f"{evidence_no}. 파일: {evidence.get('asset') or '파일명 미기재'}", styles["table_bold"]))
            story.append(_p(f"확인된 핵심 구조: {evidence.get('summary') or '분석 메모 미기재'}", styles["body"]))
            story.append(Spacer(1, 1.2 * mm))
        story.append(Spacer(1, 2 * mm))

    story.append(_p("6. 종합 의견", styles["h1"]))
    story.append(_p(overall_comment or "AI 총평이 입력되지 않았습니다.", styles["body"]))
    story.append(Spacer(1, 5 * mm))

    methodology = (
        "평가 기준: Gottweis et al. (2026), Accelerating scientific discovery with Co-Scientist의 "
        "Figure 1 및 Methods에서 확인되는 연구자 개입, 계획·조정, 전문 Agent, 실행 흐름, "
        "Memory/Context, Tools/Evidence, Feedback/Validation, Output 원칙을 준용함. "
        "이는 논문 구조의 외형 복제를 요구하는 평가가 아니라, 제출된 다중 이미지와 다중 MD의 실제 설계·내부 정합성을 확인하는 평가임."
    )
    story.append(_p(methodology, styles["small"]))

    document.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    buffer.seek(0)
    return buffer


# --------------------------------------------------------------------------
# Streamlit UI
# --------------------------------------------------------------------------
st.set_page_config(page_title="AI 아키텍처 정합성 셀프체크", layout="wide")
st.title("AI 멀티에이전트 아키텍처 정합성 셀프체크")
st.caption("Gottweis et al. (2026) 전체 논문 — Figure 1 및 Methods 기반 다중 파일 종합 점검")

with st.sidebar:
    st.header("평가 설정")
    default_key = ""
    try:
        default_key = st.secrets.get("ANTHROPIC_API_KEY", "")
    except Exception:
        pass
    api_key = st.text_input("Anthropic API Key", type="password", value=default_key)
    model = st.selectbox("모델", MODEL_OPTIONS, index=0)
    st.caption("API 키는 저장하지 않으며, 현재 세션에서만 사용됩니다.")
    st.markdown("---")
    st.caption("평가 기준: Co-Scientist Figure 1 및 Methods")

col1, col2 = st.columns(2)
prof_name = col1.text_input("교수님 성함")
dept = col2.text_input("소속/전공")

st.subheader("제출 패키지 업로드")
st.info(
    "여러 파일을 한 번에 업로드할 수 있습니다. 개요도·세부도·데이터 흐름도 등 아키텍처 파일과 "
    "기능별 MD 파일을 모두 넣으면, 파일 간 명칭·역할·흐름의 정합성까지 함께 점검합니다."
)

c1, c2 = st.columns(2)
diagram_files = c1.file_uploader(
    "① 아키텍처 구성도 원본 (1개 이상, 필수)",
    type=["png", "jpg", "jpeg", "pdf"],
    accept_multiple_files=True,
    help="여러 개의 이미지 또는 PDF를 업로드할 수 있습니다. PDF는 페이지별 아키텍처 이미지로 분석됩니다.",
)
md_files = c2.file_uploader(
    "② 기능별 MD 설명 파일 (1개 이상, 필수)",
    type=["md", "txt"],
    accept_multiple_files=True,
    help="기능별·Agent별·도구별 설명 MD 파일을 모두 업로드하세요.",
)

if diagram_files or md_files:
    upload_rows = []
    for f in diagram_files or []:
        upload_rows.append({"구분": "아키텍처", "파일명": f.name, "크기": f"{len(f.getvalue()) / 1024:.1f} KB"})
    for f in md_files or []:
        upload_rows.append({"구분": "기능 설명", "파일명": f.name, "크기": f"{len(f.getvalue()) / 1024:.1f} KB"})
    with st.expander("업로드 파일 확인", expanded=True):
        st.dataframe(upload_rows, use_container_width=True, hide_index=True)

ready = bool(api_key) and bool(diagram_files) and bool(md_files)
if not ready:
    missing = []
    if not api_key:
        missing.append("API 키(사이드바)")
    if not diagram_files:
        missing.append("아키텍처 파일 1개 이상")
    if not md_files:
        missing.append("기능별 MD 파일 1개 이상")
    st.info("평가를 시작하려면 다음이 필요합니다: " + ", ".join(missing))

if st.button("다중 파일 정합성 평가 시작", type="primary", disabled=not ready):
    try:
        with st.spinner("아키텍처 이미지와 MD 파일을 통합 분석하고 있습니다. 파일 수에 따라 다소 시간이 걸릴 수 있습니다..."):
            image_assets, diagram_inventory = diagrams_to_image_assets(diagram_files)
            md_bundle, md_inventory = md_files_to_bundle(md_files)
            inventory = diagram_inventory + md_inventory
            prompt = build_prompt(md_bundle, image_assets, inventory)
            ai_result = call_claude(api_key, model, prompt, image_assets)
            st.session_state["ai_result"] = ai_result
            st.session_state["prof_name"] = prof_name
            st.session_state["dept"] = dept
            st.session_state["model"] = model
            st.session_state["inventory"] = inventory
    except AIResponseParseError as exc:
        st.error("AI 응답을 JSON으로 해석하지 못했습니다. 평가를 다시 시도해 주세요.")
        with st.expander("AI 원본 응답 보기"):
            st.code(exc.raw_text)
    except Exception as exc:
        st.error(f"평가 중 오류가 발생했습니다: {exc}")

if "ai_result" in st.session_state:
    ai_result = st.session_state["ai_result"]
    score_map = {item.get("id"): item for item in ai_result.get("scores", [])}

    st.markdown("---")
    st.subheader("항목별 평가 결과")
    st.caption("AI 1차 채점 결과입니다. 최종 제출 전 멘토 또는 담당자가 점수와 총평을 직접 보정할 수 있습니다.")

    final_scores: list[dict[str, Any]] = []
    total = 0
    for criterion in CRITERIA:
        ai_item = score_map.get(criterion["id"], {})
        try:
            ai_score = int(ai_item.get("score", 0) or 0)
        except (TypeError, ValueError):
            ai_score = 0
        ai_score = max(0, min(ai_score, criterion["max"]))
        reason = str(ai_item.get("reason", ""))

        with st.expander(f"{criterion['name']}  |  AI 점수 {ai_score} / {criterion['max']}점", expanded=True):
            st.write(f"**점검 질문:** {criterion['question']}")
            st.write(f"**AI 판단 근거:** {reason or '근거 미제공'}")
            edited_score = st.slider(
                "최종 점수",
                min_value=0,
                max_value=criterion["max"],
                value=ai_score,
                key=f"score_{criterion['id']}",
            )
        total += edited_score
        final_scores.append(
            {
                "id": criterion["id"],
                "name": criterion["name"],
                "max": criterion["max"],
                "score": edited_score,
                "reason": reason,
            }
        )

    verdict = verdict_from_score(total)
    st.markdown("---")
    metric_left, metric_right = st.columns(2)
    metric_left.metric("총점", f"{total} / 100")
    metric_right.metric("판정", verdict)

    cross_file_issues = ai_result.get("cross_file_issues", []) or []
    st.subheader("파일 간 정합성 확인")
    if cross_file_issues:
        for issue in cross_file_issues:
            severity, _ = _severity_label(str(issue.get("severity", "low")))
            related = ", ".join(issue.get("related_files", []) or [])
            st.warning(
                f"**[{severity}] {issue.get('issue', '확인 필요')}**\n\n"
                f"관련 파일: {related or '-'}\n\n권고: {issue.get('recommendation', '-')}"
            )
    else:
        st.success("업로드된 파일 간에 AI가 명확한 모순 또는 보완 필요 사항을 탐지하지 못했습니다.")

    st.subheader("내부 정합성 점검")
    internal_checks = ai_result.get("internal_checks", []) or []
    for check in internal_checks:
        status = "통과" if check.get("pass") else "보완 필요"
        icon = "✅" if check.get("pass") else "⚠️"
        st.write(f"{icon} **{status} — {check.get('question', '')}**  ")
        if check.get("comment"):
            st.caption(check["comment"])

    evidence_by_asset = ai_result.get("evidence_by_asset", []) or []
    if evidence_by_asset:
        st.subheader("파일별 분석 메모")
        st.dataframe(
            [
                {"파일": item.get("asset", "-"), "확인된 핵심 구조": item.get("summary", "-")}
                for item in evidence_by_asset
            ],
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("종합 의견")
    overall_comment = st.text_area(
        "AI 총평 (필요 시 수정 가능)",
        str(ai_result.get("overall_comment", "")),
        height=120,
    )

    st.markdown("---")
    pdf_buffer = generate_pdf(
        st.session_state.get("prof_name", ""),
        st.session_state.get("dept", ""),
        st.session_state.get("model", model),
        final_scores,
        total,
        verdict,
        internal_checks,
        cross_file_issues,
        evidence_by_asset,
        st.session_state.get("inventory", []),
        overall_comment,
    )
    file_label = st.session_state.get("prof_name") or "result"
    st.download_button(
        "평가 결과 PDF 다운로드",
        data=pdf_buffer,
        file_name=f"architecture_consistency_report_{file_label}.pdf",
        mime="application/pdf",
        type="primary",
    )
