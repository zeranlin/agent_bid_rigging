from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from agent_bid_rigging.models import ExtractedSignals, PairwiseAssessment

DOCUMENT_CATEGORY_RULES = [
    ("开标一览表", ("开标一览表", "投标总报价", "报价表")),
    ("分项报价表", ("分项报价表", "货物名称", "单价", "总价")),
    ("授权委托书", ("授权委托书", "授权委托人", "代理人")),
    ("基本情况表", ("基本情况表", "注册资金", "主营范围")),
    ("技术偏离表", ("技术偏离表", "偏离表", "偏离程度")),
    ("项目组成员表", ("项目组成员", "项目负责人", "技术负责人")),
    ("项目实施方案", ("实施方案", "培训方案", "售后服务", "验收")),
    ("业绩情况表", ("业绩情况", "类似项目业绩", "合同签订时间")),
    ("资格证明材料", ("营业执照", "经营许可证", "声明函", "资质")),
    ("厂家授权材料", ("授权书", "授权期限", "授权产品")),
]


def build_case_manifest(
    run_name: str,
    generated_at: str,
    tender_path: str,
    bids: dict[str, str],
    output_dir: Path,
    opinion_mode: str,
) -> dict:
    return {
        "case_id": run_name,
        "generated_at": generated_at,
        "output_dir": str(output_dir.resolve()),
        "input_summary": {
            "tender_count": 1,
            "bid_count": len(bids),
            "supplier_names": list(bids.keys()),
        },
        "source_paths": {
            "tender": tender_path,
            "bids": bids,
        },
        "opinion_mode": opinion_mode,
    }


def build_source_file_index(tender_path: str, bids: dict[str, str], generated_at: str) -> list[dict]:
    rows = [_source_row("tender", "tender", tender_path, generated_at, 1)]
    for index, (supplier_name, path) in enumerate(bids.items(), start=2):
        rows.append(_source_row("bid", supplier_name, path, generated_at, index))
    return rows


def build_extracted_file_index(signals: list[ExtractedSignals]) -> list[dict]:
    rows: list[dict] = []
    for signal in signals:
        components = signal.document.metadata.get("components", [])
        if not components:
            rows.append(
                {
                    "supplier": signal.document.name,
                    "document_role": signal.document.role,
                    "component_index": 1,
                    "display_name": Path(signal.document.path).name,
                    "relative_path": Path(signal.document.path).name,
                    "parser": signal.document.parser,
                    "chars": len(signal.document.text),
                    "title": signal.document.text.splitlines()[0][:120] if signal.document.text else "",
                }
            )
            continue
        for component in components:
            rows.append(
                {
                    "supplier": signal.document.name,
                    "document_role": signal.document.role,
                    "component_index": component["index"],
                    "display_name": component["display_name"],
                    "relative_path": component["relative_path"],
                    "parser": component["parser"],
                    "chars": component["chars"],
                    "title": component.get("title", ""),
                }
            )
    return rows


def build_document_catalog(signals: list[ExtractedSignals]) -> list[dict]:
    rows: list[dict] = []
    for signal in signals:
        components = signal.document.metadata.get("components", [])
        if not components:
            rows.append(
                {
                    "supplier": signal.document.name,
                    "document_name": Path(signal.document.path).name,
                    "category": classify_document(Path(signal.document.path).name, signal.document.text),
                    "confidence": "document-level",
                }
            )
            continue
        for component in components:
            rows.append(
                {
                    "supplier": signal.document.name,
                    "document_name": component["display_name"],
                    "category": classify_document(component["display_name"], component.get("title", "")),
                    "confidence": "heuristic",
                }
            )
    return rows


def build_entity_field_table(signals: list[ExtractedSignals]) -> list[dict]:
    rows: list[dict] = []
    for signal in signals:
        field_values = {
            "phones": signal.phones,
            "emails": signal.emails,
            "bank_accounts": signal.bank_accounts,
            "legal_representatives": signal.legal_representatives,
            "addresses": signal.addresses,
            "bid_amounts": [f"{amount:.2f}" for amount in signal.bid_amounts],
        }
        for field_name, values in field_values.items():
            rows.append(
                {
                    "supplier": signal.document.name,
                    "field_name": field_name,
                    "values": values,
                    "source_document": signal.document.path,
                    "source_page": None,
                }
            )
    return rows


def build_price_analysis_table(signals: list[ExtractedSignals]) -> list[dict]:
    rows: list[dict] = []
    priced = [
        (signal.document.name, min(signal.bid_amounts))
        for signal in signals
        if signal.bid_amounts
    ]
    for signal in signals:
        current = min(signal.bid_amounts) if signal.bid_amounts else None
        nearest_gap = None
        nearest_supplier = None
        if current is not None:
            candidates = [
                (supplier, abs(price - current))
                for supplier, price in priced
                if supplier != signal.document.name
            ]
            if candidates:
                nearest_supplier, nearest_gap = min(candidates, key=lambda item: item[1])
        rows.append(
            {
                "supplier": signal.document.name,
                "bid_amount": f"{current:.2f}" if current is not None else None,
                "nearest_supplier": nearest_supplier,
                "nearest_gap": f"{nearest_gap:.2f}" if nearest_gap is not None else None,
            }
        )
    return rows


def build_review_conclusion_table(assessments: list[PairwiseAssessment]) -> dict:
    facts: list[str] = []
    suspicious_clues: list[str] = []
    exclusionary_factors: list[str] = []
    recommendations: list[str] = []

    for assessment in assessments:
        pair_label = f"{assessment.supplier_a} 与 {assessment.supplier_b}"
        if assessment.findings:
            suspicious_clues.append(
                f"{pair_label} 存在 {assessment.risk_level} 风险线索，分值 {assessment.risk_score}。"
            )
        else:
            exclusionary_factors.append(f"{pair_label} 未发现明显异常信号。")
        for finding in assessment.findings:
            facts.append(f"{pair_label}：{finding.title}。")

    if not suspicious_clues:
        recommendations.append("当前未见强异常，可保留底稿作为后续抽查依据。")
    else:
        recommendations.append("建议围绕高分供应商对补查原始电子文件、签章、时间线和外围关联信息。")

    return {
        "verified_facts": facts,
        "suspicious_clues": suspicious_clues,
        "exclusionary_factors": exclusionary_factors,
        "recommendations": recommendations,
    }


def classify_document(name: str, title: str) -> str:
    corpus = f"{name}\n{title}"
    for category, keywords in DOCUMENT_CATEGORY_RULES:
        if any(keyword in corpus for keyword in keywords):
            return category
    return "unknown"


def _source_row(role: str, label: str, path: str, generated_at: str, index: int) -> dict:
    file_path = Path(path).expanduser().resolve()
    stat = file_path.stat()
    return {
        "file_id": f"F{index:03d}",
        "role": role,
        "label": label,
        "path": str(file_path),
        "size_bytes": stat.st_size,
        "received_at": generated_at,
        "sha256": _sha256(file_path),
    }


def _sha256(path: Path) -> str:
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    digest = hashlib.sha256()
    for child in sorted(path.rglob("*")):
        if child.is_file():
            digest.update(str(child.relative_to(path)).encode("utf-8"))
            digest.update(child.read_bytes())
    return digest.hexdigest()
