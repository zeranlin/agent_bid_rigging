from __future__ import annotations

from agent_bid_rigging.core.strategy import build_review_strategy


def test_build_review_strategy_enables_targeted_ocr_tasks() -> None:
    strategy = build_review_strategy(
        opinion_mode="template",
        enable_ocr=True,
        suppliers=["alpha", "beta"],
        openai_configured=False,
        async_llm=False,
    )

    assert strategy.enable_ocr is True
    assert strategy.tender_ocr.enabled is True
    assert strategy.tender_ocr.request is not None
    assert strategy.bid_ocr["alpha"].request is not None
    assert "business_license" in strategy.bid_ocr["alpha"].request.doc_types
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
