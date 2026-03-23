from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from datetime import datetime
from itertools import combinations
from pathlib import Path

from agent_bid_rigging.models import ExtractedSignals, PairwiseAssessment, ReviewFacts, SupplierFacts

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
DIMENSION_LABELS = {
    "identity_link": "主体关联",
    "pricing_link": "报价关联",
    "text_similarity": "文本与方案关联",
    "file_homology": "结构同源",
    "authorization_chain": "授权与资质链",
    "timeline_trace": "时间与电子痕迹",
}
DIMENSION_ORDER = (
    "identity_link",
    "pricing_link",
    "text_similarity",
    "file_homology",
    "authorization_chain",
    "timeline_trace",
)
DIMENSION_TIER_LABELS = {
    "strong": "强",
    "medium": "中",
    "weak": "弱",
    "none": "未命中",
}


def _coerce_suppliers(payload: ReviewFacts | list[ExtractedSignals]) -> list[SupplierFacts] | None:
    if isinstance(payload, ReviewFacts):
        return payload.suppliers
    return None


def _observation_values(supplier: SupplierFacts, field_name: str) -> list[str]:
    observations = getattr(supplier, field_name)
    return [item.value for item in observations]


def _primary_value(supplier: SupplierFacts, field_name: str) -> str | None:
    observations = getattr(supplier, field_name)
    if not observations:
        return None
    for observation in observations:
        if observation.is_primary:
            return observation.value
    return observations[0].value


def _primary_source(supplier: SupplierFacts, field_name: str) -> tuple[str | None, int | None]:
    observations = getattr(supplier, field_name)
    if not observations:
        return None, None
    for observation in observations:
        if observation.is_primary:
            return observation.source_document, observation.source_page
    return observations[0].source_document, observations[0].source_page


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


def build_extracted_file_index(signals: ReviewFacts | list[ExtractedSignals]) -> list[dict]:
    rows: list[dict] = []
    supplier_facts = _coerce_suppliers(signals)
    if supplier_facts is not None:
        for supplier in supplier_facts:
            components = supplier.document.metadata.get("components", [])
            if not components:
                rows.append(
                    {
                        "supplier": supplier.supplier,
                        "document_role": supplier.document.role,
                        "component_index": 1,
                        "display_name": Path(supplier.document.path).name,
                        "relative_path": Path(supplier.document.path).name,
                        "parser": supplier.document.parser,
                        "chars": len(supplier.document.text),
                        "title": supplier.document.text.splitlines()[0][:120] if supplier.document.text else "",
                    }
                )
                continue
            for component in components:
                rows.append(
                    {
                        "supplier": supplier.supplier,
                        "document_role": supplier.document.role,
                        "component_index": component["index"],
                        "display_name": component["display_name"],
                        "relative_path": component["relative_path"],
                        "parser": component["parser"],
                        "chars": component["chars"],
                        "title": component.get("title", ""),
                    }
                )
        return rows
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


def build_document_catalog(signals: ReviewFacts | list[ExtractedSignals]) -> list[dict]:
    rows: list[dict] = []
    supplier_facts = _coerce_suppliers(signals)
    if supplier_facts is not None:
        for supplier in supplier_facts:
            components = supplier.document.metadata.get("components", [])
            if not components:
                rows.append(
                    {
                        "supplier": supplier.supplier,
                        "document_name": Path(supplier.document.path).name,
                        "category": classify_document(Path(supplier.document.path).name, supplier.document.text),
                        "confidence": "document-level",
                    }
                )
                continue
            for component in components:
                rows.append(
                    {
                        "supplier": supplier.supplier,
                        "document_name": component["display_name"],
                        "category": classify_document(component["display_name"], component.get("title", "")),
                        "confidence": "heuristic",
                    }
                )
        return rows
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


def build_entity_field_table(signals: ReviewFacts | list[ExtractedSignals]) -> list[dict]:
    rows: list[dict] = []
    supplier_facts = _coerce_suppliers(signals)
    if supplier_facts is not None:
        fact_fields = (
            "company_names",
            "contact_names",
            "phones",
            "emails",
            "bank_accounts",
            "unified_social_credit_codes",
            "legal_representatives",
            "authorized_representatives",
            "addresses",
            "bid_amounts",
        )
        for supplier in supplier_facts:
            for field_name in fact_fields:
                source_document, source_page = _primary_source(supplier, field_name)
                rows.append(
                    {
                        "supplier": supplier.supplier,
                        "field_name": field_name,
                        "values": _observation_values(supplier, field_name),
                        "source_document": source_document or supplier.document.path,
                        "source_page": source_page,
                    }
                )
        return rows
    for signal in signals:
        field_values = {
            "contact_names": getattr(signal, "contact_names", []),
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


def build_price_analysis_table(signals: ReviewFacts | list[ExtractedSignals]) -> list[dict]:
    rows: list[dict] = []
    supplier_facts = _coerce_suppliers(signals)
    if supplier_facts is not None:
        priced = []
        for supplier in supplier_facts:
            current_text = _primary_value(supplier, "bid_amounts")
            if current_text is not None:
                try:
                    priced.append((supplier.supplier, float(current_text)))
                except ValueError:
                    continue
        for supplier in supplier_facts:
            current_text = _primary_value(supplier, "bid_amounts")
            current = None
            if current_text is not None:
                try:
                    current = float(current_text)
                except ValueError:
                    current = None
            nearest_gap = None
            nearest_supplier = None
            if current is not None:
                candidates = [
                    (other_supplier, abs(price - current))
                    for other_supplier, price in priced
                    if other_supplier != supplier.supplier
                ]
                if candidates:
                    nearest_supplier, nearest_gap = min(candidates, key=lambda item: item[1])
            pricing_rows = list(getattr(supplier, "pricing_rows", []) or [])
            pricing_row_count = len(pricing_rows)
            tax_rates = sorted({str(row.get("tax_rate")).strip() for row in pricing_rows if str(row.get("tax_rate") or "").strip()})
            pricing_notes = sorted({str(row.get("pricing_note")).strip() for row in pricing_rows if str(row.get("pricing_note") or "").strip()})
            rows.append(
                {
                    "supplier": supplier.supplier,
                    "bid_amount": f"{current:.2f}" if current is not None else None,
                    "nearest_supplier": nearest_supplier,
                    "nearest_gap": f"{nearest_gap:.2f}" if nearest_gap is not None else None,
                    "pricing_row_count": pricing_row_count,
                    "tax_rates": tax_rates,
                    "pricing_notes": pricing_notes,
                }
            )
        return rows
    priced = [
        (signal.document.name, max(signal.bid_amounts))
        for signal in signals
        if signal.bid_amounts
    ]
    for signal in signals:
        current = max(signal.bid_amounts) if signal.bid_amounts else None
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
        if _assessment_has_actionable_clues(assessment):
            suspicious_clues.append(
                f"{pair_label} 存在需要进一步核查的可疑线索。"
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
                    "evidence_details": finding.evidence_details,
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
                "章节顺序高度同构",
                "章节顺序相似",
                "关键表格结构高度一致",
                "关键表格结构相似",
                "异常同构结构",
            },
        )
        pricing = _pricing_score(assessment)
        entity = _entity_score(assessment)
        text_score = _text_similarity_score(assessment)
        authorization = _finding_weight(
            assessment,
            {"授权链重合", "授权材料异常一致", "授权厂家重合", "授权方重合", "授权时间重合", "授权对象重合", "授权范围重合"},
        )
        timeline = _finding_weight(assessment, {"时间轨迹异常接近", "创建修改时间高度重合"})
        total = assessment.risk_score

        rows.append(
            {
                "supplier_a": assessment.supplier_a,
                "supplier_b": assessment.supplier_b,
                "dimension_summary": assessment.dimension_summary,
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
                    f"结构支持={_structure_indicator(assessment)}, "
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
    tender_document: dict | None = None,
    bid_documents: list[dict] | None = None,
    price_analysis_table: list[dict] | None = None,
    structure_similarity_table: list[dict] | None = None,
    section_similarity_table: list[dict] | None = None,
    authorization_chain_table: list[dict] | None = None,
    timeline_table: list[dict] | None = None,
    review_facts: ReviewFacts | None = None,
) -> dict:
    top_pair = max(risk_score_table, key=lambda item: item["total_score"], default=None)
    source_paths = case_manifest.get("source_paths", {})
    tender_metadata = _extract_tender_metadata((tender_document or {}).get("text", ""))
    supplier_profiles = (
        _build_supplier_profiles_from_facts(
            review_facts,
            price_analysis_table or [],
            authorization_chain_table or [],
            timeline_table or [],
        )
        if review_facts is not None
        else _build_supplier_profiles(
            bid_documents or [],
            price_analysis_table or [],
            authorization_chain_table or [],
            timeline_table or [],
        )
    )
    supplier_name_map = {profile["supplier"]: profile["full_name"] for profile in supplier_profiles}
    text_overlap_appendix = _build_text_overlap_appendix(evidence_grade_table, supplier_name_map)
    structure_summary = _build_structure_summary(
        structure_similarity_table or [],
        section_similarity_table or [],
        risk_score_table,
        evidence_grade_table,
        supplier_name_map,
    )
    suspicious_points = _build_suspicious_points(risk_score_table, evidence_grade_table, supplier_name_map)
    exclusion_points = _build_exclusion_points(review_conclusion_table, risk_score_table, supplier_name_map)
    further_checks = _build_further_checks(top_pair, supplier_name_map)
    dimension_summary_section = _build_dimension_summary_section(risk_score_table, supplier_name_map)
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
            "project_name": tender_metadata["project_name"],
            "project_id": tender_metadata["project_id"],
            "purchaser": tender_metadata["purchaser"],
            "agency": tender_metadata["agency"],
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
            "文本、章节与元数据抽取",
            "关键报价表抽取",
            "结构与同源性比对",
            "报价、主体、授权与时间线分析",
            "证据分级与风险评分",
        ],
        "review_basis": [
            "以采购人提供的招标文件、供应商提交的投标文件为基础材料。",
            "以自动抽取的结构化字段、文档分类、文本比对和风险评分结果为辅助审查依据。",
            "自动化结果仅作为审查线索，不直接替代行政认定或法律结论。",
        ],
        "review_object_profiles": supplier_profiles,
        "review_sections": [
            {
                "title": "报价情况比对",
                "points": _build_price_points(supplier_profiles),
                "opinion": _build_price_opinion(supplier_profiles),
            },
            {
                "title": "投标文件结构与文本内容比对",
                "points": structure_summary["points"],
                "opinion": structure_summary["opinion"],
            },
            {
                "title": "企业身份信息、联系人及人员信息比对",
                "points": _build_identity_points(supplier_profiles),
                "opinion": _build_identity_opinion(risk_score_table),
            },
            {
                "title": "授权及资格材料比对",
                "points": _build_authorization_points(supplier_profiles),
                "opinion": _build_authorization_opinion(supplier_profiles),
            },
            {
                "title": "文件生成特征及时间比对",
                "points": _build_timeline_points(supplier_profiles),
                "opinion": _build_timeline_opinion(supplier_profiles),
            },
            {
                "title": "围串标判断维度摘要",
                "points": dimension_summary_section["points"],
                "opinion": dimension_summary_section["opinion"],
            },
        ],
        "review_findings": review_conclusion_table["verified_facts"],
        "suspicious_clues": review_conclusion_table["suspicious_clues"],
        "exclusionary_factors": review_conclusion_table["exclusionary_factors"],
        "fact_table": fact_table,
        "clue_table": clue_table,
        "exclusion_table": exclusion_table,
        "risk_table": risk_table,
        "preliminary_conclusion": _final_conclusion(top_pair, supplier_name_map),
        "follow_up_recommendations": review_conclusion_table["recommendations"],
        "suspicious_points": suspicious_points,
        "exclusion_points": exclusion_points,
        "further_checks": further_checks,
        "audit_opinion": {
            "opinion_type": "自动审查意见",
            "main_statement": _final_conclusion(top_pair, supplier_name_map),
            "opinion_note": "现有结论系基于文件内容自动形成的复核意见，建议结合原始电子文件、外围关联信息和人工核验进一步确认。",
        },
        "evidence_summary": evidence_summary,
        "text_overlap_appendix": text_overlap_appendix,
        "risk_summary": risk_score_table,
    }
    return report


def build_formal_report_markdown(report: dict) -> str:
    supplier_names = report["project_basic_info"]["supplier_names"]
    lines = [
        "**围串标审查意见书**",
        "",
        f"项目名称：{report['project_basic_info'].get('project_name') or '未自动识别'}  ",
        f"项目编号：`{report['project_basic_info'].get('project_id') or report['project_basic_info']['case_id']}`  ",
        f"采购人：{report['project_basic_info'].get('purchaser') or '未自动识别'}  ",
        f"采购代理机构：{report['project_basic_info'].get('agency') or '未自动识别'}  ",
        "审查对象：",
    ]
    for index, profile in enumerate(report["review_object_profiles"], start=1):
        lines.append(f"{index}. {profile['full_name']}")
    lines.extend(
        [
            "",
            "审查依据：",
            "1. 采购人招标文件",
            f"2. 上述 {len(supplier_names)} 家供应商投标文件",
            "3. 投标文件中报价表、授权委托书、基本情况表、技术偏离表、实施方案、业绩材料及相关资格证明材料",
            "4. 对投标文件目录结构、文本内容、时间特征、联系方式、授权材料等进行的比对分析结果",
            "",
            "**一、审查目的**  ",
            "对本项目各投标供应商投标文件进行比对审查，判断各投标供应商之间是否存在围标、串标嫌疑，并形成初步审查意见。",
            "",
            "**二、审查情况**",
            "",
        ]
    )
    for index, section in enumerate(report["review_sections"], start=1):
        lines.append(f"{index}. **{section['title']}**")
        for point in section["points"]:
            lines.append(f"- {point}")
        lines.extend(["", "审查意见：  ", section["opinion"], ""])
    lines.extend(["**三、发现的可疑点**", ""])
    if report["suspicious_points"]:
        for index, item in enumerate(report["suspicious_points"], start=1):
            lines.append(f"{index}. {item}")
    else:
        lines.append("1. 暂未发现需要单列说明的可疑点。")
    lines.extend(["", "**四、排除性因素**", ""])
    if report["exclusion_points"]:
        for index, item in enumerate(report["exclusion_points"], start=1):
            lines.append(f"{index}. {item}")
    else:
        lines.append("1. 暂无明确排除性因素。")
    lines.extend(
        [
            "",
            "**五、初步审查结论**",
            "",
            report["audit_opinion"]["main_statement"],
            "",
            "因此，本次审查意见为：  ",
            f"**{_wrap_conclusion_statement(report['preliminary_conclusion'])}**",
            "",
            "**六、建议进一步核查事项**",
            "",
        ]
    )
    for index, item in enumerate(report["further_checks"], start=1):
        lines.append(f"{index}. {item}")
    if report.get("text_overlap_appendix"):
        lines.extend(["", "**附：文本重合证据附表**", ""])
        for index, item in enumerate(report["text_overlap_appendix"], start=1):
            lines.append(f"{index}. 供应商组合：{item['pair']}")
            lines.append(f"   线索名称：{item['finding_title']}")
            lines.append(f"   证据判断：{item['grade_text']}（{item['evidence_grade']}级）")
            locations = item.get("locations", [])
            if locations:
                for location in locations:
                    lines.append(f"   原文片段：{location['snippet']}")
                    lines.append(
                        f"   {location['left'].get('supplier') or '左侧'}来源：{_format_overlap_location_markdown(location['left'])}"
                    )
                    lines.append(
                        f"   {location['right'].get('supplier') or '右侧'}来源：{_format_overlap_location_markdown(location['right'])}"
                    )
            else:
                for snippet in item["snippets"]:
                    lines.append(f"   原文片段：{snippet}")
            lines.append("")
    lines.extend(
        [
            "",
            f"审查人：人工智能审查  ",
            f"审查日期：{_format_generated_at(report['project_basic_info']['generated_at'])}",
        ]
    )
    return "\n".join(lines)


def _extract_tender_metadata(text: str) -> dict:
    head = text[:6000]
    return {
        "project_name": _extract_first_match(head, ("项目名称", "采购项目名称", "招标项目名称")),
        "project_id": _extract_first_match(head, ("项目编号", "招标编号", "采购编号")),
        "purchaser": _extract_first_match(head, ("采购人", "采购单位")),
        "agency": _extract_first_match(head, ("采购代理机构", "代理机构")),
    }


def _build_supplier_profiles(
    bid_documents: list[dict],
    price_analysis_table: list[dict],
    authorization_chain_table: list[dict],
    timeline_table: list[dict],
) -> list[dict]:
    price_map = {row["supplier"]: row for row in price_analysis_table}
    auth_map = {row["supplier"]: row for row in authorization_chain_table}
    timeline_map = {row["supplier"]: row for row in timeline_table}
    profiles: list[dict] = []
    for doc in bid_documents:
        supplier = doc["document"]["name"]
        text = doc["document"]["text"]
        profiles.append(
            {
                "supplier": supplier,
                "full_name": _extract_company_name(text) or supplier,
                "bid_amount": price_map.get(supplier, {}).get("bid_amount") or _extract_bid_amount_from_text(text),
                "phone": _first_or_none(doc.get("phones", [])),
                "contact_name": _clean_person_name(_first_or_none(doc.get("contact_names", []))),
                "contact_name_candidates": _candidate_values(doc.get("contact_names", [])),
                "email": _first_or_none(doc.get("emails", [])),
                "bank_account": _first_or_none(doc.get("bank_accounts", [])),
                "unified_social_credit_code": _first_or_none(doc.get("unified_social_credit_codes", [])),
                "legal_representative": _clean_person_name(_first_or_none(doc.get("legal_representatives", []))),
                "legal_representative_candidates": _candidate_values(doc.get("legal_representatives", [])),
                "authorized_representative": _clean_person_name(_first_or_none(doc.get("authorized_representatives", []))),
                "authorized_representative_candidates": _candidate_values(doc.get("authorized_representatives", [])),
                "address": _first_or_none(doc.get("addresses", [])),
                "address_candidates": _candidate_values(doc.get("addresses", [])),
                "authorized_manufacturers": auth_map.get(supplier, {}).get("authorized_manufacturers", [])[:3],
                "authorization_issuers": auth_map.get(supplier, {}).get("authorization_issuers", [])[:3],
                "authorization_dates": auth_map.get(supplier, {}).get("authorization_dates", [])[:3],
                "authorization_targets": auth_map.get(supplier, {}).get("authorization_targets", [])[:3],
                "authorization_scopes": auth_map.get(supplier, {}).get("authorization_scopes", [])[:3],
                "license_numbers": auth_map.get(supplier, {}).get("license_numbers", [])[:3],
                "registration_numbers": auth_map.get(supplier, {}).get("registration_numbers", [])[:3],
                "authorization_summary": auth_map.get(supplier, {}).get("summary", "未发现明确授权链线索"),
                "created_times": timeline_map.get(supplier, {}).get("created_times", [])[:20],
                "modified_times": timeline_map.get(supplier, {}).get("modified_times", [])[:20],
                "uploaded_times": timeline_map.get(supplier, {}).get("uploaded_times", [])[:20],
                "ca_users": timeline_map.get(supplier, {}).get("ca_users", [])[:10],
                "terminal_ids": timeline_map.get(supplier, {}).get("terminal_ids", [])[:10],
                "ip_addresses": timeline_map.get(supplier, {}).get("ip_addresses", [])[:10],
                "platform_trace_count": timeline_map.get(supplier, {}).get("platform_trace_count", 0),
                "fingerprint_count": timeline_map.get(supplier, {}).get("fingerprint_count", 0),
                "timeline_summary": timeline_map.get(supplier, {}).get("summary", "无组件级时间信息"),
            }
        )
    return profiles


def _build_supplier_profiles_from_facts(
    review_facts: ReviewFacts,
    price_analysis_table: list[dict],
    authorization_chain_table: list[dict],
    timeline_table: list[dict],
) -> list[dict]:
    price_map = {row["supplier"]: row for row in price_analysis_table}
    auth_map = {row["supplier"]: row for row in authorization_chain_table}
    timeline_map = {row["supplier"]: row for row in timeline_table}
    profiles: list[dict] = []
    for supplier in review_facts.suppliers:
        profiles.append(
            {
                "supplier": supplier.supplier,
                "full_name": _primary_value(supplier, "company_names") or supplier.supplier,
                "bid_amount": price_map.get(supplier.supplier, {}).get("bid_amount") or _primary_value(supplier, "bid_amounts"),
                "phone": _primary_value(supplier, "phones"),
                "contact_name": _clean_person_name(_primary_value(supplier, "contact_names")),
                "contact_name_candidates": _candidate_values(_observation_values(supplier, "contact_names")),
                "email": _primary_value(supplier, "emails"),
                "bank_account": _primary_value(supplier, "bank_accounts"),
                "unified_social_credit_code": _primary_value(supplier, "unified_social_credit_codes"),
                "legal_representative": _clean_person_name(_primary_value(supplier, "legal_representatives")),
                "legal_representative_candidates": _candidate_values(_observation_values(supplier, "legal_representatives")),
                "authorized_representative": _clean_person_name(_primary_value(supplier, "authorized_representatives")),
                "authorized_representative_candidates": _candidate_values(_observation_values(supplier, "authorized_representatives")),
                "address": _primary_value(supplier, "addresses"),
                "address_candidates": _candidate_values(_observation_values(supplier, "addresses")),
                "authorized_manufacturers": _observation_values(supplier, "authorized_manufacturers")[:3],
                "authorization_issuers": _observation_values(supplier, "authorization_issuers")[:3],
                "authorization_dates": _observation_values(supplier, "authorization_dates")[:3],
                "authorization_targets": _observation_values(supplier, "authorization_targets")[:3],
                "authorization_scopes": _observation_values(supplier, "authorization_scopes")[:3],
                "license_numbers": _observation_values(supplier, "license_numbers")[:3],
                "registration_numbers": _observation_values(supplier, "registration_numbers")[:3],
                "authorization_summary": auth_map.get(supplier.supplier, {}).get("summary", "未发现明确授权链线索"),
                "created_times": timeline_map.get(supplier.supplier, {}).get("created_times", [])[:20],
                "modified_times": timeline_map.get(supplier.supplier, {}).get("modified_times", [])[:20],
                "uploaded_times": timeline_map.get(supplier.supplier, {}).get("uploaded_times", [])[:20],
                "ca_users": timeline_map.get(supplier.supplier, {}).get("ca_users", [])[:10],
                "terminal_ids": timeline_map.get(supplier.supplier, {}).get("terminal_ids", [])[:10],
                "ip_addresses": timeline_map.get(supplier.supplier, {}).get("ip_addresses", [])[:10],
                "platform_trace_count": timeline_map.get(supplier.supplier, {}).get("platform_trace_count", 0),
                "fingerprint_count": timeline_map.get(supplier.supplier, {}).get("fingerprint_count", 0),
                "timeline_summary": timeline_map.get(supplier.supplier, {}).get("summary", "无组件级时间信息"),
            }
        )
    return profiles


def _build_price_points(profiles: list[dict]) -> list[str]:
    points: list[str] = []
    for profile in profiles:
        if profile.get("bid_amount"):
            points.append(f"{profile['full_name']}投标总报价为 `{profile['bid_amount']}` 元。")
    return points or ["当前未从投标文件中自动提取到有效总报价。"]


def _build_price_opinion(profiles: list[dict]) -> str:
    amounts = [float(item["bid_amount"]) for item in profiles if item.get("bid_amount")]
    if len(amounts) < 2:
        return "现有材料中可用于比较的报价信息不足，暂不宜仅依据报价作出判断。"
    if len(set(amounts)) == len(amounts):
        gap = max(amounts) - min(amounts)
        return f"各家报价未出现完全一致情形，当前最大价差约为 `{gap:.2f}` 元，单凭报价差异情况尚不足以直接认定存在围串标。"
    return "存在报价完全一致或高度接近情形，建议结合其他证据进一步核查。"


def _build_structure_summary(
    structure_similarity_table: list[dict],
    section_similarity_table: list[dict],
    risk_score_table: list[dict],
    evidence_grade_table: list[dict],
    supplier_name_map: dict[str, str] | None = None,
) -> dict:
    if not structure_similarity_table:
        return {
            "points": ["当前未形成可比较的文档结构分析结果。"],
            "opinion": "结构比对信息不足，暂不作单独判断。",
        }
    avg_overlap = sum(row["category_overlap_ratio"] for row in structure_similarity_table) / len(structure_similarity_table)
    points = [
        f"各投标文件目录结构和材料类别存在一定相似性，整体上有约{_overlap_ratio_text(avg_overlap)}的材料类别可相互对应。",
        "一般目录编排或材料类别相似，在平台模板化申报场景下具有一定普遍性，应结合文件指纹、关键表格结构和其他维度综合判断。",
    ]
    for row in risk_score_table:
        pair_label = _pair_display(row["supplier_a"], row["supplier_b"], supplier_name_map)
        homology_titles = row.get("dimension_summary", {}).get("file_homology", {}).get("finding_titles", [])
        title_set = set(homology_titles)
        if "异常同构结构" in title_set:
            points.append(f"{pair_label}同时出现文件指纹、章节顺序或关键表格结构的组合命中，需进一步复核是否存在同底稿加工或异常同构制作。")
            continue
        if "文件完全一致" in title_set or "文件指纹重合" in title_set:
            points.append(f"{pair_label}存在文件指纹命中，提示部分材料可能存在同源或直接复用情形。")
        if "章节顺序高度同构" in title_set:
            points.append(f"{pair_label}章节顺序高度同构，但仍需结合文件指纹或关键表格结构进一步判断是否属于异常同构。")
        elif "章节顺序相似" in title_set:
            points.append(f"{pair_label}结构编排存在相似性，目前更接近目录响应习惯相似，单独不足以认定异常。")
        if "关键表格结构高度一致" in title_set:
            points.append(f"{pair_label}关键表格结构高度一致，需结合文件指纹或章节顺序继续复核。")
        elif "关键表格结构相似" in title_set:
            points.append(f"{pair_label}关键表格结构存在相似性，暂作为结构层面的辅助线索。")
        text_titles = set(row.get("dimension_summary", {}).get("text_similarity", {}).get("finding_titles", []))
        if "仅两家共享的共同错误表述" in text_titles:
            points.append(f"{pair_label}出现共同错误或异常表述，需结合主体、报价和原始底稿进一步复核。")
        elif "仅两家共享的罕见表达重合" in text_titles:
            points.append(f"{pair_label}存在罕见表达重合，具有一定异常性，建议继续核对原始方案来源。")
        elif "仅两家共享的一般文本相似" in text_titles:
            points.append(f"{pair_label}存在一般相似文本片段，目前更倾向于辅助性线索。")
    for row in sorted(section_similarity_table, key=lambda item: item["similarity"], reverse=True)[:4]:
        if row["similarity"] < 0.75:
            continue
        family_text = {
            "technical_plan": "技术方案",
            "implementation_plan": "实施方案",
            "training_plan": "培训方案",
        }.get(row["section_family"], row["section_family"])
        points.append(
            f"{_pair_display(row['supplier_a'], row['supplier_b'], supplier_name_map)}的{family_text}章节存在较高相似度，"
            f"相似度约为{row['similarity']:.0%}，对应起始页分别为第{row['page_a']}页和第{row['page_b']}页。"
        )
    if section_similarity_table and not any(row["similarity"] >= 0.75 for row in section_similarity_table):
        points.append("对技术方案、实施方案和培训方案进行章节级比对后，当前未发现达到高相似度阈值的章节组合。")
    opinion = "结构同源维度应优先看文件指纹、章节顺序和关键表格结构的组合关系。单独的目录相似或表格结构相似通常仅反映响应习惯接近，只有形成组合异常时，才宜进一步复核是否存在同底稿加工或异常同构制作。"
    return {"points": points, "opinion": opinion}


def _build_identity_points(profiles: list[dict]) -> list[str]:
    points: list[str] = []
    for profile in profiles:
        legal = profile.get("legal_representative") or "未自动识别"
        authorized = profile.get("authorized_representative") or "未自动识别"
        contact_name = profile.get("contact_name") or "未自动识别"
        phone = profile.get("phone") or "未自动识别"
        address = profile.get("address") or "未自动识别"
        credit_code = profile.get("unified_social_credit_code") or "未自动识别"
        points.append(
            f"{profile['full_name']}法定代表人识别为 `{legal}`，授权代表识别为 `{authorized}`，联系人识别为 `{contact_name}`，"
            f"统一社会信用代码识别为 `{credit_code}`，联系电话识别为 `{phone}`，地址识别为 `{address}`。"
        )
        conflict_note = _identity_conflict_note(profile)
        if conflict_note:
            points.append(conflict_note)
    return points or ["当前未形成可用于身份信息比对的有效结果。"]


def _build_identity_opinion(risk_score_table: list[dict]) -> str:
    if any(row["entity_link_score"] > 0 for row in risk_score_table):
        return "现有文件中发现部分联系人、账户或主体信息关联线索，建议围绕该类核心身份要素开展重点核查；如同一主体字段存在多个候选值，还应同步核验原始页面和签章件。"
    return "现有文件中未发现联系人、法定代表人、银行账户等核心身份要素的明显交叉重合，缺乏直接主体关联证据。"


def _build_authorization_points(profiles: list[dict]) -> list[str]:
    points: list[str] = []
    for profile in profiles:
        authorized_manufacturer = _format_fact_values(profile.get("authorized_manufacturers"))
        authorization_issuer = _format_fact_values(profile.get("authorization_issuers"))
        authorization_date = _format_fact_values(profile.get("authorization_dates"))
        authorization_target = _format_fact_values(profile.get("authorization_targets"))
        authorization_scope = _format_fact_values(profile.get("authorization_scopes"))
        registration_number = _format_fact_values(profile.get("registration_numbers"))
        license_number = _format_fact_values(profile.get("license_numbers"))
        points.append(
            f"{profile['full_name']}授权厂家识别为 `{authorized_manufacturer}`，授权方识别为 `{authorization_issuer}`，"
            f"授权时间识别为 `{authorization_date}`，授权对象识别为 `{authorization_target}`，"
            f"授权范围识别为 `{authorization_scope}`，注册证号识别为 `{registration_number}`，"
            f"许可证号识别为 `{license_number}`。"
        )
    return points or ["当前未提取到可供说明的授权或资格材料线索。"]


def _build_authorization_opinion(profiles: list[dict]) -> str:
    pair_messages: list[str] = []
    shared_brand_pairs: list[str] = []

    for left, right in combinations(profiles, 2):
        pair_label = f"{left['full_name']}与{right['full_name']}"
        shared_manufacturer = _shared_values(left.get("authorized_manufacturers"), right.get("authorized_manufacturers"))
        shared_issuer = _shared_values(left.get("authorization_issuers"), right.get("authorization_issuers"))
        shared_date = _shared_values(left.get("authorization_dates"), right.get("authorization_dates"))
        shared_target = _shared_values(left.get("authorization_targets"), right.get("authorization_targets"))
        shared_scope = _shared_values(left.get("authorization_scopes"), right.get("authorization_scopes"))

        if shared_manufacturer and not (shared_issuer or shared_date or shared_target or shared_scope):
            shared_brand_pairs.append(pair_label)
            continue

        if shared_issuer and shared_date:
            pair_messages.append(f"{pair_label}在授权方和授权时间上同时存在重叠，需进一步复核授权链是否异常重叠。")
            continue
        if shared_target and shared_scope:
            pair_messages.append(f"{pair_label}在授权对象和授权范围上同时存在重叠，需进一步复核是否存在异常授权安排。")
            continue
        if shared_manufacturer and shared_target:
            pair_messages.append(f"{pair_label}在授权厂家和授权对象上同时存在重叠，需进一步复核经销与授权关系。")
            continue
        if shared_manufacturer and shared_date and shared_scope:
            pair_messages.append(f"{pair_label}在授权厂家、授权时间和授权范围上同时存在重叠，需进一步复核是否存在授权链异常重叠。")

    if pair_messages:
        return "；".join(pair_messages)
    if shared_brand_pairs:
        return (
            f"{'；'.join(shared_brand_pairs)}涉及相同品牌或厂家。"
            "在设备类采购中，这种情形可能属于正常竞争，单凭同品牌或同厂家信息不足以认定授权链异常。"
        )
    if any(profile.get("authorization_summary") != "未发现明确授权链线索" for profile in profiles):
        return "现有材料中可见部分授权与资质事实，但暂未发现需单列说明的异常授权重叠组合。"
    return "现有材料未提取到稳定的授权链线索，建议结合原始授权文件和经销体系进一步核查。"


def _format_fact_values(values: list[str] | None) -> str:
    cleaned = [str(value).strip() for value in (values or []) if str(value).strip()]
    if not cleaned:
        return "未自动识别"
    deduped = list(dict.fromkeys(cleaned))[:3]
    return "、".join(deduped)


def _shared_values(left: list[str] | None, right: list[str] | None) -> list[str]:
    left_set = {str(value).strip() for value in (left or []) if str(value).strip()}
    right_set = {str(value).strip() for value in (right or []) if str(value).strip()}
    return sorted(left_set & right_set)


def _assessment_has_actionable_clues(assessment: PairwiseAssessment) -> bool:
    if not assessment.findings:
        return False
    titles = {finding.title for finding in assessment.findings}
    auth_titles = {
        "授权厂家重合",
        "授权方重合",
        "授权时间重合",
        "授权对象重合",
        "授权范围重合",
    }
    if titles <= auth_titles:
        return _authorization_titles_form_actionable_combo(titles)
    non_actionable_structure_titles = {
        "章节顺序高度同构",
        "章节顺序相似",
        "关键表格结构高度一致",
        "关键表格结构相似",
    }
    if titles <= non_actionable_structure_titles:
        return False
    text_titles = {
        "仅两家共享的共同错误表述",
        "仅两家共享的罕见表达重合",
        "仅两家共享的一般文本相似",
        "仅两家共享的非模板文本重合",
    }
    if titles <= text_titles:
        return bool(titles & {"仅两家共享的共同错误表述", "仅两家共享的罕见表达重合", "仅两家共享的非模板文本重合"})
    return True


def _risk_row_has_actionable_clues(row: dict) -> bool:
    summary = row.get("dimension_summary", {})
    matched_dimensions = {
        key
        for key, item in summary.items()
        if item.get("matched") and item.get("tier") in {"strong", "medium", "weak"}
    }
    if not matched_dimensions:
        return False
    if matched_dimensions == {"authorization_chain"}:
        auth_titles = set(summary.get("authorization_chain", {}).get("finding_titles", []))
        return _authorization_titles_form_actionable_combo(auth_titles)
    if matched_dimensions == {"file_homology"}:
        structure_titles = set(summary.get("file_homology", {}).get("finding_titles", []))
        if structure_titles <= {
            "章节顺序高度同构",
            "章节顺序相似",
            "关键表格结构高度一致",
            "关键表格结构相似",
        }:
            return False
    if matched_dimensions == {"text_similarity"}:
        text_titles = set(summary.get("text_similarity", {}).get("finding_titles", []))
        if text_titles <= {"仅两家共享的一般文本相似"}:
            return False
    return True


def _authorization_titles_form_actionable_combo(titles: set[str]) -> bool:
    if {"授权方重合", "授权时间重合"} <= titles:
        return True
    if {"授权对象重合", "授权范围重合"} <= titles:
        return True
    if {"授权厂家重合", "授权对象重合"} <= titles:
        return True
    if {"授权厂家重合", "授权时间重合", "授权范围重合"} <= titles:
        return True
    return False


def _build_timeline_points(profiles: list[dict]) -> list[str]:
    return [
        f"{profile['full_name']}文件时间特征：{profile['timeline_summary']}；创建时间提取 {len(profile.get('created_times', []))} 条，修改时间提取 {len(profile.get('modified_times', []))} 条，上传时间提取 {len(profile.get('uploaded_times', []))} 条，CA使用人 {len(profile.get('ca_users', []))} 项，终端/设备标识 {len(profile.get('terminal_ids', []))} 项，IP 地址 {len(profile.get('ip_addresses', []))} 项，平台侧痕迹 {profile.get('platform_trace_count', 0)} 条，文件指纹 {profile.get('fingerprint_count', 0)} 项。"
        for profile in profiles
    ] or ["当前未形成稳定的时间特征分析结果。"]


def _build_timeline_opinion(profiles: list[dict]) -> str:
    if any(profile.get("platform_trace_count", 0) or profile.get("ca_users") or profile.get("terminal_ids") or profile.get("ip_addresses") for profile in profiles):
        return "现有材料已提取到部分平台侧电子痕迹或终端线索，应优先围绕上传时间、CA使用人、终端标识和IP地址开展交叉核验；如出现重合，可显著提升时间与电子痕迹维度的判断价值。"
    if any(profile["timeline_summary"] in {"创建、修改时间均存在集中生成迹象", "修改时间存在集中生成迹象"} for profile in profiles):
        return "部分供应商文件在创建时间或修改时间上呈现集中生成特征，可作为时间与电子痕迹维度的辅助线索；仍需结合文件指纹、平台日志和原始元数据继续核实。"
    if all(profile["timeline_summary"] == "无组件级时间信息" for profile in profiles):
        return "现有材料未提取到足够的创建时间或修改时间信息，暂不能仅依据时间与电子痕迹作出倾向性判断。"
    return "目前未发现足以证明同一主体集中制作全部投标文件的明确时间与电子痕迹证据。"


def _build_suspicious_points(
    risk_score_table: list[dict],
    evidence_grade_table: list[dict],
    supplier_name_map: dict[str, str] | None = None,
) -> list[str]:
    points: list[str] = []
    evidence_by_pair: dict[str, list[dict]] = {}
    for row in evidence_grade_table:
        evidence_by_pair.setdefault(row["pair"], []).append(row)
    for row in risk_score_table:
        if row["risk_level"] in {"medium", "high", "critical"} and _risk_row_has_actionable_clues(row):
            pair_label = _pair_display(row["supplier_a"], row["supplier_b"], supplier_name_map)
            points.append(f"{pair_label}之间存在需要进一步核查的可疑线索。")
            evidence_key = f"{row['supplier_a']} 与 {row['supplier_b']}"
            pair_evidence = [
                item for item in evidence_by_pair.get(evidence_key, [])
                if item["evidence_grade"] in {"A", "B", "C"}
            ]
            if pair_evidence:
                pair_evidence.sort(key=lambda item: (item["evidence_grade"], item["finding_title"]))
                top_evidence = pair_evidence[0]
                grade_text = _evidence_reason_to_plain_text(top_evidence.get("reason", "")) or "需要结合其他证据综合判断"
                points.append(
                    f"{pair_label}存在需进一步复核的线索，当前属于{grade_text}（{top_evidence['evidence_grade']}级）。"
                )
    return points


def _build_dimension_summary_section(
    risk_score_table: list[dict],
    supplier_name_map: dict[str, str] | None = None,
) -> dict:
    if not risk_score_table:
        return {
            "points": ["当前未形成可供说明的维度化比对结果。"],
            "opinion": "维度化判断信息不足，暂无法从主体关联、报价关联、结构同源等角度形成综合说明。",
        }
    points: list[str] = []
    for row in risk_score_table:
        pair_label = _pair_display(row["supplier_a"], row["supplier_b"], supplier_name_map)
        points.append(f"{pair_label}：{_render_dimension_summary_text(row.get('dimension_summary', {}))}。")
    matched_pairs = [row for row in risk_score_table if _has_meaningful_dimension_hit(row.get("dimension_summary", {}))]
    if not matched_pairs:
        opinion = "现有比对结果中，各供应商组合在六个判断维度上均未形成足以单独抬高风险等级的明确命中。"
    else:
        pair_labels = "；".join(
            _pair_display(row["supplier_a"], row["supplier_b"], supplier_name_map)
            for row in matched_pairs[:3]
        )
        opinion = (
            f"从六个判断维度看，{pair_labels}已出现部分维度命中，"
            "应结合命中维度的强弱层级和具体证据继续复核，不能仅依据单一维度直接定性。"
        )
    return {"points": points, "opinion": opinion}


def _render_dimension_summary_text(summary: dict[str, dict]) -> str:
    if not summary:
        return "主体关联、报价关联、文本与方案关联、结构同源、授权与资质链、时间与电子痕迹均未形成明确命中"
    parts: list[str] = []
    for key in DIMENSION_ORDER:
        item = summary.get(key, {})
        label = DIMENSION_LABELS[key]
        tier = DIMENSION_TIER_LABELS.get(item.get("tier", "none"), "未命中")
        parts.append(f"{label}{tier}")
    return "；".join(parts)


def _has_meaningful_dimension_hit(summary: dict[str, dict]) -> bool:
    return any(
        item.get("tier") in {"strong", "medium", "weak"} and item.get("matched")
        for item in summary.values()
    )


def _build_text_overlap_appendix(
    evidence_grade_table: list[dict],
    supplier_name_map: dict[str, str] | None = None,
) -> list[dict]:
    rows: list[dict] = []
    for item in evidence_grade_table:
        if "文本重合" not in item.get("finding_title", ""):
            continue
        rows.append(
            {
                "pair": _replace_supplier_names(item["pair"], supplier_name_map),
                "finding_title": _plain_text_overlap_title(item["finding_title"]),
                "evidence_grade": item["evidence_grade"],
                "grade_text": _evidence_reason_to_plain_text(item.get("reason", "")),
                "snippets": _extract_overlap_snippets(item.get("evidence", [])),
                "locations": _extract_overlap_locations(item.get("evidence_details", []), supplier_name_map),
            }
        )
    return rows


def _text_overlap_snippets_for_pair(pair: str, evidence_grade_table: list[dict]) -> list[str]:
    for item in evidence_grade_table:
        if item.get("pair") == pair and "文本重合" in item.get("finding_title", ""):
            return _extract_overlap_snippets(item.get("evidence", []))
    return []


def _extract_overlap_snippets(evidence_items: list[str]) -> list[str]:
    snippets: list[str] = []
    for evidence in evidence_items:
        if "重合行:" in evidence:
            snippet = evidence.split("重合行:", 1)[1].strip()
        else:
            snippet = evidence.strip()
        if snippet:
            snippets.append(snippet)
    return snippets[:5]


def _extract_overlap_locations(evidence_details: list[dict], supplier_name_map: dict[str, str] | None = None) -> list[dict]:
    rows: list[dict] = []
    for detail in evidence_details[:5]:
        rows.append(
            {
                "snippet": detail.get("snippet", ""),
                "left": _format_overlap_side(detail.get("left", {}), supplier_name_map),
                "right": _format_overlap_side(detail.get("right", {}), supplier_name_map),
            }
        )
    return rows


def _format_overlap_side(side: dict, supplier_name_map: dict[str, str] | None = None) -> dict:
    supplier = side.get("supplier", "")
    return {
        "supplier": supplier_name_map.get(supplier, supplier) if supplier_name_map else supplier,
        "source_document": side.get("source_document"),
        "source_page": side.get("source_page"),
        "source_line": side.get("source_line"),
        "component_title": side.get("component_title"),
    }


def _evidence_reason_to_plain_text(reason: str) -> str:
    if not reason:
        return "需要结合其他证据综合判断"
    return reason.rstrip("。")


def _plain_text_overlap_title(title: str) -> str:
    if title == "仅两家共享的共同错误表述":
        return "两家投标文件存在共同错误或异常表述"
    if title == "仅两家共享的罕见表达重合":
        return "两家投标文件存在罕见表达重合"
    if title == "仅两家共享的一般文本相似":
        return "两家投标文件存在一般相似文本片段"
    if title == "仅两家共享的非模板文本重合":
        return "两家投标文件存在相似文本片段"
    return title


def _format_overlap_location_markdown(location: dict) -> str:
    parts = []
    if location.get("source_document"):
        parts.append(str(location["source_document"]))
    if location.get("component_title"):
        parts.append(str(location["component_title"]))
    page = location.get("source_page")
    line = location.get("source_line")
    if page is not None and line is not None:
        parts.append(f"第{page}页第{line}行")
    elif page is not None:
        parts.append(f"第{page}页")
    elif line is not None:
        parts.append(f"第{line}行")
    return " / ".join(parts) if parts else "位置未定位"


def _build_exclusion_points(
    review_conclusion_table: dict,
    risk_score_table: list[dict],
    supplier_name_map: dict[str, str] | None = None,
) -> list[str]:
    points = [
        _replace_supplier_names(item, supplier_name_map)
        for item in review_conclusion_table.get("exclusionary_factors", [])
    ]
    if all(row["entity_link_score"] == 0 for row in risk_score_table):
        points.append("各供应商之间未发现联系人、法定代表人、银行账户等核心身份要素的明显重合。")
    if all(row["file_homology_score"] == 0 for row in risk_score_table):
        points.append("未发现完全相同的文件指纹或足以证明直接复制形成的同源文件证据。")
    return points


def _build_further_checks(top_pair: dict | None, supplier_name_map: dict[str, str] | None = None) -> list[str]:
    focus = ""
    if top_pair:
        focus = f"重点核查 {_pair_display(top_pair['supplier_a'], top_pair['supplier_b'], supplier_name_map)}的"
    return [
        f"核查采购平台后台日志、投标客户端登录 IP、上传终端和操作时间轨迹，{focus}上传行为是否存在重合。".strip(),
        "核查 CA 证书申请、使用人、办证联系人、证书设备信息是否存在关联。",
        "核查供应商股东、实际控制人、监事、高管、历史联系电话、联系邮箱、社保缴纳单位是否存在交叉。",
        "核查报价形成依据、产品授权链条、厂家授权时间及经销体系是否存在异常重叠。",
        "对疑似关联供应商的技术响应底稿、报价测算底稿、投标文件原始可编辑文件进行延伸核验。",
        "必要时调取平台日志、邮件往来及其他外围客观证据，综合判断是否存在协同投标行为。",
    ]


def _extract_first_match(text: str, labels: tuple[str, ...]) -> str | None:
    for label in labels:
        pattern = re.compile(rf"(?:^|\n)\s*{re.escape(label)}\s*[:：]?\s*([^\n]{{2,120}})")
        match = pattern.search(text)
        if match:
            value = match.group(1).strip()
            value = re.sub(r"^(名称|单位名称)\s*[:：]?\s*", "", value)
            value = value.strip(" ：:;；")
            if _looks_metadata_value_reasonable(value):
                return value
    return None


def _extract_company_name(text: str) -> str | None:
    pattern = re.compile(r"([A-Za-z（）()·\u4e00-\u9fff]{4,}(?:有限责任公司|股份有限公司|有限公司|公司))")
    matches = pattern.findall(text)
    return matches[0].strip() if matches else None


def _first_or_none(values: list[str]) -> str | None:
    return values[0] if values else None


def _candidate_values(values: list[str] | None) -> list[str]:
    cleaned = [str(value).strip() for value in (values or []) if str(value).strip()]
    return list(dict.fromkeys(cleaned))[:3]


def _identity_conflict_note(profile: dict) -> str:
    notes: list[str] = []
    legal_candidates = _remaining_candidates(
        profile.get("legal_representative_candidates", []),
        profile.get("legal_representative"),
    )
    authorized_candidates = _remaining_candidates(
        profile.get("authorized_representative_candidates", []),
        profile.get("authorized_representative"),
    )
    contact_candidates = _remaining_candidates(
        profile.get("contact_name_candidates", []),
        profile.get("contact_name"),
    )
    address_candidates = _remaining_candidates(
        profile.get("address_candidates", []),
        profile.get("address"),
    )
    if legal_candidates:
        notes.append(f"法定代表人另有候选值 `{ '、'.join(legal_candidates) }`")
    if authorized_candidates:
        notes.append(f"授权代表另有候选值 `{ '、'.join(authorized_candidates) }`")
    if contact_candidates:
        notes.append(f"联系人另有候选值 `{ '、'.join(contact_candidates) }`")
    if address_candidates:
        notes.append(f"地址另有候选值 `{ '、'.join(address_candidates) }`")
    if not notes:
        return ""
    return f"{profile['full_name']}主体字段存在多个候选值，当前优先采用上述主采纳值；另识别到：{'；'.join(notes)}，建议结合原始页和签章件进一步核验。"


def _remaining_candidates(values: list[str], primary: str | None) -> list[str]:
    primary_text = str(primary or "").strip()
    return [value for value in values if value and value != primary_text][:3]


def _extract_bid_amount_from_text(text: str) -> str | None:
    patterns = (
        r"(?:投标总报价|投标报价|报价金额)\s*[:：]?\s*([0-9][0-9,，.]{3,})",
        r"(?:总价|金额合计)\s*[:：]?\s*([0-9][0-9,，.]{3,})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = match.group(1).replace("，", ",").replace(",", "")
            try:
                amount = float(value)
                if amount >= 1000:
                    return f"{amount:.2f}"
            except ValueError:
                continue
    return None


def _clean_person_name(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"[^\u4e00-\u9fff]", "", value)
    if 2 <= len(cleaned) <= 6:
        return cleaned
    return None


def _looks_metadata_value_reasonable(value: str) -> bool:
    if not value or len(value) > 80:
        return False
    bad_tokens = ("签订合同", "供应商须知", "应当", "应按", "不得", "应在")
    return not any(token in value for token in bad_tokens)


def _wrap_conclusion_statement(text: str) -> str:
    if "未发现明显异常" in text:
        return "现阶段未发现足以直接认定围串标的充分证据。"
    if "补充核查" in text:
        return "存在一定可疑线索，但证据尚不足，建议继续补充核查。"
    if "重点复核" in text or "进一步取证" in text:
        return "存在较强可疑线索，建议列为重点复核对象并继续取证。"
    return text


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


def build_section_similarity_table(review_facts: ReviewFacts) -> list[dict]:
    rows: list[dict] = []
    target_families = ("technical_plan", "implementation_plan", "training_plan")
    for left, right in combinations(review_facts.suppliers, 2):
        for family in target_families:
            left_text = _family_text(left, family)
            right_text = _family_text(right, family)
            if not left_text or not right_text:
                continue
            similarity = round(SequenceMatcher(None, _normalize_similarity_text(left_text), _normalize_similarity_text(right_text)).ratio(), 4)
            rows.append(
                {
                    "supplier_a": left.supplier,
                    "supplier_b": right.supplier,
                    "section_family": family,
                    "title_a": _family_title(left, family),
                    "title_b": _family_title(right, family),
                    "page_a": _family_start_page(left, family),
                    "page_b": _family_start_page(right, family),
                    "similarity": similarity,
                    "chars_a": len(left_text),
                    "chars_b": len(right_text),
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


def _family_rows(supplier: SupplierFacts, family: str) -> list[dict]:
    return [row for row in supplier.section_rows if row.get("family") == family]


def _family_text(supplier: SupplierFacts, family: str) -> str:
    return "\n".join(row.get("text", "") for row in _family_rows(supplier, family)).strip()


def _family_title(supplier: SupplierFacts, family: str) -> str | None:
    rows = _family_rows(supplier, family)
    return rows[0].get("title") if rows else None


def _family_start_page(supplier: SupplierFacts, family: str) -> int | None:
    rows = _family_rows(supplier, family)
    if not rows:
        return None
    return rows[0].get("start_page")


def _normalize_similarity_text(text: str) -> str:
    return re.sub(r"\s+", "", text[:20000])


def build_authorization_chain_table(signals: ReviewFacts | list[ExtractedSignals]) -> list[dict]:
    rows: list[dict] = []
    supplier_facts = _coerce_suppliers(signals)
    if supplier_facts is not None:
        for supplier in supplier_facts:
            manufacturer_mentions = _observation_values(supplier, "manufacturers")
            authorized_manufacturers = _observation_values(supplier, "authorized_manufacturers")
            authorization_issuers = _observation_values(supplier, "authorization_issuers")
            authorization_dates = _observation_values(supplier, "authorization_dates")
            authorization_targets = _observation_values(supplier, "authorization_targets")
            authorization_scopes = _observation_values(supplier, "authorization_scopes")
            authorization_mentions = _observation_values(supplier, "authorization_mentions")[:20]
            rows.append(
                {
                    "supplier": supplier.supplier,
                    "manufacturer_mentions": manufacturer_mentions,
                    "authorized_manufacturers": authorized_manufacturers,
                    "authorization_issuers": authorization_issuers,
                    "authorization_dates": authorization_dates,
                    "authorization_targets": authorization_targets,
                    "authorization_scopes": authorization_scopes,
                    "authorization_mentions": authorization_mentions,
                    "summary": (
                        "发现授权链关键信息"
                        if authorization_mentions or manufacturer_mentions or authorized_manufacturers or authorization_issuers or authorization_dates or authorization_targets or authorization_scopes
                        else "未发现明确授权链线索"
                    ),
                }
            )
        return rows
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


def build_license_match_table(signals: ReviewFacts | list[ExtractedSignals]) -> list[dict]:
    rows: list[dict] = []
    supplier_facts = _coerce_suppliers(signals)
    if supplier_facts is not None:
        for supplier in supplier_facts:
            license_lines = _observation_values(supplier, "authorization_mentions")[:20]
            registration_ids = sorted(
                set(_observation_values(supplier, "license_numbers") + _observation_values(supplier, "registration_numbers"))
            )[:20]
            rows.append(
                {
                    "supplier": supplier.supplier,
                    "license_lines": license_lines,
                    "registration_ids": registration_ids,
                }
            )
        return rows
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


def build_timeline_table(signals: ReviewFacts | list[ExtractedSignals]) -> list[dict]:
    rows: list[dict] = []
    supplier_facts = _coerce_suppliers(signals)
    if supplier_facts is not None:
        for supplier in supplier_facts:
            components = supplier.document.metadata.get("components", [])
            created_times = supplier.timeline_created_times[:20]
            modified_times = supplier.timeline_modified_times[:20]
            uploaded_times = supplier.timeline_uploaded_times[:20]
            ca_users = supplier.timeline_ca_users[:10]
            terminal_ids = supplier.timeline_terminal_ids[:10]
            ip_addresses = supplier.timeline_ip_addresses[:10]
            platform_trace_count = len(supplier.platform_trace_lines)
            fingerprint_count = len({row.get("sha256") for row in supplier.file_fingerprints if row.get("sha256")})
            rows.append(
                {
                    "supplier": supplier.supplier,
                    "component_count": len(components) or 1,
                    "created_times": created_times,
                    "modified_times": modified_times,
                    "uploaded_times": uploaded_times,
                    "ca_users": ca_users,
                    "terminal_ids": terminal_ids,
                    "ip_addresses": ip_addresses,
                    "platform_trace_count": platform_trace_count,
                    "fingerprint_count": fingerprint_count,
                    "summary": (
                        "发现平台侧电子痕迹"
                        if uploaded_times or ca_users or terminal_ids or ip_addresses or platform_trace_count
                        else
                        "创建、修改时间均存在集中生成迹象"
                        if created_times
                        and modified_times
                        and len(set(created_times)) <= max(1, len(created_times) // 4)
                        and len(set(modified_times)) <= max(1, len(modified_times) // 4)
                        else "修改时间存在集中生成迹象"
                        if modified_times and len(set(modified_times)) <= max(1, len(modified_times) // 4)
                        else "无组件级时间信息" if not components else "未见明显集中生成特征"
                    ),
                }
            )
        return rows
    for signal in signals:
        components = signal.document.metadata.get("components", [])
        if not components:
            rows.append(
                {
                    "supplier": signal.document.name,
                    "component_count": 1,
                    "created_times": [],
                    "modified_times": [],
                    "fingerprint_count": 1,
                "summary": "无组件级时间信息",
            }
        )
            continue
        created_times = [component.get("created_at") for component in components if component.get("created_at")]
        modified_times = [component.get("modified_at") for component in components if component.get("modified_at")]
        uploaded_times = [normalize_text_field(component.get("upload_at")) for component in components if component.get("upload_at")]
        ca_users = [normalize_text_field(component.get("ca_user")) for component in components if component.get("ca_user")]
        terminal_ids = [
            normalize_text_field(component.get("terminal_id") or component.get("client_id") or component.get("device_id"))
            for component in components
            if component.get("terminal_id") or component.get("client_id") or component.get("device_id")
        ]
        ip_addresses = [
            normalize_text_field(component.get("client_ip") or component.get("upload_ip") or component.get("ip"))
            for component in components
            if component.get("client_ip") or component.get("upload_ip") or component.get("ip")
        ]
        rows.append(
            {
                "supplier": signal.document.name,
                "component_count": len(components),
                "created_times": created_times[:20],
                "modified_times": modified_times[:20],
                "uploaded_times": uploaded_times[:20],
                "ca_users": ca_users[:10],
                "terminal_ids": terminal_ids[:10],
                "ip_addresses": ip_addresses[:10],
                "platform_trace_count": sum(
                    1
                    for component in components
                    if component.get("upload_at")
                    or component.get("ca_user")
                    or component.get("terminal_id")
                    or component.get("client_id")
                    or component.get("device_id")
                    or component.get("client_ip")
                    or component.get("upload_ip")
                    or component.get("ip")
                ),
                "fingerprint_count": len({component.get("sha256") for component in components if component.get("sha256")}),
                "summary": (
                    "发现平台侧电子痕迹"
                    if uploaded_times or ca_users or terminal_ids or ip_addresses
                    else
                    "创建、修改时间均存在集中生成迹象"
                    if created_times
                    and modified_times
                    and len(set(created_times)) <= max(1, len(created_times) // 4)
                    and len(set(modified_times)) <= max(1, len(modified_times) // 4)
                    else "修改时间存在集中生成迹象"
                    if modified_times and len(set(modified_times)) <= max(1, len(modified_times) // 4)
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
    if finding.title in {"仅两家共享的共同错误表述", "仅两家共享的罕见表达重合"}:
        return "B"
    if finding.title in {"仅两家共享的一般文本相似", "仅两家共享的非模板文本重合"}:
        return "C"
    if finding.title in {"银行账号重合", "联系人电话重合", "邮箱重合", "法定代表人信息重合"}:
        return "A"
    if "报价" in finding.title or "共享" in finding.title or finding.title in {"特殊计价说明重合", "授权对象重合", "授权范围重合"}:
        return "B"
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
        if finding.title == "分项报价结构高度一致":
            return 18
        if finding.title == "分项报价结构相似":
            return 12
        if finding.title == "特殊计价说明重合":
            return 10
        if finding.title == "分项报价税率一致":
            return 8
        if finding.title == "分项报价单项重合":
            return 6
    return 0


def _entity_score(assessment: PairwiseAssessment) -> int:
    score = 0
    for finding in assessment.findings:
        if finding.title in {"统一社会信用代码重合", "联系人电话重合", "邮箱重合", "银行账号重合", "法定代表人信息重合", "授权代表信息重合", "地址信息重合"}:
            score += min(10, finding.weight)
    return min(30, score)


def _text_similarity_score(assessment: PairwiseAssessment) -> int:
    scores = [
        finding.weight
        for finding in assessment.findings
        if finding.title in {
            "仅两家共享的共同错误表述",
            "仅两家共享的罕见表达重合",
            "仅两家共享的一般文本相似",
            "仅两家共享的非模板文本重合",
        }
        or "文本重合" in finding.title
    ]
    return max(scores) if scores else 0


def _finding_weight(assessment: PairwiseAssessment, titles: set[str]) -> int:
    for finding in assessment.findings:
        if finding.title in titles:
            return finding.weight
    return 0


def _authorization_indicator(left: dict, right: dict) -> str:
    left_auth = set(left.get("manufacturer_mentions", [])) | set(left.get("authorized_manufacturers", [])) | set(left.get("authorization_targets", []))
    right_auth = set(right.get("manufacturer_mentions", [])) | set(right.get("authorized_manufacturers", [])) | set(right.get("authorization_targets", []))
    overlap = {item for item in (left_auth & right_auth) if item}
    if overlap:
        return f"shared:{len(overlap)}"
    return "none"


def _structure_indicator(assessment: PairwiseAssessment) -> str:
    titles = [
        finding.title
        for finding in assessment.findings
        if finding.title
        in {
            "文件完全一致",
            "文件指纹重合",
            "章节顺序高度同构",
            "章节顺序相似",
            "关键表格结构高度一致",
            "关键表格结构相似",
            "异常同构结构",
        }
    ]
    if not titles:
        return "none"
    return "；".join(titles[:4])


def _timeline_indicator(left: dict, right: dict) -> str:
    left_created = set(left.get("created_times", []))
    right_created = set(right.get("created_times", []))
    left_times = set(left.get("modified_times", []))
    right_times = set(right.get("modified_times", []))
    left_uploaded = set(left.get("uploaded_times", []))
    right_uploaded = set(right.get("uploaded_times", []))
    left_ca = set(left.get("ca_users", []))
    right_ca = set(right.get("ca_users", []))
    left_terminal = set(left.get("terminal_ids", []))
    right_terminal = set(right.get("terminal_ids", []))
    left_ip = set(left.get("ip_addresses", []))
    right_ip = set(right.get("ip_addresses", []))
    fingerprint_count = min(int(left.get("fingerprint_count", 0) or 0), int(right.get("fingerprint_count", 0) or 0))
    shared_created = left_created & right_created
    shared_modified = left_times & right_times
    shared_uploaded = left_uploaded & right_uploaded
    shared_ca = left_ca & right_ca
    shared_terminal = left_terminal & right_terminal
    shared_ip = left_ip & right_ip
    parts: list[str] = []
    if shared_created:
        parts.append(f"created:{len(shared_created)}")
    if shared_modified:
        parts.append(f"modified:{len(shared_modified)}")
    if shared_uploaded:
        parts.append(f"uploaded:{len(shared_uploaded)}")
    if shared_ca:
        parts.append(f"ca:{len(shared_ca)}")
    if shared_terminal:
        parts.append(f"terminal:{len(shared_terminal)}")
    if shared_ip:
        parts.append(f"ip:{len(shared_ip)}")
    if fingerprint_count:
        parts.append(f"fingerprints:{fingerprint_count}")
    if parts:
        return "；".join(parts)
    return "none"


def _risk_level_from_total(total: int) -> str:
    if total >= 75:
        return "critical"
    if total >= 45:
        return "high"
    if total >= 20:
        return "medium"
    return "low"


def _final_conclusion(top_pair: dict | None, supplier_name_map: dict[str, str] | None = None) -> str:
    if not top_pair:
        return "现有证据不足以形成实质性审查判断。"
    pair_label = _pair_display(top_pair["supplier_a"], top_pair["supplier_b"], supplier_name_map)
    if top_pair["risk_level"] == "critical":
        return f"存在较强可疑线索，建议对 {pair_label}进一步取证。"
    if top_pair["risk_level"] == "high":
        return f"存在较强可疑线索，建议重点复核 {pair_label}。"
    if top_pair["risk_level"] == "medium":
        return f"存在可疑线索，建议对 {pair_label}补充核查。"
    return "未发现明显异常。"


def _pair_display(left: str, right: str, supplier_name_map: dict[str, str] | None = None) -> str:
    if not supplier_name_map:
        return f"{left}与{right}"
    return f"{supplier_name_map.get(left, left)}与{supplier_name_map.get(right, right)}"


def _replace_supplier_names(text: str, supplier_name_map: dict[str, str] | None = None) -> str:
    if not supplier_name_map:
        return text
    updated = text
    for short, full in sorted(supplier_name_map.items(), key=lambda item: len(item[0]), reverse=True):
        updated = updated.replace(short, full)
    return updated


def _format_generated_at(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value.replace("T", " ")


def _overlap_ratio_text(value: float) -> str:
    return f"{round(value * 100)}%"
