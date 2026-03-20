from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from agent_bid_rigging.core.artifacts import (
    build_authorization_chain_table,
    build_case_manifest,
    build_document_catalog,
    build_duplicate_detection_table,
    build_evidence_grade_table,
    build_entity_field_table,
    build_extracted_file_index,
    build_file_fingerprint_table,
    build_formal_report,
    build_formal_report_markdown,
    build_price_analysis_table,
    build_review_conclusion_table,
    build_risk_score_table,
    build_source_file_index,
    build_structure_similarity_table,
    build_shared_error_table,
    build_text_similarity_table,
    build_timeline_table,
    build_license_match_table,
)
from agent_bid_rigging.core.extractor import build_tender_baseline, extract_signals
from agent_bid_rigging.core.llm_review import generate_llm_review_layers
from agent_bid_rigging.core.opinion import generate_review_opinion
from agent_bid_rigging.core.scoring import assess_pairs
from agent_bid_rigging.models import ExtractedSignals
from agent_bid_rigging.utils.file_loader import load_document


def run_review(
    tender_path: str,
    bids: dict[str, str],
    output_dir: str | None = None,
    label: str | None = None,
    opinion_mode: str = "auto",
) -> dict:
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    generated_at = now.isoformat(timespec="seconds")
    run_name = label or f"review_{timestamp}"
    base_dir = Path(output_dir) if output_dir else Path("runs") / run_name
    base_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir = base_dir / "normalized"
    normalized_dir.mkdir(exist_ok=True)

    tender_doc = load_document("tender", "tender", tender_path)
    tender_lines = build_tender_baseline(tender_doc)
    bid_signals: list[ExtractedSignals] = []

    for supplier_name, path in bids.items():
        loaded = load_document(supplier_name, "bid", path)
        signals = extract_signals(loaded, tender_lines=tender_lines)
        bid_signals.append(signals)
        _write_json(normalized_dir / f"{supplier_name}.json", signals.to_dict())

    assessments = assess_pairs(bid_signals)
    assessment_dicts = [assessment.to_dict() for assessment in assessments]

    case_manifest = build_case_manifest(
        run_name=run_name,
        generated_at=generated_at,
        tender_path=tender_path,
        bids=bids,
        output_dir=base_dir,
        opinion_mode=opinion_mode,
    )
    source_file_index = build_source_file_index(tender_path, bids, generated_at)
    extracted_file_index = build_extracted_file_index(bid_signals)
    document_catalog = build_document_catalog(bid_signals)
    entity_field_table = build_entity_field_table(bid_signals)
    price_analysis_table = build_price_analysis_table(bid_signals)
    structure_similarity_table = build_structure_similarity_table(bid_signals)
    file_fingerprint_table = build_file_fingerprint_table(bid_signals)
    duplicate_detection_table = build_duplicate_detection_table(bid_signals)
    text_similarity_table = build_text_similarity_table(bid_signals)
    shared_error_table = build_shared_error_table(bid_signals)
    authorization_chain_table = build_authorization_chain_table(bid_signals)
    license_match_table = build_license_match_table(bid_signals)
    timeline_table = build_timeline_table(bid_signals)
    review_conclusion_table = build_review_conclusion_table(assessments)
    evidence_grade_table = build_evidence_grade_table(assessments)
    risk_score_table = build_risk_score_table(
        assessments=assessments,
        structure_similarity_table=structure_similarity_table,
        duplicate_detection_table=duplicate_detection_table,
        text_similarity_table=text_similarity_table,
        authorization_chain_table=authorization_chain_table,
        timeline_table=timeline_table,
    )
    formal_report = build_formal_report(
        case_manifest=case_manifest,
        document_catalog=document_catalog,
        review_conclusion_table=review_conclusion_table,
        evidence_grade_table=evidence_grade_table,
        risk_score_table=risk_score_table,
        tender_document=tender_doc.to_dict(),
        bid_documents=[signal.to_dict() for signal in bid_signals],
        price_analysis_table=price_analysis_table,
        structure_similarity_table=structure_similarity_table,
        authorization_chain_table=authorization_chain_table,
        timeline_table=timeline_table,
    )
    formal_report_markdown = build_formal_report_markdown(formal_report)

    report = {
        "run_name": run_name,
        "generated_at": generated_at,
        "tender": tender_doc.to_dict(),
        "suppliers": list(bids.keys()),
        "normalized_documents": [signal.to_dict() for signal in bid_signals],
        "pairwise_assessments": assessment_dicts,
        "case_manifest": case_manifest,
        "source_file_index": source_file_index,
        "extracted_file_index": extracted_file_index,
        "document_catalog": document_catalog,
        "entity_field_table": entity_field_table,
        "price_analysis_table": price_analysis_table,
        "structure_similarity_table": structure_similarity_table,
        "file_fingerprint_table": file_fingerprint_table,
        "duplicate_detection_table": duplicate_detection_table,
        "text_similarity_table": text_similarity_table,
        "shared_error_table": shared_error_table,
        "authorization_chain_table": authorization_chain_table,
        "license_match_table": license_match_table,
        "timeline_table": timeline_table,
        "evidence_grade_table": evidence_grade_table,
        "risk_score_table": risk_score_table,
        "review_conclusion_table": review_conclusion_table,
        "formal_report": formal_report,
    }
    llm_review_layers = None
    llm_review_error = None
    try:
        llm_review_layers = generate_llm_review_layers(
            report,
            formal_report_markdown=formal_report_markdown,
            opinion_mode=opinion_mode,
        )
    except Exception as exc:  # noqa: BLE001
        llm_review_error = str(exc)

    if llm_review_layers and llm_review_layers.get("section_report"):
        formal_report_markdown = llm_review_layers["section_report"]
    if llm_review_layers:
        report["llm_review_layers"] = llm_review_layers
    if llm_review_error:
        report["llm_review_error"] = llm_review_error

    opinion = generate_review_opinion(report, opinion_mode=opinion_mode, llm_review_layers=llm_review_layers)

    _write_json(base_dir / "manifest.json", case_manifest)
    _write_json(base_dir / "case_manifest.json", case_manifest)
    _write_json(base_dir / "source_file_index.json", {"rows": source_file_index})
    _write_json(base_dir / "extracted_file_index.json", {"rows": extracted_file_index})
    _write_json(base_dir / "document_catalog.json", {"rows": document_catalog})
    _write_json(base_dir / "entity_field_table.json", {"rows": entity_field_table})
    _write_json(base_dir / "price_analysis_table.json", {"rows": price_analysis_table})
    _write_json(base_dir / "structure_similarity_table.json", {"rows": structure_similarity_table})
    _write_json(base_dir / "file_fingerprint_table.json", {"rows": file_fingerprint_table})
    _write_json(base_dir / "duplicate_detection_table.json", {"rows": duplicate_detection_table})
    _write_json(base_dir / "text_similarity_table.json", {"rows": text_similarity_table})
    _write_json(base_dir / "shared_error_table.json", {"rows": shared_error_table})
    _write_json(base_dir / "authorization_chain_table.json", {"rows": authorization_chain_table})
    _write_json(base_dir / "license_match_table.json", {"rows": license_match_table})
    _write_json(base_dir / "timeline_table.json", {"rows": timeline_table})
    _write_json(base_dir / "evidence_grade_table.json", {"rows": evidence_grade_table})
    _write_json(base_dir / "risk_score_table.json", {"rows": risk_score_table})
    _write_json(base_dir / "review_conclusion_table.json", review_conclusion_table)
    _write_json(base_dir / "formal_report.json", formal_report)
    if llm_review_layers:
        _write_json(base_dir / "llm_review_layers.json", llm_review_layers)
        (base_dir / "llm_evidence_interpretation.md").write_text(
            llm_review_layers["evidence_interpretation"],
            encoding="utf-8",
        )
        (base_dir / "llm_section_report.md").write_text(
            llm_review_layers["section_report"],
            encoding="utf-8",
        )
        (base_dir / "llm_conclusion_memo.md").write_text(
            llm_review_layers["conclusion_memo"],
            encoding="utf-8",
        )
    _write_json(base_dir / "pairwise_report.json", report)
    (base_dir / "summary.md").write_text(_build_summary(report), encoding="utf-8")
    (base_dir / "formal_report.md").write_text(formal_report_markdown, encoding="utf-8")
    _write_json(base_dir / "opinion.json", opinion)
    (base_dir / "opinion.md").write_text(opinion["document"], encoding="utf-8")
    return report


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_summary(report: dict) -> str:
    lines = [
        f"# 围串标审查报告: {report['run_name']}",
        "",
        f"- 生成时间: {report['generated_at']}",
        f"- 供应商数量: {len(report['suppliers'])}",
        "",
        "## 总体结论",
        "",
        _overall_conclusion(report["pairwise_assessments"]),
        "",
        "## 两两风险结果",
        "",
    ]
    if not report["pairwise_assessments"]:
        lines.append("没有可比较的供应商对。")
        return "\n".join(lines)

    for item in report["pairwise_assessments"]:
        lines.append(
            f"### {item['supplier_a']} vs {item['supplier_b']} - {item['risk_level']} ({item['risk_score']})"
        )
        if not item["findings"]:
            lines.append("- 未发现明显异常信号。")
            lines.append("")
            continue
        for finding in item["findings"]:
            evidence = "；".join(finding["evidence"])
            lines.append(f"- {finding['title']} [+{finding['weight']}]: {evidence}")
        lines.append("")
    return "\n".join(lines)


def _overall_conclusion(assessments: list[dict]) -> str:
    if not assessments:
        return "没有可比较的供应商对。"
    top = max(assessments, key=lambda item: item["risk_score"])
    if top["risk_level"] == "critical":
        return f"发现高强度异常线索，当前最需重点复核的供应商对为 {top['supplier_a']} 与 {top['supplier_b']}。"
    if top["risk_level"] == "high":
        return f"发现较高强度异常线索，当前最需重点复核的供应商对为 {top['supplier_a']} 与 {top['supplier_b']}。"
    if top["risk_level"] == "medium":
        return f"发现一定异常线索，建议优先复核 {top['supplier_a']} 与 {top['supplier_b']}。"
    return "未发现足以支持明显围串标怀疑的强异常信号。"
