from __future__ import annotations

from agent_bid_rigging.capabilities.ocr import OCR_MODE_GENERIC, OCR_MODE_TARGETED, OcrRequest
from agent_bid_rigging.capabilities.ocr.prompts import build_ocr_user_prompt


def test_ocr_request_from_input_defaults_to_generic() -> None:
    request = OcrRequest.from_input(None)
    assert request.mode == OCR_MODE_GENERIC
    assert request.include_raw_text is True
    assert request.include_images is True


def test_ocr_request_from_input_supports_targeted_mode() -> None:
    request = OcrRequest.from_input(
        {
            "mode": "targeted",
            "doc_types": ["quotation", "business_license"],
            "fields": ["company_name", "bid_total_amount"],
            "file_hints": ["开标一览表", "报价表"],
            "max_images": "12",
        }
    )
    assert request.mode == OCR_MODE_TARGETED
    assert request.doc_types == ["quotation", "business_license"]
    assert request.fields == ["company_name", "bid_total_amount"]
    assert request.file_hints == ["开标一览表", "报价表"]
    assert request.max_images == 12


def test_targeted_prompt_includes_requested_scope() -> None:
    request = OcrRequest(
        mode=OCR_MODE_TARGETED,
        doc_types=["quotation"],
        fields=["bid_total_amount", "brand"],
    )
    prompt = build_ocr_user_prompt("sample.pdf", 2, 1, request=request)
    assert "调用模式：targeted" in prompt
    assert "quotation" in prompt
    assert "bid_total_amount" in prompt
