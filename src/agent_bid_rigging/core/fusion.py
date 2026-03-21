from __future__ import annotations

import re
from pathlib import Path

from agent_bid_rigging.capabilities import CapabilityContext
from agent_bid_rigging.capabilities.ocr import OcrCapability
from agent_bid_rigging.models import ExtractedSignals


def run_ocr_collection(
    capability: OcrCapability,
    run_name: str,
    role: str,
    supplier: str | None,
    source_path: str,
    output_dir: Path,
) -> dict:
    try:
        result = capability.run(
            CapabilityContext(
                run_id=run_name,
                source_path=source_path,
                metadata={"role": role, "supplier": supplier},
            ),
            source_path=source_path,
            output_dir=str(output_dir),
        )
    except ValueError:
        return {
            "image_index_rows": [],
            "image_ocr_rows": [],
        }

    payload = result.payload
    image_index_rows: list[dict] = []
    image_ocr_rows: list[dict] = []

    for image in payload.get("images", []):
        image_index_rows.append(
            {
                "role": role,
                "supplier": supplier,
                "source_path": image.get("source_path") or source_path,
                "page_index": image.get("page_index"),
                "image_index": image.get("image_index"),
                "image_id": f"IMG{int(image.get('image_index', 0)):03d}" if image.get("image_index") else None,
                "image_name": image.get("image_name"),
                "stored_path": image.get("stored_path"),
                "media_type": image.get("media_type"),
                "width": image.get("width"),
                "height": image.get("height"),
            }
        )

    for item in payload.get("image_results", []):
        image = item.get("image", {})
        image_ocr_rows.append(
            {
                "role": role,
                "supplier": supplier,
                "source_path": image.get("source_path") or source_path,
                "page_index": image.get("page_index"),
                "stored_path": image.get("stored_path"),
                "image_index": image.get("image_index"),
                "image_id": f"IMG{int(image.get('image_index', 0)):03d}" if image.get("image_index") else None,
                "doc_type": item.get("doc_type"),
                "summary": item.get("summary"),
                "extracted_text": item.get("extracted_text"),
                "fields": item.get("fields") or {},
                "confidence": item.get("confidence"),
            }
        )

    return {
        "image_index_rows": image_index_rows,
        "image_ocr_rows": image_ocr_rows,
    }


def merge_ocr_into_signal(signal: ExtractedSignals, ocr_rows: list[dict]) -> None:
    supplier_rows = [row for row in ocr_rows if row.get("supplier") == signal.document.name]
    if not supplier_rows:
        return

    phones = set(signal.phones)
    legal_reps = set(signal.legal_representatives)
    addresses = set(signal.addresses)
    bid_amounts = list(signal.bid_amounts)

    for row in supplier_rows:
        fields = row.get("fields") or {}
        if phone := normalize_text_field(fields.get("phone")):
            phones.add(phone)
        if legal_rep := normalize_text_field(fields.get("legal_representative")):
            legal_reps.add(legal_rep)
        if address := normalize_text_field(fields.get("address")):
            addresses.add(address)
        amount = parse_ocr_amount(fields.get("bid_total_amount"))
        if amount is not None and amount not in bid_amounts:
            bid_amounts.append(amount)

    signal.phones = sorted(phones)
    signal.legal_representatives = sorted(legal_reps)
    signal.addresses = sorted(addresses)
    signal.bid_amounts = sorted(bid_amounts)


def renumber_ocr_rows(image_index_rows: list[dict], image_ocr_rows: list[dict]) -> None:
    image_id_map: dict[tuple[str, int | None, str | None], tuple[int, str]] = {}
    for index, row in enumerate(image_index_rows, start=1):
        image_number = index
        image_id = f"IMG{image_number:03d}"
        key = (str(row.get("stored_path")), row.get("page_index"), row.get("supplier"))
        row["image_index"] = image_number
        row["image_id"] = image_id
        image_id_map[key] = (image_number, image_id)

    for row in image_ocr_rows:
        key = (str(row.get("stored_path")), row.get("page_index"), row.get("supplier"))
        if key not in image_id_map:
            continue
        image_number, image_id = image_id_map[key]
        row["image_index"] = image_number
        row["image_id"] = image_id


def append_ocr_entity_rows(entity_field_table: list[dict], ocr_rows: list[dict]) -> None:
    field_mapping = {
        "company_name": "company_name",
        "legal_representative": "legal_representatives",
        "bid_total_amount": "bid_amounts",
        "address": "addresses",
        "phone": "phones",
    }
    grouped: dict[tuple[str, str], dict] = {}
    for row in ocr_rows:
        supplier = row.get("supplier")
        if not supplier:
            continue
        for source_key, field_name in field_mapping.items():
            value = normalize_text_field((row.get("fields") or {}).get(source_key))
            if not value:
                continue
            bucket = grouped.setdefault(
                (supplier, field_name),
                {
                    "supplier": supplier,
                    "field_name": field_name,
                    "values": [],
                    "source_document": row.get("source_path"),
                    "source_page": row.get("page_index"),
                },
            )
            if value not in bucket["values"]:
                bucket["values"].append(value)
    entity_field_table.extend(grouped.values())


def append_ocr_authorization_rows(authorization_chain_table: list[dict], ocr_rows: list[dict]) -> None:
    by_supplier = {row["supplier"]: row for row in authorization_chain_table}
    for row in ocr_rows:
        supplier = row.get("supplier")
        if not supplier:
            continue
        table_row = by_supplier.get(supplier)
        if not table_row:
            continue
        fields = row.get("fields") or {}
        manufacturer = normalize_text_field(fields.get("manufacturer"))
        if manufacturer and manufacturer not in table_row["manufacturer_mentions"]:
            table_row["manufacturer_mentions"].append(manufacturer)
        if row.get("doc_type") == "authorization_letter":
            mention = compact_ocr_line(row)
            if mention and mention not in table_row["authorization_mentions"]:
                table_row["authorization_mentions"].append(mention)
        if table_row["authorization_mentions"]:
            table_row["summary"] = "发现授权/厂家关键词"


def append_ocr_license_rows(license_match_table: list[dict], ocr_rows: list[dict]) -> None:
    by_supplier = {row["supplier"]: row for row in license_match_table}
    for row in ocr_rows:
        supplier = row.get("supplier")
        if not supplier:
            continue
        table_row = by_supplier.get(supplier)
        if not table_row:
            continue
        fields = row.get("fields") or {}
        for key in ("license_number", "registration_number"):
            value = normalize_text_field(fields.get(key))
            if value and value not in table_row["registration_ids"]:
                table_row["registration_ids"].append(value)
        if row.get("doc_type") in {"license", "business_license", "registration_certificate"}:
            line = compact_ocr_line(row)
            if line and line not in table_row["license_lines"]:
                table_row["license_lines"].append(line)


def compact_ocr_line(row: dict) -> str:
    summary = normalize_text_field(row.get("summary"))
    extracted = normalize_text_field(row.get("extracted_text"))
    if summary and extracted:
        return f"{summary}：{extracted[:120]}"
    return summary or extracted or ""


def parse_ocr_amount(value: object) -> float | None:
    text = normalize_text_field(value)
    if not text:
        return None
    match = re.search(r"([1-9]\d{0,2}(?:,\d{3})+(?:\.\d+)?|[1-9]\d{3,}(?:\.\d+)?)", text)
    if not match:
        return None
    try:
        amount = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    return amount if amount >= 1000 else None


def normalize_text_field(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return str(value).strip()
