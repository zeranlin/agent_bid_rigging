from __future__ import annotations

import re
from pathlib import Path

from agent_bid_rigging.capabilities import CapabilityContext
from agent_bid_rigging.capabilities.ocr import OcrCapability, OcrRequest
from agent_bid_rigging.models import (
    ExtractedSignals,
    FactObservation,
    LoadedDocument,
    ReviewFacts,
    SupplierFacts,
)


def run_ocr_collection(
    capability: OcrCapability,
    run_name: str,
    role: str,
    supplier: str | None,
    source_path: str,
    output_dir: Path,
    request: OcrRequest | None = None,
) -> dict:
    request = request or build_review_ocr_request(role=role, supplier=supplier)
    try:
        result = capability.run(
            CapabilityContext(
                run_id=run_name,
                source_path=source_path,
                metadata={"role": role, "supplier": supplier},
            ),
            source_path=source_path,
            output_dir=str(output_dir),
            request=request,
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
                "request_mode": payload.get("request", {}).get("mode"),
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
                "request_mode": payload.get("request", {}).get("mode"),
            }
        )

    return {
        "image_index_rows": image_index_rows,
        "image_ocr_rows": image_ocr_rows,
    }


def build_review_facts(
    tender_document: LoadedDocument,
    bid_signals: list[ExtractedSignals],
    image_index_rows: list[dict],
    image_ocr_rows: list[dict],
) -> ReviewFacts:
    return ReviewFacts(
        tender_document=tender_document,
        suppliers=[_build_supplier_facts(signal, image_ocr_rows) for signal in bid_signals],
        image_index_rows=[dict(row) for row in image_index_rows],
        image_ocr_rows=[dict(row) for row in image_ocr_rows],
    )


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


def _build_supplier_facts(signal: ExtractedSignals, image_ocr_rows: list[dict]) -> SupplierFacts:
    supplier_rows = [row for row in image_ocr_rows if row.get("supplier") == signal.document.name]
    company_name_candidates = _build_company_name_observations(signal)
    facts = SupplierFacts(
        supplier=signal.document.name,
        document=signal.document,
        text_hash=signal.text_hash,
        line_count=signal.line_count,
        token_count=signal.token_count,
        non_tender_lines=list(signal.non_tender_lines),
        rare_line_fingerprints=dict(signal.rare_line_fingerprints),
        candidate_overlap_lines=list(signal.candidate_overlap_lines),
        candidate_overlap_refs={key: [dict(row) for row in value] for key, value in signal.candidate_overlap_refs.items()},
        company_names=company_name_candidates,
        phones=_build_text_observations(signal.phones, signal.document.path),
        emails=_build_text_observations(signal.emails, signal.document.path),
        bank_accounts=_build_text_observations(signal.bank_accounts, signal.document.path),
        legal_representatives=_build_text_observations(signal.legal_representatives, signal.document.path),
        addresses=_build_text_observations(signal.addresses, signal.document.path),
        bid_amounts=_build_amount_observations(signal.bid_amounts, signal.document.path),
        timeline_modified_times=_extract_modified_times(signal.document.metadata.get("components", [])),
    )

    for row in supplier_rows:
        fields = row.get("fields") or {}
        source_document = row.get("source_path") or signal.document.path
        source_page = row.get("page_index")
        confidence = row.get("confidence")

        _append_observation(
            facts.company_names,
            normalize_text_field(fields.get("company_name")),
            source_document,
            source_page,
            confidence,
            prefer_primary=not facts.company_names,
        )
        _append_observation(
            facts.phones,
            normalize_text_field(fields.get("phone")),
            source_document,
            source_page,
            confidence,
            prefer_primary=not facts.phones,
        )
        _append_observation(
            facts.legal_representatives,
            normalize_text_field(fields.get("legal_representative")),
            source_document,
            source_page,
            confidence,
            prefer_primary=not facts.legal_representatives,
        )
        _append_observation(
            facts.addresses,
            normalize_text_field(fields.get("address")),
            source_document,
            source_page,
            confidence,
            prefer_primary=not facts.addresses,
        )
        _append_observation(
            facts.manufacturers,
            normalize_text_field(fields.get("manufacturer")),
            source_document,
            source_page,
            confidence,
            prefer_primary=not facts.manufacturers,
        )
        _append_observation(
            facts.brands,
            normalize_text_field(fields.get("brand")),
            source_document,
            source_page,
            confidence,
            prefer_primary=not facts.brands,
        )
        _append_observation(
            facts.models,
            normalize_text_field(fields.get("model")),
            source_document,
            source_page,
            confidence,
            prefer_primary=not facts.models,
        )
        _append_observation(
            facts.license_numbers,
            normalize_text_field(fields.get("license_number")),
            source_document,
            source_page,
            confidence,
            prefer_primary=not facts.license_numbers,
        )
        _append_observation(
            facts.registration_numbers,
            normalize_text_field(fields.get("registration_number")),
            source_document,
            source_page,
            confidence,
            prefer_primary=not facts.registration_numbers,
        )

        amount = parse_ocr_amount(fields.get("bid_total_amount"))
        if amount is not None:
            _append_observation(
                facts.bid_amounts,
                f"{amount:.2f}",
                source_document,
                source_page,
                confidence,
                prefer_primary=not facts.bid_amounts,
            )

        mention = compact_ocr_line(row)
        if row.get("doc_type") == "authorization_letter":
            _append_observation(
                facts.authorization_mentions,
                mention,
                source_document,
                source_page,
                confidence,
                prefer_primary=not facts.authorization_mentions,
            )
        elif mention and row.get("doc_type") in {"license", "business_license", "registration_certificate"}:
            _append_observation(
                facts.authorization_mentions,
                mention,
                source_document,
                source_page,
                confidence,
                prefer_primary=False,
            )

    return facts


def _build_text_observations(values: list[str], source_document: str) -> list[FactObservation]:
    observations: list[FactObservation] = []
    for index, value in enumerate(values):
        normalized = normalize_text_field(value)
        if not normalized:
            continue
        observations.append(
            FactObservation(
                value=normalized,
                source_type="text",
                source_document=source_document,
                is_primary=index == 0,
            )
        )
    return observations


def _build_company_name_observations(signal: ExtractedSignals) -> list[FactObservation]:
    observations: list[FactObservation] = []
    extracted = _extract_company_name_from_text(signal.document.text)
    if extracted:
        observations.append(
            FactObservation(
                value=extracted,
                source_type="text",
                source_document=signal.document.path,
                is_primary=True,
            )
        )
    if not any(item.value == signal.document.name for item in observations):
        observations.append(
            FactObservation(
                value=signal.document.name,
                source_type="text",
                source_document=signal.document.path,
                is_primary=not observations,
            )
        )
    return observations


def _build_amount_observations(values: list[float], source_document: str) -> list[FactObservation]:
    unique_values = sorted(set(values))
    observations: list[FactObservation] = []
    for index, value in enumerate(unique_values):
        observations.append(
            FactObservation(
                value=f"{value:.2f}",
                source_type="text",
                source_document=source_document,
                is_primary=index == len(unique_values) - 1,
            )
        )
    return observations


def _append_observation(
    bucket: list[FactObservation],
    value: str,
    source_document: str,
    source_page: int | None,
    confidence: float | None,
    *,
    prefer_primary: bool,
) -> None:
    if not value:
        return
    if any(item.value == value for item in bucket):
        return
    bucket.append(
        FactObservation(
            value=value,
            source_type="ocr",
            source_document=source_document,
            source_page=source_page,
            confidence=confidence,
            is_primary=prefer_primary,
        )
    )


def _extract_modified_times(components: list[dict]) -> list[str]:
    return [
        component["modified_at"]
        for component in components
        if component.get("modified_at")
    ]


def _extract_company_name_from_text(text: str) -> str | None:
    pattern = re.compile(r"([A-Za-z（）()·\u4e00-\u9fff]{4,}(?:有限责任公司|股份有限公司|有限公司|公司))")
    matches = pattern.findall(text)
    if not matches:
        return None
    return matches[0].strip()
