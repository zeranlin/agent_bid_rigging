from __future__ import annotations

from agent_bid_rigging.core.extractor import extract_signals
from agent_bid_rigging.core.scoring import assess_pairs
from agent_bid_rigging.core.strategy import build_review_strategy
from agent_bid_rigging.tests.test_core import load_document_from_text


def test_build_review_strategy_enables_targeted_ocr_tasks() -> None:
    alpha = extract_signals(load_document_from_text("alpha", "bid", "投标总报价：100000"))
    beta = extract_signals(load_document_from_text("beta", "bid", "联系人电话：13800000000"))
    strategy = build_review_strategy(
        opinion_mode="template",
        enable_ocr=True,
        suppliers=["alpha", "beta"],
        bid_signals=[alpha, beta],
        preliminary_assessments=assess_pairs([alpha, beta]),
        openai_configured=False,
        async_llm=False,
    )

    assert strategy.enable_ocr is True
    assert strategy.tender_ocr.enabled is True
    assert strategy.tender_ocr.request is not None
    assert strategy.tender_ocr.request.max_sources == 3
    assert strategy.tender_ocr.request.max_images == 12
    assert strategy.bid_ocr["alpha"].request is not None
    assert "business_license" in strategy.bid_ocr["alpha"].request.doc_types
    assert strategy.bid_ocr["alpha"].request.max_sources == 4
    assert strategy.bid_ocr["alpha"].request.max_images == 20
    assert strategy.bid_ocr["alpha"].reasons
    assert strategy.llm is not None
    assert strategy.llm.enabled is False


def test_build_review_strategy_controls_llm_sync_and_async() -> None:
    sync_strategy = build_review_strategy(
        opinion_mode="llm",
        enable_ocr=False,
        suppliers=["alpha"],
        openai_configured=True,
        async_llm=False,
    )
    async_strategy = build_review_strategy(
        opinion_mode="llm",
        enable_ocr=False,
        suppliers=["alpha"],
        openai_configured=True,
        async_llm=True,
    )

    assert sync_strategy.llm is not None
    assert sync_strategy.llm.enabled is True
    assert sync_strategy.llm.wait_for_completion is True
    assert sync_strategy.llm.async_enabled is False

    assert async_strategy.llm is not None
    assert async_strategy.llm.async_enabled is True
    assert async_strategy.llm.wait_for_completion is False


def test_build_review_strategy_triggers_ocr_for_missing_fields_and_medium_risk() -> None:
    alpha = extract_signals(
        load_document_from_text("alpha", "bid", "联系人电话：13800000000\n投标总报价：100000\n自定义说明：错别字壹号")
    )
    beta = extract_signals(
        load_document_from_text("beta", "bid", "联系人电话：13800000000\n投标总报价：100000\n自定义说明：错别字壹号")
    )
    gamma = extract_signals(load_document_from_text("gamma", "bid", "投标总报价：150000\n法定代表人：张三"))
    strategy = build_review_strategy(
        opinion_mode="template",
        enable_ocr=True,
        suppliers=["alpha", "beta", "gamma"],
        bid_signals=[alpha, beta, gamma],
        preliminary_assessments=assess_pairs([alpha, beta, gamma]),
        openai_configured=False,
        async_llm=False,
    )

    assert "案件初筛已达到 medium 及以上风险" in strategy.bid_ocr["alpha"].reasons
    assert any("法定代表人" in reason for reason in strategy.bid_ocr["alpha"].reasons)
    assert any("许可证号" in reason for reason in strategy.bid_ocr["gamma"].reasons)
