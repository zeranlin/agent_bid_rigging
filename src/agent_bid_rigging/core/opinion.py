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
    conclusion = _conclusion_text(top_risk)
    findings = _format_key_findings(report)
    formal_report = report.get("formal_report", {})
    risk_summary = formal_report.get("risk_summary", [])
    evidence_summary = formal_report.get("evidence_summary", [])

    lines = [
        "# 围串标审查意见书",
        "",
        "## 一、审查概况",
        "",
        f"本次审查针对运行批次 `{report['run_name']}` 开展，系统共接收 1 份招标文件和 {len(report['suppliers'])} 份投标文件。",
        f"审查生成时间为 {report['generated_at']}，审查对象为 {'、'.join(report['suppliers'])}。",
        "",
        "## 二、审查依据与方法",
        "",
        "本意见书基于规则引擎自动抽取的客观信号形成，包括联系人信息、银行账号、地址、法定代表人、报价异常、非模板文本重合、结构同源、授权链和时间轨迹等线索。",
        "",
        "## 三、审查发现",
        "",
        findings,
        "",
        "## 四、风险评分摘要",
        "",
        _format_risk_summary(risk_summary),
        "",
        "## 五、主要证据摘要",
        "",
        _format_evidence_summary(evidence_summary),
        "",
        "## 六、初步审查意见",
        "",
        conclusion,
        "",
        "## 七、建议措施",
        "",
        _recommendations(top_risk),
        "",
        "## 八、说明",
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
            "1. 结构包括：审查概况、审查依据与方法、审查发现、风险评分摘要、主要证据摘要、初步审查意见、建议措施、说明。",
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
            f"- {item['supplier_a']} 与 {item['supplier_b']}：总分 {item['total_score']}，风险等级 {item['risk_level']}。"
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
