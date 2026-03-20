from __future__ import annotations

from datetime import datetime

from agent_bid_rigging.utils.openai_client import OpenAIResponsesClient


def generate_llm_review_layers(report: dict, formal_report_markdown: str, opinion_mode: str) -> dict | None:
    selected_mode = opinion_mode
    if opinion_mode == "auto":
        selected_mode = "llm" if OpenAIResponsesClient.is_configured() else "template"

    if selected_mode != "llm":
        return None

    client = OpenAIResponsesClient.from_env()
    evidence_markdown = client.generate_markdown(
        system_prompt=_system_prompt("evidence"),
        user_prompt=_build_evidence_input(report),
    )
    section_markdown = client.generate_markdown(
        system_prompt=_system_prompt("section"),
        user_prompt=_build_section_input(report, formal_report_markdown, evidence_markdown),
    )
    conclusion_markdown = client.generate_markdown(
        system_prompt=_system_prompt("conclusion"),
        user_prompt=_build_conclusion_input(report, evidence_markdown, section_markdown),
    )
    opinion_markdown = client.generate_markdown(
        system_prompt=_system_prompt("opinion"),
        user_prompt=_build_opinion_input(report, evidence_markdown, section_markdown, conclusion_markdown),
    )

    return {
        "mode": "llm",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "evidence_interpretation": evidence_markdown.strip(),
        "section_report": section_markdown.strip(),
        "conclusion_memo": conclusion_markdown.strip(),
        "opinion_document": opinion_markdown.strip(),
    }


def _system_prompt(layer: str) -> str:
    base = (
        "你是一名政府采购围串标审查代理。"
        "你必须严格依据输入材料写作，不得编造事实。"
        "结论必须克制，证据不足时只能写存在可疑线索、建议进一步核查。"
        "输出使用简体中文 Markdown。"
    )
    if layer == "evidence":
        return base + "你负责证据解释，重点区分强证据、弱证据、模板化因素和排除性因素。"
    if layer == "section":
        return base + "你负责分节审查报告起草，输出完整、正式、适合审查底稿的正文。"
    if layer == "conclusion":
        return base + "你负责综合审查结论，写出审慎的初步结论和核查建议。"
    return base + "你负责整合前序结果，输出完整《围串标审查意见书》。"


def _build_evidence_input(report: dict) -> str:
    lines = [
        "请对以下围串标审查证据做解释，不要直接下违法定性。",
        "",
        f"项目名称: {report['formal_report']['project_basic_info'].get('project_name') or report['run_name']}",
        f"供应商: {', '.join(report['suppliers'])}",
        "",
        "风险评分表:",
    ]
    for row in report["risk_score_table"]:
        lines.append(
            f"- {row['supplier_a']} vs {row['supplier_b']}: total={row['total_score']}, "
            f"level={row['risk_level']}, text={row['technical_text_score']}, entity={row['entity_link_score']}, "
            f"pricing={row['pricing_score']}, file={row['file_homology_score']}"
        )
    lines.append("")
    lines.append("证据分级表:")
    for row in report["evidence_grade_table"][:20]:
        lines.append(
            f"- {row['pair']} / {row['finding_title']} / {row['evidence_grade']} / {row['reason']}"
        )
    lines.extend(
        [
            "",
            "写作要求:",
            "1. 分为：证据强度判断、可疑点解释、排除性因素、人工复核重点。",
            "2. 需要明确哪些线索可能来自模板化或行业常见写法。",
            "3. 不要超出输入证据作结论。",
        ]
    )
    return "\n".join(lines)


def _build_section_input(report: dict, formal_report_markdown: str, evidence_markdown: str) -> str:
    return "\n".join(
        [
            "请根据以下结构化审查结果和证据解释，输出完整《围串标审查意见书》正文，风格接近政府采购审查底稿。",
            "",
            "现有模板报告:",
            formal_report_markdown,
            "",
            "证据解释:",
            evidence_markdown,
            "",
            "约束:",
            "1. 保持项目名称、项目编号、采购人、审查对象等已识别信息。",
            "2. 结构包括：审查目的、审查情况、发现的可疑点、排除性因素、初步审查结论、建议进一步核查事项。",
            "3. 语言正式、谨慎、可复核。",
            "4. 不能编造未提供的报价、品牌、型号、人员信息。",
        ]
    )


def _build_conclusion_input(report: dict, evidence_markdown: str, section_markdown: str) -> str:
    return "\n".join(
        [
            "请基于以下材料，单独写出“初步审查结论 + 核查建议”两部分。",
            "",
            "证据解释:",
            evidence_markdown,
            "",
            "报告正文:",
            section_markdown,
            "",
            "要求:",
            "1. 初步结论必须审慎。",
            "2. 明确指出当前是否足以直接认定围串标。",
            "3. 核查建议要具体、可执行。",
        ]
    )


def _build_opinion_input(
    report: dict,
    evidence_markdown: str,
    section_markdown: str,
    conclusion_markdown: str,
) -> str:
    return "\n".join(
        [
            "请综合以下内容，输出最终《围串标审查意见书》。",
            "",
            "证据解释代理输出:",
            evidence_markdown,
            "",
            "分节审查报告代理输出:",
            section_markdown,
            "",
            "综合审查结论代理输出:",
            conclusion_markdown,
            "",
            "要求:",
            "1. 用正式、克制、完整的中文 Markdown。",
            "2. 结论与证据强度严格一致。",
            "3. 如果证据不足，明确写暂不能认定围串标。",
        ]
    )
