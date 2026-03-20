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


def build_evidence_grade_table(assessments: list[PairwiseAssessment]) -> list[dict]:
    rows: list[dict] = []
    for assessment in assessments:
        pair_label = f"{assessment.supplier_a} 与 {assessment.supplier_b}"
        for finding in assessment.findings:
            rows.append(
                {
                    "pair": pair_label,
                    "finding_title": finding.title,
                    "evidence_grade": _evidence_grade(finding),
                    "reason": _evidence_reason(finding),
                    "evidence": finding.evidence,
                }
            )
    return rows


def build_risk_score_table(
    assessments: list[PairwiseAssessment],
    structure_similarity_table: list[dict],
    duplicate_detection_table: list[dict],
    text_similarity_table: list[dict],
    authorization_chain_table: list[dict],
    timeline_table: list[dict],
) -> list[dict]:
    structure_map = {(row["supplier_a"], row["supplier_b"]): row for row in structure_similarity_table}
    duplicate_map = {(row["supplier_a"], row["supplier_b"]): row for row in duplicate_detection_table}
    text_map = {(row["supplier_a"], row["supplier_b"]): row for row in text_similarity_table}
    timeline_map = {row["supplier"]: row for row in timeline_table}
    auth_map = {row["supplier"]: row for row in authorization_chain_table}

    rows: list[dict] = []
    for assessment in assessments:
        key = (assessment.supplier_a, assessment.supplier_b)
        structure_row = structure_map.get(key, {})
        duplicate_row = duplicate_map.get(key, {})
        text_row = text_map.get(key, {})

        file_homology = _finding_weight(
            assessment,
            {
                "文件完全一致",
                "文件高度同源",
                "文件指纹重合",
            },
        )
        pricing = _pricing_score(assessment)
        entity = _entity_score(assessment)
        text_score = _text_similarity_score(assessment)
        authorization = _finding_weight(assessment, {"授权链重合", "授权材料异常一致"})
        timeline = _finding_weight(assessment, {"时间轨迹异常接近", "创建修改时间高度重合"})
        total = assessment.risk_score

        rows.append(
            {
                "supplier_a": assessment.supplier_a,
                "supplier_b": assessment.supplier_b,
                "file_homology_score": file_homology,
                "pricing_score": pricing,
                "technical_text_score": text_score,
                "entity_link_score": entity,
                "authorization_score": authorization,
                "timeline_score": timeline,
                "total_score": total,
                "risk_level": assessment.risk_level,
                "explanation": (
                    f"主评分口径={assessment.risk_score}, "
                    f"结构相似度={structure_row.get('category_overlap_ratio', 0)}, "
                    f"重复文件数={duplicate_row.get('duplicate_count', 0)}, "
                    f"文本相似度={text_row.get('full_text_similarity', 0)}, "
                    f"授权支持={_authorization_indicator(auth_map.get(assessment.supplier_a, {}), auth_map.get(assessment.supplier_b, {}))}, "
                    f"时间支持={_timeline_indicator(timeline_map.get(assessment.supplier_a, {}), timeline_map.get(assessment.supplier_b, {}))}"
                ),
            }
        )
    return rows


def build_formal_report(
    case_manifest: dict,
    document_catalog: list[dict],
    review_conclusion_table: dict,
    evidence_grade_table: list[dict],
    risk_score_table: list[dict],
) -> dict:
    top_pair = max(risk_score_table, key=lambda item: item["total_score"], default=None)
    source_paths = case_manifest.get("source_paths", {})
    evidence_summary = evidence_grade_table[:12]
    fact_table = [
        {"序号": index, "事实内容": item, "性质": "已识别事实"}
        for index, item in enumerate(review_conclusion_table["verified_facts"], start=1)
    ]
    clue_table = [
        {
            "序号": index,
            "线索内容": item,
            "处置建议": "列为重点复核对象" if "critical" in item or "high" in item else "纳入一般复核",
        }
        for index, item in enumerate(review_conclusion_table["suspicious_clues"], start=1)
    ]
    exclusion_table = [
        {"序号": index, "排除事项": item, "说明": "当前自动审查未见明显异常。"}
        for index, item in enumerate(review_conclusion_table["exclusionary_factors"], start=1)
    ]
    risk_table = [
        {
            "供应商组合": f"{item['supplier_a']} / {item['supplier_b']}",
            "文件同源分": item["file_homology_score"],
            "报价异常分": item["pricing_score"],
            "文本相似分": item["technical_text_score"],
            "主体关联分": item["entity_link_score"],
            "授权关联分": item["authorization_score"],
            "时间轨迹分": item["timeline_score"],
            "总分": item["total_score"],
            "风险等级": item["risk_level"],
        }
        for item in risk_score_table
    ]
    report = {
        "project_basic_info": {
            "case_id": case_manifest["case_id"],
            "generated_at": case_manifest["generated_at"],
            "supplier_names": case_manifest["input_summary"]["supplier_names"],
        },
        "review_scope": {
            "tender_count": case_manifest["input_summary"]["tender_count"],
            "bid_count": case_manifest["input_summary"]["bid_count"],
            "document_catalog_count": len(document_catalog),
        },
        "document_acceptance": {
            "tender_source": source_paths.get("tender", ""),
            "bid_sources": source_paths.get("bids", {}),
        },
        "review_method": [
            "文件接收与建档",
            "文本与元数据抽取",
            "结构与同源性比对",
            "报价、主体、授权与时间线分析",
            "证据分级与风险评分",
        ],
        "review_basis": [
            "以采购人提供的招标文件、供应商提交的投标文件为基础材料。",
            "以自动抽取的结构化字段、文档分类、文本比对和风险评分结果为辅助审查依据。",
            "自动化结果仅作为审查线索，不直接替代行政认定或法律结论。",
        ],
        "review_findings": review_conclusion_table["verified_facts"],
        "suspicious_clues": review_conclusion_table["suspicious_clues"],
        "exclusionary_factors": review_conclusion_table["exclusionary_factors"],
        "fact_table": fact_table,
        "clue_table": clue_table,
        "exclusion_table": exclusion_table,
        "risk_table": risk_table,
        "preliminary_conclusion": _final_conclusion(top_pair),
        "follow_up_recommendations": review_conclusion_table["recommendations"],
        "audit_opinion": {
            "opinion_type": "自动审查意见",
            "main_statement": _final_conclusion(top_pair),
            "opinion_note": "现有结论系基于文件内容自动形成的复核意见，建议结合原始电子文件、外围关联信息和人工核验进一步确认。",
        },
        "evidence_summary": evidence_summary,
        "risk_summary": risk_score_table,
    }
    return report


def build_formal_report_markdown(report: dict) -> str:
    lines = [
        "# 政府采购围串标审查报告",
        "",
        "## 一、审查事项",
        "",
        f"案件编号：{report['project_basic_info']['case_id']}",
        "",
        f"本次审查围绕 {'、'.join(report['project_basic_info']['supplier_names'])} 等投标供应商提交的投标文件开展，重点核查投标文件之间是否存在异常关联、同源编制、报价协同或者其他疑似围串标线索。",
        "",
        "## 二、基本情况",
        "",
        f"- 生成时间：{report['project_basic_info']['generated_at']}",
        f"- 招标文件数量：{report['review_scope']['tender_count']}",
        f"- 投标文件数量：{report['review_scope']['bid_count']}",
        f"- 已编目文档数量：{report['review_scope']['document_catalog_count']}",
        "",
        "## 三、文件接收情况",
        "",
        f"- 招标文件来源：`{report['document_acceptance']['tender_source']}`",
    ]
    for supplier, source in report["document_acceptance"]["bid_sources"].items():
        lines.append(f"- {supplier} 投标文件来源：`{source}`")
    lines.extend(
        [
            "",
            "## 四、审查依据与方法",
            "",
        ]
    )
    for item in report["review_basis"]:
        lines.append(f"- {item}")
    lines.extend([""])
    for item in report["review_method"]:
        lines.append(f"- {item}")
    lines.extend(["", "## 五、审查事实表", ""])
    lines.extend(_render_markdown_table(report["fact_table"], ["序号", "事实内容", "性质"]))
    lines.extend(["", "## 六、异常线索表", ""])
    if report["clue_table"]:
        lines.extend(_render_markdown_table(report["clue_table"], ["序号", "线索内容", "处置建议"]))
    else:
        lines.append("未识别到需要重点说明的异常线索。")
    lines.extend(["", "## 七、排除性因素表", ""])
    if report["exclusion_table"]:
        lines.extend(_render_markdown_table(report["exclusion_table"], ["序号", "排除事项", "说明"]))
    else:
        lines.append("暂无明确排除性因素。")
    lines.extend(["", "## 八、风险评分表", ""])
    lines.extend(
        _render_markdown_table(
            report["risk_table"],
            ["供应商组合", "文件同源分", "报价异常分", "文本相似分", "主体关联分", "授权关联分", "时间轨迹分", "总分", "风险等级"],
        )
    )
    lines.extend(["", "## 九、主要证据摘要", ""])
    if report["evidence_summary"]:
        lines.extend(_render_markdown_table(report["evidence_summary"], ["pair", "finding_title", "evidence_grade", "reason"]))
    else:
        lines.append("暂无可归集的高价值证据摘要。")
    lines.extend(
        [
            "",
            "## 十、审查意见",
            "",
            report["audit_opinion"]["main_statement"],
            "",
            report["audit_opinion"]["opinion_note"],
            "",
            "## 十一、后续核查建议",
            "",
        ]
    )
    for item in report["follow_up_recommendations"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## 十二、说明",
            "",
            "本报告为自动审查底稿，结论应结合人工复核、原始电子文件和外围客观证据综合判断。",
        ]
    )
    return "\n".join(lines)


def _render_markdown_table(rows: list[dict], columns: list[str]) -> list[str]:
    if not rows:
        return ["无。"]
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join(["---"] * len(columns)) + " |"
    rendered = [header, divider]
    for row in rows:
        rendered.append("| " + " | ".join(_sanitize_cell(row.get(column, "")) for column in columns) + " |")
    return rendered


def _sanitize_cell(value: object) -> str:
    text = str(value)
    return text.replace("\n", "<br>").replace("|", "\\|")


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


def _evidence_grade(finding) -> str:
    if finding.title in {"银行账号重合", "联系人电话重合", "邮箱重合", "法定代表人信息重合"}:
        return "A"
    if "报价" in finding.title or "共享" in finding.title:
        return "B"
    if "文本重合" in finding.title:
        return "C"
    return "D"


def _evidence_reason(finding) -> str:
    grade = _evidence_grade(finding)
    return {
        "A": "高价值直接关联字段或强同源证据。",
        "B": "较强异常线索，需要结合其他证据判断。",
        "C": "辅助性文本或结构线索，不能单独定性。",
        "D": "背景信息或低强度信息。",
    }[grade]


def _pricing_score(assessment: PairwiseAssessment) -> int:
    for finding in assessment.findings:
        if finding.title == "投标报价完全一致":
            return 25
        if finding.title == "投标报价极度接近":
            return 18
        if finding.title == "投标报价较为接近":
            return 10
    return 0


def _entity_score(assessment: PairwiseAssessment) -> int:
    score = 0
    for finding in assessment.findings:
        if finding.title in {"联系人电话重合", "邮箱重合", "银行账号重合", "法定代表人信息重合", "地址信息重合"}:
            score += min(10, finding.weight)
    return min(30, score)


def _text_similarity_score(assessment: PairwiseAssessment) -> int:
    for finding in assessment.findings:
        if "文本重合" in finding.title:
            return finding.weight
    return 0


def _finding_weight(assessment: PairwiseAssessment, titles: set[str]) -> int:
    for finding in assessment.findings:
        if finding.title in titles:
            return finding.weight
    return 0


def _authorization_indicator(left: dict, right: dict) -> str:
    left_auth = set(left.get("manufacturer_mentions", []))
    right_auth = set(right.get("manufacturer_mentions", []))
    overlap = left_auth & right_auth
    if overlap:
        return f"shared:{len(overlap)}"
    return "none"


def _timeline_indicator(left: dict, right: dict) -> str:
    left_times = set(left.get("modified_times", []))
    right_times = set(right.get("modified_times", []))
    if left_times and right_times and left_times & right_times:
        return f"shared:{len(left_times & right_times)}"
    return "none"


def _risk_level_from_total(total: int) -> str:
    if total >= 75:
        return "critical"
    if total >= 45:
        return "high"
    if total >= 20:
        return "medium"
    return "low"


def _final_conclusion(top_pair: dict | None) -> str:
    if not top_pair:
        return "现有证据不足以形成实质性审查判断。"
    if top_pair["risk_level"] == "critical":
        return f"存在较强可疑线索，建议对 {top_pair['supplier_a']} 与 {top_pair['supplier_b']} 进一步取证。"
    if top_pair["risk_level"] == "high":
        return f"存在较强可疑线索，建议重点复核 {top_pair['supplier_a']} 与 {top_pair['supplier_b']}。"
    if top_pair["risk_level"] == "medium":
        return f"存在可疑线索，建议对 {top_pair['supplier_a']} 与 {top_pair['supplier_b']} 补充核查。"
    return "未发现明显异常。"
