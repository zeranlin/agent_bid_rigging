from __future__ import annotations

from agent_bid_rigging.capabilities import CapabilityContext, CapabilityResult


def test_capability_context_to_dict() -> None:
    context = CapabilityContext(
        run_id="demo_run",
        source_path="/tmp/sample.pdf",
        metadata={"page": 1},
    )

    assert context.to_dict() == {
        "run_id": "demo_run",
        "source_path": "/tmp/sample.pdf",
        "metadata": {"page": 1},
    }


def test_capability_result_to_dict() -> None:
    result = CapabilityResult(
        capability="ocr",
        backend="qwen3.5-27b",
        status="completed",
        payload={"text": "投标总报价：1788700"},
        evidence=["page-1-image"],
        warnings=["confidence below threshold"],
    )

    assert result.to_dict() == {
        "capability": "ocr",
        "backend": "qwen3.5-27b",
        "status": "completed",
        "payload": {"text": "投标总报价：1788700"},
        "evidence": ["page-1-image"],
        "warnings": ["confidence below threshold"],
    }
