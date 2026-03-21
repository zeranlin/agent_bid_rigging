from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path

from agent_bid_rigging.capabilities.base import CapabilityContext, CapabilityResult, ReviewCapability
from agent_bid_rigging.capabilities.ocr.contracts import OcrRequest, OcrResponse
from agent_bid_rigging.capabilities.ocr.pdf_images import build_image_record, extract_pdf_images
from agent_bid_rigging.capabilities.ocr.qwen_backend import QwenOcrBackend
from agent_bid_rigging.capabilities.ocr.schemas import OcrImageResult

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".jp2"}
OCR_DISCOVERY_SUFFIXES = IMAGE_SUFFIXES | {".pdf"}


class OcrCapability(ReviewCapability):
    name = "ocr"

    def __init__(self, backend: QwenOcrBackend | None = None) -> None:
        self.backend = backend or QwenOcrBackend()

    def run(self, context: CapabilityContext, **kwargs: object) -> CapabilityResult:
        source_path = kwargs.get("source_path") or context.source_path
        if not source_path:
            raise ValueError("source_path is required for OCR capability")
        request = OcrRequest.from_input(kwargs.get("request"))

        source = Path(str(source_path)).expanduser().resolve()
        output_dir = Path(str(kwargs.get("output_dir") or source.parent / f"{source.stem}_ocr")).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        warnings: list[str] = []
        sources = _discover_sources(source, request=request)
        images = []
        global_index = 0
        for source_item in sources:
            source_images = _extract_source_images(source_item, output_dir / "images")
            for image in source_images:
                global_index += 1
                image.image_index = global_index
            images.extend(source_images)
            if request.max_images is not None and len(images) >= request.max_images:
                images = images[: request.max_images]
                warnings.append("OCR image collection reached max_images limit.")
                break
        if not images:
            warnings.append("No embedded images were extracted from the source document.")

        image_results: list[OcrImageResult] = []
        for image in images:
            try:
                image_results.append(self.backend.analyze_image(image, context, request=request))
            except TypeError:
                image_results.append(self.backend.analyze_image(image, context))

        response = OcrResponse(
            request=request,
            source_path=str(source),
            output_dir=str(output_dir),
            source_count=len(sources),
            image_count=len(images),
            images=images if request.include_images else [],
            image_results=image_results,
            warnings=warnings,
        )
        payload = response.to_dict()
        payload["sources"] = [str(item) for item in sources]
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
                "source_path": image.source_path or str(source),
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
                "source_path": result.image.source_path or str(source),
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


def _discover_sources(source: Path, request: OcrRequest) -> list[Path]:
    if source.is_dir():
        sources = [
            path
            for path in sorted(source.rglob("*"))
            if path.is_file() and _should_ingest_source(path, request=request)
        ]
        if request.max_sources is not None:
            return sources[: request.max_sources]
        return sources
    if source.suffix.lower() == ".zip":
        temp_dir = Path(tempfile.mkdtemp(prefix="agent_bid_rigging_ocr_"))
        with zipfile.ZipFile(source) as archive:
            archive.extractall(temp_dir)
        return _discover_sources(temp_dir, request=request)
    if _should_ingest_source(source, request=request):
        return [source]
    raise ValueError(f"Unsupported OCR source format: {source.suffix}")


def _extract_source_images(source: Path, target_dir: Path) -> list:
    suffix = source.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_images(source, target_dir)
    if suffix in IMAGE_SUFFIXES:
        return [build_image_record(source)]
    return []


def _should_ingest_source(path: Path, request: OcrRequest) -> bool:
    if path.name.startswith("._"):
        return False
    if "__MACOSX" in path.parts:
        return False
    if request.file_hints and not any(hint in str(path) for hint in request.file_hints):
        return False
    return path.suffix.lower() in OCR_DISCOVERY_SUFFIXES
