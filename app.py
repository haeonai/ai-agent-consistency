"""
AI Agent 시스템 아키텍처 적합성·정합성 셀프체크 — Streamlit 앱
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

# 시스템 유형별 평가 프로파일. 모든 프로파일은 100점이지만 Agent 수가 아닌 설계 적합성을 평가한다.
EVALUATION_PROFILES = {
    "multi_agent": {
        "name": "멀티에이전트 협업형",
        "description": "복수 Agent가 역할을 나누고 Supervisor·Workflow·피드백으로 협업하는 시스템",
        "criteria": [
            {"id": "actor_boundary", "name": "① Actor · Input · System Boundary", "max": 10, "question": "사용자/연구자, 입력, 시스템, 외부 자원의 경계와 상호작용이 명확한가?"},
            {"id": "orchestration", "name": "② Orchestration · Execution", "max": 20, "question": "Supervisor/Orchestrator/Planner가 목표를 해석하고 작업·순서·상태를 조정하는 방식이 명확한가?"},
            {"id": "specialized_agents", "name": "③ Specialized Agents", "max": 20, "question": "2개 이상의 전문 역할이 중복 없이 구분되고, 각 Agent의 역할·입력·출력이 설명되는가?"},
            {"id": "information_flow", "name": "④ Information · Control Flow", "max": 15, "question": "Agent 간 호출·협업·정보 전달 방향과 핵심 전달 객체가 명확한가?"},
            {"id": "tools_evidence", "name": "⑤ Memory · Tools · Evidence", "max": 10, "question": "Memory/DB/RAG/Search/API/외부 모델의 목적과 연결 관계가 명확한가?"},
            {"id": "feedback_validation", "name": "⑥ Feedback · Validation", "max": 10, "question": "검토·평가·재작업·종료 조건이 실제 설계에 맞게 표현되는가?"},
            {"id": "output_consistency", "name": "⑦ Output · Cross-file Consistency", "max": 15, "question": "최종 산출물과 여러 이미지·MD의 명칭·역할·입출력·도구 사용이 일치하는가?"},
        ],
    },
    "deterministic_pipeline": {
        "name": "결정론·감사가능 파이프라인형",
        "description": "동일 입력의 재현성, 근거 좌표, 버전·감사 추적을 우선하는 고정 순서 처리 시스템",
        "criteria": [
            {"id": "purpose_boundary", "name": "① Purpose · Boundary", "max": 10, "question": "적용 목적, 입력 범위, 산출물, 시스템 경계가 명확한가?"},
            {"id": "deterministic_execution", "name": "② Deterministic Execution", "max": 20, "question": "처리 단계·순서·분기·종료 조건이 고정 또는 명시적으로 제어되어 동일 입력에서 재현 가능한가?"},
            {"id": "provenance_audit", "name": "③ Provenance · Auditability", "max": 20, "question": "입력·문서·인용 좌표·중간 산출물·파라미터·버전의 추적과 감사가 가능한가?"},
            {"id": "data_flow", "name": "④ Data · Transform Flow", "max": 15, "question": "각 단계의 입력·변환·출력과 전달 방향이 명확한가?"},
            {"id": "evidence_versioning", "name": "⑤ Evidence · Version Control", "max": 10, "question": "근거 출처, 데이터/모델/프롬프트 버전, 접근·기록 규칙이 실제 사용 범위에 맞게 설명되는가?"},
            {"id": "verification_exception", "name": "⑥ Verification · Exception", "max": 10, "question": "검증 규칙, 오류·누락·충돌 처리, 사람 검토 또는 재실행 조건이 명확한가?"},
            {"id": "output_consistency", "name": "⑦ Output · Cross-file Consistency", "max": 15, "question": "산출물의 재현·해석 가능성과 이미지·MD 간 단계·용어·입출력의 일치가 확보되는가?"},
        ],
    },
    "single_agent_workflow": {
        "name": "단일 Agent·도구 워크플로형",
        "description": "한 Agent 또는 하나의 명확한 Workflow가 특정 기능을 수행하는 시스템",
        "criteria": [
            {"id": "actor_scope", "name": "① Actor · Scope · Boundary", "max": 10, "question": "사용자, 업무 범위, 입력·출력, 시스템 경계가 명확한가?"},
            {"id": "execution_control", "name": "② Task · Execution Control", "max": 20, "question": "단일 Agent/Workflow가 수행할 작업, 순서, 조건, 종료 방식이 명확한가?"},
            {"id": "capability_tool", "name": "③ Capability · Tool Boundary", "max": 20, "question": "Agent의 책임 범위와 사용 Tool/API/지식원의 역할·한계가 명확한가?"},
            {"id": "flow_traceability", "name": "④ Information Flow · Traceability", "max": 15, "question": "질의·근거·처리 결과의 전달 흐름과 추적 가능성이 명확한가?"},
            {"id": "context_evidence", "name": "⑤ Context · Evidence", "max": 10, "question": "대화이력·DB·RAG 등 실제 사용하는 컨텍스트와 근거 관리가 설명되는가?"},
            {"id": "validation_approval", "name": "⑥ Validation · Approval", "max": 10, "question": "검증, 오류 처리, 사람 승인 또는 안전장치가 실제 운영 방식에 맞게 표현되는가?"},
            {"id": "output_consistency", "name": "⑦ Output · Cross-file Consistency", "max": 15, "question": "결과물·수용자와 이미지·MD의 기능·입출력·명칭이 일치하는가?"},
        ],
    },
    "human_approval": {
        "name": "사람 승인 중심 워크플로형",
        "description": "교육·행정·상담·의료·법무처럼 사람의 최종 책임과 승인 절차가 핵심인 시스템",
        "criteria": [
            {"id": "actor_responsibility", "name": "① Actor · Responsibility", "max": 10, "question": "사용자·담당자·승인권자의 책임과 시스템 경계가 명확한가?"},
            {"id": "workflow_control", "name": "② Workflow · Case Control", "max": 20, "question": "접수·처리·검토·승인·반려·종료의 업무 흐름과 상태가 명확한가?"},
            {"id": "role_handoff", "name": "③ Role · Handoff", "max": 20, "question": "AI, 담당자, 관리자 등 역할 분담과 인수인계·책임 전환 지점이 명확한가?"},
            {"id": "flow_audit", "name": "④ Information Flow · Audit", "max": 15, "question": "정보 이동, 결정 근거, 처리 이력, 기록 방향이 추적 가능한가?"},
            {"id": "resource_privacy", "name": "⑤ Resource · Privacy", "max": 10, "question": "DB/API/문서 및 개인정보·민감정보의 접근 목적과 통제가 설명되는가?"},
            {"id": "approval_exception", "name": "⑥ Approval · Exception", "max": 10, "question": "승인·반려 기준, 예외·오류 처리, 에스컬레이션 또는 사람 검토가 명확한가?"},
            {"id": "output_consistency", "name": "⑦ Output · Cross-file Consistency", "max": 15, "question": "최종 안내·결정·문서와 이미지·MD의 역할·상태·입출력이 일치하는가?"},
        ],
    },
    "custom_hybrid": {
        "name": "혼합·맞춤형",
        "description": "멀티 Agent, 파이프라인, 사람 승인, 도메인 규칙 등이 결합되거나 독특한 구조를 가진 시스템",
        "criteria": [
            {"id": "intent_fit", "name": "① Design Intent · Fit", "max": 20, "question": "설계 목적과 선택한 아키텍처 방식이 도메인 요구사항에 논리적으로 맞는가?"},
            {"id": "component_boundary", "name": "② Component · Boundary", "max": 20, "question": "주요 구성요소의 책임·경계·의존 관계가 명확한가?"},
            {"id": "flow_traceability", "name": "③ Flow · Traceability", "max": 15, "question": "입력·상태·근거·결과의 흐름이 추적 가능하게 표현되는가?"},
            {"id": "evidence_state", "name": "④ Evidence · State Control", "max": 10, "question": "도구·DB·Memory·규칙·상태를 실제 사용 방식에 맞게 관리하는가?"},
            {"id": "quality_control", "name": "⑤ Quality · Safety Control", "max": 15, "question": "검증·예외·안전·사람 개입 또는 대체 통제가 실제 위험에 맞게 존재하는가?"},
            {"id": "output_consistency", "name": "⑥ Output · Cross-file Consistency", "max": 20, "question": "최종 산출물과 이미지·MD의 명칭·역할·흐름·근거가 일치하는가?"},
        ],
    },
}

PROFILE_SELECTION_OPTIONS = {
    "자동 판별": "auto",
    "멀티에이전트 협업형": "multi_agent",
    "결정론·감사가능 파이프라인형": "deterministic_pipeline",
    "단일 Agent·도구 워크플로형": "single_agent_workflow",
    "사람 승인 중심 워크플로형": "human_approval",
    "혼합·맞춤형": "custom_hybrid",
}

# 호환성: 외부 테스트·기존 참조용 기본값. 실제 평가에는 선택된 프로파일을 사용한다.
CRITERIA = EVALUATION_PROFILES["multi_agent"]["criteria"]


def get_profile(profile_id: str) -> dict[str, Any]:
    return EVALUATION_PROFILES.get(profile_id, EVALUATION_PROFILES["custom_hybrid"])


def profile_catalog_text() -> str:
    blocks = []
    for profile_id, profile in EVALUATION_PROFILES.items():
        criteria_text = "\n".join(
            f"  - id={criterion['id']} | {criterion['name']} ({criterion['max']}점): {criterion['question']}"
            for criterion in profile["criteria"]
        )
        blocks.append(f"### {profile_id} | {profile['name']}\n{profile['description']}\n{criteria_text}")
    return "\n\n".join(blocks)


GENERIC_INTERNAL_CHECKS = [
    "여러 이미지와 MD에 나타난 동일 구성요소 또는 단계의 이름·역할·방향이 서로 일치하는가?",
    "입력·처리·출력·근거·상태의 흐름이 이미지와 MD에서 모순 없이 설명되는가?",
    "선택한 아키텍처 유형과 의도적으로 사용하지 않은 구조의 이유가 설계 의도에 맞는가?",
    "실제 사용하는 DB/API/도구/Memory/규칙만 이미지와 MD에 반영되어 있는가?",
    "프로파일에 맞는 검증·감사·승인·피드백 또는 대체 통제가 실제 운영 방식과 일치하는가?",
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


def build_prompt(
    md_bundle: str,
    image_assets: list[dict[str, Any]],
    inventory: list[dict[str, Any]],
    requested_profile_id: str,
    domain: str,
    design_intent: str,
    intentionally_excluded: str,
) -> str:
    inventory_text = "\n".join(
        f"- {item['kind']}: {item['name']} ({item['detail']})" for item in inventory
    )
    image_lines: list[str] = []
    for idx, asset in enumerate(image_assets, start=1):
        page_label = f" / {asset['page']}쪽" if asset["page"] else ""
        image_lines.append(f"- 이미지 {idx}: {asset['name']}{page_label}")
    image_text = "\n".join(image_lines)
    reference = load_reference()
    catalog = profile_catalog_text()
    internal_text = "\n".join(f"- {question}" for question in GENERIC_INTERNAL_CHECKS)

    if requested_profile_id == "auto":
        profile_instruction = (
            "사용자가 자동 판별을 선택했습니다. 아키텍처 이미지·MD·설계 의도를 종합해 아래 프로파일 중 가장 적합한 "
            "하나를 선택하고, 선택한 프로파일의 정확한 criteria ID와 배점으로만 채점하세요. "
            "구조가 독특하거나 두 유형 이상이 동등하게 결합되면 custom_hybrid를 선택하세요."
        )
        active_criteria_text = "자동 판별 후 선택한 프로파일의 criteria를 사용"
    else:
        selected_profile = get_profile(requested_profile_id)
        active_criteria_text = "\n".join(
            f"- id=\"{criterion['id']}\" | {criterion['name']} (배점 {criterion['max']}점): {criterion['question']}"
            for criterion in selected_profile["criteria"]
        )
        profile_instruction = (
            f"사용자가 {requested_profile_id} | {selected_profile['name']} 프로파일을 명시적으로 선택했습니다. "
            "이 프로파일의 criteria ID와 배점으로만 채점하세요. 제출물이 선택 프로파일과 본질적으로 맞지 않는 경우에만 "
            "그 불일치를 지적하고, 다른 프로파일의 필수 요소가 없다는 이유로 감점하지 마세요."
        )

    return f"""당신은 다양한 도메인의 AI 시스템 아키텍처와 설명 문서 사이의 정합성을 평가하는 보조자입니다.

## 평가의 가장 중요한 공정성 원칙
Gottweis et al. (2026) Co-Scientist는 멀티에이전트 협업형의 참조 사례일 뿐, 모든 AI 시스템이 Supervisor·다수 Agent·토너먼트·반복 피드백을 가져야 한다는 규격이 아닙니다. 시스템의 **실제 목적과 설계 의도에 맞는 구조 선택**을 평가하세요.

특히 동일 입력의 재현, 인용 좌표 보존, 감사가능성, 규정 준수, 안전성 또는 사람의 최종 책임이 중요한 시스템은 동적 조정과 다수 Agent를 의도적으로 배제한 결정론적 파이프라인 또는 승인 워크플로를 선택할 수 있습니다. 이 경우 Supervisor나 전문 Agent가 없다는 사실은 감점 사유가 아닙니다. 대신 처리 순서, 입력·버전·근거 추적, 검증, 예외 처리, 승인 또는 대체 통제가 명확한지 평가하세요.

## 제출자가 선언한 맥락
- 적용 도메인: {domain or '미입력'}
- 시스템 유형 선택: {requested_profile_id}
- 핵심 설계 의도: {design_intent or '미입력'}
- 의도적으로 제외한 구조와 사유: {intentionally_excluded or '미입력'}

## 전체 논문 기반 참조 원칙
Co-Scientist 논문에서 상위 원칙만 참조하세요: 명확한 목표, 역할 또는 처리단계의 분리, 정보·근거의 추적, 검증·피드백 또는 대체 통제, 사람의 책임 있는 관여, 결과의 명확성. 논문 그림의 외형 복제나 Agent 수 자체를 평가하지 마세요.

{reference}

## 평가 프로파일 카탈로그
{catalog}

## 프로파일 적용 지침
{profile_instruction}

## 업로드 범위
아래의 여러 아키텍처 이미지와 여러 MD 파일은 하나의 프로젝트 제출 패키지입니다. 개요도·세부도·데이터 흐름도 등 여러 이미지가 서로 보완 관계일 수 있으므로, 한 파일에 없는 내용을 다른 파일에서 발견했다고 감점하지 마세요. 다만 동일한 구성요소 또는 처리단계의 명칭·역할·입출력·도구 사용·흐름 방향이 이미지끼리 또는 이미지와 MD 사이에서 모순되면 지적하세요.

### 업로드 파일 목록
{inventory_text}

### Vision 입력 이미지 목록
{image_text}

### 기능별 MD 파일 내용
{md_bundle if md_bundle.strip() else '(MD 파일 없음 또는 비어 있음)'}

## 채점 지침
- 이미지와 MD에서 실제로 확인되는 내용만 근거로 삼으세요. 확인되지 않는 내용은 추정하지 마세요.
- 각 항목 점수는 0 이상 배점 이하의 정수여야 하며, 선택한 프로파일의 총점은 100점입니다.
- 의도적으로 미사용인 Agent, Memory, Tool, Feedback, 사람 승인은 ‘미사용 사유와 대체 통제’가 명확하면 감점하지 마세요.
- 설계 의도와 실제 표현이 일치하는지, 여러 파일을 종합했을 때 내부 정합성이 있는지를 우선 평가하세요.
- 설계 선택 그 자체를 ‘프레이밍 실패’로 간주하지 말고, 해당 도메인의 품질 요구사항을 충족하는지를 판단하세요.

## 이번 평가에 사용할 항목
{active_criteria_text}

## 공통 내부 정합성 점검 (참고용)
{internal_text}

다른 설명 없이 아래 JSON 형식의 객체 하나만 응답하세요. scores에는 선택한 프로파일의 모든 criterion ID를 정확히 한 번씩 포함하세요.
{{
  "evaluation_profile": {{
    "id": "선택한 프로파일 ID",
    "name": "선택한 프로파일명",
    "selection_reason": "이 프로파일이 도메인과 설계 의도에 맞는 이유",
    "fairness_note": "의도적으로 제외한 구조를 어떻게 공정하게 해석했는지"
  }},
  "scores": [
    {{"id": "선택한 프로파일의 criterion ID", "score": 0, "reason": "이미지·MD·설계 의도에 근거한 판단"}}
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
  "overall_comment": "전체 총평 2~3문장. 설계 강점, 선택 프로파일의 적합성, 핵심 보완점, 제출 준비 상태를 포함"
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
    canvas.drawString(18 * mm, page_height - 10 * mm, "AI Agent 시스템 아키텍처 적합성·정합성 평가 결과")
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
    evaluation_profile: dict[str, Any],
    domain: str,
    design_intent: str,
    intentionally_excluded: str,
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
        title="AI Agent 시스템 아키텍처 적합성·정합성 평가 결과",
        author="AI MASTER 정합성 셀프체크",
    )

    story: list[Any] = []
    story.append(Paragraph("AI Agent 시스템 아키텍처<br/>적합성·정합성 평가 결과", styles["title"]))
    story.append(
        _p(
            "Gottweis et al. (2026) 전체 논문 기반 — 시스템 유형·도메인·설계 의도에 맞춘 적응형 정합성 평가",
            styles["subtitle"],
        )
    )

    meta_rows = [
        [_p("제출 교수", styles["table_bold"]), _p(prof_name or "미입력", styles["table"]),
         _p("소속/전공", styles["table_bold"]), _p(dept or "미입력", styles["table"])],
        [_p("평가 프로파일", styles["table_bold"]), _p(evaluation_profile.get("name") or "미확정", styles["table"]),
         _p("적용 도메인", styles["table_bold"]), _p(domain or "미입력", styles["table"])],
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
    story.extend([banner, Spacer(1, 4 * mm)])

    story.append(_p("0. 평가 프레임과 설계 의도", styles["h1"]))
    story.append(_p(f"선택 근거: {evaluation_profile.get('selection_reason') or '선택 근거 미제공'}", styles["body"]))
    story.append(_p(f"공정성 해석: {evaluation_profile.get('fairness_note') or '설계 의도에 따라 평가함'}", styles["body"]))
    story.append(_p(f"핵심 설계 의도: {design_intent or '미입력'}", styles["body"]))
    story.append(_p(f"의도적으로 제외한 구조와 사유: {intentionally_excluded or '미입력'}", styles["body"]))
    story.append(Spacer(1, 2 * mm))

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
        "평가 기준: Gottweis et al. (2026), Accelerating scientific discovery with Co-Scientist의 Figure 1 및 Methods에서 "
        "도출한 상위 원칙(목표 명확성, 역할 또는 처리단계 분리, 정보·근거 추적, 검증·피드백 또는 대체 통제, "
        "사람의 책임 있는 관여, 결과의 명확성)을 준용함. 본 결과는 '" + (evaluation_profile.get("name") or "미확정") + "' 프로파일로 평가했으며, "
        "Supervisor·다수 Agent·Feedback 등 특정 구조의 부재 자체는 설계 의도와 대체 통제가 명확할 경우 감점 사유가 아님."
    )
    story.append(_p(methodology, styles["small"]))

    document.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    buffer.seek(0)
    return buffer


# --------------------------------------------------------------------------
# Streamlit UI
# --------------------------------------------------------------------------
st.set_page_config(page_title="AI Agent 시스템 아키텍처 정합성 셀프체크", layout="wide")
st.title("AI Agent 시스템 아키텍처 적합성·정합성 셀프체크")
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

st.subheader("평가 맥락 설정")
st.caption("시스템의 실제 구조를 먼저 선언하면, 해당 목적에 맞는 기준으로 정합성을 평가합니다.")
context_col1, context_col2 = st.columns(2)
profile_label = context_col1.selectbox(
    "시스템 유형·평가 프로파일",
    list(PROFILE_SELECTION_OPTIONS.keys()),
    help="자동 판별을 쓰거나, 시스템 성격에 맞는 프로파일을 직접 선택하세요.",
)
requested_profile_id = PROFILE_SELECTION_OPTIONS[profile_label]
domain = context_col2.text_input(
    "적용 도메인",
    placeholder="예: 근거이론 연구, 학사행정, 지역산업 분석, 교육과정 설계",
)
design_intent = st.text_area(
    "핵심 설계 의도",
    placeholder="예: 동일 입력에서 동일 결과를 보장하고, 문장별 인용 좌표와 처리 이력을 감사 가능하게 유지함.",
    height=85,
)
intentionally_excluded = st.text_area(
    "의도적으로 제외한 구조와 사유",
    placeholder="예: 동적 Supervisor와 다수 Agent는 재현성·감사가능성·인용 좌표 보존을 위해 의도적으로 사용하지 않음.",
    height=85,
)
st.info(
    "중요: Supervisor, 다수 Agent, Memory, Feedback Loop가 없다는 이유만으로 감점하지 않습니다. "
    "미사용 사유와 대체 통제(재현성, 감사, 승인, 검증, 예외처리 등)가 실제 설계에 맞게 설명되었는지를 봅니다."
)

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
            prompt = build_prompt(
                md_bundle,
                image_assets,
                inventory,
                requested_profile_id,
                domain,
                design_intent,
                intentionally_excluded,
            )
            ai_result = call_claude(api_key, model, prompt, image_assets)
            for key in list(st.session_state.keys()):
                if key.startswith("score_"):
                    del st.session_state[key]
            st.session_state["ai_result"] = ai_result
            st.session_state["prof_name"] = prof_name
            st.session_state["dept"] = dept
            st.session_state["model"] = model
            st.session_state["inventory"] = inventory
            st.session_state["requested_profile_id"] = requested_profile_id
            st.session_state["domain"] = domain
            st.session_state["design_intent"] = design_intent
            st.session_state["intentionally_excluded"] = intentionally_excluded
    except AIResponseParseError as exc:
        st.error("AI 응답을 JSON으로 해석하지 못했습니다. 평가를 다시 시도해 주세요.")
        with st.expander("AI 원본 응답 보기"):
            st.code(exc.raw_text)
    except Exception as exc:
        st.error(f"평가 중 오류가 발생했습니다: {exc}")

if "ai_result" in st.session_state:
    ai_result = st.session_state["ai_result"]
    score_map = {item.get("id"): item for item in ai_result.get("scores", [])}
    profile_result = ai_result.get("evaluation_profile", {}) or {}
    requested_profile_id_result = st.session_state.get("requested_profile_id", "auto")
    model_profile_id = str(profile_result.get("id", ""))
    if requested_profile_id_result != "auto":
        active_profile_id = requested_profile_id_result
        selection_reason = profile_result.get("selection_reason") or "사용자가 시스템 목적에 맞는 프로파일을 명시적으로 선택했음."
        fairness_note = profile_result.get("fairness_note") or "선택 프로파일 이외의 구조 부재는 감점하지 않고, 대체 통제의 명확성을 평가함."
    elif model_profile_id in EVALUATION_PROFILES:
        active_profile_id = model_profile_id
        selection_reason = profile_result.get("selection_reason") or "업로드 자료를 바탕으로 자동 판별함."
        fairness_note = profile_result.get("fairness_note") or "설계 목적에 맞는 구조를 기준으로 평가함."
    else:
        active_profile_id = "custom_hybrid"
        selection_reason = "자동 판별 결과가 유효하지 않아 혼합·맞춤형 프로파일을 기본 적용함."
        fairness_note = "특정 구조의 부재 자체를 감점하지 않고 설계 의도와 대체 통제를 평가함."
    active_profile = get_profile(active_profile_id)
    evaluation_profile = {
        "id": active_profile_id,
        "name": active_profile["name"],
        "selection_reason": selection_reason,
        "fairness_note": fairness_note,
    }

    st.markdown("---")
    st.subheader("적용 평가 프로파일")
    st.info(f"**{active_profile['name']}** — {active_profile['description']}")
    st.caption(f"선택 근거: {selection_reason}")
    st.caption(f"공정성 해석: {fairness_note}")

    st.subheader("항목별 평가 결과")
    st.caption("AI 1차 채점 결과입니다. 이 점수는 적용 프로파일 안에서만 해석하며, Agent 수가 많거나 적다는 사실만으로 평가하지 않습니다.")

    final_scores: list[dict[str, Any]] = []
    total = 0
    for criterion in active_profile["criteria"]:
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
                key=f"score_{active_profile_id}_{criterion['id']}",
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
        evaluation_profile,
        st.session_state.get("domain", ""),
        st.session_state.get("design_intent", ""),
        st.session_state.get("intentionally_excluded", ""),
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
