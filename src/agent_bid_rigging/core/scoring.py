from __future__ import annotations

from collections import Counter
from itertools import combinations

from agent_bid_rigging.models import ExtractedSignals, PairwiseAssessment, PairwiseFinding


def assess_pairs(signals: list[ExtractedSignals]) -> list[PairwiseAssessment]:
    global_line_counts: Counter[str] = Counter()
    for item in signals:
        global_line_counts.update(set(item.candidate_overlap_lines))

    assessments: list[PairwiseAssessment] = []
    for left, right in combinations(signals, 2):
        findings: list[PairwiseFinding] = []

        findings.extend(_shared_field_findings("联系人电话重合", 30, left.phones, right.phones))
        findings.extend(_shared_field_findings("邮箱重合", 25, left.emails, right.emails))
        findings.extend(_shared_field_findings("银行账号重合", 35, left.bank_accounts, right.bank_accounts))
        findings.extend(
            _shared_field_findings(
                "法定代表人信息重合",
                25,
                left.legal_representatives,
                right.legal_representatives,
            )
        )
        findings.extend(_shared_field_findings("地址信息重合", 20, left.addresses, right.addresses))
        findings.extend(_price_findings(left, right))
        findings.extend(_pair_only_line_findings(left, right, global_line_counts))

        score = sum(finding.weight for finding in findings)
        assessments.append(
            PairwiseAssessment(
                supplier_a=left.document.name,
                supplier_b=right.document.name,
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


def _price_findings(left: ExtractedSignals, right: ExtractedSignals) -> list[PairwiseFinding]:
    if not left.bid_amounts or not right.bid_amounts:
        return []

    findings: list[PairwiseFinding] = []
    left_min = min(left.bid_amounts)
    right_min = min(right.bid_amounts)
    diff = abs(left_min - right_min)
    base = max(abs(left_min), abs(right_min), 1.0)
    ratio = diff / base

    if diff == 0:
        findings.append(
            PairwiseFinding(
                title="投标报价完全一致",
                weight=35,
                evidence=[f"{left.document.name} 与 {right.document.name} 报价均为 {left_min:.2f}"],
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
    left: ExtractedSignals,
    right: ExtractedSignals,
    global_line_counts: Counter[str],
) -> list[PairwiseFinding]:
    overlap = sorted(
        line
        for line in (set(left.candidate_overlap_lines) & set(right.candidate_overlap_lines))
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
            evidence=[f"重合行: {line}" for line in overlap[:5]],
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
