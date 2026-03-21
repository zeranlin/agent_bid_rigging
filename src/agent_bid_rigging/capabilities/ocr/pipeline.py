from __future__ import annotations

import json
from pathlib import Path

from agent_bid_rigging.capabilities.base import CapabilityContext, CapabilityResult, ReviewCapability
from agent_bid_rigging.capabilities.ocr.pdf_images import build_image_record, extract_pdf_images
from agent_bid_rigging.capabilities.ocr.qwen_backend import QwenOcrBackend
from agent_bid_rigging.capabilities.ocr.schemas import OcrImageResult


class OcrCapability(ReviewCapability):
    name = "ocr"

    def __init__(self, backend: QwenOcrBackend | None = None) -> None:
        self.backend = backend or QwenOcrBackend()

    def run(self, context: CapabilityContext, **kwargs: object) -> CapabilityResult:
        source_path = kwargs.get("source_path") or context.source_path
        if not source_path:
            raise ValueError("source_path is required for OCR capability")

        source = Path(str(source_path)).expanduser().resolve()
        output_dir = Path(str(kwargs.get("output_dir") or source.parent / f"{source.stem}_ocr")).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        if source.suffix.lower() == ".pdf":
            images = extract_pdf_images(source, output_dir / "images")
        elif source.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            images = [build_image_record(source)]
        else:
            raise ValueError(f"Unsupported OCR source format: {source.suffix}")

        warnings: list[str] = []
        if not images:
            warnings.append("No embedded images were extracted from the source document.")

        image_results: list[OcrImageResult] = []
        for image in images:
            image_results.append(self.backend.analyze_image(image, context))

        payload = {
            "source_path": str(source),
            "output_dir": str(output_dir),
            "image_count": len(images),
            "images": [image.to_dict() for image in images],
            "image_results": [result.to_dict() for result in image_results],
        }
        image_index = {"rows": _build_image_index_rows(source, images)}
        image_ocr_table = {"rows": _build_image_ocr_rows(source, image_results)}
        (output_dir / "image_index.json").write_text(json.dumps(image_index, ensure_ascii=False, indent=2), encoding="utf-8")
        (output_dir / "image_ocr_table.json").write_text(
            json.dumps(image_ocr_table, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (output_dir / "ocr_result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (output_dir / "ocr_result.md").write_text(_build_markdown(payload), encoding="utf-8")
        return CapabilityResult(
            capability=self.name,
            backend=self.backend.client.model,
            status="completed",
            payload=payload,
            evidence=[result.image.stored_path for result in image_results],
            warnings=warnings,
        )


def _build_markdown(payload: dict) -> str:
    lines = [
        "# OCR Capability Result",
        "",
        f"- Source: {payload['source_path']}",
        f"- Extracted images: {payload['image_count']}",
        "",
    ]
    for item in payload["image_results"]:
        image = item["image"]
        lines.append(f"## Image {image['image_index']}")
        lines.append("")
        lines.append(f"- Page: {image['page_index'] or 'N/A'}")
        lines.append(f"- Stored path: {image['stored_path']}")
        lines.append(f"- Doc type: {item['doc_type']}")
        lines.append(f"- Confidence: {item['confidence']}")
        lines.append(f"- Summary: {item['summary']}")
        if item["extracted_text"]:
            lines.append(f"- Extracted text: {item['extracted_text']}")
        if item["fields"]:
            lines.append(f"- Fields: {json.dumps(item['fields'], ensure_ascii=False)}")
        lines.append("")
    return "\n".join(lines)


def _build_image_index_rows(source: Path, images: list) -> list[dict]:
    rows: list[dict] = []
    for image in images:
        rows.append(
            {
                "image_id": f"IMG{image.image_index:03d}",
                "source_path": str(source),
                "page_index": image.page_index,
                "image_index": image.image_index,
                "image_name": image.image_name,
                "stored_path": image.stored_path,
                "media_type": image.media_type,
                "width": image.width,
                "height": image.height,
            }
        )
    return rows


def _build_image_ocr_rows(source: Path, image_results: list[OcrImageResult]) -> list[dict]:
    rows: list[dict] = []
    for result in image_results:
        rows.append(
            {
                "image_id": f"IMG{result.image.image_index:03d}",
                "source_path": str(source),
                "page_index": result.image.page_index,
                "stored_path": result.image.stored_path,
                "doc_type": result.doc_type,
                "summary": result.summary,
                "extracted_text": result.extracted_text,
                "fields": result.fields,
                "confidence": result.confidence,
            }
        )
    return rows
