from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class LoadedDocument:
    name: str
    role: str
    path: str
    parser: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExtractedSignals:
    document: LoadedDocument
    text_hash: str
    line_count: int
    token_count: int
    bid_amounts: list[float] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    bank_accounts: list[str] = field(default_factory=list)
    contact_names: list[str] = field(default_factory=list)
    legal_representatives: list[str] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)
    non_tender_lines: list[str] = field(default_factory=list)
    rare_line_fingerprints: dict[str, str] = field(default_factory=dict)
    candidate_overlap_lines: list[str] = field(default_factory=list)
    candidate_overlap_refs: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["document"]["path"] = str(Path(self.document.path))
        return data


@dataclass(slots=True)
class FactObservation:
    value: str
    source_type: str
    source_document: str
    source_page: int | None = None
    confidence: float | None = None
    is_primary: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SupplierFacts:
    supplier: str
    document: LoadedDocument
    text_hash: str
    line_count: int
    token_count: int
    non_tender_lines: list[str] = field(default_factory=list)
    rare_line_fingerprints: dict[str, str] = field(default_factory=dict)
    candidate_overlap_lines: list[str] = field(default_factory=list)
    candidate_overlap_refs: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    company_names: list[FactObservation] = field(default_factory=list)
    phones: list[FactObservation] = field(default_factory=list)
    emails: list[FactObservation] = field(default_factory=list)
    bank_accounts: list[FactObservation] = field(default_factory=list)
    contact_names: list[FactObservation] = field(default_factory=list)
    unified_social_credit_codes: list[FactObservation] = field(default_factory=list)
    legal_representatives: list[FactObservation] = field(default_factory=list)
    authorized_representatives: list[FactObservation] = field(default_factory=list)
    addresses: list[FactObservation] = field(default_factory=list)
    bid_amounts: list[FactObservation] = field(default_factory=list)
    pricing_rows: list[dict[str, Any]] = field(default_factory=list)
    manufacturers: list[FactObservation] = field(default_factory=list)
    authorized_manufacturers: list[FactObservation] = field(default_factory=list)
    authorization_issuers: list[FactObservation] = field(default_factory=list)
    authorization_dates: list[FactObservation] = field(default_factory=list)
    authorization_targets: list[FactObservation] = field(default_factory=list)
    authorization_scopes: list[FactObservation] = field(default_factory=list)
    brands: list[FactObservation] = field(default_factory=list)
    models: list[FactObservation] = field(default_factory=list)
    license_numbers: list[FactObservation] = field(default_factory=list)
    registration_numbers: list[FactObservation] = field(default_factory=list)
    authorization_mentions: list[FactObservation] = field(default_factory=list)
    timeline_created_times: list[str] = field(default_factory=list)
    timeline_modified_times: list[str] = field(default_factory=list)
    timeline_uploaded_times: list[str] = field(default_factory=list)
    timeline_ca_users: list[str] = field(default_factory=list)
    timeline_terminal_ids: list[str] = field(default_factory=list)
    timeline_ip_addresses: list[str] = field(default_factory=list)
    platform_trace_lines: list[str] = field(default_factory=list)
    file_fingerprints: list[dict[str, Any]] = field(default_factory=list)
    section_order_profile: list[str] = field(default_factory=list)
    table_structure_profiles: list[dict[str, Any]] = field(default_factory=list)
    section_rows: list[dict[str, Any]] = field(default_factory=list)
    table_rows: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["document"]["path"] = str(Path(self.document.path))
        return data


@dataclass(slots=True)
class ReviewFacts:
    tender_document: LoadedDocument
    suppliers: list[SupplierFacts] = field(default_factory=list)
    image_index_rows: list[dict[str, Any]] = field(default_factory=list)
    image_ocr_rows: list[dict[str, Any]] = field(default_factory=list)
    section_catalog_rows: list[dict[str, Any]] = field(default_factory=list)
    table_extract_rows: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tender_document": self.tender_document.to_dict(),
            "suppliers": [supplier.to_dict() for supplier in self.suppliers],
            "image_index_rows": self.image_index_rows,
            "image_ocr_rows": self.image_ocr_rows,
            "section_catalog_rows": self.section_catalog_rows,
            "table_extract_rows": self.table_extract_rows,
        }


@dataclass(slots=True)
class PairwiseFinding:
    title: str
    weight: int
    evidence: list[str]
    evidence_details: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PairwiseAssessment:
    supplier_a: str
    supplier_b: str
    risk_score: int
    risk_level: str
    findings: list[PairwiseFinding]
    dimension_summary: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "supplier_a": self.supplier_a,
            "supplier_b": self.supplier_b,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "findings": [finding.to_dict() for finding in self.findings],
            "dimension_summary": self.dimension_summary,
        }
