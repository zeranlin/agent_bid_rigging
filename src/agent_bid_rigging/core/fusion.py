from __future__ import annotations

import re
from pathlib import Path

from agent_bid_rigging.capabilities import CapabilityContext
from agent_bid_rigging.capabilities.ocr import OcrCapability, OcrRequest
from agent_bid_rigging.capabilities.pdf_sectioning import PdfSectioningCapability
from agent_bid_rigging.capabilities.pdf_tables import PdfTablesCapability
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
    section_catalog_rows: list[dict] | None = None,
    table_extract_rows: list[dict] | None = None,
) -> ReviewFacts:
    section_catalog_rows = section_catalog_rows or []
    table_extract_rows = table_extract_rows or []
    return ReviewFacts(
        tender_document=tender_document,
        suppliers=[_build_supplier_facts(signal, image_ocr_rows, section_catalog_rows, table_extract_rows) for signal in bid_signals],
        image_index_rows=[dict(row) for row in image_index_rows],
        image_ocr_rows=[dict(row) for row in image_ocr_rows],
        section_catalog_rows=[dict(row) for row in section_catalog_rows],
        table_extract_rows=[dict(row) for row in table_extract_rows],
    )


def run_pdf_section_collection(
    capability: PdfSectioningCapability,
    run_name: str,
    role: str,
    supplier: str | None,
    source_path: str,
    output_dir: Path,
) -> dict:
    result = capability.run(
        CapabilityContext(
            run_id=run_name,
            source_path=source_path,
            metadata={"role": role, "supplier": supplier},
        ),
        source_path=source_path,
        output_dir=str(output_dir),
        include_text=True,
    )
    payload = result.payload
    rows = []
    for section in payload.get("sections", []):
        rows.append(
            {
                "role": role,
                "supplier": supplier,
                "source_path": source_path,
                **section,
            }
        )
    return {"section_catalog_rows": rows, "payload": payload}


def run_pdf_table_collection(
    capability: PdfTablesCapability,
    run_name: str,
    role: str,
    supplier: str | None,
    source_path: str,
    output_dir: Path,
    section_payload: dict,
) -> dict:
    result = capability.run(
        CapabilityContext(
            run_id=run_name,
            source_path=source_path,
            metadata={"role": role, "supplier": supplier},
        ),
        source_path=source_path,
        output_dir=str(output_dir),
        section_payload=section_payload,
    )
    payload = result.payload
    rows = []
    for row in payload.get("rows", []):
        rows.append(
            {
                "role": role,
                "supplier": supplier,
                "source_path": source_path,
                **row,
            }
        )
    return {"table_extract_rows": rows, "payload": payload}


def merge_ocr_into_signal(signal: ExtractedSignals, ocr_rows: list[dict]) -> None:
    supplier_rows = [row for row in ocr_rows if row.get("supplier") == signal.document.name]
    if not supplier_rows:
        return

    phones = set(signal.phones)
    contact_names = set(signal.contact_names)
    legal_reps = set(signal.legal_representatives)
    addresses = set(signal.addresses)
    bid_amounts = list(signal.bid_amounts)

    for row in supplier_rows:
        fields = row.get("fields") or {}
        if phone := normalize_text_field(fields.get("phone")):
            phones.add(phone)
        if contact_name := normalize_text_field(fields.get("contact_name") or fields.get("contact_person")):
            contact_names.add(contact_name)
        if legal_rep := normalize_text_field(fields.get("legal_representative")):
            legal_reps.add(legal_rep)
        if address := normalize_text_field(fields.get("address")):
            addresses.add(address)
        amount = parse_ocr_amount(fields.get("bid_total_amount"))
        if amount is not None and amount not in bid_amounts:
            bid_amounts.append(amount)

    signal.phones = sorted(phones)
    signal.contact_names = sorted(contact_names)
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
        "authorized_representative": "authorized_representatives",
        "unified_social_credit_code": "unified_social_credit_codes",
        "social_credit_code": "unified_social_credit_codes",
        "authorized_manufacturer": "authorized_manufacturers",
        "authorization_issuer": "authorization_issuers",
        "authorization_date": "authorization_dates",
        "authorization_target": "authorization_targets",
        "authorized_party": "authorization_targets",
        "authorization_scope": "authorization_scopes",
        "bid_total_amount": "bid_amounts",
        "address": "addresses",
        "phone": "phones",
        "contact_name": "contact_names",
        "contact_person": "contact_names",
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
        table_row.setdefault("manufacturer_mentions", [])
        table_row.setdefault("authorized_manufacturers", [])
        table_row.setdefault("authorization_issuers", [])
        table_row.setdefault("authorization_dates", [])
        table_row.setdefault("authorization_targets", [])
        table_row.setdefault("authorization_scopes", [])
        table_row.setdefault("authorization_mentions", [])
        fields = row.get("fields") or {}
        manufacturer = normalize_text_field(fields.get("manufacturer"))
        if manufacturer and manufacturer not in table_row["manufacturer_mentions"]:
            table_row["manufacturer_mentions"].append(manufacturer)
        authorized_manufacturer = normalize_text_field(fields.get("authorized_manufacturer") or fields.get("manufacturer"))
        if authorized_manufacturer and authorized_manufacturer not in table_row["authorized_manufacturers"]:
            table_row["authorized_manufacturers"].append(authorized_manufacturer)
        authorization_issuer = normalize_text_field(fields.get("authorization_issuer"))
        if authorization_issuer and authorization_issuer not in table_row["authorization_issuers"]:
            table_row["authorization_issuers"].append(authorization_issuer)
        authorization_date = _normalize_date_text(fields.get("authorization_date"))
        if authorization_date and authorization_date not in table_row["authorization_dates"]:
            table_row["authorization_dates"].append(authorization_date)
        authorization_target = normalize_text_field(fields.get("authorization_target") or fields.get("authorized_party"))
        if authorization_target and authorization_target not in table_row["authorization_targets"]:
            table_row["authorization_targets"].append(authorization_target)
        authorization_scope = normalize_text_field(fields.get("authorization_scope"))
        if authorization_scope and authorization_scope not in table_row["authorization_scopes"]:
            table_row["authorization_scopes"].append(authorization_scope)
        if row.get("doc_type") == "authorization_letter":
            mention = compact_ocr_line(row)
            if mention and mention not in table_row["authorization_mentions"]:
                table_row["authorization_mentions"].append(mention)
        if (
            table_row["authorization_mentions"]
            or table_row["manufacturer_mentions"]
            or table_row["authorized_manufacturers"]
            or table_row["authorization_issuers"]
            or table_row["authorization_dates"]
            or table_row["authorization_targets"]
            or table_row["authorization_scopes"]
        ):
            table_row["summary"] = "发现授权链关键信息"


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


def _build_supplier_facts(
    signal: ExtractedSignals,
    image_ocr_rows: list[dict],
    section_catalog_rows: list[dict],
    table_extract_rows: list[dict],
) -> SupplierFacts:
    supplier_rows = [row for row in image_ocr_rows if row.get("supplier") == signal.document.name]
    supplier_section_rows = [row for row in section_catalog_rows if row.get("supplier") == signal.document.name]
    supplier_table_rows = [row for row in table_extract_rows if row.get("supplier") == signal.document.name]
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
        contact_names=_build_text_observations(signal.contact_names, signal.document.path),
        unified_social_credit_codes=[],
        legal_representatives=_build_text_observations(signal.legal_representatives, signal.document.path),
        authorized_representatives=[],
        addresses=_build_text_observations(signal.addresses, signal.document.path),
        bid_amounts=_build_amount_observations(signal.bid_amounts, signal.document.path),
        pricing_rows=[],
        timeline_created_times=_extract_created_times(signal.document.metadata.get("components", [])),
        timeline_modified_times=_extract_modified_times(signal.document.metadata.get("components", [])),
        timeline_uploaded_times=_extract_component_field(signal.document.metadata.get("components", []), "upload_at"),
        timeline_ca_users=_extract_component_field(signal.document.metadata.get("components", []), "ca_user"),
        timeline_terminal_ids=_extract_component_field(signal.document.metadata.get("components", []), "terminal_id", "client_id", "device_id"),
        timeline_ip_addresses=_extract_component_field(signal.document.metadata.get("components", []), "client_ip", "upload_ip", "ip"),
        platform_trace_lines=_extract_platform_trace_lines(signal.document.metadata.get("components", [])),
        file_fingerprints=_build_file_fingerprints(signal),
        section_order_profile=_build_section_order_profile(supplier_section_rows),
        table_structure_profiles=_build_table_structure_profiles(supplier_table_rows),
        authorized_manufacturers=[],
        authorization_issuers=[],
        authorization_dates=[],
        authorization_targets=[],
        authorization_scopes=[],
        section_rows=[dict(row) for row in supplier_section_rows],
        table_rows=[dict(row) for row in supplier_table_rows],
    )

    for row in supplier_table_rows:
        if row.get("field_name") == "bid_total_amount":
            _append_capability_observation(
                facts.bid_amounts,
                normalize_text_field(row.get("value")),
                source_document=row.get("source_path") or signal.document.path,
                source_page=row.get("source_page"),
                confidence=row.get("confidence"),
                source_type="table",
                prefer_primary=not facts.bid_amounts,
            )
        if row.get("field_name") == "pricing_row":
            facts.pricing_rows.append(
                {
                    "value": normalize_text_field(row.get("value")),
                    "item_name": normalize_text_field(row.get("item_name")),
                    "amount": normalize_text_field(row.get("amount")),
                    "tax_rate": normalize_text_field(row.get("tax_rate")),
                    "pricing_note": normalize_text_field(row.get("pricing_note")),
                    "is_total_row": bool(row.get("is_total_row")),
                    "source_document": row.get("source_path") or signal.document.path,
                    "source_page": row.get("source_page"),
                    "source_section": row.get("source_section"),
                    "confidence": row.get("confidence"),
                    "snippet": row.get("snippet"),
                }
            )

    _augment_supplier_profile_observations(facts)

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
            facts.contact_names,
            normalize_text_field(fields.get("contact_name") or fields.get("contact_person")),
            source_document,
            source_page,
            confidence,
            prefer_primary=not facts.contact_names,
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
            facts.authorized_representatives,
            normalize_text_field(fields.get("authorized_representative") or fields.get("authorized_person")),
            source_document,
            source_page,
            confidence,
            prefer_primary=not facts.authorized_representatives,
        )
        _append_observation(
            facts.unified_social_credit_codes,
            _normalize_credit_code(fields.get("unified_social_credit_code") or fields.get("social_credit_code")),
            source_document,
            source_page,
            confidence,
            prefer_primary=not facts.unified_social_credit_codes,
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
            facts.authorized_manufacturers,
            normalize_text_field(fields.get("authorized_manufacturer") or fields.get("manufacturer")),
            source_document,
            source_page,
            confidence,
            prefer_primary=not facts.authorized_manufacturers and row.get("doc_type") == "authorization_letter",
        )
        _append_observation(
            facts.authorization_issuers,
            normalize_text_field(fields.get("authorization_issuer")),
            source_document,
            source_page,
            confidence,
            prefer_primary=not facts.authorization_issuers,
        )
        _append_observation(
            facts.authorization_dates,
            _normalize_date_text(fields.get("authorization_date")),
            source_document,
            source_page,
            confidence,
            prefer_primary=not facts.authorization_dates,
        )
        _append_observation(
            facts.authorization_targets,
            normalize_text_field(fields.get("authorization_target") or fields.get("authorized_party")),
            source_document,
            source_page,
            confidence,
            prefer_primary=not facts.authorization_targets,
        )
        _append_observation(
            facts.authorization_scopes,
            normalize_text_field(fields.get("authorization_scope")),
            source_document,
            source_page,
            confidence,
            prefer_primary=not facts.authorization_scopes,
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

    facts.company_names = _filter_company_name_observations(facts.company_names)
    facts.contact_names = _filter_contact_observations(facts.contact_names)
    facts.legal_representatives = _filter_legal_observations(facts.legal_representatives)
    facts.authorized_representatives = _filter_legal_observations(facts.authorized_representatives)
    facts.addresses = _filter_address_observations(facts.addresses)
    facts.unified_social_credit_codes = _filter_credit_code_observations(facts.unified_social_credit_codes)
    _resolve_identity_fact_primaries(facts)

    return facts


def _build_file_fingerprints(signal: ExtractedSignals) -> list[dict]:
    fingerprints: list[dict] = [
        {
            "display_name": Path(signal.document.path).name,
            "relative_path": Path(signal.document.path).name,
            "sha256": signal.text_hash,
            "size_bytes": signal.document.metadata.get("size_bytes"),
            "scope": "document",
        }
    ]
    for component in signal.document.metadata.get("components", []):
        sha256 = component.get("sha256")
        if not sha256:
            continue
        fingerprints.append(
            {
                "display_name": component.get("display_name"),
                "relative_path": component.get("relative_path"),
                "sha256": sha256,
                "size_bytes": component.get("size_bytes"),
                "scope": "component",
            }
        )
    return fingerprints


def _build_section_order_profile(section_rows: list[dict]) -> list[str]:
    ordered_rows = sorted(
        section_rows,
        key=lambda row: (
            row.get("start_page") or 10**9,
            row.get("end_page") or 10**9,
            str(row.get("title") or ""),
        ),
    )
    profile: list[str] = []
    for row in ordered_rows:
        family = normalize_text_field(row.get("family"))
        title = normalize_text_field(row.get("title"))
        label = family or _normalize_section_label(title)
        if label:
            profile.append(label)
    return profile


def _build_table_structure_profiles(table_rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in table_rows:
        source_section = normalize_text_field(row.get("source_section")) or normalize_text_field(row.get("table_type")) or "unknown"
        field_name = normalize_text_field(row.get("field_name")) or "unknown"
        grouped.setdefault((source_section, field_name), []).append(row)

    profiles: list[dict] = []
    for (source_section, field_name), rows in sorted(grouped.items()):
        column_keys = sorted(
            {
                key
                for row in rows
                for key, value in row.items()
                if key
                in {
                    "item_name",
                    "amount",
                    "tax_rate",
                    "pricing_note",
                    "is_total_row",
                    "field_name",
                    "table_type",
                }
                and value not in (None, "", False)
            }
        )
        row_count = len(rows)
        signature = "|".join(
            [
                _normalize_section_label(source_section) or source_section,
                field_name,
                ",".join(column_keys),
                str(row_count),
            ]
        )
        profiles.append(
            {
                "source_section": source_section,
                "field_name": field_name,
                "column_keys": column_keys,
                "row_count": row_count,
                "signature": signature,
            }
        )
    return profiles


def _normalize_section_label(value: str) -> str:
    text = normalize_text_field(value)
    if not text:
        return ""
    text = re.sub(r"^[一二三四五六七八九十0-9]+\s*[\.、)]\s*", "", text)
    text = re.sub(r"^[0-9]+(?:\.[0-9]+)*\s*", "", text)
    return text.strip()


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
    extracted = _extract_company_name_from_profile_text(signal.document.text)
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


def _augment_supplier_profile_observations(facts: SupplierFacts) -> None:
    profile_text = _build_profile_text(facts)
    source_document = facts.document.path
    source_page = _first_profile_page(facts)

    company_name = _extract_company_name_from_profile_text(profile_text)
    if company_name:
        _promote_primary_observation(
            facts.company_names,
            company_name,
            source_document=source_document,
            source_page=source_page,
            confidence=0.93,
            source_type="section",
        )

    legal = _extract_legal_representative_from_profile_text(profile_text)
    if legal:
        _promote_primary_observation(
            facts.legal_representatives,
            legal,
            source_document=source_document,
            source_page=source_page,
            confidence=0.9,
            source_type="section",
        )

    authorized = _extract_authorized_representative_from_profile_text(profile_text)
    if authorized:
        _promote_primary_observation(
            facts.authorized_representatives,
            authorized,
            source_document=source_document,
            source_page=source_page,
            confidence=0.88,
            source_type="section",
        )

    authorization_manufacturer = _extract_authorized_manufacturer_from_profile_text(profile_text)
    if authorization_manufacturer:
        _promote_primary_observation(
            facts.authorized_manufacturers,
            authorization_manufacturer,
            source_document=source_document,
            source_page=source_page,
            confidence=0.84,
            source_type="section",
        )

    authorization_issuer = _extract_authorization_issuer_from_profile_text(profile_text)
    if authorization_issuer:
        _promote_primary_observation(
            facts.authorization_issuers,
            authorization_issuer,
            source_document=source_document,
            source_page=source_page,
            confidence=0.83,
            source_type="section",
        )

    authorization_date = _extract_authorization_date_from_profile_text(profile_text)
    if authorization_date:
        _promote_primary_observation(
            facts.authorization_dates,
            authorization_date,
            source_document=source_document,
            source_page=source_page,
            confidence=0.82,
            source_type="section",
        )

    authorization_target = _extract_authorization_target_from_profile_text(profile_text)
    if authorization_target:
        _promote_primary_observation(
            facts.authorization_targets,
            authorization_target,
            source_document=source_document,
            source_page=source_page,
            confidence=0.8,
            source_type="section",
        )

    authorization_scope = _extract_authorization_scope_from_profile_text(profile_text)
    if authorization_scope:
        _promote_primary_observation(
            facts.authorization_scopes,
            authorization_scope,
            source_document=source_document,
            source_page=source_page,
            confidence=0.78,
            source_type="section",
        )

    phone = _extract_phone_from_profile_text(profile_text)
    if phone:
        _promote_primary_observation(
            facts.phones,
            phone,
            source_document=source_document,
            source_page=source_page,
            confidence=0.85,
            source_type="section",
        )

    contact_name = _extract_contact_name_from_profile_text(profile_text)
    if contact_name:
        _promote_primary_observation(
            facts.contact_names,
            contact_name,
            source_document=source_document,
            source_page=source_page,
            confidence=0.82,
            source_type="section",
        )

    credit_code = _extract_unified_social_credit_code_from_profile_text(profile_text)
    if credit_code:
        _promote_primary_observation(
            facts.unified_social_credit_codes,
            credit_code,
            source_document=source_document,
            source_page=source_page,
            confidence=0.94,
            source_type="section",
        )

    address = _extract_address_from_profile_text(profile_text)
    if address:
        _promote_primary_observation(
            facts.addresses,
            address,
            source_document=source_document,
            source_page=source_page,
            confidence=0.82,
            source_type="section",
        )

    facts.company_names = _filter_company_name_observations(facts.company_names)
    facts.contact_names = _filter_contact_observations(facts.contact_names)
    facts.legal_representatives = _filter_legal_observations(facts.legal_representatives)
    facts.authorized_representatives = _filter_legal_observations(facts.authorized_representatives)
    facts.addresses = _filter_address_observations(facts.addresses)
    facts.unified_social_credit_codes = _filter_credit_code_observations(facts.unified_social_credit_codes)
    _resolve_identity_fact_primaries(facts)


def _build_profile_text(facts: SupplierFacts) -> str:
    page_refs = facts.document.metadata.get("components", [])
    first_pages = "\n".join(component.get("text", "") for component in page_refs[:8] if component.get("text"))
    if not first_pages:
        first_pages = facts.document.text[:4000]
    relevant_sections = []
    for row in facts.section_rows:
        title = str(row.get("title") or "")
        family = str(row.get("family") or "")
        if family in {"bid_letter", "qualification", "authorization", "quotation"} or any(
            token in title for token in ("法定代表", "授权", "资格", "基本情况", "报价", "投标函", "响应函")
        ):
            relevant_sections.append(str(row.get("text") or ""))
    return "\n".join(part for part in [first_pages, *relevant_sections] if part).strip()


def _first_profile_page(facts: SupplierFacts) -> int | None:
    if facts.section_rows:
        return min((row.get("start_page") for row in facts.section_rows if row.get("start_page") is not None), default=None)
    return None


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
    existing = next((item for item in bucket if item.value == value), None)
    if existing is not None:
        _maybe_upgrade_observation(
            existing,
            source_document=source_document,
            source_page=source_page,
            confidence=confidence,
            source_type="ocr",
            prefer_primary=prefer_primary,
        )
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


def _append_capability_observation(
    bucket: list[FactObservation],
    value: str,
    source_document: str,
    source_page: int | None,
    confidence: float | None,
    *,
    source_type: str,
    prefer_primary: bool,
) -> None:
    if not value:
        return
    existing = next((item for item in bucket if item.value == value), None)
    if existing is not None:
        _maybe_upgrade_observation(
            existing,
            source_document=source_document,
            source_page=source_page,
            confidence=confidence,
            source_type=source_type,
            prefer_primary=prefer_primary,
        )
        return
    bucket.append(
        FactObservation(
            value=value,
            source_type=source_type,
            source_document=source_document,
            source_page=source_page,
            confidence=confidence,
            is_primary=prefer_primary,
        )
    )


def _promote_primary_observation(
    bucket: list[FactObservation],
    value: str,
    *,
    source_document: str,
    source_page: int | None,
    confidence: float | None,
    source_type: str,
) -> None:
    if not value:
        return
    existing = next((item for item in bucket if item.value == value), None)
    for item in bucket:
        item.is_primary = False
    if existing is not None:
        existing.is_primary = True
        existing.source_document = source_document
        existing.source_page = source_page
        existing.confidence = confidence
        existing.source_type = source_type
        return
    bucket.insert(
        0,
        FactObservation(
            value=value,
            source_type=source_type,
            source_document=source_document,
            source_page=source_page,
            confidence=confidence,
            is_primary=True,
        ),
    )


def _maybe_upgrade_observation(
    item: FactObservation,
    *,
    source_document: str,
    source_page: int | None,
    confidence: float | None,
    source_type: str,
    prefer_primary: bool,
) -> None:
    candidate = FactObservation(
        value=item.value,
        source_type=source_type,
        source_document=source_document,
        source_page=source_page,
        confidence=confidence,
        is_primary=prefer_primary,
    )
    if _observation_rank(candidate) > _observation_rank(item):
        item.source_document = source_document
        item.source_page = source_page
        item.confidence = confidence
        item.source_type = source_type
    item.is_primary = item.is_primary or prefer_primary


def _extract_modified_times(components: list[dict]) -> list[str]:
    return [
        component["modified_at"]
        for component in components
        if component.get("modified_at")
    ]


def _extract_created_times(components: list[dict]) -> list[str]:
    return [
        component["created_at"]
        for component in components
        if component.get("created_at")
    ]


def _extract_component_field(components: list[dict], *keys: str) -> list[str]:
    values: list[str] = []
    for component in components:
        for key in keys:
            value = normalize_text_field(component.get(key))
            if value and value not in values:
                values.append(value)
    return values


def _extract_platform_trace_lines(components: list[dict]) -> list[str]:
    lines: list[str] = []
    for component in components:
        parts: list[str] = []
        upload_time = normalize_text_field(component.get("upload_at"))
        ca_user = normalize_text_field(component.get("ca_user"))
        terminal_id = normalize_text_field(component.get("terminal_id") or component.get("client_id") or component.get("device_id"))
        ip_address = normalize_text_field(component.get("client_ip") or component.get("upload_ip") or component.get("ip"))
        if upload_time:
            parts.append(f"upload={upload_time}")
        if ca_user:
            parts.append(f"ca={ca_user}")
        if terminal_id:
            parts.append(f"terminal={terminal_id}")
        if ip_address:
            parts.append(f"ip={ip_address}")
        if parts:
            line = "；".join(parts)
            if line not in lines:
                lines.append(line)
    return lines


def _extract_company_name_from_text(text: str) -> str | None:
    pattern = re.compile(r"([A-Za-z（）()·\u4e00-\u9fff]{4,}(?:有限责任公司|股份有限公司|有限公司|公司))")
    matches = pattern.findall(text)
    if not matches:
        return None
    return matches[0].strip()


def _extract_company_name_from_profile_text(text: str) -> str | None:
    patterns = (
        r"(?:比选单位名称|投标人名称|投标人全称|投标人|比选单位)\s*[:：]\s*([^\n（(]{2,40})",
        r"投\s*标\s*人\s*[:：]\s*([^\n（(]{2,40})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = _clean_company_like_value(match.group(1))
            if value:
                return value
    return _extract_company_name_from_text("\n".join(text.splitlines()[:40]))


def _extract_legal_representative_from_profile_text(text: str) -> str | None:
    patterns = (
        r"姓\s*名\s*[:：]\s*([A-Za-z\u4e00-\u9fff]{2,8})\s*(?:性别|职务|年)",
        r"兹证明\s*([A-Za-z\u4e00-\u9fff]{2,8})\s*[（(]姓名",
        r"本人\s*([A-Za-z\u4e00-\u9fff]{2,8})\s*(?:[（(]姓名[)）])?\s*系",
        r"法人代表\s*([A-Za-z\u4e00-\u9fff]{2,8})\s*授权",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = match.group(1).strip()
            if value and value not in {"单位负责人", "法定代表人"}:
                return value
    return None


def _extract_authorized_representative_from_profile_text(text: str) -> str | None:
    patterns = (
        r"(?:委托代理人|被授权人|授权代表|代理人)\s*[:：]\s*([A-Za-z\u4e00-\u9fff]{2,8})",
        r"现授权委托\s*([A-Za-z\u4e00-\u9fff]{2,8})\s*(?:为|作为)我",
        r"特委托\s*([A-Za-z\u4e00-\u9fff]{2,8})\s*(?:为|作为)我",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = match.group(1).strip()
            if value and value not in {"法定代表人", "授权代表", "委托代理人", "代理人"}:
                return value
    return None


def _extract_phone_from_profile_text(text: str) -> str | None:
    patterns = (
        r"(?:联系方式|联系电话|电话)\s*[:：]\s*([0-9*－—\-]{7,20})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = match.group(1).replace("－", "-").replace("—", "-").strip()
            if value:
                return value
    return None


def _extract_contact_name_from_profile_text(text: str) -> str | None:
    patterns = (
        r"(?:联系人|项目联系人|联系人姓名|联\s*系\s*人)\s*[:：]\s*([A-Za-z\u4e00-\u9fff]{2,8})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = match.group(1).strip()
            if value and value not in {"联系人", "项目联系人"}:
                return value
    return None


def _extract_authorized_manufacturer_from_profile_text(text: str) -> str | None:
    patterns = (
        r"(?:授权厂家|厂家名称|制造商|生产厂家)\s*[:：]\s*([^\n]{2,80})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = _clean_company_like_value(match.group(1))
            if value:
                return value
    return None


def _extract_authorization_issuer_from_profile_text(text: str) -> str | None:
    patterns = (
        r"([A-Za-z（）()·\u4e00-\u9fff]{4,}(?:有限责任公司|股份有限公司|有限公司|公司))\s*(?:现|特)?授权",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = _clean_company_like_value(match.group(1))
            if value:
                return value
    return None


def _extract_authorization_date_from_profile_text(text: str) -> str | None:
    patterns = (
        r"(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)",
        r"(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _normalize_date_text(match.group(1))
    return None


def _extract_authorization_target_from_profile_text(text: str) -> str | None:
    patterns = (
        r"(?:授权(?:给|予|对象)|被授权(?:单位|人)|授权经销商)\s*[:：]?\s*([^\n]{2,80})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = _clean_company_like_value(match.group(1))
            if value:
                return value
    return None


def _extract_authorization_scope_from_profile_text(text: str) -> str | None:
    patterns = (
        r"(?:授权范围|授权产品|授权内容|授权项目)\s*[:：]?\s*([^\n]{4,120})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = normalize_text_field(match.group(1)).strip(" ：:;；,.，")
            if value:
                return value[:120]
    return None


def _extract_unified_social_credit_code_from_profile_text(text: str) -> str | None:
    patterns = (
        r"(?:统一社会信用代码|社会信用代码|信用代码)\s*[:：]?\s*([0-9A-Z]{18})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return None


def _extract_address_from_profile_text(text: str) -> str | None:
    patterns = (
        r"(?:地\s*址|联系地址|办公地址)\s*[:：]\s*([^\n]{6,120})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = re.sub(r"\s+", " ", match.group(1)).strip(" ：:;；,.，")
            if value and "发票等信息" not in value and "商品数量" not in value:
                return value
    return None


def _clean_company_like_value(value: str) -> str:
    cleaned = re.sub(r"[（(].*$", "", value).strip()
    cleaned = cleaned.strip("：:;；,.， ")
    if len(cleaned) < 2:
        return ""
    return cleaned


def _filter_company_name_observations(observations: list[FactObservation]) -> list[FactObservation]:
    filtered = [item for item in observations if _looks_like_company_name(item.value)]
    return _rebuild_primary(filtered)


def _filter_legal_observations(observations: list[FactObservation]) -> list[FactObservation]:
    return _filter_person_observations(observations, contact_mode=False)


def _filter_contact_observations(observations: list[FactObservation]) -> list[FactObservation]:
    return _filter_person_observations(observations, contact_mode=True)


def _filter_address_observations(observations: list[FactObservation]) -> list[FactObservation]:
    filtered: list[FactObservation] = []
    seen: set[str] = set()
    for item in observations:
        normalized = _normalize_address_text(item.value)
        if not _looks_like_address(normalized):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        filtered.append(
            FactObservation(
                value=normalized,
                source_type=item.source_type,
                source_document=item.source_document,
                source_page=item.source_page,
                confidence=item.confidence,
                is_primary=item.is_primary,
            )
        )
    return _rebuild_primary(filtered)


def _filter_person_observations(
    observations: list[FactObservation],
    *,
    contact_mode: bool,
) -> list[FactObservation]:
    filtered: list[FactObservation] = []
    seen: set[str] = set()
    for item in observations:
        normalized = _normalize_person_name_text(item.value)
        if contact_mode:
            if not _looks_like_contact_name(normalized):
                continue
        elif not _looks_like_person_name(normalized):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        filtered.append(
            FactObservation(
                value=normalized,
                source_type=item.source_type,
                source_document=item.source_document,
                source_page=item.source_page,
                confidence=item.confidence,
                is_primary=item.is_primary,
            )
        )
    return _rebuild_primary(filtered)


def _filter_credit_code_observations(observations: list[FactObservation]) -> list[FactObservation]:
    filtered = [item for item in observations if _looks_like_credit_code(item.value)]
    return _rebuild_primary(filtered)


def _rebuild_primary(observations: list[FactObservation]) -> list[FactObservation]:
    if not observations:
        return observations
    has_primary = any(item.is_primary for item in observations)
    if not has_primary:
        observations[0].is_primary = True
    return observations


def _resolve_identity_fact_primaries(facts: SupplierFacts) -> None:
    for field_name in (
        "company_names",
        "phones",
        "emails",
        "bank_accounts",
        "contact_names",
        "unified_social_credit_codes",
        "legal_representatives",
        "authorized_representatives",
        "addresses",
    ):
        bucket = getattr(facts, field_name)
        if not bucket:
            continue
        winner = max(bucket, key=_observation_rank)
        for item in bucket:
            item.is_primary = item is winner


def _observation_rank(item: FactObservation) -> tuple[float, int, int, int]:
    confidence = item.confidence if item.confidence is not None else _default_confidence(item.source_type)
    source_priority = _source_priority(item.source_type)
    primary_hint = 1 if item.is_primary else 0
    page_rank = -(item.source_page or 10**6)
    return (float(source_priority), confidence, primary_hint, page_rank)


def _default_confidence(source_type: str) -> float:
    defaults = {
        "section": 0.90,
        "table": 0.84,
        "text": 0.76,
        "ocr": 0.68,
    }
    return defaults.get(source_type, 0.60)


def _source_priority(source_type: str) -> int:
    priorities = {
        "section": 4,
        "table": 3,
        "text": 2,
        "ocr": 1,
    }
    return priorities.get(source_type, 0)


def _looks_like_company_name(value: str) -> bool:
    return bool(value) and (
        "投标人" in value
        or "公司" in value
        or "集团" in value
        or "企业" in value
    )


def _looks_like_person_name(value: str) -> bool:
    normalized = _normalize_person_name_text(value)
    if not normalized:
        return False
    if any(token in normalized for token in ("单位负责人", "证明书", "法定代表", "控股", "关系", "企业", "签字", "盖章")):
        return False
    return bool(re.fullmatch(r"[A-Za-z\u4e00-\u9fff]{2,8}", normalized))


def _looks_like_contact_name(value: str) -> bool:
    normalized = _normalize_person_name_text(value)
    if not normalized:
        return False
    if any(token in normalized for token in ("电话", "邮箱", "地址", "公司", "法定代表", "授权", "项目")):
        return False
    return bool(re.fullmatch(r"[A-Za-z\u4e00-\u9fff]{2,8}", normalized))


def _looks_like_address(value: str) -> bool:
    if not value:
        return False
    if "@" in value or "发票等信息" in value or "商品数量" in value:
        return False
    return any(token in value for token in ("省", "市", "区", "县", "路", "街", "号", "镇", "大厦", "园", "楼"))


def _normalize_address_text(value: str) -> str:
    normalized = normalize_text_field(value)
    if not normalized:
        return ""
    normalized = normalized.replace("（", "(").replace("）", ")")
    normalized = normalized.replace("中国", "")
    normalized = re.sub(r"[，,；;。]+", "", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    normalized = re.sub(r"[，,。；;：:]+$", "", normalized)
    return normalized


def _normalize_person_name_text(value: str) -> str:
    normalized = normalize_text_field(value)
    if not normalized:
        return ""
    normalized = re.sub(r"(先生|女士|老师)$", "", normalized)
    normalized = re.sub(
        r"(联系人|项目联系人|法定代表人|授权代表|委托代理人|代理人|被授权人|授权委托人)",
        "",
        normalized,
    )
    normalized = re.sub(r"[^\u4e00-\u9fffA-Za-z]", "", normalized)
    return normalized


def _looks_like_credit_code(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9A-Z]{18}", value or ""))


def _normalize_credit_code(value: object) -> str:
    normalized = normalize_text_field(value).upper().replace(" ", "")
    return normalized if _looks_like_credit_code(normalized) else ""


def _normalize_date_text(value: object) -> str:
    normalized = normalize_text_field(value)
    if not normalized:
        return ""
    normalized = re.sub(r"\s+", "", normalized)
    normalized = normalized.replace("/", "-").replace(".", "-")
    return normalized
