from __future__ import annotations

import json
import re
from pathlib import Path

from agent_bid_rigging.capabilities.base import CapabilityContext
from agent_bid_rigging.capabilities.ocr.contracts import OcrRequest
from agent_bid_rigging.capabilities.ocr.prompts import OCR_SYSTEM_PROMPT, build_ocr_user_prompt
from agent_bid_rigging.capabilities.ocr.schemas import OcrImageRecord, OcrImageResult
from agent_bid_rigging.utils.openai_client import OpenAIResponsesClient


class QwenOcrBackend:
    def __init__(self, client: OpenAIResponsesClient | None = None) -> None:
        self.client = client or OpenAIResponsesClient.from_env()

    def analyze_image(
        self,
        image: OcrImageRecord,
        context: CapabilityContext,
        request: OcrRequest | None = None,
    ) -> OcrImageResult:
        user_prompt = build_ocr_user_prompt(
            source_label=context.source_path or image.stored_path,
            page_index=image.page_index,
            image_index=image.image_index,
            request=request,
        )
        response_text = self.client.generate_chat_vision_text(
            system_prompt=OCR_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            image_path=image.stored_path,
        )
        parsed = _parse_json_response(response_text)
        return OcrImageResult(
            image=image,
            doc_type=str(parsed.get("doc_type", "unknown")),
            summary=str(parsed.get("summary", "")),
            extracted_text=str(parsed.get("extracted_text", "")),
            fields=parsed.get("fields", {}) or {},
            confidence=_coerce_confidence(parsed.get("confidence")),
            raw_response=parsed,
        )


def _parse_json_response(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return {
            "doc_type": _infer_doc_type(text),
            "summary": _summary_from_text(text),
            "extracted_text": text,
            "fields": {},
            "confidence": None,
        }


def _coerce_confidence(value: object) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _infer_doc_type(text: str) -> str:
    lowered = text.lower()
    mapping = [
        ("营业执照", "business_license"),
        ("授权书", "authorization_letter"),
        ("注册证", "registration_certificate"),
        ("许可证", "license"),
        ("身份证", "identity_document"),
        ("报价", "quotation"),
        ("法定代表人", "legal_representative_document"),
    ]
    for keyword, doc_type in mapping:
        if keyword.lower() in lowered:
            return doc_type
    return "unknown"


def _summary_from_text(text: str) -> str:
    for line in reversed([item.strip() for item in text.splitlines() if item.strip()]):
        if len(line) <= 120:
            return line
    return text[:120]
