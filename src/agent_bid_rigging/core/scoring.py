from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
from itertools import combinations
import re

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
ERROR_LIKE_TOKENS = (
    "错误",
    "有误",
    "错填",
    "漏填",
    "缺失",
    "不一致",
    "不满足",
    "未响应",
    "负偏离",
    "作废",
    "已退回",
    "空白",
    "错别字",
    "笔误",
    "误写",
    "误录",
    "错漏",
    "漏页",
    "缺页",
    "漏项",
    "错项",
)
RARE_EXPRESSION_TOKENS = (
    "api",
    "json",
    "xml",
    "token",
    "sku",
    "ca",
    "ip",
    "md5",
    "sha",
    "v1",
    "v2",
    "v3",
    "回滚窗口",
    "双轨校验",
    "幂等",
    "mapping",
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
        findings.extend(_normalized_shared_person_findings("联系人姓名重合", 10, _contact_names(left), _contact_names(right)))
        findings.extend(
            _normalized_shared_person_findings(
                "法定代表人信息重合",
                25,
                _legal_representatives(left),
                _legal_representatives(right),
            )
        )
        findings.extend(
            _normalized_shared_person_findings(
                "授权代表信息重合",
                20,
                _authorized_representatives(left),
                _authorized_representatives(right),
            )
        )
        findings.extend(_normalized_shared_field_findings("地址信息重合", 20, _addresses(left), _addresses(right)))
        findings.extend(_price_findings(left, right))
        findings.extend(_pricing_row_findings(left, right))
        findings.extend(_authorization_findings(left, right))
        findings.extend(_structure_findings(left, right))
        findings.extend(_timeline_findings(left, right))
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


def _normalized_shared_field_findings(
    title: str,
    weight: int,
    left_values: list[str],
    right_values: list[str],
) -> list[PairwiseFinding]:
    left_map = {_normalize_address(value): value for value in left_values if _normalize_address(value)}
    right_map = {_normalize_address(value): value for value in right_values if _normalize_address(value)}
    overlap = sorted(set(left_map) & set(right_map))
    if not overlap:
        return []
    return [
        PairwiseFinding(
            title=title,
            weight=weight,
            evidence=[f"共享字段值: {left_map[value]} / {right_map[value]}" for value in overlap[:5]],
        )
    ]


def _normalized_shared_person_findings(
    title: str,
    weight: int,
    left_values: list[str],
    right_values: list[str],
) -> list[PairwiseFinding]:
    left_map = {_normalize_person_name(value): value for value in left_values if _normalize_person_name(value)}
    right_map = {_normalize_person_name(value): value for value in right_values if _normalize_person_name(value)}
    overlap = sorted(set(left_map) & set(right_map))
    if not overlap:
        return []
    return [
        PairwiseFinding(
            title=title,
            weight=weight,
            evidence=[f"共享字段值: {left_map[value]} / {right_map[value]}" for value in overlap[:5]],
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

    error_lines = [line for line in overlap if _is_shared_error_like_overlap(line, left, right)]
    rare_lines = [
        line
        for line in overlap
        if line not in error_lines and _is_rare_expression_overlap(line, left, right)
    ]
    general_lines = [line for line in overlap if line not in error_lines and line not in rare_lines]

    findings: list[PairwiseFinding] = []
    if error_lines:
        weight = 28 if len(error_lines) >= 2 else 18
        findings.append(
            PairwiseFinding(
                title="仅两家共享的共同错误表述",
                weight=weight,
                evidence=[_format_overlap_evidence(line, left, right) for line in error_lines[:5]],
                evidence_details=[_build_overlap_evidence_detail(line, left, right) for line in error_lines[:5]],
            )
        )
    if rare_lines:
        weight = 22 if len(rare_lines) >= 3 else 14
        findings.append(
            PairwiseFinding(
                title="仅两家共享的罕见表达重合",
                weight=weight,
                evidence=[_format_overlap_evidence(line, left, right) for line in rare_lines[:5]],
                evidence_details=[_build_overlap_evidence_detail(line, left, right) for line in rare_lines[:5]],
            )
        )
    if general_lines and not findings:
        weight = 8 if len(general_lines) >= 4 else 4
        findings.append(
            PairwiseFinding(
                title="仅两家共享的一般文本相似",
                weight=weight,
                evidence=[_format_overlap_evidence(line, left, right) for line in general_lines[:5]],
                evidence_details=[_build_overlap_evidence_detail(line, left, right) for line in general_lines[:5]],
            )
        )

    return findings


def _pricing_row_findings(left: ExtractedSignals | SupplierFacts, right: ExtractedSignals | SupplierFacts) -> list[PairwiseFinding]:
    findings: list[PairwiseFinding] = []
    left_rows = _normalized_pricing_rows(left)
    right_rows = _normalized_pricing_rows(right)

    structure_overlap = sorted(set(left_rows) & set(right_rows))
    if structure_overlap:
        if len(structure_overlap) >= 3:
            title = "分项报价结构高度一致"
            weight = 20
        elif len(structure_overlap) >= 2:
            title = "分项报价结构相似"
            weight = 12
        else:
            title = "分项报价单项重合"
            weight = 6
        findings.append(
            PairwiseFinding(
                title=title,
                weight=weight,
                evidence=[f"共享报价行: {value}" for value in structure_overlap[:5]],
            )
        )

    tax_overlap = sorted(set(_pricing_tax_rates(left)) & set(_pricing_tax_rates(right)))
    if tax_overlap:
        findings.append(
            PairwiseFinding(
                title="分项报价税率一致",
                weight=6 if len(tax_overlap) == 1 else 10,
                evidence=[f"共享税率: {value}" for value in tax_overlap[:5]],
            )
        )

    note_overlap = sorted(set(_pricing_notes(left)) & set(_pricing_notes(right)))
    if note_overlap:
        findings.append(
            PairwiseFinding(
                title="特殊计价说明重合",
                weight=8 if len(note_overlap) == 1 else 12,
                evidence=[f"共享计价说明: {value}" for value in note_overlap[:5]],
            )
        )

    return findings


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
    findings.extend(
        _shared_field_findings(
            "授权对象重合",
            12,
            _authorization_targets(left),
            _authorization_targets(right),
        )
    )
    findings.extend(
        _shared_field_findings(
            "授权范围重合",
            10,
            _authorization_scopes(left),
            _authorization_scopes(right),
        )
    )
    return findings


def _structure_findings(left: ExtractedSignals | SupplierFacts, right: ExtractedSignals | SupplierFacts) -> list[PairwiseFinding]:
    findings: list[PairwiseFinding] = []
    file_hit = False
    section_high = False
    table_high = False

    left_doc_hash = _document_fingerprint(left)
    right_doc_hash = _document_fingerprint(right)
    shared_component_hashes = sorted(_component_fingerprints(left) & _component_fingerprints(right))
    if left_doc_hash and right_doc_hash and left_doc_hash == right_doc_hash:
        findings.append(
            PairwiseFinding(
                title="文件完全一致",
                weight=30,
                evidence=[
                    f"{_supplier_name(left)} 与 {_supplier_name(right)} 文档级指纹一致",
                    *_shared_component_examples(left, right),
                ],
            )
        )
        file_hit = True
    elif len(shared_component_hashes) >= 2:
        findings.append(
            PairwiseFinding(
                title="文件完全一致",
                weight=28,
                evidence=[
                    f"共享组件指纹数: {len(shared_component_hashes)}",
                    *_shared_component_examples(left, right),
                ],
            )
        )
        file_hit = True
    elif shared_component_hashes:
        findings.append(
            PairwiseFinding(
                title="文件指纹重合",
                weight=18,
                evidence=[
                    f"共享组件指纹数: {len(shared_component_hashes)}",
                    *_shared_component_examples(left, right),
                ],
            )
        )
        file_hit = True

    left_profile = _section_order_profile(left)
    right_profile = _section_order_profile(right)
    section_similarity = _sequence_similarity(left_profile, right_profile)
    if min(len(left_profile), len(right_profile)) >= 4 and section_similarity >= 0.9:
        findings.append(
            PairwiseFinding(
                title="章节顺序高度同构",
                weight=12,
                evidence=[
                    f"章节顺序相似度 {section_similarity:.0%}",
                    f"章节画像示例: {_section_profile_preview(left_profile)} / {_section_profile_preview(right_profile)}",
                ],
            )
        )
        section_high = True
    elif min(len(left_profile), len(right_profile)) >= 3 and section_similarity >= 0.75:
        findings.append(
            PairwiseFinding(
                title="章节顺序相似",
                weight=6,
                evidence=[
                    f"章节顺序相似度 {section_similarity:.0%}",
                    f"章节画像示例: {_section_profile_preview(left_profile)} / {_section_profile_preview(right_profile)}",
                ],
            )
        )

    table_summary = _table_structure_overlap(left, right)
    if table_summary["high"]:
        findings.append(
            PairwiseFinding(
                title="关键表格结构高度一致",
                weight=12,
                evidence=[
                    f"共享关键表格结构签名数: {table_summary['shared_count']}",
                    *_table_structure_examples(table_summary),
                ],
            )
        )
        table_high = True
    elif table_summary["similar"]:
        findings.append(
            PairwiseFinding(
                title="关键表格结构相似",
                weight=6,
                evidence=[
                    f"共享关键表格结构轮廓数: {table_summary['shared_count']}",
                    *_table_structure_examples(table_summary),
                ],
            )
        )

    if (file_hit and section_high) or (file_hit and table_high) or (section_high and table_high):
        findings.append(
            PairwiseFinding(
                title="异常同构结构",
                weight=20,
                evidence=[_abnormal_homology_reason(file_hit, section_high, table_high)],
            )
        )

    return findings


def _timeline_findings(left: ExtractedSignals | SupplierFacts, right: ExtractedSignals | SupplierFacts) -> list[PairwiseFinding]:
    findings: list[PairwiseFinding] = []
    left_created = set(_timeline_created_times(left))
    right_created = set(_timeline_created_times(right))
    left_modified = set(_timeline_modified_times(left))
    right_modified = set(_timeline_modified_times(right))

    shared_created = sorted(left_created & right_created)
    shared_modified = sorted(left_modified & right_modified)
    if shared_created and shared_modified:
        findings.append(
            PairwiseFinding(
                title="创建修改时间高度重合",
                weight=18,
                evidence=[
                    f"共享创建时间数: {len(shared_created)}",
                    f"共享修改时间数: {len(shared_modified)}",
                ],
            )
        )
    elif shared_created or shared_modified:
        findings.append(
            PairwiseFinding(
                title="时间轨迹异常接近",
                weight=10,
                evidence=[
                    f"共享创建时间数: {len(shared_created)}",
                    f"共享修改时间数: {len(shared_modified)}",
                ],
            )
        )

    shared_uploaded = sorted(set(_timeline_uploaded_times(left)) & set(_timeline_uploaded_times(right)))
    if shared_uploaded:
        findings.append(
            PairwiseFinding(
                title="上传时间高度重合",
                weight=8,
                evidence=[f"共享上传时间数: {len(shared_uploaded)}"],
            )
        )

    shared_ca_users = sorted(set(_timeline_ca_users(left)) & set(_timeline_ca_users(right)))
    if shared_ca_users:
        findings.append(
            PairwiseFinding(
                title="CA使用人重合",
                weight=16,
                evidence=[f"共享CA使用人: {value}" for value in shared_ca_users[:5]],
            )
        )

    shared_terminals = sorted(set(_timeline_terminal_ids(left)) & set(_timeline_terminal_ids(right)))
    shared_ips = sorted(set(_timeline_ip_addresses(left)) & set(_timeline_ip_addresses(right)))
    if shared_terminals or shared_ips:
        evidence: list[str] = []
        if shared_terminals:
            evidence.extend(f"共享终端标识: {value}" for value in shared_terminals[:5])
        if shared_ips:
            evidence.extend(f"共享IP地址: {value}" for value in shared_ips[:5])
        findings.append(
            PairwiseFinding(
                title="终端/IP信息重合",
                weight=18 if shared_terminals and shared_ips else 12,
                evidence=evidence,
            )
        )

    shared_platform_traces = sorted(set(_platform_trace_lines(left)) & set(_platform_trace_lines(right)))
    if shared_platform_traces:
        findings.append(
            PairwiseFinding(
                title="平台侧电子痕迹重合",
                weight=20,
                evidence=[f"共享平台侧痕迹: {value}" for value in shared_platform_traces[:5]],
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


def _is_shared_error_like_overlap(line: str, left: ExtractedSignals | SupplierFacts, right: ExtractedSignals | SupplierFacts) -> bool:
    lowered = line.lower()
    if any(token in lowered for token in ERROR_LIKE_TOKENS):
        return True
    if re.search(r"(序号|页码|编号).{0,8}(有误|错误|不一致|缺失|漏填|错填|作废)", line):
        return True
    left_refs = _candidate_overlap_refs(left).get(line, [])
    right_refs = _candidate_overlap_refs(right).get(line, [])
    if _refs_include_titles(left_refs, ("偏离", "应答", "响应")) and _refs_include_titles(right_refs, ("偏离", "应答", "响应")):
        return any(token in lowered for token in ("不", "未", "负偏离", "缺失", "错误", "有误"))
    return False


def _is_rare_expression_overlap(line: str, left: ExtractedSignals | SupplierFacts, right: ExtractedSignals | SupplierFacts) -> bool:
    if len(line) < 14:
        return False
    if line not in _rare_lines(left) or line not in _rare_lines(right):
        return False
    lowered = line.lower()
    if any(token in lowered for token in RARE_EXPRESSION_TOKENS):
        return True
    if re.search(r"[A-Za-z0-9]", line) and re.search(r"[\u4e00-\u9fff]", line):
        return True
    if sum(1 for token in ("(", ")", "（", "）", "/", "%", "-", "_", ":", "：") if token in line) >= 2:
        return True
    if len(re.findall(r"[A-Za-z]{2,}|\d{2,}", line)) >= 2:
        return True
    return False


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


def _refs_include_titles(refs: list[dict], keywords: tuple[str, ...]) -> bool:
    for ref in refs:
        title = str(ref.get("component_title") or "")
        source_document = str(ref.get("source_document") or "")
        corpus = f"{title} {source_document}"
        if any(keyword in corpus for keyword in keywords):
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
        "联系人姓名重合",
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
        "分项报价税率一致",
        "特殊计价说明重合",
    }:
        return "pricing_link"
    if title in {"仅两家共享的共同错误表述", "仅两家共享的罕见表达重合", "仅两家共享的一般文本相似"} or "文本重合" in title:
        return "text_similarity"
    if title in {"文件完全一致", "文件高度同源", "文件指纹重合", "章节顺序高度同构", "章节顺序相似", "关键表格结构高度一致", "关键表格结构相似", "异常同构结构"}:
        return "file_homology"
    if title in {"授权链重合", "授权材料异常一致", "授权厂家重合", "授权方重合", "授权时间重合", "授权对象重合", "授权范围重合"}:
        return "authorization_chain"
    if title in {"时间轨迹异常接近", "创建修改时间高度重合", "上传时间高度重合", "CA使用人重合", "终端/IP信息重合", "平台侧电子痕迹重合"}:
        return "timeline_trace"
    return "text_similarity"


def _tier_for_finding(title: str, weight: int) -> str:
    if title in {"统一社会信用代码重合", "银行账号重合"}:
        return "strong"
    if title in {"联系人电话重合", "邮箱重合", "投标报价完全一致", "分项报价结构高度一致", "文件完全一致", "文件指纹重合", "异常同构结构"}:
        return "strong"
    if title in {"法定代表人信息重合", "授权厂家重合", "授权方重合", "授权对象重合", "章节顺序高度同构", "关键表格结构高度一致"}:
        return "medium"
    if title in {"授权代表信息重合", "地址信息重合", "投标报价极度接近", "分项报价结构相似", "授权时间重合", "特殊计价说明重合", "授权范围重合"}:
        return "medium"
    if title in {"联系人姓名重合", "分项报价税率一致", "章节顺序相似", "关键表格结构相似", "时间轨迹异常接近", "上传时间高度重合"}:
        return "weak"
    if title in {"创建修改时间高度重合", "CA使用人重合", "终端/IP信息重合", "平台侧电子痕迹重合"}:
        return "medium"
    if title == "仅两家共享的共同错误表述":
        return "medium"
    if title == "仅两家共享的罕见表达重合":
        return "medium"
    if title == "仅两家共享的一般文本相似":
        return "weak"
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


def _rare_lines(item: ExtractedSignals | SupplierFacts) -> set[str]:
    if isinstance(item, SupplierFacts):
        return set(item.rare_line_fingerprints.values())
    return set(item.rare_line_fingerprints.values())


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


def _contact_names(item: ExtractedSignals | SupplierFacts) -> list[str]:
    if isinstance(item, SupplierFacts):
        return [fact.value for fact in item.contact_names]
    return getattr(item, "contact_names", [])


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


def _timeline_created_times(item: ExtractedSignals | SupplierFacts) -> list[str]:
    if isinstance(item, SupplierFacts):
        return list(item.timeline_created_times)
    return [
        component["created_at"]
        for component in item.document.metadata.get("components", [])
        if component.get("created_at")
    ]


def _timeline_modified_times(item: ExtractedSignals | SupplierFacts) -> list[str]:
    if isinstance(item, SupplierFacts):
        return list(item.timeline_modified_times)
    return [
        component["modified_at"]
        for component in item.document.metadata.get("components", [])
        if component.get("modified_at")
    ]


def _timeline_uploaded_times(item: ExtractedSignals | SupplierFacts) -> list[str]:
    if isinstance(item, SupplierFacts):
        return list(item.timeline_uploaded_times)
    return [
        normalize_text_field(component.get("upload_at"))
        for component in item.document.metadata.get("components", [])
        if component.get("upload_at")
    ]


def _timeline_ca_users(item: ExtractedSignals | SupplierFacts) -> list[str]:
    if isinstance(item, SupplierFacts):
        return list(item.timeline_ca_users)
    return [
        normalize_text_field(component.get("ca_user"))
        for component in item.document.metadata.get("components", [])
        if component.get("ca_user")
    ]


def _timeline_terminal_ids(item: ExtractedSignals | SupplierFacts) -> list[str]:
    if isinstance(item, SupplierFacts):
        return list(item.timeline_terminal_ids)
    values: list[str] = []
    for component in item.document.metadata.get("components", []):
        value = normalize_text_field(component.get("terminal_id") or component.get("client_id") or component.get("device_id"))
        if value:
            values.append(value)
    return values


def _timeline_ip_addresses(item: ExtractedSignals | SupplierFacts) -> list[str]:
    if isinstance(item, SupplierFacts):
        return list(item.timeline_ip_addresses)
    values: list[str] = []
    for component in item.document.metadata.get("components", []):
        value = normalize_text_field(component.get("client_ip") or component.get("upload_ip") or component.get("ip"))
        if value:
            values.append(value)
    return values


def _platform_trace_lines(item: ExtractedSignals | SupplierFacts) -> list[str]:
    if isinstance(item, SupplierFacts):
        return list(item.platform_trace_lines)
    lines: list[str] = []
    for component in item.document.metadata.get("components", []):
        parts: list[str] = []
        for value in (
            component.get("upload_at"),
            component.get("ca_user"),
            component.get("terminal_id") or component.get("client_id") or component.get("device_id"),
            component.get("client_ip") or component.get("upload_ip") or component.get("ip"),
        ):
            normalized = normalize_text_field(value)
            if normalized:
                parts.append(normalized)
        if parts:
            lines.append("｜".join(parts))
    return lines


def _normalize_address(value: str) -> str:
    normalized = str(value or "").strip()
    normalized = normalized.replace("（", "(").replace("）", ")")
    normalized = normalized.replace("中国", "")
    normalized = re.sub(r"[，,；;。]+", "", normalized)
    normalized = "".join(normalized.split())
    return normalized.rstrip("，,。；;：:")


def _normalize_person_name(value: str) -> str:
    normalized = normalize_text_field(value)
    normalized = re.sub(r"(先生|女士|老师)$", "", normalized)
    normalized = re.sub(
        r"(联系人|项目联系人|法定代表人|授权代表|委托代理人|代理人|被授权人|授权委托人)",
        "",
        normalized,
    )
    normalized = re.sub(r"[^\u4e00-\u9fffA-Za-z]", "", normalized)
    return normalized


def normalize_text_field(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text)
    return text


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


def _pricing_rows(item: ExtractedSignals | SupplierFacts) -> list[dict[str, str]]:
    if isinstance(item, SupplierFacts):
        rows: list[dict[str, str]] = []
        for row in item.pricing_rows:
            if not row.get("value"):
                continue
            rows.append(
                {
                    "value": str(row.get("value") or ""),
                    "item_name": str(row.get("item_name") or ""),
                    "amount": str(row.get("amount") or ""),
                    "tax_rate": str(row.get("tax_rate") or ""),
                    "pricing_note": str(row.get("pricing_note") or ""),
                }
            )
        return rows
    return []


def _normalized_pricing_rows(item: ExtractedSignals | SupplierFacts) -> list[str]:
    rows = []
    for row in _pricing_rows(item):
        item_name = normalize_text_field(row.get("item_name"))
        amount = normalize_text_field(row.get("amount"))
        if item_name and amount:
            rows.append(f"{item_name}={amount}")
            continue
        value = normalize_text_field(row.get("value"))
        if value:
            rows.append(value)
    return rows


def _pricing_tax_rates(item: ExtractedSignals | SupplierFacts) -> list[str]:
    rates = []
    for row in _pricing_rows(item):
        tax_rate = normalize_text_field(row.get("tax_rate"))
        if tax_rate:
            rates.append(tax_rate)
    return rates


def _pricing_notes(item: ExtractedSignals | SupplierFacts) -> list[str]:
    notes = []
    for row in _pricing_rows(item):
        note = normalize_text_field(row.get("pricing_note"))
        if note:
            notes.append(note)
    return notes


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


def _authorization_targets(item: ExtractedSignals | SupplierFacts) -> list[str]:
    if isinstance(item, SupplierFacts):
        return [fact.value for fact in item.authorization_targets]
    return []


def _authorization_scopes(item: ExtractedSignals | SupplierFacts) -> list[str]:
    if isinstance(item, SupplierFacts):
        return [fact.value for fact in item.authorization_scopes]
    return []


def _document_fingerprint(item: ExtractedSignals | SupplierFacts) -> str | None:
    if isinstance(item, SupplierFacts):
        for row in item.file_fingerprints:
            if row.get("scope") == "document" and row.get("sha256"):
                return str(row["sha256"])
        return item.text_hash or None
    return item.text_hash or None


def _component_fingerprints(item: ExtractedSignals | SupplierFacts) -> set[str]:
    if isinstance(item, SupplierFacts):
        return {
            str(row["sha256"])
            for row in item.file_fingerprints
            if row.get("scope") == "component" and row.get("sha256")
        }
    return {
        str(component["sha256"])
        for component in item.document.metadata.get("components", [])
        if component.get("sha256")
    }


def _section_order_profile(item: ExtractedSignals | SupplierFacts) -> list[str]:
    if isinstance(item, SupplierFacts):
        return list(item.section_order_profile)
    return []


def _sequence_similarity(left: list[str], right: list[str]) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, "|".join(left), "|".join(right)).ratio()


def _table_structure_profiles(item: ExtractedSignals | SupplierFacts) -> list[dict]:
    if isinstance(item, SupplierFacts):
        return list(item.table_structure_profiles)
    return []


def _table_structure_overlap(left: ExtractedSignals | SupplierFacts, right: ExtractedSignals | SupplierFacts) -> dict[str, object]:
    left_profiles = _table_structure_profiles(left)
    right_profiles = _table_structure_profiles(right)
    if not left_profiles or not right_profiles:
        return {"high": False, "similar": False, "shared_count": 0}

    left_signatures = {str(row.get("signature")) for row in left_profiles if row.get("signature")}
    right_signatures = {str(row.get("signature")) for row in right_profiles if row.get("signature")}
    shared_signatures = sorted(left_signatures & right_signatures)
    if shared_signatures:
        return {
            "high": any(_is_high_table_signature_match(signature) for signature in shared_signatures),
            "similar": True,
            "shared_count": len(shared_signatures),
            "shared_examples": shared_signatures[:3],
        }

    left_shapes = {_table_profile_shape(row) for row in left_profiles}
    right_shapes = {_table_profile_shape(row) for row in right_profiles}
    shared_shapes = [shape for shape in sorted(left_shapes & right_shapes) if shape]
    return {
        "high": False,
        "similar": bool(shared_shapes),
        "shared_count": len(shared_shapes),
        "shared_examples": shared_shapes[:3],
    }


def _shared_component_examples(left: ExtractedSignals | SupplierFacts, right: ExtractedSignals | SupplierFacts) -> list[str]:
    shared = _shared_component_names(left, right)
    if not shared:
        return []
    return [f"共享组件示例: {'、'.join(shared[:3])}"]


def _shared_component_names(left: ExtractedSignals | SupplierFacts, right: ExtractedSignals | SupplierFacts) -> list[str]:
    left_names = _component_names_by_hash(left)
    right_names = _component_names_by_hash(right)
    shared_hashes = sorted(set(left_names) & set(right_names))
    names: list[str] = []
    for sha in shared_hashes:
        for name in left_names.get(sha, []):
            if name and name not in names:
                names.append(name)
        for name in right_names.get(sha, []):
            if name and name not in names:
                names.append(name)
    return names[:5]


def _component_names_by_hash(item: ExtractedSignals | SupplierFacts) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    if isinstance(item, SupplierFacts):
        rows = item.file_fingerprints
    else:
        rows = item.document.metadata.get("components", [])
    for row in rows:
        sha = str(row.get("sha256") or "").strip()
        if not sha:
            continue
        name = str(row.get("display_name") or row.get("relative_path") or "").strip()
        if not name:
            continue
        bucket = mapping.setdefault(sha, [])
        if name not in bucket:
            bucket.append(name)
    return mapping


def _section_profile_preview(profile: list[str]) -> str:
    return " > ".join(profile[:4]) if profile else "无章节画像"


def _table_structure_examples(summary: dict[str, object]) -> list[str]:
    examples = [str(item) for item in (summary.get("shared_examples") or []) if str(item).strip()]
    if not examples:
        return []
    return [f"结构示例: {'；'.join(examples[:2])}"]


def _table_profile_shape(row: dict) -> str:
    source_section = str(row.get("source_section") or "")
    field_name = str(row.get("field_name") or "")
    column_keys = ",".join(sorted(str(value) for value in row.get("column_keys", [])))
    return f"{source_section}|{field_name}|{column_keys}"


def _is_high_table_signature_match(signature: str) -> bool:
    parts = signature.split("|")
    if len(parts) < 4:
        return False
    try:
        row_count = int(parts[-1])
    except ValueError:
        return False
    return row_count >= 2


def _abnormal_homology_reason(file_hit: bool, section_high: bool, table_high: bool) -> str:
    parts: list[str] = []
    if file_hit:
        parts.append("文件指纹命中")
    if section_high:
        parts.append("章节顺序高度同构")
    if table_high:
        parts.append("关键表格结构高度一致")
    return "；".join(parts) + "，需进一步复核是否存在同底稿加工或异常同构制作"
