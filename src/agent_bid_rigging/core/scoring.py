from __future__ import annotations

from collections import Counter
from itertools import combinations

from agent_bid_rigging.models import ExtractedSignals, PairwiseAssessment, PairwiseFinding, ReviewFacts, SupplierFacts


def assess_pairs(signals: ReviewFacts | list[ExtractedSignals]) -> list[PairwiseAssessment]:
    suppliers = _coerce_suppliers(signals)
    global_line_counts: Counter[str] = Counter()
    for item in suppliers:
        global_line_counts.update(set(_candidate_overlap_lines(item)))

    assessments: list[PairwiseAssessment] = []
    for left, right in combinations(suppliers, 2):
        findings: list[PairwiseFinding] = []

        findings.extend(_shared_field_findings("联系人电话重合", 30, _phones(left), _phones(right)))
        findings.extend(_shared_field_findings("邮箱重合", 25, _emails(left), _emails(right)))
        findings.extend(_shared_field_findings("银行账号重合", 35, _bank_accounts(left), _bank_accounts(right)))
        findings.extend(
            _shared_field_findings(
                "法定代表人信息重合",
                25,
                _legal_representatives(left),
                _legal_representatives(right),
            )
        )
        findings.extend(_shared_field_findings("地址信息重合", 20, _addresses(left), _addresses(right)))
        findings.extend(_price_findings(left, right))
        findings.extend(_pair_only_line_findings(left, right, global_line_counts))

        score = sum(finding.weight for finding in findings)
        assessments.append(
            PairwiseAssessment(
                supplier_a=_supplier_name(left),
                supplier_b=_supplier_name(right),
                risk_score=score,
                risk_level=_risk_level(score),
                findings=sorted(findings, key=lambda item: item.weight, reverse=True),
            )
        )
    return sorted(assessments, key=lambda item: item.risk_score, reverse=True)


def _shared_field_findings(
    title: str,
    weight: int,
    left_values: list[str],
    right_values: list[str],
) -> list[PairwiseFinding]:
    overlap = sorted(set(left_values) & set(right_values))
    if not overlap:
        return []
    return [
        PairwiseFinding(
            title=title,
            weight=weight,
            evidence=[f"共享字段值: {value}" for value in overlap[:5]],
        )
    ]


def _price_findings(left: ExtractedSignals | SupplierFacts, right: ExtractedSignals | SupplierFacts) -> list[PairwiseFinding]:
    left_prices = _bid_amounts(left)
    right_prices = _bid_amounts(right)
    if not left_prices or not right_prices:
        return []

    findings: list[PairwiseFinding] = []
    left_total = max(left_prices)
    right_total = max(right_prices)
    diff = abs(left_total - right_total)
    base = max(abs(left_total), abs(right_total), 1.0)
    ratio = diff / base

    if diff == 0:
        findings.append(
            PairwiseFinding(
                title="投标报价完全一致",
                weight=35,
                evidence=[f"{_supplier_name(left)} 与 {_supplier_name(right)} 报价均为 {left_total:.2f}"],
            )
        )
    elif ratio <= 0.001:
        findings.append(
            PairwiseFinding(
                title="投标报价极度接近",
                weight=20,
                evidence=[f"价差 {diff:.2f}，相对差异 {ratio:.4%}"],
            )
        )
    elif ratio <= 0.005:
        findings.append(
            PairwiseFinding(
                title="投标报价较为接近",
                weight=10,
                evidence=[f"价差 {diff:.2f}，相对差异 {ratio:.4%}"],
            )
        )
    return findings


def _pair_only_line_findings(
    left: ExtractedSignals | SupplierFacts,
    right: ExtractedSignals | SupplierFacts,
    global_line_counts: Counter[str],
) -> list[PairwiseFinding]:
    overlap = sorted(
        line
        for line in (set(_candidate_overlap_lines(left)) & set(_candidate_overlap_lines(right)))
        if global_line_counts[line] == 2
    )
    if not overlap:
        return []

    if len(overlap) >= 8:
        weight = 30
    elif len(overlap) >= 4:
        weight = 20
    else:
        weight = 10

    return [
        PairwiseFinding(
            title="仅两家共享的非模板文本重合",
            weight=weight,
            evidence=[
                _format_overlap_evidence(line, left, right)
                for line in overlap[:5]
            ],
            evidence_details=[
                _build_overlap_evidence_detail(line, left, right)
                for line in overlap[:5]
            ],
        )
    ]


def _risk_level(score: int) -> str:
    if score >= 80:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 20:
        return "medium"
    return "low"


def _coerce_suppliers(signals: ReviewFacts | list[ExtractedSignals]) -> list[ExtractedSignals | SupplierFacts]:
    if isinstance(signals, ReviewFacts):
        return list(signals.suppliers)
    return list(signals)


def _supplier_name(item: ExtractedSignals | SupplierFacts) -> str:
    if isinstance(item, SupplierFacts):
        return item.supplier
    return item.document.name


def _candidate_overlap_lines(item: ExtractedSignals | SupplierFacts) -> list[str]:
    if isinstance(item, SupplierFacts):
        return item.candidate_overlap_lines
    return item.candidate_overlap_lines


def _candidate_overlap_refs(item: ExtractedSignals | SupplierFacts) -> dict[str, list[dict]]:
    if isinstance(item, SupplierFacts):
        return item.candidate_overlap_refs
    return item.candidate_overlap_refs


def _build_overlap_evidence_detail(
    line: str,
    left: ExtractedSignals | SupplierFacts,
    right: ExtractedSignals | SupplierFacts,
) -> dict:
    left_ref = _candidate_overlap_refs(left).get(line, [{}])[0]
    right_ref = _candidate_overlap_refs(right).get(line, [{}])[0]
    return {
        "snippet": line,
        "left": {
            "supplier": _supplier_name(left),
            **left_ref,
        },
        "right": {
            "supplier": _supplier_name(right),
            **right_ref,
        },
    }


def _format_overlap_evidence(
    line: str,
    left: ExtractedSignals | SupplierFacts,
    right: ExtractedSignals | SupplierFacts,
) -> str:
    detail = _build_overlap_evidence_detail(line, left, right)
    return (
        f"重合行: {line} | "
        f"{_supplier_name(left)}来源: {_format_ref(detail['left'])} | "
        f"{_supplier_name(right)}来源: {_format_ref(detail['right'])}"
    )


def _format_ref(ref: dict) -> str:
    source_document = ref.get("source_document") or "未知文件"
    source_page = ref.get("source_page")
    source_line = ref.get("source_line")
    component_title = ref.get("component_title") or ""
    location_parts = []
    if source_page is not None:
        location_parts.append(f"第{source_page}页")
    if source_line is not None:
        location_parts.append(f"第{source_line}行")
    location = "，".join(location_parts) if location_parts else "位置未定位"
    if component_title:
        return f"{source_document} / {component_title} / {location}"
    return f"{source_document} / {location}"


def _phones(item: ExtractedSignals | SupplierFacts) -> list[str]:
    if isinstance(item, SupplierFacts):
        return [fact.value for fact in item.phones]
    return item.phones


def _emails(item: ExtractedSignals | SupplierFacts) -> list[str]:
    if isinstance(item, SupplierFacts):
        return [fact.value for fact in item.emails]
    return item.emails


def _bank_accounts(item: ExtractedSignals | SupplierFacts) -> list[str]:
    if isinstance(item, SupplierFacts):
        return [fact.value for fact in item.bank_accounts]
    return item.bank_accounts


def _legal_representatives(item: ExtractedSignals | SupplierFacts) -> list[str]:
    if isinstance(item, SupplierFacts):
        return [fact.value for fact in item.legal_representatives]
    return item.legal_representatives


def _addresses(item: ExtractedSignals | SupplierFacts) -> list[str]:
    if isinstance(item, SupplierFacts):
        return [fact.value for fact in item.addresses]
    return item.addresses


def _bid_amounts(item: ExtractedSignals | SupplierFacts) -> list[float]:
    if isinstance(item, SupplierFacts):
        values: list[float] = []
        for fact in item.bid_amounts:
            try:
                values.append(float(fact.value))
            except ValueError:
                continue
        return values
    return item.bid_amounts
