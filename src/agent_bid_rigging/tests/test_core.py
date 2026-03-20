from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

from agent_bid_rigging.core.extractor import build_tender_baseline, extract_signals
from agent_bid_rigging.core.opinion import generate_review_opinion
from agent_bid_rigging.core.scoring import assess_pairs
from agent_bid_rigging.core.artifacts import build_duplicate_detection_table, classify_document
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


def load_document_from_text(name: str, role: str, text: str):
    temp_dir = Path(tempfile.mkdtemp(prefix="agent_bid_rigging_test_"))
    path = temp_dir / f"{name}_{role}.txt"
    path.write_text(text, encoding="utf-8")
    return load_document(name, role, str(path))
