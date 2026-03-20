from __future__ import annotations

import hashlib
import re
from datetime import datetime
from itertools import combinations
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
AUTHORIZATION_PATTERNS = ("授权书", "授权期限", "授权产品", "厂家授权", "授权对象")
LICENSE_PATTERNS = ("营业执照", "经营许可证", "注册证", "检验报告", "许可证")


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


def build_structure_similarity_table(signals: list[ExtractedSignals]) -> list[dict]:
    rows: list[dict] = []
    for left, right in combinations(signals, 2):
        left_components = left.document.metadata.get("components", [])
        right_components = right.document.metadata.get("components", [])
        left_categories = [classify_document(c["display_name"], c.get("title", "")) for c in left_components]
        right_categories = [classify_document(c["display_name"], c.get("title", "")) for c in right_components]
        shared_categories = sorted(set(left_categories) & set(right_categories))
        sequence_overlap = _jaccard(left_categories, right_categories)
        rows.append(
            {
                "supplier_a": left.document.name,
                "supplier_b": right.document.name,
                "file_count_a": len(left_components) or 1,
                "file_count_b": len(right_components) or 1,
                "shared_categories": shared_categories,
                "category_overlap_ratio": round(sequence_overlap, 4),
                "naming_style_similarity": _naming_style_similarity(left_components, right_components),
            }
        )
    return rows


def build_file_fingerprint_table(signals: list[ExtractedSignals]) -> list[dict]:
    rows: list[dict] = []
    for signal in signals:
        components = signal.document.metadata.get("components", [])
        if not components:
            rows.append(
                {
                    "supplier": signal.document.name,
                    "display_name": Path(signal.document.path).name,
                    "size_bytes": signal.document.metadata.get("size_bytes"),
                    "sha256": signal.text_hash,
                }
            )
            continue
        for component in components:
            rows.append(
                {
                    "supplier": signal.document.name,
                    "display_name": component["display_name"],
                    "relative_path": component["relative_path"],
                    "size_bytes": component.get("size_bytes"),
                    "sha256": component.get("sha256"),
                }
            )
    return rows


def build_duplicate_detection_table(signals: list[ExtractedSignals]) -> list[dict]:
    rows: list[dict] = []
    for left, right in combinations(signals, 2):
        left_hashes = {
            component.get("sha256"): component
            for component in left.document.metadata.get("components", [])
            if component.get("sha256")
        }
        right_hashes = {
            component.get("sha256"): component
            for component in right.document.metadata.get("components", [])
            if component.get("sha256")
        }
        overlap = sorted(set(left_hashes) & set(right_hashes))
        rows.append(
            {
                "supplier_a": left.document.name,
                "supplier_b": right.document.name,
                "duplicate_count": len(overlap),
                "duplicates": [
                    {
                        "sha256": sha,
                        "file_a": left_hashes[sha]["display_name"],
                        "file_b": right_hashes[sha]["display_name"],
                    }
                    for sha in overlap[:20]
                ],
                "classification": (
                    "完全一致" if overlap else "完全不同"
                ),
            }
        )
    return rows


def build_text_similarity_table(signals: list[ExtractedSignals]) -> list[dict]:
    rows: list[dict] = []
    for left, right in combinations(signals, 2):
        rows.append(
            {
                "supplier_a": left.document.name,
                "supplier_b": right.document.name,
                "full_text_similarity": round(
                    _jaccard(_sentence_ngrams(left.document.text), _sentence_ngrams(right.document.text)),
                    4,
                ),
                "implementation_similarity": round(
                    _jaccard(
                        _targeted_sentences(left.document.text, ("实施", "售后", "培训", "验收")),
                        _targeted_sentences(right.document.text, ("实施", "售后", "培训", "验收")),
                    ),
                    4,
                ),
                "technical_deviation_similarity": round(
                    _jaccard(
                        _targeted_sentences(left.document.text, ("偏离", "响应", "技术参数")),
                        _targeted_sentences(right.document.text, ("偏离", "响应", "技术参数")),
                    ),
                    4,
                ),
            }
        )
    return rows


def build_shared_error_table(signals: list[ExtractedSignals]) -> list[dict]:
    rows: list[dict] = []
    for left, right in combinations(signals, 2):
        shared = sorted(
            set(_error_like_lines(left.document.text)) & set(_error_like_lines(right.document.text))
        )
        rows.append(
            {
                "supplier_a": left.document.name,
                "supplier_b": right.document.name,
                "shared_error_count": len(shared),
                "shared_examples": shared[:10],
            }
        )
    return rows


def build_authorization_chain_table(signals: list[ExtractedSignals]) -> list[dict]:
    rows: list[dict] = []
    for signal in signals:
        text = signal.document.text
        rows.append(
            {
                "supplier": signal.document.name,
                "manufacturer_mentions": _extract_named_values(text, ("制造商名称", "生产厂家", "制造商")),
                "authorization_mentions": _find_lines(text, AUTHORIZATION_PATTERNS)[:20],
                "summary": "发现授权/厂家关键词" if _find_lines(text, AUTHORIZATION_PATTERNS) else "未发现明确授权链线索",
            }
        )
    return rows


def build_license_match_table(signals: list[ExtractedSignals]) -> list[dict]:
    rows: list[dict] = []
    for signal in signals:
        text = signal.document.text
        lines = _find_lines(text, LICENSE_PATTERNS)
        registration_ids = sorted(set(re.findall(r"[A-Z0-9]{6,}-?[A-Z0-9-]*", text)))
        rows.append(
            {
                "supplier": signal.document.name,
                "license_lines": lines[:20],
                "registration_ids": registration_ids[:20],
            }
        )
    return rows


def build_timeline_table(signals: list[ExtractedSignals]) -> list[dict]:
    rows: list[dict] = []
    for signal in signals:
        components = signal.document.metadata.get("components", [])
        if not components:
            rows.append(
                {
                    "supplier": signal.document.name,
                    "component_count": 1,
                    "modified_times": [],
                    "summary": "无组件级时间信息",
                }
            )
            continue
        modified_times = [component.get("modified_at") for component in components if component.get("modified_at")]
        rows.append(
            {
                "supplier": signal.document.name,
                "component_count": len(components),
                "modified_times": modified_times[:20],
                "summary": (
                    "存在集中生成迹象"
                    if len(set(modified_times)) <= max(1, len(modified_times) // 4)
                    else "未见明显集中生成特征"
                ),
            }
        )
    return rows


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


def _jaccard(left: list[str] | set[str], right: list[str] | set[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    union = left_set | right_set
    if not union:
        return 0.0
    return len(left_set & right_set) / len(union)


def _naming_style_similarity(left_components: list[dict], right_components: list[dict]) -> str:
    left_names = {_normalize_name_style(item["display_name"]) for item in left_components}
    right_names = {_normalize_name_style(item["display_name"]) for item in right_components}
    score = _jaccard(left_names, right_names)
    if score >= 0.8:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


def _normalize_name_style(name: str) -> str:
    return re.sub(r"\d+", "#", name.lower())


def _sentence_ngrams(text: str, size: int = 12) -> set[str]:
    compact = re.sub(r"\s+", "", text)
    return {
        compact[i : i + size]
        for i in range(max(0, len(compact) - size + 1))
        if re.search(r"[\u4e00-\u9fffA-Za-z]", compact[i : i + size])
    }


def _targeted_sentences(text: str, keywords: tuple[str, ...]) -> list[str]:
    lines = []
    for line in re.split(r"[\n。；]", text):
        stripped = line.strip()
        if len(stripped) >= 12 and any(keyword in stripped for keyword in keywords):
            lines.append(stripped)
    return lines


def _error_like_lines(text: str) -> list[str]:
    lines: list[str] = []
    for line in re.split(r"[\n。；]", text):
        stripped = line.strip()
        if len(stripped) < 12:
            continue
        if any(token in stripped for token in ("错", "有误", "负偏离", "不满足", "缺失")):
            lines.append(stripped)
    return lines


def _find_lines(text: str, keywords: tuple[str, ...]) -> list[str]:
    rows: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and any(keyword in stripped for keyword in keywords):
            rows.append(stripped[:200])
    return rows


def _extract_named_values(text: str, field_names: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for field_name in field_names:
        pattern = re.compile(rf"{re.escape(field_name)}\s*[:：]?\s*([^\n]{{2,120}})")
        values.extend(match.strip() for match in pattern.findall(text))
    return values[:20]
