from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from agent_bid_rigging.core.extractor import build_tender_baseline, extract_signals
from agent_bid_rigging.core.scoring import assess_pairs
from agent_bid_rigging.models import ExtractedSignals
from agent_bid_rigging.utils.file_loader import load_document


def run_review(
    tender_path: str,
    bids: dict[str, str],
    output_dir: str | None = None,
    label: str | None = None,
) -> dict:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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

    report = {
        "run_name": run_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tender": tender_doc.to_dict(),
        "suppliers": list(bids.keys()),
        "pairwise_assessments": [assessment.to_dict() for assessment in assessments],
    }
    manifest = {
        "run_name": run_name,
        "output_dir": str(base_dir.resolve()),
        "tender_path": tender_doc.path,
        "bid_paths": bids,
    }

    _write_json(base_dir / "manifest.json", manifest)
    _write_json(base_dir / "pairwise_report.json", report)
    (base_dir / "summary.md").write_text(_build_summary(report), encoding="utf-8")
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
