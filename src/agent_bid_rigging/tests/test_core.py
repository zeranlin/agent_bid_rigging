from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

from agent_bid_rigging.core.extractor import build_tender_baseline, extract_signals
from agent_bid_rigging.core.opinion import generate_review_opinion
from agent_bid_rigging.core.scoring import assess_pairs
from agent_bid_rigging.core.artifacts import (
    build_duplicate_detection_table,
    build_evidence_grade_table,
    build_formal_report,
    build_formal_report_markdown,
    build_risk_score_table,
    classify_document,
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
        "pairwise_assessments": [
            {
                "supplier_a": "alpha",
                "supplier_b": "beta",
                "risk_score": 90,
                "risk_level": "critical",
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
    assert "`alpha` 与 `beta`" in opinion["document"]


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


def load_document_from_text(name: str, role: str, text: str):
    temp_dir = Path(tempfile.mkdtemp(prefix="agent_bid_rigging_test_"))
    path = temp_dir / f"{name}_{role}.txt"
    path.write_text(text, encoding="utf-8")
    return load_document(name, role, str(path))
