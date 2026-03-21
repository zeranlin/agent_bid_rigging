from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from agent_bid_rigging.capabilities.ocr.schemas import OcrImageRecord, OcrImageResult


OCR_MODE_GENERIC = "generic"
OCR_MODE_TARGETED = "targeted"
OCR_MODES = {OCR_MODE_GENERIC, OCR_MODE_TARGETED}


@dataclass(slots=True)
class OcrRequest:
    mode: str = OCR_MODE_GENERIC
    doc_types: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    page_hints: list[int] = field(default_factory=list)
    file_hints: list[str] = field(default_factory=list)
    max_sources: int | None = None
    max_images: int | None = None
    confidence_threshold: float | None = None
    include_raw_text: bool = True
    include_images: bool = True
    include_debug_payload: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_input(cls, request: "OcrRequest | dict[str, Any] | None") -> "OcrRequest":
        if request is None:
            return cls()
        if isinstance(request, cls):
            return request
        payload = dict(request)
        mode = str(payload.get("mode", OCR_MODE_GENERIC)).strip().lower() or OCR_MODE_GENERIC
        if mode not in OCR_MODES:
            raise ValueError(f"Unsupported OCR mode: {mode}")
        return cls(
            mode=mode,
            doc_types=_normalize_str_list(payload.get("doc_types")),
            fields=_normalize_str_list(payload.get("fields")),
            page_hints=_normalize_int_list(payload.get("page_hints")),
            file_hints=_normalize_str_list(payload.get("file_hints")),
            max_sources=_normalize_int(payload.get("max_sources")),
            max_images=_normalize_int(payload.get("max_images")),
            confidence_threshold=_normalize_float(payload.get("confidence_threshold")),
            include_raw_text=_normalize_bool(payload.get("include_raw_text"), default=True),
            include_images=_normalize_bool(payload.get("include_images"), default=True),
            include_debug_payload=_normalize_bool(payload.get("include_debug_payload"), default=False),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(slots=True)
class OcrResponse:
    request: OcrRequest
    source_path: str
    output_dir: str
    source_count: int
    image_count: int
    images: list[OcrImageRecord] = field(default_factory=list)
    image_results: list[OcrImageResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "source_path": self.source_path,
            "output_dir": self.output_dir,
            "source_count": self.source_count,
            "image_count": self.image_count,
            "images": [item.to_dict() for item in self.images],
            "image_results": [item.to_dict() for item in self.image_results],
            "warnings": self.warnings,
        }


def _normalize_str_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(item).strip() for item in value if str(item).strip()]


def _normalize_int_list(value: Any) -> list[int]:
    if value is None or value == "":
        return []
    items = [value] if isinstance(value, int) else value
    normalized: list[int] = []
    for item in items:
        try:
            normalized.append(int(item))
        except (TypeError, ValueError):
            continue
    return normalized


def _normalize_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_bool(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
