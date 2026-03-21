from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from agent_bid_rigging.capabilities.ocr import OcrCapability
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
from agent_bid_rigging.core.fusion import (
    append_ocr_authorization_rows,
    append_ocr_entity_rows,
    append_ocr_license_rows,
    merge_ocr_into_signal,
    renumber_ocr_rows,
    run_ocr_collection,
)
from agent_bid_rigging.core.llm_review import generate_llm_review_layers
from agent_bid_rigging.core.opinion import generate_review_opinion
from agent_bid_rigging.core.scoring import assess_pairs
from agent_bid_rigging.utils.file_loader import load_document
from agent_bid_rigging.utils.openai_client import OpenAIResponsesClient


def run_review(
    tender_path: str,
    bids: dict[str, str],
    output_dir: str | None = None,
    label: str | None = None,
    opinion_mode: str = "auto",
    enable_ocr: bool = False,
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
    image_index_rows: list[dict] = []
    image_ocr_rows: list[dict] = []
    ocr_capability = OcrCapability() if enable_ocr else None

    if ocr_capability is not None:
        tender_ocr = run_ocr_collection(
            capability=ocr_capability,
            run_name=run_name,
            role="tender",
            supplier=None,
            source_path=tender_path,
            output_dir=base_dir / "ocr" / "tender",
        )
        image_index_rows.extend(tender_ocr["image_index_rows"])
        image_ocr_rows.extend(tender_ocr["image_ocr_rows"])

    for supplier_name, path in bids.items():
        loaded = load_document(supplier_name, "bid", path)
        signals = extract_signals(loaded, tender_lines=tender_lines)
        if ocr_capability is not None:
            bid_ocr = run_ocr_collection(
                capability=ocr_capability,
                run_name=run_name,
                role="bid",
                supplier=supplier_name,
                source_path=path,
                output_dir=base_dir / "ocr" / supplier_name,
            )
            image_index_rows.extend(bid_ocr["image_index_rows"])
            image_ocr_rows.extend(bid_ocr["image_ocr_rows"])
            merge_ocr_into_signal(signals, bid_ocr["image_ocr_rows"])
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
    renumber_ocr_rows(image_index_rows, image_ocr_rows)
    if image_ocr_rows:
        append_ocr_entity_rows(entity_field_table, image_ocr_rows)
        append_ocr_authorization_rows(authorization_chain_table, image_ocr_rows)
        append_ocr_license_rows(license_match_table, image_ocr_rows)
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
    rule_formal_report_markdown = build_formal_report_markdown(formal_report)

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
        "image_index": image_index_rows,
        "image_ocr_table": image_ocr_rows,
        "evidence_grade_table": evidence_grade_table,
        "risk_score_table": risk_score_table,
        "review_conclusion_table": review_conclusion_table,
        "formal_report": formal_report,
    }

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
    _write_json(base_dir / "image_index.json", {"rows": image_index_rows})
    _write_json(base_dir / "image_ocr_table.json", {"rows": image_ocr_rows})
    _write_json(base_dir / "evidence_grade_table.json", {"rows": evidence_grade_table})
    _write_json(base_dir / "risk_score_table.json", {"rows": risk_score_table})
    _write_json(base_dir / "review_conclusion_table.json", review_conclusion_table)
    _write_json(base_dir / "formal_report.json", formal_report)
    (base_dir / "summary.md").write_text(_build_summary(report), encoding="utf-8")
    _write_json(base_dir / "formal_report.rule.json", formal_report)
    (base_dir / "formal_report.rule.md").write_text(rule_formal_report_markdown, encoding="utf-8")
    (base_dir / "formal_report.md").write_text(rule_formal_report_markdown, encoding="utf-8")

    llm_requested = _llm_requested(opinion_mode)
    llm_status = {
        "requested_mode": opinion_mode,
        "state": "not-requested" if not llm_requested else "running",
    }
    _write_json(base_dir / "llm_status.json", llm_status)
    _write_json(base_dir / "pairwise_report.json", report)

    if llm_requested and _use_async_llm():
        rule_opinion = generate_review_opinion(report, opinion_mode="template")
        pending_opinion = _pending_llm_opinion(report)
        _write_json(base_dir / "opinion.json", pending_opinion)
        (base_dir / "opinion.md").write_text(pending_opinion["document"], encoding="utf-8")
        _write_json(base_dir / "opinion.rule.json", rule_opinion)
        (base_dir / "opinion.rule.md").write_text(rule_opinion["document"], encoding="utf-8")
        report["llm_status"] = llm_status
        _spawn_llm_finisher(base_dir)
        return report

    llm_review_layers = None
    llm_review_error = None
    try:
        llm_review_layers = generate_llm_review_layers(
            report,
            formal_report_markdown=rule_formal_report_markdown,
            opinion_mode=opinion_mode,
        )
    except Exception as exc:  # noqa: BLE001
        llm_review_error = str(exc)

    llm_formal_report_markdown = None
    if llm_review_layers and llm_review_layers.get("section_report"):
        llm_formal_report_markdown = llm_review_layers["section_report"]
    if llm_review_layers:
        report["llm_review_layers"] = llm_review_layers
        llm_status = {
            "requested_mode": opinion_mode,
            "state": "completed",
            "generated_at": llm_review_layers.get("generated_at"),
        }
    if llm_review_error:
        report["llm_review_error"] = llm_review_error
        llm_status = {
            "requested_mode": opinion_mode,
            "state": "failed",
            "error": llm_review_error,
        }

    opinion = generate_review_opinion(report, opinion_mode=opinion_mode, llm_review_layers=llm_review_layers)
    rule_opinion = generate_review_opinion(report, opinion_mode="template")
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
        _write_json(base_dir / "formal_report.llm.json", formal_report)
        if llm_formal_report_markdown:
            (base_dir / "formal_report.llm.md").write_text(llm_formal_report_markdown, encoding="utf-8")
        _write_json(base_dir / "opinion.llm.json", opinion)
        (base_dir / "opinion.llm.md").write_text(opinion["document"], encoding="utf-8")
    _write_json(base_dir / "llm_status.json", llm_status)
    _write_json(base_dir / "pairwise_report.json", report)
    _write_json(base_dir / "opinion.rule.json", rule_opinion)
    (base_dir / "opinion.rule.md").write_text(rule_opinion["document"], encoding="utf-8")
    final_formal_report_markdown = llm_formal_report_markdown or rule_formal_report_markdown
    (base_dir / "formal_report.md").write_text(final_formal_report_markdown, encoding="utf-8")
    _write_json(base_dir / "opinion.json", opinion)
    (base_dir / "opinion.md").write_text(opinion["document"], encoding="utf-8")
    return report


def finish_llm_review(run_dir: str) -> dict:
    base_dir = Path(run_dir).expanduser().resolve()
    report = _load_report_context(base_dir)
    formal_report_markdown = (
        (base_dir / "formal_report.rule.md").read_text(encoding="utf-8")
        if (base_dir / "formal_report.rule.md").exists()
        else (base_dir / "formal_report.md").read_text(encoding="utf-8")
    )
    llm_status = {
        "requested_mode": report.get("case_manifest", {}).get("opinion_mode", "llm"),
        "state": "running",
    }
    _write_json(base_dir / "llm_status.json", llm_status)

    try:
        llm_review_layers = generate_llm_review_layers(
            report,
            formal_report_markdown=formal_report_markdown,
            opinion_mode="llm",
        )
        if not llm_review_layers:
            raise RuntimeError("LLM layers were not generated.")

        report["llm_review_layers"] = llm_review_layers
        llm_formal_report_markdown = llm_review_layers.get("section_report", formal_report_markdown)
        opinion = generate_review_opinion(report, opinion_mode="llm", llm_review_layers=llm_review_layers)
        rule_opinion = generate_review_opinion(report, opinion_mode="template")

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
        _write_json(base_dir / "formal_report.llm.json", report["formal_report"])
        (base_dir / "formal_report.llm.md").write_text(llm_formal_report_markdown, encoding="utf-8")
        (base_dir / "formal_report.md").write_text(llm_formal_report_markdown, encoding="utf-8")
        _write_json(base_dir / "opinion.rule.json", rule_opinion)
        (base_dir / "opinion.rule.md").write_text(rule_opinion["document"], encoding="utf-8")
        _write_json(base_dir / "opinion.llm.json", opinion)
        (base_dir / "opinion.llm.md").write_text(opinion["document"], encoding="utf-8")
        _write_json(base_dir / "opinion.json", opinion)
        (base_dir / "opinion.md").write_text(opinion["document"], encoding="utf-8")
        llm_status = {
            "requested_mode": "llm",
            "state": "completed",
            "generated_at": llm_review_layers.get("generated_at"),
        }
    except Exception as exc:  # noqa: BLE001
        report["llm_review_error"] = str(exc)
        fallback = generate_review_opinion(report, opinion_mode="template")
        _write_json(base_dir / "opinion.rule.json", fallback)
        (base_dir / "opinion.rule.md").write_text(fallback["document"], encoding="utf-8")
        _write_json(base_dir / "opinion.json", fallback)
        (base_dir / "opinion.md").write_text(fallback["document"], encoding="utf-8")
        llm_status = {
            "requested_mode": "llm",
            "state": "failed",
            "error": str(exc),
        }

    report["llm_status"] = llm_status
    _write_json(base_dir / "llm_status.json", llm_status)
    _write_json(base_dir / "pairwise_report.json", report)
    return llm_status


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


def _llm_requested(opinion_mode: str) -> bool:
    if opinion_mode == "llm":
        return True
    if opinion_mode == "auto":
        return OpenAIResponsesClient.is_configured()
    return False


def _use_async_llm() -> bool:
    return _env_truthy(os.environ.get("AGENT_BID_RIGGING_ASYNC_LLM", ""))


def _pending_llm_opinion(report: dict) -> dict:
    base = generate_review_opinion(report, opinion_mode="template")
    return {
        "mode": "pending-llm",
        "generated_at": base["generated_at"],
        "document": (
            base["document"]
            + "\n\n> 注：LLM 增强层仍在后台运行，完成后将自动更新本意见书与正式报告。"
        ),
    }


def _spawn_llm_finisher(base_dir: Path) -> None:
    subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-m",
            "agent_bid_rigging.cli",
            "finish-llm",
            "--run-dir",
            str(base_dir),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env=os.environ.copy(),
    )


def _env_truthy(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _load_report_context(base_dir: Path) -> dict:
    report_path = base_dir / "pairwise_report.json"
    if report_path.exists():
        return json.loads(report_path.read_text(encoding="utf-8"))

    case_manifest = json.loads((base_dir / "case_manifest.json").read_text(encoding="utf-8"))
    formal_report = json.loads((base_dir / "formal_report.json").read_text(encoding="utf-8"))
    risk_score_table = json.loads((base_dir / "risk_score_table.json").read_text(encoding="utf-8"))["rows"]
    evidence_grade_table = json.loads((base_dir / "evidence_grade_table.json").read_text(encoding="utf-8"))["rows"]
    review_conclusion_table = json.loads((base_dir / "review_conclusion_table.json").read_text(encoding="utf-8"))
    image_index = _read_rows_file(base_dir / "image_index.json")
    image_ocr_table = _read_rows_file(base_dir / "image_ocr_table.json")
    normalized_documents = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((base_dir / "normalized").glob("*.json"))
    ]
    pairwise_assessments = _rebuild_pairwise_assessments(risk_score_table, evidence_grade_table)
    return {
        "run_name": case_manifest["case_id"],
        "generated_at": case_manifest["generated_at"],
        "suppliers": case_manifest["input_summary"]["supplier_names"],
        "normalized_documents": normalized_documents,
        "pairwise_assessments": pairwise_assessments,
        "case_manifest": case_manifest,
        "risk_score_table": risk_score_table,
        "evidence_grade_table": evidence_grade_table,
        "review_conclusion_table": review_conclusion_table,
        "image_index": image_index,
        "image_ocr_table": image_ocr_table,
        "formal_report": formal_report,
    }


def _rebuild_pairwise_assessments(risk_rows: list[dict], evidence_rows: list[dict]) -> list[dict]:
    evidence_map: dict[tuple[str, str], list[dict]] = {}
    for row in evidence_rows:
        pair = row["pair"].split(" 与 ")
        if len(pair) != 2:
            continue
        key = (pair[0], pair[1])
        evidence_map.setdefault(key, []).append(
            {
                "title": row["finding_title"],
                "weight": _weight_from_finding_title(row["finding_title"]),
                "evidence": row.get("evidence", []),
            }
        )

    rows: list[dict] = []
    for item in risk_rows:
        key = (item["supplier_a"], item["supplier_b"])
        rows.append(
            {
                "supplier_a": item["supplier_a"],
                "supplier_b": item["supplier_b"],
                "risk_score": item["total_score"],
                "risk_level": item["risk_level"],
                "findings": evidence_map.get(key, []),
            }
        )
    return rows


def _weight_from_finding_title(title: str) -> int:
    weights = {
        "银行账号重合": 35,
        "联系人电话重合": 30,
        "邮箱重合": 25,
        "法定代表人信息重合": 25,
        "地址信息重合": 20,
        "投标报价完全一致": 35,
        "投标报价极度接近": 20,
        "投标报价较为接近": 10,
        "仅两家共享的非模板文本重合": 30,
    }
    return weights.get(title, 10)


def _read_rows_file(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("rows", [])
