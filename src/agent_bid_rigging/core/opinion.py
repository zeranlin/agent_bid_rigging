from __future__ import annotations

from datetime import datetime

from agent_bid_rigging.utils.openai_client import OpenAIResponsesClient


def generate_review_opinion(report: dict, opinion_mode: str = "auto", llm_review_layers: dict | None = None) -> dict:
    selected_mode = opinion_mode
    if opinion_mode == "auto":
        selected_mode = "llm" if OpenAIResponsesClient.is_configured() else "template"

    if selected_mode == "llm":
        if llm_review_layers and llm_review_layers.get("opinion_document"):
            return {
                "mode": llm_review_layers.get("mode", "llm"),
                "generated_at": llm_review_layers.get("generated_at", datetime.now().isoformat(timespec="seconds")),
                "document": llm_review_layers["opinion_document"],
            }
        try:
            document = _generate_llm_opinion(report)
            return {
                "mode": "llm",
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "document": document,
            }
        except Exception as exc:  # noqa: BLE001
            fallback = _generate_template_opinion(report)
            return {
                "mode": "template-fallback",
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "document": fallback,
                "fallback_reason": str(exc),
            }

    document = _generate_template_opinion(report)
    return {
        "mode": "template",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "document": document,
    }


def _generate_llm_opinion(report: dict) -> str:
    client = OpenAIResponsesClient.from_env()
    return client.generate_markdown(
        system_prompt=_system_prompt(),
        user_prompt=_build_llm_input(report),
    )


def _generate_template_opinion(report: dict) -> str:
    top_risk = max(
        report["pairwise_assessments"],
        key=lambda item: item["risk_score"],
        default=None,
    )
    formal_report = report.get("formal_report", {})
    basic_info = formal_report.get("project_basic_info", {})
    risk_summary = formal_report.get("risk_summary", [])
    evidence_summary = formal_report.get("evidence_summary", [])
    review_conclusion = report.get("review_conclusion_table", {})
    supplier_names = _supplier_display_names(formal_report, report)

    lines = [
        "# 围串标审查意见书",
        "",
        "## 一、项目概况",
        "",
        f"- 项目名称：{basic_info.get('project_name') or report['run_name']}",
        f"- 项目编号：`{basic_info.get('project_id') or report['run_name']}`",
        f"- 采购人：{basic_info.get('purchaser') or '未自动识别'}",
        f"- 采购代理机构：{basic_info.get('agency') or '未自动识别'}",
        f"- 审查对象：{'、'.join(supplier_names)}",
        f"- 审查生成时间：{report['generated_at']}",
        "",
        "## 二、审查依据与方法",
        "",
        "本意见书基于采购人提供的招标文件、供应商提交的投标文件，以及系统自动抽取形成的结构化事实、风险评分和证据分级结果形成。",
        "审查方法包括文本抽取、OCR 辅助识别、统一事实融合、两两比对评分和证据摘要归纳。",
        "",
        "## 三、事实摘要",
        "",
        _format_fact_summary(formal_report, report),
        "",
        "## 四、主要可疑线索",
        "",
        _format_suspicious_clues(review_conclusion, report),
        "",
        "## 五、排除性因素",
        "",
        _format_exclusionary_factors(review_conclusion, risk_summary),
        "",
        "## 六、风险评分与主要证据摘要",
        "",
        _format_risk_summary(risk_summary),
        "",
        _format_evidence_summary(evidence_summary),
        "",
        "## 七、初步审查意见",
        "",
        _conclusion_text(top_risk),
        "",
        "## 八、建议进一步核查事项",
        "",
        _recommendations(top_risk),
        "",
        "## 九、说明",
        "",
        "本意见书为自动生成的审查底稿，旨在为政府采购审查人员提供复核起点，不能替代最终行政认定或法律结论。",
    ]
    return "\n".join(lines)


def _system_prompt() -> str:
    return (
        "你是一名政府采购围串标审查代理。"
        "你的任务是基于给定的结构化证据，输出正式、克制、可复核的《围串标审查意见书》。"
        "不要夸大结论，不要捏造证据。"
        "如果证据不足，只能写‘存在可疑线索，建议进一步核查’，不能直接下违法定性。"
        "输出请使用简体中文 Markdown。"
    )


def _build_llm_input(report: dict) -> str:
    lines = [
        "请根据以下结构化审查结果，起草《围串标审查意见书》。",
        "",
        f"运行批次: {report['run_name']}",
        f"生成时间: {report['generated_at']}",
        f"供应商列表: {', '.join(report['suppliers'])}",
        "",
        "两两比对结果:",
    ]
    for item in report["pairwise_assessments"]:
        lines.append(
            f"- {item['supplier_a']} vs {item['supplier_b']}: "
            f"risk_level={item['risk_level']}, risk_score={item['risk_score']}"
        )
        if not item["findings"]:
            lines.append("  - 未发现明显异常信号")
            continue
        for finding in item["findings"]:
            lines.append(
                f"  - {finding['title']} (+{finding['weight']}): {'；'.join(finding['evidence'])}"
            )

    lines.extend(
        [
            "",
            "写作要求:",
            "1. 结构包括：项目概况、审查依据与方法、事实摘要、主要可疑线索、排除性因素、风险评分与主要证据摘要、初步审查意见、建议进一步核查事项、说明。",
            "2. 结论要与证据强度匹配。",
            "3. 明确指出高风险供应商对及其证据。",
            "4. 若风险较低，应说明暂未发现明显异常。",
            "5. 文风正式、审慎、适合审查底稿。",
        ]
    )
    return "\n".join(lines)


def _format_key_findings(report: dict) -> str:
    sections: list[str] = []
    for item in report["pairwise_assessments"]:
        header = (
            f"### {item['supplier_a']} 与 {item['supplier_b']}"
            f" (`{item['risk_level']}`, {item['risk_score']}分)"
        )
        sections.append(header)
        if not item["findings"]:
            sections.append("- 未发现明显异常信号。")
            sections.append("")
            continue
        for finding in item["findings"]:
            sections.append(f"- {finding['title']}：{'；'.join(finding['evidence'])}")
        sections.append("")
    return "\n".join(sections).rstrip()


def _supplier_display_names(formal_report: dict, report: dict) -> list[str]:
    profiles = formal_report.get("review_object_profiles", [])
    if profiles:
        return [profile.get("full_name") or profile.get("supplier") for profile in profiles]
    return report.get("suppliers", [])


def _format_fact_summary(formal_report: dict, report: dict) -> str:
    sections = formal_report.get("review_sections", [])
    if not sections:
        return _format_key_findings(report)
    lines: list[str] = []
    for section in sections:
        lines.append(f"### {section['title']}")
        for point in section.get("points", [])[:5]:
            lines.append(f"- {point}")
        if opinion := section.get("opinion"):
            lines.append(f"- 审查意见：{opinion}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _format_suspicious_clues(review_conclusion: dict, report: dict) -> str:
    clues = review_conclusion.get("suspicious_clues", [])
    if not clues:
        return "- 暂未发现需要单列说明的可疑线索。"
    lines = [f"- {item}" for item in clues]
    evidence_pairs = {item["pair"] for item in report.get("formal_report", {}).get("evidence_summary", [])}
    for item in report["pairwise_assessments"]:
        pair = f"{item['supplier_a']} 与 {item['supplier_b']}"
        if item["risk_level"] in {"medium", "high", "critical"} and pair not in evidence_pairs and item["findings"]:
            lines.append(f"- {pair}：{item['findings'][0]['title']}。")
    return "\n".join(lines)


def _format_exclusionary_factors(review_conclusion: dict, risk_summary: list[dict]) -> str:
    factors = list(review_conclusion.get("exclusionary_factors", []))
    if all(item.get("entity_link_score", 0) == 0 for item in risk_summary):
        factors.append("各供应商之间未发现联系人、法定代表人、银行账户等核心身份要素的明显重合。")
    if not factors:
        return "- 暂无明确排除性因素。"
    return "\n".join(f"- {item}" for item in factors)


def _conclusion_text(top_risk: dict | None) -> str:
    if not top_risk:
        return "本次自动审查未形成可供比较的供应商对，暂无法出具明确比对意见。"
    if top_risk["risk_level"] == "critical":
        return (
            f"综合现有证据，`{top_risk['supplier_a']}` 与 `{top_risk['supplier_b']}` 之间存在较强围串标可疑线索，"
            "建议立即开展重点复核，包括原件核验、编制终端排查、账户及联系人关联核查等。"
        )
    if top_risk["risk_level"] == "high":
        return (
            f"综合现有证据，`{top_risk['supplier_a']}` 与 `{top_risk['supplier_b']}` 存在较高程度异常关联，"
            "具备进一步核查必要。"
        )
    if top_risk["risk_level"] == "medium":
        return "系统发现部分可疑重合线索，建议结合现场核验、原始材料和外部工商信息进一步判断。"
    return "本次自动审查暂未发现足以支撑明显围串标怀疑的强异常信号。"


def _recommendations(top_risk: dict | None) -> str:
    if not top_risk or top_risk["risk_level"] == "low":
        return (
            "建议保留本次自动审查工件，作为后续抽检和复核底稿；如后续出现投诉举报或外部线索，再结合原始电子文件元数据开展复审。"
        )
    return (
        "建议调取原始电子投标文件及形成过程材料，核查联系人、设备、网络、账号、排版痕迹等关联信息；"
        "必要时结合工商、社保、纳税、银行流水等外围证据开展联合核查。"
    )


def _format_risk_summary(risk_summary: list[dict]) -> str:
    if not risk_summary:
        return "- 暂无风险评分结果。"
    lines = []
    for item in risk_summary:
        lines.append(
            f"- {item['supplier_a']} 与 {item['supplier_b']}：当前已识别出{_risk_level_text(item['risk_level'])}，建议结合相关证据继续复核。"
        )
    return "\n".join(lines)


def _format_evidence_summary(evidence_summary: list[dict]) -> str:
    if not evidence_summary:
        return "- 暂无主要证据摘要。"
    lines = []
    for item in evidence_summary[:8]:
        lines.append(
            f"- {item['pair']}：{item['finding_title']}，证据等级 {item['evidence_grade']}。"
        )
    return "\n".join(lines)


def _risk_level_text(level: str) -> str:
    mapping = {
        "low": "暂未发现明显异常信号",
        "medium": "需要进一步核查的可疑线索",
        "high": "较强可疑线索",
        "critical": "较强可疑线索",
    }
    return mapping.get(level, "可疑线索")
