from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

from agent_bid_rigging.models import FactObservation
from agent_bid_rigging.core.extractor import build_tender_baseline, extract_signals
from agent_bid_rigging.core.fusion import build_review_facts
from agent_bid_rigging.core.opinion import generate_review_opinion
from agent_bid_rigging.core.scoring import assess_pairs
from agent_bid_rigging.core.artifacts import (
    _extract_tender_metadata,
    _build_supplier_profiles_from_facts,
    build_authorization_chain_table,
    build_duplicate_detection_table,
    build_evidence_grade_table,
    build_formal_report,
    build_formal_report_markdown,
    build_review_conclusion_table,
    build_risk_score_table,
    build_timeline_table,
    classify_document,
    _build_timeline_opinion,
    _build_timeline_points,
)
from agent_bid_rigging.utils.file_loader import load_document


def test_load_plain_text_document(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("第一行\r\n\r\n第二行", encoding="utf-8")
    doc = load_document("sample", "bid", str(path))
    assert doc.parser == "plain-text"
    assert doc.text == "第一行\n\n第二行"


def test_unsupported_suffix_raises(tmp_path: Path) -> None:
    path = tmp_path / "sample.xls"
    path.write_text("data", encoding="utf-8")
    try:
        load_document("sample", "bid", str(path))
    except ValueError as exc:
        assert "Unsupported document format" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_load_zip_archive_with_multiple_documents(tmp_path: Path) -> None:
    source_dir = tmp_path / "vendor"
    source_dir.mkdir()
    (source_dir / "part1.txt").write_text("联系人电话：13800000000", encoding="utf-8")
    (source_dir / "part2.txt").write_text("投标总报价：123456.00", encoding="utf-8")
    archive_path = tmp_path / "vendor.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.write(source_dir / "part1.txt", arcname="part1.txt")
        archive.write(source_dir / "part2.txt", arcname="part2.txt")

    doc = load_document("vendor", "bid", str(archive_path))
    assert doc.parser == "zip-archive"
    assert "联系人电话：13800000000" in doc.text
    assert "投标总报价：123456.00" in doc.text
    assert doc.metadata["component_count"] == 2


def test_unreadable_archive_names_fall_back_to_titles(tmp_path: Path) -> None:
    source_dir = tmp_path / "vendor"
    source_dir.mkdir()
    bad_name = "σåàΦÆÖσÅñµüÆ.txt"
    (source_dir / bad_name).write_text("授权委托书\n授权委托人：张三", encoding="utf-8")
    archive_path = tmp_path / "vendor_bad.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.write(source_dir / bad_name, arcname=bad_name)

    doc = load_document("vendor", "bid", str(archive_path))
    component = doc.metadata["components"][0]
    assert component["display_name"] == "授权委托书"
    assert component["relative_path"] == "授权委托书.txt"
    assert component["source_path"] == "授权委托书.txt"


def test_extract_signals_filters_tender_template() -> None:
    tender_text = "项目名称：城市保洁\n联系人电话：010-11112222\n通用条款"
    bid_text = (
        "项目名称：城市保洁\n联系人电话：13800000000\n"
        "投标报价：100000\n特别承诺：我司单独编制此文件"
    )
    tender = load_document_from_text("tender", "tender", tender_text)
    bid = load_document_from_text("alpha", "bid", bid_text)
    baseline = build_tender_baseline(tender)
    signals = extract_signals(bid, tender_lines=baseline)
    assert signals.phones == ["13800000000"]
    assert signals.bid_amounts == [100000.0]
    assert "特别承诺：我司单独编制此文件" in signals.non_tender_lines
    assert "项目名称：城市保洁" not in signals.non_tender_lines


def test_extract_signals_finds_contact_name() -> None:
    bid = load_document_from_text("alpha", "bid", "联系人：王小明\n联系电话：13800000000\n投标报价：100000")
    signals = extract_signals(bid)
    assert signals.contact_names == ["王小明"]


def test_extract_signals_finds_price_in_opening_table() -> None:
    bid = load_document_from_text(
        "alpha",
        "bid",
        "开标一览表（报价表）\n项目编号：ABC-001\n投标总报价（元）\n1\n1,788,700.00\n交货期：30日",
    )
    signals = extract_signals(bid)
    assert 1788700.0 in signals.bid_amounts


def test_pairwise_scoring_finds_shared_signals() -> None:
    tender = load_document_from_text("tender", "tender", "项目名称：保洁服务")
    baseline = build_tender_baseline(tender)
    left = extract_signals(
        load_document_from_text(
            "alpha",
            "bid",
            "联系人电话：13800000000\n邮箱：same@example.com\n投标报价：100000\n自定义说明：错别字壹号",
        ),
        tender_lines=baseline,
    )
    right = extract_signals(
        load_document_from_text(
            "beta",
            "bid",
            "联系人电话：13800000000\n邮箱：same@example.com\n投标报价：100000\n自定义说明：错别字壹号",
        ),
        tender_lines=baseline,
    )
    assessment = assess_pairs([left, right])[0]
    assert assessment.risk_level in {"high", "critical"}
    assert assessment.risk_score >= 80
    assert assessment.dimension_summary["identity_link"]["matched"] is True
    assert assessment.dimension_summary["identity_link"]["tier"] == "strong"


def test_pairwise_scoring_can_stay_low() -> None:
    tender = load_document_from_text("tender", "tender", "项目名称：保洁服务")
    baseline = build_tender_baseline(tender)
    left = extract_signals(
        load_document_from_text("alpha", "bid", "联系人电话：13800000000\n投标报价：100000"),
        tender_lines=baseline,
    )
    right = extract_signals(
        load_document_from_text("beta", "bid", "联系人电话：13900000000\n投标报价：130000"),
        tender_lines=baseline,
    )
    assessment = assess_pairs([left, right])[0]
    assert assessment.risk_level == "low"


def test_pairwise_scoring_accepts_review_facts() -> None:
    tender = load_document_from_text("tender", "tender", "项目名称：保洁服务")
    baseline = build_tender_baseline(tender)
    left = extract_signals(
        load_document_from_text(
            "alpha",
            "bid",
            "联系人电话：13800000000\n邮箱：same@example.com\n投标报价：100000\n自定义说明：错别字壹号",
        ),
        tender_lines=baseline,
    )
    right = extract_signals(
        load_document_from_text(
            "beta",
            "bid",
            "联系人电话：13800000000\n邮箱：same@example.com\n投标报价：100000\n自定义说明：错别字壹号",
        ),
        tender_lines=baseline,
    )
    review_facts = build_review_facts(tender, [left, right], [], [])
    assessment = assess_pairs(review_facts)[0]
    assert assessment.risk_level in {"high", "critical"}
    assert assessment.risk_score >= 80


def test_pairwise_scoring_uses_new_review_facts_identity_and_authorization_fields() -> None:
    tender = load_document_from_text("tender", "tender", "项目名称：设备采购")
    left = extract_signals(load_document_from_text("alpha", "bid", "投标总报价：100000"))
    right = extract_signals(load_document_from_text("beta", "bid", "投标总报价：100000"))
    ocr_rows = [
        {
            "supplier": "alpha",
            "source_path": "/tmp/alpha.pdf",
            "page_index": 1,
            "doc_type": "authorization_letter",
            "summary": "授权书",
            "extracted_text": "授权厂家：测试厂家",
            "fields": {
                "authorized_representative": "李四",
                "unified_social_credit_code": "91150105MA0ABCDE1X",
                "authorized_manufacturer": "测试厂家",
                "authorization_issuer": "测试厂家股份有限公司",
                "authorization_date": "2023-12-19",
                "authorization_target": "内蒙古测试经销商有限公司",
                "authorization_scope": "电子胃肠镜及配套设备",
            },
            "confidence": 0.95,
        },
        {
            "supplier": "beta",
            "source_path": "/tmp/beta.pdf",
            "page_index": 1,
            "doc_type": "authorization_letter",
            "summary": "授权书",
            "extracted_text": "授权厂家：测试厂家",
            "fields": {
                "authorized_representative": "李四",
                "unified_social_credit_code": "91150105MA0ABCDE1X",
                "authorized_manufacturer": "测试厂家",
                "authorization_issuer": "测试厂家股份有限公司",
                "authorization_date": "2023-12-19",
                "authorization_target": "内蒙古测试经销商有限公司",
                "authorization_scope": "电子胃肠镜及配套设备",
            },
            "confidence": 0.95,
        },
    ]
    review_facts = build_review_facts(tender, [left, right], [], ocr_rows)
    assessment = assess_pairs(review_facts)[0]
    titles = {finding.title for finding in assessment.findings}
    assert "统一社会信用代码重合" in titles
    assert "授权代表信息重合" in titles
    assert "授权厂家重合" in titles
    assert "授权方重合" in titles
    assert "授权时间重合" in titles
    assert "授权对象重合" in titles
    assert "授权范围重合" in titles
    assert assessment.dimension_summary["identity_link"]["matched"] is True
    assert assessment.dimension_summary["identity_link"]["tier"] == "strong"
    assert assessment.dimension_summary["authorization_chain"]["matched"] is True
    assert assessment.dimension_summary["authorization_chain"]["tier"] == "medium"


def test_pairwise_scoring_uses_pricing_rows_from_review_facts() -> None:
    tender = load_document_from_text("tender", "tender", "项目名称：设备采购")
    left = extract_signals(load_document_from_text("alpha", "bid", "投标总报价：100000"))
    right = extract_signals(load_document_from_text("beta", "bid", "投标总报价：120000"))
    review_facts = build_review_facts(tender, [left, right], [], [])
    review_facts.suppliers[0].pricing_rows.extend(
        [
            {"value": "成品软件=1000000.00"},
            {"value": "定制开发=900000.00"},
            {"value": "系统实施报价=100000.00"},
        ]
    )
    review_facts.suppliers[1].pricing_rows.extend(
        [
            {"value": "成品软件=1000000.00"},
            {"value": "定制开发=900000.00"},
            {"value": "系统实施报价=100000.00"},
        ]
    )
    assessment = assess_pairs(review_facts)[0]
    assert any(finding.title == "分项报价结构高度一致" for finding in assessment.findings)
    assert assessment.dimension_summary["pricing_link"]["matched"] is True
    assert assessment.dimension_summary["pricing_link"]["tier"] == "strong"


def test_pairwise_scoring_distinguishes_total_bid_and_pricing_structure_findings() -> None:
    tender = load_document_from_text("tender", "tender", "项目名称：设备采购")
    left = extract_signals(load_document_from_text("alpha", "bid", "投标总报价：100000"))
    right = extract_signals(load_document_from_text("beta", "bid", "投标总报价：100200"))
    review_facts = build_review_facts(tender, [left, right], [], [])
    review_facts.suppliers[0].pricing_rows.extend(
        [
            {"value": "成品软件=80000.00", "item_name": "成品软件", "amount": "80000.00", "tax_rate": "13%", "pricing_note": "含税"},
            {"value": "实施服务=20000.00", "item_name": "实施服务", "amount": "20000.00", "tax_rate": "13%", "pricing_note": "含税"},
        ]
    )
    review_facts.suppliers[1].pricing_rows.extend(
        [
            {"value": "成品软件=80000.00", "item_name": "成品软件", "amount": "80000.00", "tax_rate": "13%", "pricing_note": "含税"},
            {"value": "实施服务=20000.00", "item_name": "实施服务", "amount": "20000.00", "tax_rate": "13%", "pricing_note": "含税"},
        ]
    )

    assessment = assess_pairs(review_facts)[0]
    titles = {finding.title for finding in assessment.findings}

    assert "投标报价较为接近" in titles
    assert "分项报价结构相似" in titles or "分项报价结构高度一致" in titles
    assert "分项报价税率一致" in titles
    assert "特殊计价说明重合" in titles


def test_pairwise_scoring_uses_contact_names_and_normalized_addresses() -> None:
    tender = load_document_from_text("tender", "tender", "项目名称：设备采购")
    left = extract_signals(load_document_from_text("alpha", "bid", "联系人：王小明\n地址：呼和浩特市 新城区示例路1号\n投标报价：100000"))
    right = extract_signals(load_document_from_text("beta", "bid", "联系人：王小明\n地址：呼和浩特市新城区示例路1号\n投标报价：120000"))

    assessment = assess_pairs(build_review_facts(tender, [left, right], [], []))[0]
    titles = {finding.title for finding in assessment.findings}

    assert "联系人姓名重合" in titles
    assert "地址信息重合" in titles
    assert assessment.dimension_summary["identity_link"]["matched"] is True


def test_pairwise_scoring_normalizes_person_name_variants() -> None:
    tender = load_document_from_text("tender", "tender", "项目名称：设备采购")
    left = extract_signals(load_document_from_text("alpha", "bid", "投标报价：100000"))
    right = extract_signals(load_document_from_text("beta", "bid", "投标报价：120000"))
    review_facts = build_review_facts(tender, [left, right], [], [])
    review_facts.suppliers[0].contact_names = [
        FactObservation(value="王小明先生", source_type="ocr", source_document="/tmp/a.pdf", is_primary=True)
    ]
    review_facts.suppliers[1].contact_names = [
        FactObservation(value="王小明", source_type="text", source_document="/tmp/b.txt", is_primary=True)
    ]

    assessment = assess_pairs(review_facts)[0]
    titles = {finding.title for finding in assessment.findings}

    assert "联系人姓名重合" in titles


def test_signature_noise_does_not_create_high_risk() -> None:
    tender = load_document_from_text("tender", "tender", "项目名称：保洁服务")
    baseline = build_tender_baseline(tender)
    left = extract_signals(
        load_document_from_text(
            "alpha",
            "bid",
            "法定代表人身份证明\n法定代表人（签字）：\n授权委托人（签字）：\n投标报价：100000",
        ),
        tender_lines=baseline,
    )
    right = extract_signals(
        load_document_from_text(
            "beta",
            "bid",
            "法定代表人身份证明\n法定代表人（签字）：\n授权委托人（签字）：\n投标报价：150000",
        ),
        tender_lines=baseline,
    )
    assessment = assess_pairs([left, right])[0]
    assert assessment.risk_level == "low"
    assert not assessment.findings


def test_template_opinion_mentions_high_risk_pair() -> None:
    report = {
        "run_name": "demo",
        "generated_at": "2026-03-20T19:35:19",
        "suppliers": ["alpha", "beta"],
        "review_conclusion_table": {
            "suspicious_clues": ["alpha 与 beta 存在 high 风险线索。"],
            "exclusionary_factors": [],
        },
        "formal_report": {
            "project_basic_info": {
                "project_name": "测试项目",
                "project_id": "P-001",
                "purchaser": "测试采购人",
                "agency": "测试代理机构",
            },
            "review_object_profiles": [
                {"full_name": "阿尔法公司"},
                {"full_name": "贝塔公司"},
            ],
            "review_sections": [
                {"title": "报价情况比对", "points": ["阿尔法公司报价为 100000 元。"], "opinion": "报价差异不足以单独定性。"}
            ],
            "risk_summary": [],
            "evidence_summary": [],
        },
        "pairwise_assessments": [
            {
                "supplier_a": "alpha",
                "supplier_b": "beta",
                "risk_score": 90,
                "risk_level": "critical",
                "dimension_summary": {
                    "identity_link": {"matched": True, "score": 30, "tier": "strong", "finding_titles": ["联系人电话重合"]},
                    "pricing_link": {"matched": False, "score": 0, "tier": "none", "finding_titles": []},
                    "text_similarity": {"matched": False, "score": 0, "tier": "none", "finding_titles": []},
                    "file_homology": {"matched": False, "score": 0, "tier": "none", "finding_titles": []},
                    "authorization_chain": {"matched": False, "score": 0, "tier": "none", "finding_titles": []},
                    "timeline_trace": {"matched": False, "score": 0, "tier": "none", "finding_titles": []},
                },
                "findings": [
                    {
                        "title": "联系人电话重合",
                        "weight": 30,
                        "evidence": ["共享字段值: 13800000000"],
                    }
                ],
            }
        ],
    }
    opinion = generate_review_opinion(report, opinion_mode="template")
    assert opinion["mode"] == "template"
    assert "围串标审查意见书" in opinion["document"]
    assert "## 一、项目概况" in opinion["document"]
    assert "## 三、事实摘要" in opinion["document"]
    assert "## 五、排除性因素" in opinion["document"]
    assert "alpha 与 beta" in opinion["document"]
    assert "维度判断：主体关联强" in opinion["document"]


def test_extract_tender_metadata_can_fallback_to_body_project_name() -> None:
    text = (
        "项目编号：招标编号_TEST_001\n"
        "此次电子商城项目A以XX旅游股份有限公司为主体进行公开比选。\n"
        "其余内容略。"
    )
    metadata = _extract_tender_metadata(text)
    assert metadata["project_name"] == "电子商城项目A"
    assert metadata["project_id"] == "招标编号_TEST_001"


def test_normative_response_sections_do_not_trigger_text_overlap_finding() -> None:
    tender = load_document_from_text("tender", "tender", "项目名称：电子胃肠镜等设备采购项目")
    baseline = build_tender_baseline(tender)
    left = extract_signals(
        load_document_from_text(
            "alpha",
            "bid",
            "技术偏离表\n1、最小可视距离≤3mm。 1、最小可视距离 2mm。 响应 见彩页\n"
            "投标承诺书\n你方组织的 电子胃肠镜等设备采购项目(项目名称)的招标，\n"
            "投标人业绩情况表\n投标人根据上述业绩情况后附销售或服务合同复印件。",
        ),
        tender_lines=baseline,
    )
    right = extract_signals(
        load_document_from_text(
            "beta",
            "bid",
            "技术偏离表\n1、最小可视距离≤3mm。 1、最小可视距离 2mm。 响应 见彩页\n"
            "投标承诺书\n你方组织的 电子胃肠镜等设备采购项目(项目名称)的招标，\n"
            "投标人业绩情况表\n投标人根据上述业绩情况后附销售或服务合同复印件。",
        ),
        tender_lines=baseline,
    )
    assessment = assess_pairs([left, right])[0]
    assert all(finding.title != "仅两家共享的非模板文本重合" for finding in assessment.findings)
    assert all(finding.title != "仅两家共享的一般文本相似" for finding in assessment.findings)


def test_document_classifier_tags_known_document() -> None:
    category = classify_document("开标一览表.pdf", "开标一览表 投标总报价（元）")
    assert category == "开标一览表"


def test_duplicate_detection_table_marks_same_component_hash() -> None:
    tender = load_document_from_text("tender", "tender", "项目名称：设备采购")
    baseline = build_tender_baseline(tender)
    text = "授权书\n授权产品：设备A\n授权期限：一年"
    left = extract_signals(load_document_from_text("alpha", "bid", text), tender_lines=baseline)
    right = extract_signals(load_document_from_text("beta", "bid", text), tender_lines=baseline)
    left.document.metadata["components"] = [
        {"display_name": "授权书A", "sha256": "samehash", "relative_path": "a.txt", "size_bytes": 10}
    ]
    right.document.metadata["components"] = [
        {"display_name": "授权书B", "sha256": "samehash", "relative_path": "b.txt", "size_bytes": 10}
    ]
    table = build_duplicate_detection_table([left, right])
    assert table[0]["duplicate_count"] == 1
    assert table[0]["classification"] == "完全一致"


def test_evidence_grading_and_formal_report() -> None:
    assessment = assess_pairs(
        [
            extract_signals(load_document_from_text("alpha", "bid", "联系人电话：13800000000\n投标报价：100000")),
            extract_signals(load_document_from_text("beta", "bid", "联系人电话：13800000000\n投标报价：100000")),
        ]
    )[0]
    evidence = build_evidence_grade_table([assessment])
    assert evidence
    risk = build_risk_score_table([assessment], [], [], [], [], [])
    report = build_formal_report(
        case_manifest={
            "case_id": "case-1",
            "generated_at": "2026-03-20T20:30:00",
            "input_summary": {"supplier_names": ["alpha", "beta"], "tender_count": 1, "bid_count": 2},
        },
        document_catalog=[],
        review_conclusion_table={
            "verified_facts": ["alpha 与 beta：联系人电话重合。"],
            "suspicious_clues": ["alpha 与 beta 存在 high 风险线索。"],
            "exclusionary_factors": [],
            "recommendations": ["补充核查。"],
        },
        evidence_grade_table=evidence,
        risk_score_table=risk,
    )
    markdown = build_formal_report_markdown(report)
    assert "围串标审查意见书" in markdown
    assert "审查目的" in markdown
    assert "初步审查结论" in markdown
    assert report["preliminary_conclusion"]
    assert report["audit_opinion"]["main_statement"]


def test_formal_report_uses_full_names_and_keeps_timeline_and_clues_consistent() -> None:
    risk_rows = [
        {"supplier_a": "恒禾", "supplier_b": "华康", "total_score": 30, "risk_level": "medium", "technical_text_score": 30, "entity_link_score": 0, "pricing_score": 0, "file_homology_score": 0, "authorization_score": 0, "timeline_score": 0, "dimension_summary": {"identity_link": {"matched": False, "score": 0, "tier": "none", "finding_titles": []}, "pricing_link": {"matched": False, "score": 0, "tier": "none", "finding_titles": []}, "text_similarity": {"matched": True, "score": 30, "tier": "medium", "finding_titles": ["仅两家共享的非模板文本重合"]}, "file_homology": {"matched": False, "score": 0, "tier": "none", "finding_titles": []}, "authorization_chain": {"matched": False, "score": 0, "tier": "none", "finding_titles": []}, "timeline_trace": {"matched": False, "score": 0, "tier": "none", "finding_titles": []}}},
        {"supplier_a": "恒禾", "supplier_b": "唯美", "total_score": 30, "risk_level": "medium", "technical_text_score": 30, "entity_link_score": 0, "pricing_score": 0, "file_homology_score": 0, "authorization_score": 0, "timeline_score": 0, "dimension_summary": {"identity_link": {"matched": False, "score": 0, "tier": "none", "finding_titles": []}, "pricing_link": {"matched": False, "score": 0, "tier": "none", "finding_titles": []}, "text_similarity": {"matched": True, "score": 30, "tier": "medium", "finding_titles": ["仅两家共享的非模板文本重合"]}, "file_homology": {"matched": False, "score": 0, "tier": "none", "finding_titles": []}, "authorization_chain": {"matched": False, "score": 0, "tier": "none", "finding_titles": []}, "timeline_trace": {"matched": False, "score": 0, "tier": "none", "finding_titles": []}}},
        {"supplier_a": "华康", "supplier_b": "唯美", "total_score": 0, "risk_level": "low", "technical_text_score": 0, "entity_link_score": 0, "pricing_score": 0, "file_homology_score": 0, "authorization_score": 0, "timeline_score": 0, "dimension_summary": {"identity_link": {"matched": False, "score": 0, "tier": "none", "finding_titles": []}, "pricing_link": {"matched": False, "score": 0, "tier": "none", "finding_titles": []}, "text_similarity": {"matched": False, "score": 0, "tier": "none", "finding_titles": []}, "file_homology": {"matched": False, "score": 0, "tier": "none", "finding_titles": []}, "authorization_chain": {"matched": False, "score": 0, "tier": "none", "finding_titles": []}, "timeline_trace": {"matched": False, "score": 0, "tier": "none", "finding_titles": []}}},
    ]
    evidence_rows = [
        {
            "pair": "恒禾 与 华康",
            "finding_title": "仅两家共享的非模板文本重合",
            "evidence_grade": "B",
            "reason": "较强异常线索，需要结合其他证据判断。",
            "evidence": ["重合行: 培训特点是目的性、针对性、实效性和创新性："],
            "evidence_details": [
                {
                    "snippet": "培训特点是目的性、针对性、实效性和创新性：",
                    "left": {
                        "supplier": "恒禾",
                        "source_document": "恒禾.txt",
                        "source_page": None,
                        "source_line": 120,
                        "component_title": "项目实施方案",
                    },
                    "right": {
                        "supplier": "华康",
                        "source_document": "华康.txt",
                        "source_page": None,
                        "source_line": 118,
                        "component_title": "项目实施方案",
                    },
                }
            ],
        },
        {
            "pair": "恒禾 与 唯美",
            "finding_title": "仅两家共享的非模板文本重合",
            "evidence_grade": "B",
            "reason": "较强异常线索，需要结合其他证据判断。",
            "evidence": ["重合行: 整理设备试运转中的情况(包括故障排除)记录；"],
            "evidence_details": [
                {
                    "snippet": "整理设备试运转中的情况(包括故障排除)记录；",
                    "left": {
                        "supplier": "恒禾",
                        "source_document": "恒禾.txt",
                        "source_page": None,
                        "source_line": 80,
                        "component_title": "项目实施方案",
                    },
                    "right": {
                        "supplier": "唯美",
                        "source_document": "唯美.txt",
                        "source_page": None,
                        "source_line": 66,
                        "component_title": "项目实施方案",
                    },
                }
            ],
        },
    ]
    report = build_formal_report(
        case_manifest={
            "case_id": "case-2",
            "generated_at": "2026-03-21T10:00:00",
            "input_summary": {"supplier_names": ["恒禾", "华康", "唯美"], "tender_count": 1, "bid_count": 3},
            "source_paths": {},
        },
        document_catalog=[],
        review_conclusion_table={
            "verified_facts": [
                "恒禾 与 华康：仅两家共享的非模板文本重合。",
                "恒禾 与 唯美：仅两家共享的非模板文本重合。",
            ],
            "suspicious_clues": [
                "恒禾 与 华康 存在 medium 风险线索，分值 30。",
                "恒禾 与 唯美 存在 medium 风险线索，分值 30。",
            ],
            "exclusionary_factors": ["华康 与 唯美 未发现明显异常信号。"],
            "recommendations": ["补充核查。"],
        },
        evidence_grade_table=evidence_rows,
        risk_score_table=risk_rows,
        structure_similarity_table=[
            {"supplier_a": "恒禾", "supplier_b": "华康", "category_overlap_ratio": 0.66},
            {"supplier_a": "恒禾", "supplier_b": "唯美", "category_overlap_ratio": 0.66},
            {"supplier_a": "华康", "supplier_b": "唯美", "category_overlap_ratio": 0.66},
        ],
        timeline_table=[
            {"supplier": "恒禾", "summary": "未见明显集中生成特征"},
            {"supplier": "华康", "summary": "未见明显集中生成特征"},
            {"supplier": "唯美", "summary": "未见明显集中生成特征"},
        ],
        bid_documents=[
            {"document": {"name": "恒禾", "text": "内蒙古恒禾创业信息科技服务有限公司"}, "phones": [], "emails": [], "bank_accounts": [], "legal_representatives": [], "addresses": []},
            {"document": {"name": "华康", "text": "华康君安（北京）科技有限公司"}, "phones": [], "emails": [], "bank_accounts": [], "legal_representatives": [], "addresses": []},
            {"document": {"name": "唯美", "text": "内蒙古维美科技有限公司"}, "phones": [], "emails": [], "bank_accounts": [], "legal_representatives": [], "addresses": []},
        ],
    )
    markdown = build_formal_report_markdown(report)
    assert "内蒙古恒禾创业信息科技服务有限公司与华康君安（北京）科技有限公司" in markdown
    assert "内蒙古恒禾创业信息科技服务有限公司与内蒙古维美科技有限公司" in markdown
    assert "部分供应商文件存在集中生成迹象" not in markdown
    assert "平均类别重合度" not in markdown
    assert "medium 风险线索" not in markdown
    assert "总分为" not in markdown
    assert "审查日期：2026-03-21 10:00:00" in markdown
    assert "审查人：人工智能审查" in markdown
    assert "附：文本重合证据附表" in markdown
    assert "恒禾.txt / 项目实施方案 / 第120行" in markdown
    assert "一般目录编排或材料类别相似" in markdown
    assert "**围串标判断维度摘要**" in markdown
    assert "文本与方案关联中" in markdown
    assert "主体关联未命中" in markdown


def test_authorization_section_treats_shared_manufacturer_as_normal_competition() -> None:
    tender = load_document_from_text("tender", "tender", "项目名称：设备采购")
    left = extract_signals(load_document_from_text("alpha", "bid", "投标总报价：100000"))
    right = extract_signals(load_document_from_text("beta", "bid", "投标总报价：120000"))
    ocr_rows = [
        {
            "supplier": "alpha",
            "source_path": "/tmp/alpha.pdf",
            "page_index": 1,
            "doc_type": "authorization_letter",
            "summary": "授权书",
            "extracted_text": "授权厂家：测试厂家",
            "fields": {
                "authorized_manufacturer": "测试厂家",
            },
            "confidence": 0.95,
        },
        {
            "supplier": "beta",
            "source_path": "/tmp/beta.pdf",
            "page_index": 1,
            "doc_type": "authorization_letter",
            "summary": "授权书",
            "extracted_text": "授权厂家：测试厂家",
            "fields": {
                "authorized_manufacturer": "测试厂家",
            },
            "confidence": 0.95,
        },
    ]
    review_facts = build_review_facts(tender, [left, right], [], ocr_rows)
    assessments = assess_pairs(review_facts)
    evidence = build_evidence_grade_table(assessments)
    risk = build_risk_score_table(assessments, [], [], [], build_authorization_chain_table(review_facts), [])
    review_conclusion = build_review_conclusion_table(assessments)
    report = build_formal_report(
        case_manifest={
            "case_id": "case-auth-1",
            "generated_at": "2026-03-23T12:00:00",
            "input_summary": {"supplier_names": ["alpha", "beta"], "tender_count": 1, "bid_count": 2},
            "source_paths": {},
        },
        document_catalog=[],
        review_conclusion_table=review_conclusion,
        evidence_grade_table=evidence,
        risk_score_table=risk,
        review_facts=review_facts,
        authorization_chain_table=build_authorization_chain_table(review_facts),
    )
    markdown = build_formal_report_markdown(report)

    assert "授权厂家识别为 `测试厂家`" in markdown
    assert "授权对象识别为 `未自动识别`" in markdown
    assert "在设备类采购中，这种情形可能属于正常竞争" in markdown
    assert "主要可疑线索" not in markdown or "授权厂家重合" not in markdown
    assert report["suspicious_clues"] == []


def test_authorization_section_explains_actionable_overlap_combinations() -> None:
    tender = load_document_from_text("tender", "tender", "项目名称：设备采购")
    left = extract_signals(load_document_from_text("alpha", "bid", "投标总报价：100000"))
    right = extract_signals(load_document_from_text("beta", "bid", "投标总报价：120000"))
    ocr_rows = [
        {
            "supplier": "alpha",
            "source_path": "/tmp/alpha.pdf",
            "page_index": 1,
            "doc_type": "authorization_letter",
            "summary": "授权书",
            "extracted_text": "授权书",
            "fields": {
                "authorization_issuer": "测试厂家股份有限公司",
                "authorization_date": "2023-12-19",
                "authorization_target": "内蒙古测试经销商有限公司",
                "authorization_scope": "电子胃肠镜及配套设备",
            },
            "confidence": 0.95,
        },
        {
            "supplier": "beta",
            "source_path": "/tmp/beta.pdf",
            "page_index": 1,
            "doc_type": "authorization_letter",
            "summary": "授权书",
            "extracted_text": "授权书",
            "fields": {
                "authorization_issuer": "测试厂家股份有限公司",
                "authorization_date": "2023-12-19",
                "authorization_target": "内蒙古测试经销商有限公司",
                "authorization_scope": "电子胃肠镜及配套设备",
            },
            "confidence": 0.95,
        },
    ]
    review_facts = build_review_facts(tender, [left, right], [], ocr_rows)
    auth_table = build_authorization_chain_table(review_facts)
    assessments = assess_pairs(review_facts)
    evidence = build_evidence_grade_table(assessments)
    risk = build_risk_score_table(assessments, [], [], [], auth_table, [])
    review_conclusion = build_review_conclusion_table(assessments)
    report = build_formal_report(
        case_manifest={
            "case_id": "case-auth-2",
            "generated_at": "2026-03-23T12:10:00",
            "input_summary": {"supplier_names": ["alpha", "beta"], "tender_count": 1, "bid_count": 2},
            "source_paths": {},
        },
        document_catalog=[],
        review_conclusion_table=review_conclusion,
        evidence_grade_table=evidence,
        risk_score_table=risk,
        review_facts=review_facts,
        authorization_chain_table=auth_table,
    )
    markdown = build_formal_report_markdown(report)
    opinion = generate_review_opinion(
        {
            "run_name": "case-auth-2",
            "generated_at": "2026-03-23T12:10:00",
            "suppliers": ["alpha", "beta"],
            "review_conclusion_table": review_conclusion,
            "formal_report": report,
            "pairwise_assessments": [
                {
                    "supplier_a": item["supplier_a"],
                    "supplier_b": item["supplier_b"],
                    "risk_score": item["total_score"],
                    "risk_level": item["risk_level"],
                    "dimension_summary": item["dimension_summary"],
                    "findings": [],
                }
                for item in risk
            ],
        },
        opinion_mode="template",
    )

    assert auth_table[0]["authorization_targets"] == ["内蒙古测试经销商有限公司"]
    assert auth_table[0]["authorization_scopes"] == ["电子胃肠镜及配套设备"]
    assert "授权对象识别为 `内蒙古测试经销商有限公司`" in markdown
    assert "授权范围识别为 `电子胃肠镜及配套设备`" in markdown
    assert "需进一步复核授权链是否异常重叠" in markdown or "需进一步复核是否存在异常授权安排" in markdown
    assert report["suspicious_clues"]
    assert "授权及资格材料比对" in opinion["document"]
    assert "需进一步复核授权链是否异常重叠" in opinion["document"] or "需进一步复核是否存在异常授权安排" in opinion["document"]


def test_risk_score_table_matches_pairwise_assessment() -> None:
    assessment = assess_pairs(
        [
            extract_signals(
                load_document_from_text(
                    "alpha",
                    "bid",
                    "联系人电话：13800000000\n邮箱：same@example.com\n投标报价：100000\n特别说明：售后培训方案一致",
                )
            ),
            extract_signals(
                load_document_from_text(
                    "beta",
                    "bid",
                    "联系人电话：13800000000\n邮箱：same@example.com\n投标报价：100000\n特别说明：售后培训方案一致",
                )
            ),
        ]
    )[0]
    risk_table = build_risk_score_table([assessment], [], [], [], [], [])
    assert risk_table[0]["total_score"] == assessment.risk_score
    assert risk_table[0]["risk_level"] == assessment.risk_level
    assert risk_table[0]["dimension_summary"] == assessment.dimension_summary


def test_structure_homology_detects_abnormal_combo_from_file_and_section_profiles() -> None:
    tender = load_document_from_text("tender", "tender", "项目名称：设备采购")
    left = extract_signals(load_document_from_text("alpha", "bid", "投标总报价：100000"))
    right = extract_signals(load_document_from_text("beta", "bid", "投标总报价：120000"))
    review_facts = build_review_facts(tender, [left, right], [], [])
    for supplier in review_facts.suppliers:
        supplier.file_fingerprints.extend(
            [
                {"display_name": "共同文件A.pdf", "relative_path": "共同文件A.pdf", "sha256": "same-1", "size_bytes": 10, "scope": "component"},
                {"display_name": "共同文件B.pdf", "relative_path": "共同文件B.pdf", "sha256": "same-2", "size_bytes": 11, "scope": "component"},
            ]
        )
        supplier.section_order_profile = ["letter", "quotation", "business_profile", "technical_plan", "implementation_plan"]

    assessment = assess_pairs(review_facts)[0]
    titles = {finding.title for finding in assessment.findings}
    file_finding = next(f for f in assessment.findings if f.title == "文件完全一致")
    section_finding = next(f for f in assessment.findings if f.title == "章节顺序高度同构")

    assert "文件完全一致" in titles
    assert "章节顺序高度同构" in titles
    assert "异常同构结构" in titles
    assert any("共同文件A.pdf" in line for line in file_finding.evidence)
    assert any("章节画像示例" in line for line in section_finding.evidence)
    assert assessment.dimension_summary["file_homology"]["matched"] is True
    assert assessment.dimension_summary["file_homology"]["tier"] == "strong"


def test_structure_homology_keeps_section_similarity_as_auxiliary_signal() -> None:
    tender = load_document_from_text("tender", "tender", "项目名称：设备采购")
    left = extract_signals(load_document_from_text("alpha", "bid", "投标总报价：100000"))
    right = extract_signals(load_document_from_text("beta", "bid", "投标总报价：120000"))
    review_facts = build_review_facts(tender, [left, right], [], [])
    review_facts.suppliers[0].section_order_profile = ["letter", "quotation", "technical_plan", "implementation_plan"]
    review_facts.suppliers[1].section_order_profile = ["letter", "quotation", "technical_plan", "implementation_plan"]

    assessment = assess_pairs(review_facts)[0]
    titles = {finding.title for finding in assessment.findings}
    review_conclusion = build_review_conclusion_table([assessment])

    assert "章节顺序高度同构" in titles
    assert "异常同构结构" not in titles
    assert review_conclusion["suspicious_clues"] == []


def test_structure_homology_detects_table_structure_without_forcing_combo() -> None:
    tender = load_document_from_text("tender", "tender", "项目名称：设备采购")
    left = extract_signals(load_document_from_text("alpha", "bid", "投标总报价：100000"))
    right = extract_signals(load_document_from_text("beta", "bid", "投标总报价：120000"))
    review_facts = build_review_facts(tender, [left, right], [], [])
    for supplier in review_facts.suppliers:
        supplier.table_structure_profiles = [
            {
                "source_section": "开标一览表",
                "field_name": "pricing_row",
                "column_keys": ["amount", "field_name", "item_name", "tax_rate"],
                "row_count": 2,
                "signature": "开标一览表|pricing_row|amount,field_name,item_name,tax_rate|2",
            }
        ]

    assessment = assess_pairs(review_facts)[0]
    titles = {finding.title for finding in assessment.findings}

    assert "关键表格结构高度一致" in titles
    assert "异常同构结构" not in titles


def test_timeline_trace_detects_shared_created_and_modified_times() -> None:
    tender = load_document_from_text("tender", "tender", "项目名称：设备采购")
    left = extract_signals(load_document_from_text("alpha", "bid", "投标总报价：100000"))
    right = extract_signals(load_document_from_text("beta", "bid", "投标总报价：120000"))
    left.document.metadata["components"] = [
        {"display_name": "A.pdf", "relative_path": "A.pdf", "sha256": "ha", "created_at": "2026-03-20T10:00:00", "modified_at": "2026-03-20T10:05:00"}
    ]
    right.document.metadata["components"] = [
        {"display_name": "B.pdf", "relative_path": "B.pdf", "sha256": "hb", "created_at": "2026-03-20T10:00:00", "modified_at": "2026-03-20T10:05:00"}
    ]
    review_facts = build_review_facts(tender, [left, right], [], [])

    assessment = assess_pairs(review_facts)[0]
    titles = {finding.title for finding in assessment.findings}

    assert "创建修改时间高度重合" in titles
    assert assessment.dimension_summary["timeline_trace"]["matched"] is True
    assert assessment.dimension_summary["timeline_trace"]["tier"] == "medium"


def test_timeline_trace_detects_platform_side_signals() -> None:
    tender = load_document_from_text("tender", "tender", "项目名称：设备采购")
    left = extract_signals(load_document_from_text("alpha", "bid", "投标总报价：100000"))
    right = extract_signals(load_document_from_text("beta", "bid", "投标总报价：120000"))
    left.document.metadata["components"] = [
        {"display_name": "A.pdf", "relative_path": "A.pdf", "sha256": "ha", "upload_at": "2026-03-20T10:08:00", "ca_user": "张三", "terminal_id": "terminal-1", "client_ip": "10.10.0.8"}
    ]
    right.document.metadata["components"] = [
        {"display_name": "B.pdf", "relative_path": "B.pdf", "sha256": "hb", "upload_at": "2026-03-20T10:08:00", "ca_user": "张三", "terminal_id": "terminal-1", "client_ip": "10.10.0.8"}
    ]
    review_facts = build_review_facts(tender, [left, right], [], [])

    assessment = assess_pairs(review_facts)[0]
    titles = {finding.title for finding in assessment.findings}

    assert "上传时间高度重合" in titles
    assert "CA使用人重合" in titles
    assert "终端/IP信息重合" in titles
    assert "平台侧电子痕迹重合" in titles
    assert assessment.dimension_summary["timeline_trace"]["matched"] is True


def test_timeline_table_and_report_include_created_modified_and_fingerprint_support() -> None:
    tender = load_document_from_text("tender", "tender", "项目名称：设备采购")
    left = extract_signals(load_document_from_text("alpha", "bid", "投标总报价：100000"))
    left.document.metadata["components"] = [
        {"display_name": "A.pdf", "relative_path": "A.pdf", "sha256": "ha", "created_at": "2026-03-20T10:00:00", "modified_at": "2026-03-20T10:05:00"}
    ]
    review_facts = build_review_facts(tender, [left], [], [])
    timeline_table = build_timeline_table(review_facts)
    profiles = _build_supplier_profiles_from_facts(review_facts, [], [], timeline_table)

    assert timeline_table[0]["created_times"] == ["2026-03-20T10:00:00"]
    assert timeline_table[0]["modified_times"] == ["2026-03-20T10:05:00"]
    assert timeline_table[0]["fingerprint_count"] >= 1

    points = _build_timeline_points(profiles)
    opinion = _build_timeline_opinion(profiles)

    assert "创建时间提取 1 条" in points[0]
    assert "修改时间提取 1 条" in points[0]
    assert "文件指纹" in points[0]
    assert "时间与电子痕迹" in opinion or "创建时间" in opinion


def test_timeline_table_and_report_include_platform_side_fields() -> None:
    tender = load_document_from_text("tender", "tender", "项目名称：设备采购")
    left = extract_signals(load_document_from_text("alpha", "bid", "投标总报价：100000"))
    left.document.metadata["components"] = [
        {"display_name": "A.pdf", "relative_path": "A.pdf", "sha256": "ha", "created_at": "2026-03-20T10:00:00", "modified_at": "2026-03-20T10:05:00", "upload_at": "2026-03-20T10:08:00", "ca_user": "张三", "terminal_id": "terminal-1", "client_ip": "10.10.0.8"}
    ]
    review_facts = build_review_facts(tender, [left], [], [])
    timeline_table = build_timeline_table(review_facts)
    profiles = _build_supplier_profiles_from_facts(review_facts, [], [], timeline_table)

    assert timeline_table[0]["uploaded_times"] == ["2026-03-20T10:08:00"]
    assert timeline_table[0]["ca_users"] == ["张三"]
    assert timeline_table[0]["terminal_ids"] == ["terminal-1"]
    assert timeline_table[0]["ip_addresses"] == ["10.10.0.8"]
    assert timeline_table[0]["platform_trace_count"] == 1
    assert "A.pdf[upload=2026-03-20T10:08:00" in timeline_table[0]["trace_examples"][0]
    assert timeline_table[0]["summary"] == "发现平台侧电子痕迹"

    points = _build_timeline_points(profiles)
    opinion = _build_timeline_opinion(profiles)

    assert "上传时间提取 1 条" in points[0]
    assert "CA使用人 1 项" in points[0]
    assert "终端/设备标识 1 项" in points[0]
    assert "IP 地址 1 项" in points[0]
    assert "平台侧痕迹 1 条" in points[0]
    assert "组件级轨迹示例" in points[0]
    assert "平台侧电子痕迹" in opinion


def test_formal_report_explains_normal_vs_abnormal_structure_homology() -> None:
    risk_rows = [
        {
            "supplier_a": "甲",
            "supplier_b": "乙",
            "total_score": 12,
            "risk_level": "low",
            "technical_text_score": 0,
            "entity_link_score": 0,
            "pricing_score": 0,
            "file_homology_score": 6,
            "authorization_score": 0,
            "timeline_score": 0,
            "dimension_summary": {
                "identity_link": {"matched": False, "score": 0, "tier": "none", "finding_titles": []},
                "pricing_link": {"matched": False, "score": 0, "tier": "none", "finding_titles": []},
                "text_similarity": {"matched": False, "score": 0, "tier": "none", "finding_titles": []},
                "file_homology": {"matched": True, "score": 6, "tier": "weak", "finding_titles": ["章节顺序相似"]},
                "authorization_chain": {"matched": False, "score": 0, "tier": "none", "finding_titles": []},
                "timeline_trace": {"matched": False, "score": 0, "tier": "none", "finding_titles": []},
            },
            "explanation": "结构支持=章节顺序相似",
        },
        {
            "supplier_a": "甲",
            "supplier_b": "丙",
            "total_score": 32,
            "risk_level": "medium",
            "technical_text_score": 0,
            "entity_link_score": 0,
            "pricing_score": 0,
            "file_homology_score": 20,
            "authorization_score": 0,
            "timeline_score": 0,
            "dimension_summary": {
                "identity_link": {"matched": False, "score": 0, "tier": "none", "finding_titles": []},
                "pricing_link": {"matched": False, "score": 0, "tier": "none", "finding_titles": []},
                "text_similarity": {"matched": False, "score": 0, "tier": "none", "finding_titles": []},
                "file_homology": {"matched": True, "score": 20, "tier": "strong", "finding_titles": ["文件指纹重合", "章节顺序高度同构", "异常同构结构"]},
                "authorization_chain": {"matched": False, "score": 0, "tier": "none", "finding_titles": []},
                "timeline_trace": {"matched": False, "score": 0, "tier": "none", "finding_titles": []},
            },
            "explanation": "结构支持=文件指纹重合；章节顺序高度同构；异常同构结构",
        },
    ]
    report = build_formal_report(
        case_manifest={
            "case_id": "case-structure-1",
            "generated_at": "2026-03-23T14:00:00",
            "input_summary": {"supplier_names": ["甲", "乙", "丙"], "tender_count": 1, "bid_count": 3},
            "source_paths": {},
        },
        document_catalog=[],
        review_conclusion_table={
            "verified_facts": [],
            "suspicious_clues": ["甲 与 丙 存在需要进一步核查的可疑线索。"],
            "exclusionary_factors": ["甲 与 乙 未发现明显异常信号。"],
            "recommendations": ["补充核查。"],
        },
        evidence_grade_table=[],
        risk_score_table=risk_rows,
        structure_similarity_table=[
            {"supplier_a": "甲", "supplier_b": "乙", "category_overlap_ratio": 0.8},
            {"supplier_a": "甲", "supplier_b": "丙", "category_overlap_ratio": 0.85},
        ],
        section_similarity_table=[],
        bid_documents=[
            {"document": {"name": "甲", "text": "甲公司"}, "phones": [], "emails": [], "bank_accounts": [], "legal_representatives": [], "addresses": []},
            {"document": {"name": "乙", "text": "乙公司"}, "phones": [], "emails": [], "bank_accounts": [], "legal_representatives": [], "addresses": []},
            {"document": {"name": "丙", "text": "丙公司"}, "phones": [], "emails": [], "bank_accounts": [], "legal_representatives": [], "addresses": []},
        ],
    )
    markdown = build_formal_report_markdown(report)

    assert "结构编排存在相似性" in markdown
    assert "需进一步复核是否存在同底稿加工或异常同构制作" in markdown


def test_formal_report_identity_section_explains_candidate_conflicts() -> None:
    tender = load_document_from_text("tender", "tender", "项目名称：设备采购")
    left = extract_signals(
        load_document_from_text(
            "alpha",
            "bid",
            "内蒙古阿尔法科技有限公司\n法定代表人：张三\n联系人：王小明\n地址：呼和浩特市新城区示例路1号\n投标报价：100000",
        )
    )
    right = extract_signals(
        load_document_from_text(
            "beta",
            "bid",
            "内蒙古贝塔科技有限公司\n法定代表人：李四\n联系人：赵六\n地址：包头市昆都仑区示例路2号\n投标报价：120000",
        )
    )
    review_facts = build_review_facts(tender, [left, right], [], [])
    review_facts.suppliers[0].contact_names.append(
        review_facts.suppliers[0].contact_names[0].__class__(
            value="王小明先生",
            source_type="ocr",
            source_document="/tmp/a.pdf",
            source_page=1,
            confidence=0.8,
            is_primary=False,
        )
    )
    review_facts.suppliers[0].addresses.append(
        review_facts.suppliers[0].addresses[0].__class__(
            value="中国呼和浩特市新城区示例路1号",
            source_type="ocr",
            source_document="/tmp/a.pdf",
            source_page=1,
            confidence=0.8,
            is_primary=False,
        )
    )
    price_table = build_risk_score_table(assess_pairs(review_facts), [], [], [], [], [])
    report = build_formal_report(
        case_manifest={
            "case_id": "case-identity-conflict",
            "generated_at": "2026-03-23T18:30:00",
            "input_summary": {"supplier_names": ["alpha", "beta"], "tender_count": 1, "bid_count": 2},
            "source_paths": {},
        },
        document_catalog=[],
        review_conclusion_table=build_review_conclusion_table(assess_pairs(review_facts)),
        evidence_grade_table=build_evidence_grade_table(assess_pairs(review_facts)),
        risk_score_table=price_table,
        review_facts=review_facts,
        authorization_chain_table=build_authorization_chain_table(review_facts),
    )
    markdown = build_formal_report_markdown(report)

    assert "主体字段存在多个候选值" in markdown
    assert "联系人另有候选值 `王小明先生`" in markdown
    assert "地址另有候选值 `中国呼和浩特市新城区示例路1号`" in markdown


def test_formal_report_identity_section_explains_source_confidence_and_role_resolution() -> None:
    tender = load_document_from_text("tender", "tender", "项目名称：设备采购")
    left = extract_signals(
        load_document_from_text(
            "alpha",
            "bid",
            "内蒙古阿尔法科技有限公司\n法定代表人：张三\n联系人：李四\n委托代理人：李四\n统一社会信用代码：91150105MA0ABCDE1X\n地址：呼和浩特市新城区示例路1号\n投标报价：100000",
        )
    )
    right = extract_signals(
        load_document_from_text(
            "beta",
            "bid",
            "内蒙古贝塔科技有限公司\n法定代表人：王五\n联系人：赵六\n地址：包头市昆都仑区示例路2号\n投标报价：120000",
        )
    )
    review_facts = build_review_facts(tender, [left, right], [], [])
    report = build_formal_report(
        case_manifest={
            "case_id": "case-identity-source-note",
            "generated_at": "2026-03-23T20:30:00",
            "input_summary": {"supplier_names": ["alpha", "beta"], "tender_count": 1, "bid_count": 2},
            "source_paths": {},
        },
        document_catalog=[],
        review_conclusion_table=build_review_conclusion_table(assess_pairs(review_facts)),
        evidence_grade_table=build_evidence_grade_table(assess_pairs(review_facts)),
        risk_score_table=build_risk_score_table(assess_pairs(review_facts), [], [], [], [], []),
        review_facts=review_facts,
        authorization_chain_table=build_authorization_chain_table(review_facts),
    )
    markdown = build_formal_report_markdown(report)

    assert "主体字段主采纳依据" in markdown
    assert "法定代表人主采纳来源为" in markdown
    assert "统一社会信用代码主采纳来源为" in markdown
    assert "联系人与授权代表识别为同一人" in markdown


def test_template_like_service_lines_do_not_trigger_text_overlap_finding() -> None:
    left = extract_signals(
        load_document_from_text(
            "alpha",
            "bid",
            "\n".join(
                [
                    "培训特点是目的性、针对性、实效性和创新性：",
                    "结合建设项目及实际状况，提供适合客户的、有针对性的培训方案。",
                    "实效性：项目自始至终，我们都通过与客户组成共同的工作小组。",
                    "备专业技术人员，为该项目提供技术培训。",
                ]
            ),
        )
    )
    right = extract_signals(
        load_document_from_text(
            "beta",
            "bid",
            "\n".join(
                [
                    "培训特点是目的性、针对性、实效性和创新性：",
                    "结合建设项目及实际状况，提供适合客户的、有针对性的培训方案。",
                    "实效性：项目自始至终，我们都通过与客户组成共同的工作小组。",
                    "备专业技术人员，为该项目提供技术培训。",
                ]
            ),
        )
    )
    assessment = assess_pairs([left, right])[0]
    assert not any(finding.title == "仅两家共享的非模板文本重合" for finding in assessment.findings)
    assert not any(finding.title == "仅两家共享的一般文本相似" for finding in assessment.findings)


def test_shared_error_like_text_is_prioritized_over_general_overlap() -> None:
    left = extract_signals(
        load_document_from_text(
            "alpha",
            "bid",
            "商务应答\n供应商A专用说明。\n联系人电话填写有误，税率字段漏填，导致应答表字段信息缺失。\n其余内容略。",
        )
    )
    right = extract_signals(
        load_document_from_text(
            "beta",
            "bid",
            "商务应答\n供应商B专用说明。\n联系人电话填写有误，税率字段漏填，导致应答表字段信息缺失。\n其余内容略。",
        )
    )

    assessment = assess_pairs([left, right])[0]
    titles = {finding.title for finding in assessment.findings}

    assert "仅两家共享的字段错填" in titles
    assert "仅两家共享的一般文本相似" not in titles
    assert assessment.dimension_summary["text_similarity"]["tier"] == "medium"


def test_shared_rare_expression_is_detected_as_text_signal() -> None:
    line = "订单状态映射采用 API-v2/JSON 双轨校验并保留 7 天回滚窗口。"
    left = extract_signals(load_document_from_text("alpha", "bid", f"技术说明\n{line}\n其余内容略。"))
    right = extract_signals(load_document_from_text("beta", "bid", f"技术说明\n{line}\n其余内容略。"))

    assessment = assess_pairs([left, right])[0]
    titles = {finding.title for finding in assessment.findings}

    assert "仅两家共享的罕见表达重合" in titles


def test_shared_numbering_error_is_detected_as_error_like_text_signal() -> None:
    line = "序号 3 页码填写有误，导致附件编号与目录页码对应关系错误。"
    left = extract_signals(load_document_from_text("alpha", "bid", f"技术应答\n供应商A备注。\n{line}\n其余内容略。"))
    right = extract_signals(load_document_from_text("beta", "bid", f"技术应答\n供应商B备注。\n{line}\n其余内容略。"))

    assessment = assess_pairs([left, right])[0]
    titles = {finding.title for finding in assessment.findings}

    assert "仅两家共享的编号错误" in titles


def test_shared_formatting_error_is_detected_as_text_signal() -> None:
    line = "项目名称：电子商城建设项目（服务期十二个月，交付要求详见附件。"
    left = extract_signals(load_document_from_text("alpha", "bid", f"技术应答\n供应商A备注。\n{line}\n其余内容略。"))
    right = extract_signals(load_document_from_text("beta", "bid", f"技术应答\n供应商B备注。\n{line}\n其余内容略。"))

    assessment = assess_pairs([left, right])[0]
    titles = {finding.title for finding in assessment.findings}

    assert "仅两家共享的排版错误" in titles


def test_shared_logic_conflict_is_detected_as_text_signal() -> None:
    line = "交付时间前后不符，与附件说明不一致，导致实施安排存在逻辑冲突。"
    left = extract_signals(load_document_from_text("alpha", "bid", f"技术应答\n供应商A备注。\n{line}\n其余内容略。"))
    right = extract_signals(load_document_from_text("beta", "bid", f"技术应答\n供应商B备注。\n{line}\n其余内容略。"))

    assessment = assess_pairs([left, right])[0]
    titles = {finding.title for finding in assessment.findings}

    assert "仅两家共享的逻辑矛盾表述" in titles


def test_shared_error_category_uses_highest_priority_match() -> None:
    line = "序号 3 填写有误，与目录不符，导致该页内容前后存在逻辑矛盾。"
    left = extract_signals(load_document_from_text("alpha", "bid", f"技术应答\n供应商A备注。\n{line}\n其余内容略。"))
    right = extract_signals(load_document_from_text("beta", "bid", f"技术应答\n供应商B备注。\n{line}\n其余内容略。"))

    assessment = assess_pairs([left, right])[0]
    titles = {finding.title for finding in assessment.findings}

    assert "仅两家共享的逻辑矛盾表述" in titles
    assert "仅两家共享的字段错填" not in titles
    assert "仅两家共享的编号错误" not in titles


def test_text_error_titles_are_rendered_consistently_in_report_and_appendix() -> None:
    tender = load_document_from_text("tender", "tender", "项目名称：设备采购")
    line = "交付时间前后不符，与附件说明不一致，导致实施安排存在逻辑冲突。"
    left = extract_signals(load_document_from_text("alpha", "bid", f"技术应答\n供应商A备注。\n{line}\n其余内容略。"))
    right = extract_signals(load_document_from_text("beta", "bid", f"技术应答\n供应商B备注。\n{line}\n其余内容略。"))

    assessments = assess_pairs([left, right])
    evidence = build_evidence_grade_table(assessments)
    risk = build_risk_score_table(assessments, [], [], [], [], [])
    review_conclusion = build_review_conclusion_table(assessments)
    report = build_formal_report(
        case_manifest={
            "case_id": "case-text-logic-1",
            "generated_at": "2026-03-23T12:20:00",
            "input_summary": {"supplier_names": ["alpha", "beta"], "tender_count": 1, "bid_count": 2},
            "source_paths": {},
        },
        document_catalog=[],
        review_conclusion_table=review_conclusion,
        evidence_grade_table=evidence,
        risk_score_table=risk,
        review_facts=build_review_facts(tender, [left, right], [], []),
    )
    markdown = build_formal_report_markdown(report)

    assert "仅两家共享的逻辑矛盾表述" in {item["finding_title"] for item in evidence}
    assert "两家投标文件存在逻辑矛盾表述" in markdown
    assert "出现相同逻辑矛盾或前后不符表述" in markdown


def test_text_error_titles_render_four_categories_in_appendix() -> None:
    mapping = {
        "仅两家共享的排版错误": "两家投标文件存在排版错误",
        "仅两家共享的编号错误": "两家投标文件存在编号错误",
        "仅两家共享的字段错填": "两家投标文件存在字段错填",
        "仅两家共享的逻辑矛盾表述": "两家投标文件存在逻辑矛盾表述",
    }
    for finding_title, appendix_title in mapping.items():
        report = build_formal_report(
            case_manifest={
                "case_id": "case-text-appendix",
                "generated_at": "2026-03-24T10:00:00",
                "input_summary": {"supplier_names": ["alpha", "beta"], "tender_count": 1, "bid_count": 2},
                "source_paths": {},
            },
            document_catalog=[],
            review_conclusion_table={
                "verified_facts": [],
                "suspicious_clues": [],
                "exclusionary_factors": [],
                "recommendations": [],
            },
            evidence_grade_table=[
                {
                    "pair": "alpha 与 beta",
                    "finding_title": finding_title,
                    "evidence_grade": "B",
                    "reason": "较强异常线索，需要结合其他证据判断。",
                    "evidence": ["重合行: 示例片段"],
                    "evidence_details": [],
                }
            ],
            risk_score_table=[],
        )
        appendix_titles = [item["finding_title"] for item in report["text_overlap_appendix"]]
        assert appendix_title in appendix_titles


def test_general_text_similarity_does_not_form_actionable_clue_by_itself() -> None:
    line = "该模块支持多角色协同处理并保留完整业务流转记录。"
    left = extract_signals(load_document_from_text("alpha", "bid", f"说明\n背景描述A。\n{line}\n其余内容略。"))
    right = extract_signals(load_document_from_text("beta", "bid", f"说明\n背景描述B。\n{line}\n补充说明。"))

    assessment = assess_pairs([left, right])[0]
    report = build_review_conclusion_table([assessment])
    titles = {finding.title for finding in assessment.findings}

    assert "仅两家共享的一般文本相似" not in titles
    assert report["suspicious_clues"] == []


def test_two_generic_solution_lines_do_not_trigger_general_text_similarity() -> None:
    lines = [
        "系统支持采购单位在线查询订单状态并进行业务流转处理。",
        "平台提供供应商商品管理、配置维护和数据展示能力。",
    ]
    left = extract_signals(load_document_from_text("alpha", "bid", "技术方案\n" + "\n".join(lines)))
    right = extract_signals(load_document_from_text("beta", "bid", "技术方案\n" + "\n".join(lines)))

    assessment = assess_pairs([left, right])[0]
    titles = {finding.title for finding in assessment.findings}

    assert "仅两家共享的一般文本相似" not in titles


def load_document_from_text(name: str, role: str, text: str):
    temp_dir = Path(tempfile.mkdtemp(prefix="agent_bid_rigging_test_"))
    path = temp_dir / f"{name}_{role}.txt"
    path.write_text(text, encoding="utf-8")
    return load_document(name, role, str(path))
