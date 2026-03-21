from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class PdfTableRow:
    table_type: str
    field_name: str
    value: str
    source_section: str
    source_page: int
    confidence: float
    snippet: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class PdfTableResponse:
    source_path: str
    output_dir: str
    row_count: int = 0
    rows: list[PdfTableRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source_path": self.source_path,
            "output_dir": self.output_dir,
            "row_count": self.row_count,
            "rows": [row.to_dict() for row in self.rows],
            "warnings": self.warnings,
        }
