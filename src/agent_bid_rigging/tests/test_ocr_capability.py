from __future__ import annotations

import json
from pathlib import Path

from agent_bid_rigging.capabilities import CapabilityContext
from agent_bid_rigging.capabilities.ocr.pipeline import OcrCapability
from agent_bid_rigging.capabilities.ocr.qwen_backend import QwenOcrBackend
from agent_bid_rigging.capabilities.ocr.schemas import OcrImageResult


class StubBackend(QwenOcrBackend):
    def __init__(self) -> None:
        class StubClient:
            model = "stub-qwen"

        self.client = StubClient()

    def analyze_image(self, image, context, request=None):  # noqa: ANN001, D401
        return OcrImageResult(
            image=image,
            doc_type="license",
            summary="医疗器械相关证照图片",
            extracted_text="注册证编号 ABC123",
            fields={"registration_number": "ABC123"},
            confidence=0.91,
            raw_response={"stub": True},
        )


def test_ocr_capability_extracts_pdf_images_and_writes_outputs(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[4]
    source_pdf = (
        root
        / "test_target"
        / "wcb"
        / "鄂-电子胃肠镜等设备采购项目 - 副本"
        / "投标文件"
        / "采购包1"
        / "华康君安（北京）科技有限公司(包1)"
        / "投标人（供应商）应提交的相关证明.pdf"
    )
    output_dir = tmp_path / "ocr_run"
    capability = OcrCapability(backend=StubBackend())

    result = capability.run(
        CapabilityContext(run_id="ocr_demo", source_path=str(source_pdf)),
        source_path=str(source_pdf),
        output_dir=str(output_dir),
    )

    payload = result.to_dict()["payload"]
    assert payload["image_count"] >= 1
    assert payload["image_results"][0]["doc_type"] == "license"
    assert (output_dir / "image_index.json").exists()
    assert (output_dir / "image_ocr_table.json").exists()
    assert (output_dir / "ocr_result.json").exists()
    assert (output_dir / "ocr_result.md").exists()
    stored = Path(payload["images"][0]["stored_path"])
    assert stored.exists()
    written = json.loads((output_dir / "ocr_result.json").read_text(encoding="utf-8"))
    image_index = json.loads((output_dir / "image_index.json").read_text(encoding="utf-8"))
    image_ocr_table = json.loads((output_dir / "image_ocr_table.json").read_text(encoding="utf-8"))
    assert image_index["rows"][0]["image_id"] == "IMG001"
    assert image_ocr_table["rows"][0]["doc_type"] == "license"
    assert written["image_results"][0]["fields"]["registration_number"] == "ABC123"
