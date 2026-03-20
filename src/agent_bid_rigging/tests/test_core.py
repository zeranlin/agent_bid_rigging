from __future__ import annotations

import tempfile
from pathlib import Path

from agent_bid_rigging.core.extractor import build_tender_baseline, extract_signals
from agent_bid_rigging.core.opinion import generate_review_opinion
from agent_bid_rigging.core.scoring import assess_pairs
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


def load_document_from_text(name: str, role: str, text: str):
    temp_dir = Path(tempfile.mkdtemp(prefix="agent_bid_rigging_test_"))
    path = temp_dir / f"{name}_{role}.txt"
    path.write_text(text, encoding="utf-8")
    return load_document(name, role, str(path))
