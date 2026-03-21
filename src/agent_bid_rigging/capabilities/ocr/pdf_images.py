from __future__ import annotations

import mimetypes
from pathlib import Path

from pypdf import PdfReader

from agent_bid_rigging.capabilities.ocr.schemas import OcrImageRecord


def extract_pdf_images(pdf_path: str | Path, output_dir: str | Path) -> list[OcrImageRecord]:
    source = Path(pdf_path).expanduser().resolve()
    target_dir = Path(output_dir).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    reader = PdfReader(str(source))
    records: list[OcrImageRecord] = []
    image_counter = 0
    for page_index, page in enumerate(reader.pages, start=1):
        for local_index, image in enumerate(page.images, start=1):
            image_counter += 1
            image_name = _safe_image_name(image.name or f"page_{page_index}_image_{local_index}.bin")
            suffix = Path(image_name).suffix or ".bin"
            indirect = getattr(image, "indirect_reference", {}) or {}
            stored_name = f"page_{page_index:03d}_img_{local_index:02d}{suffix}"
            stored_path = target_dir / stored_name
            stored_path.write_bytes(image.data)
            records.append(
                OcrImageRecord(
                    source_path=str(source),
                    page_index=page_index,
                    image_index=image_counter,
                    image_name=image_name,
                    stored_path=str(stored_path),
                    media_type=_media_type_from_suffix(suffix),
                    width=indirect.get("/Width"),
                    height=indirect.get("/Height"),
                )
            )
    return records


def build_image_record(image_path: str | Path, image_index: int = 1) -> OcrImageRecord:
    source = Path(image_path).expanduser().resolve()
    mime_type, _ = mimetypes.guess_type(source.name)
    return OcrImageRecord(
        source_path=str(source),
        page_index=None,
        image_index=image_index,
        image_name=source.name,
        stored_path=str(source),
        media_type=mime_type or "image/png",
    )


def _safe_image_name(name: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in name)


def _suffix_from_media_type(media_type: str | None) -> str:
    if media_type == "image/jpeg":
        return ".jpg"
    if media_type == "image/png":
        return ".png"
    if media_type == "image/webp":
        return ".webp"
    return ".bin"


def _media_type_from_suffix(suffix: str) -> str:
    mapping = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".jp2": "image/jp2",
    }
    return mapping.get(suffix.lower(), "application/octet-stream")
