from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class OcrImageRecord:
    page_index: int | None
    image_index: int
    image_name: str
    stored_path: str
    media_type: str
    width: int | None = None
    height: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class OcrImageResult:
    image: OcrImageRecord
    doc_type: str
    summary: str
    extracted_text: str
    fields: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["image"]["stored_path"] = str(Path(self.image.stored_path))
        return data
