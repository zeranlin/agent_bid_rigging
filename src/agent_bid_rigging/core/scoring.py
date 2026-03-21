from __future__ import annotations

from collections import Counter
from itertools import combinations

from agent_bid_rigging.models import ExtractedSignals, PairwiseAssessment, PairwiseFinding, ReviewFacts, SupplierFacts

DIMENSION_NAMES = (
    "identity_link",
    "pricing_link",
    "text_similarity",
    "file_homology",
    "authorization_chain",
    "timeline_trace",
)

TEMPLATE_OVERLAP_PATTERNS = (
    "培训特点",
    "有针对性的培训方案",
    "共同的工作小组",
    "应保证设备安装、维修、操作安全的要求",
    "应方便工件的存放、运输和现场的清理",
    "定期作好并整理设备安全方便检查",
    "整理设备试运转中的情况",
    "受到过良好教育",
    "专业技术人员，为该项目提供技术培训",
    "响应 见彩页",
    "投标人根据上述业绩情况后附销售或服务合同复印件",
    "你方组织的",
    "项目名称)的招标",
    "一个 SKU",
    "商品详情页展示",
    "已签订、已退回、已作废的合同信息",
    "品牌数据由平台方统一维护",
    "加入购物车",
    "注册人姓名",
    "单位账号",
    "开户银行全称",
    "支付费用总额的 50%",
    "商城前端展示",
    "供应商填写商品",
    "采购单位",
    "采购服务中心",
    "供应商服务中心",
    "运营管理中心",
    "移动应用",
    "供应商录入商品时",
    "商品详情页",
    "供应商评价主要来源于订单评价积累",
    "正在进行中的项目可进入竞价大厅公开报价",
    "询比价周期内",
    "背靠背报价",
    "报价不可修改",
    "最后报价",
    "加入收藏",
    "立即下单",
)
TEMPLATE_COMPONENT_PATTERNS = (
    "项目实施方案",
    "质量保证及售后服务承诺",
    "售后服务",
    "培训",
    "主要商务要求",
    "具有履行合同所必需的设备和专业技术",
    "供应商应提交的相关资格证明材料",
    "技术偏离表",
    "投标承诺书",
    "投标人业绩情况表",
    "业绩情况表",
    "商务要求",
    "服务承诺",
    "技术方案",
    "功能方案",
    "运营方案",
    "服务方案",
    "项目概述",
    "总体设计方案",
    "功能设计方案",
    "电子商城",
    "商城",
    "询比价",
    "功能设计",
    "系统功能",
)


def assess_pairs(signals: ReviewFacts | list[ExtractedSignals]) -> list[PairwiseAssessment]:
    suppliers = _coerce_suppliers(signals)
    global_line_counts: Counter[str] = Counter()
    for item in suppliers:
        global_line_counts.update(set(_candidate_overlap_lines(item)))

    assessments: list[PairwiseAssessment] = []
    for left, right in combinations(suppliers, 2):
        findings: list[PairwiseFinding] = []

        findings.extend(_shared_field_findings("统一社会信用代码重合", 40, _unified_social_credit_codes(left), _unified_social_credit_codes(right)))
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
        findings.extend(
            _shared_field_findings(
                "授权代表信息重合",
                20,
                _authorized_representatives(left),
                _authorized_representatives(right),
            )
        )
        findings.extend(_shared_field_findings("地址信息重合", 20, _addresses(left), _addresses(right)))
        findings.extend(_price_findings(left, right))
        findings.extend(_pricing_row_findings(left, right))
        findings.extend(_authorization_findings(left, right))
        findings.extend(_pair_only_line_findings(left, right, global_line_counts))

        score = sum(finding.weight for finding in findings)
        assessments.append(
            PairwiseAssessment(
                supplier_a=_supplier_name(left),
                supplier_b=_supplier_name(right),
                risk_score=score,
                risk_level=_risk_level(score),
                findings=sorted(findings, key=lambda item: item.weight, reverse=True),
                dimension_summary=_build_dimension_summary(findings),
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
    overlap = [line for line in overlap if not _is_template_like_overlap(line, left, right)]
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


def _pricing_row_findings(left: ExtractedSignals | SupplierFacts, right: ExtractedSignals | SupplierFacts) -> list[PairwiseFinding]:
    left_rows = _pricing_rows(left)
    right_rows = _pricing_rows(right)
    overlap = sorted(set(left_rows) & set(right_rows))
    if not overlap:
        return []

    if len(overlap) >= 3:
        title = "分项报价结构高度一致"
        weight = 20
    elif len(overlap) >= 2:
        title = "分项报价结构相似"
        weight = 12
    else:
        title = "分项报价单项重合"
        weight = 6
    return [
        PairwiseFinding(
            title=title,
            weight=weight,
            evidence=[f"共享报价行: {value}" for value in overlap[:5]],
        )
    ]


def _authorization_findings(left: ExtractedSignals | SupplierFacts, right: ExtractedSignals | SupplierFacts) -> list[PairwiseFinding]:
    findings: list[PairwiseFinding] = []
    findings.extend(
        _shared_field_findings(
            "授权厂家重合",
            18,
            _authorized_manufacturers(left),
            _authorized_manufacturers(right),
        )
    )
    findings.extend(
        _shared_field_findings(
            "授权方重合",
            15,
            _authorization_issuers(left),
            _authorization_issuers(right),
        )
    )
    findings.extend(
        _shared_field_findings(
            "授权时间重合",
            8,
            _authorization_dates(left),
            _authorization_dates(right),
        )
    )
    return findings


def _is_template_like_overlap(line: str, left: ExtractedSignals | SupplierFacts, right: ExtractedSignals | SupplierFacts) -> bool:
    if any(pattern in line for pattern in TEMPLATE_OVERLAP_PATTERNS):
        return True
    left_refs = _candidate_overlap_refs(left).get(line, [])
    right_refs = _candidate_overlap_refs(right).get(line, [])
    if _refs_look_template_like(left_refs) and _refs_look_template_like(right_refs):
        return True
    return _refs_look_normative_like(left_refs) or _refs_look_normative_like(right_refs)


def _refs_look_template_like(refs: list[dict]) -> bool:
    if not refs:
        return False
    for ref in refs:
        title = str(ref.get("component_title") or "")
        source_document = str(ref.get("source_document") or "")
        corpus = f"{title} {source_document}"
        if any(pattern in corpus for pattern in TEMPLATE_COMPONENT_PATTERNS):
            return True
    return False


def _refs_look_normative_like(refs: list[dict]) -> bool:
    if not refs:
        return False
    for ref in refs:
        title = str(ref.get("component_title") or "")
        source_document = str(ref.get("source_document") or "")
        corpus = f"{title} {source_document}"
        if any(
            pattern in corpus
            for pattern in (
                "技术偏离表",
                "投标承诺书",
                "投标人业绩情况表",
                "业绩情况表",
                "项目实施方案",
                "质量保证及售后服务承诺",
                "售后服务",
                "培训",
                "供应商应提交的相关资格证明材料",
            )
        ):
            return True
    return False


def _risk_level(score: int) -> str:
    if score >= 80:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 20:
        return "medium"
    return "low"


def _build_dimension_summary(findings: list[PairwiseFinding]) -> dict[str, dict[str, object]]:
    summary = {
        name: {
            "matched": False,
            "score": 0,
            "tier": "none",
            "finding_titles": [],
        }
        for name in DIMENSION_NAMES
    }
    for finding in findings:
        dimension = _dimension_for_finding(finding.title)
        tier = _tier_for_finding(finding.title, finding.weight)
        item = summary[dimension]
        item["matched"] = True
        item["score"] = int(item["score"]) + finding.weight
        item["finding_titles"].append(finding.title)
        if _tier_rank(tier) > _tier_rank(str(item["tier"])):
            item["tier"] = tier
    return summary


def _dimension_for_finding(title: str) -> str:
    if title in {
        "统一社会信用代码重合",
        "联系人电话重合",
        "邮箱重合",
        "银行账号重合",
        "法定代表人信息重合",
        "授权代表信息重合",
        "地址信息重合",
    }:
        return "identity_link"
    if title in {
        "投标报价完全一致",
        "投标报价极度接近",
        "投标报价较为接近",
        "分项报价结构高度一致",
        "分项报价结构相似",
        "分项报价单项重合",
    }:
        return "pricing_link"
    if "文本重合" in title:
        return "text_similarity"
    if title in {"文件完全一致", "文件高度同源", "文件指纹重合"}:
        return "file_homology"
    if title in {"授权链重合", "授权材料异常一致", "授权厂家重合", "授权方重合", "授权时间重合"}:
        return "authorization_chain"
    if title in {"时间轨迹异常接近", "创建修改时间高度重合"}:
        return "timeline_trace"
    return "text_similarity"


def _tier_for_finding(title: str, weight: int) -> str:
    if title in {"统一社会信用代码重合", "银行账号重合"}:
        return "strong"
    if title in {"联系人电话重合", "邮箱重合", "投标报价完全一致", "分项报价结构高度一致"}:
        return "strong"
    if title in {"法定代表人信息重合", "授权厂家重合", "授权方重合"}:
        return "medium"
    if title in {"授权代表信息重合", "地址信息重合", "投标报价极度接近", "分项报价结构相似", "授权时间重合"}:
        return "medium"
    if "文本重合" in title:
        return "medium" if weight >= 20 else "weak"
    if title in {"投标报价较为接近", "分项报价单项重合"}:
        return "weak"
    return "medium" if weight >= 20 else "weak"


def _tier_rank(tier: str) -> int:
    return {
        "none": 0,
        "weak": 1,
        "medium": 2,
        "strong": 3,
    }.get(tier, 0)


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


def _unified_social_credit_codes(item: ExtractedSignals | SupplierFacts) -> list[str]:
    if isinstance(item, SupplierFacts):
        return [fact.value for fact in item.unified_social_credit_codes]
    return []


def _legal_representatives(item: ExtractedSignals | SupplierFacts) -> list[str]:
    if isinstance(item, SupplierFacts):
        return [fact.value for fact in item.legal_representatives]
    return item.legal_representatives


def _authorized_representatives(item: ExtractedSignals | SupplierFacts) -> list[str]:
    if isinstance(item, SupplierFacts):
        return [fact.value for fact in item.authorized_representatives]
    return []


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


def _pricing_rows(item: ExtractedSignals | SupplierFacts) -> list[str]:
    if isinstance(item, SupplierFacts):
        return [str(row.get("value")) for row in item.pricing_rows if row.get("value")]
    return []


def _authorized_manufacturers(item: ExtractedSignals | SupplierFacts) -> list[str]:
    if isinstance(item, SupplierFacts):
        return [fact.value for fact in item.authorized_manufacturers]
    return []


def _authorization_issuers(item: ExtractedSignals | SupplierFacts) -> list[str]:
    if isinstance(item, SupplierFacts):
        return [fact.value for fact in item.authorization_issuers]
    return []


def _authorization_dates(item: ExtractedSignals | SupplierFacts) -> list[str]:
    if isinstance(item, SupplierFacts):
        return [fact.value for fact in item.authorization_dates]
    return []
