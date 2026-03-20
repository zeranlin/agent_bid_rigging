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
    legal_representatives: list[str] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)
    non_tender_lines: list[str] = field(default_factory=list)
    rare_line_fingerprints: dict[str, str] = field(default_factory=dict)
    candidate_overlap_lines: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["document"]["path"] = str(Path(self.document.path))
        return data


@dataclass(slots=True)
class PairwiseFinding:
    title: str
    weight: int
    evidence: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PairwiseAssessment:
    supplier_a: str
    supplier_b: str
    risk_score: int
    risk_level: str
    findings: list[PairwiseFinding]

    def to_dict(self) -> dict[str, Any]:
        return {
            "supplier_a": self.supplier_a,
            "supplier_b": self.supplier_b,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "findings": [finding.to_dict() for finding in self.findings],
        }
