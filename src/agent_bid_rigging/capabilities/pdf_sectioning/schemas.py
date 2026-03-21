from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class PdfSection:
    title: str
    family: str
    start_page: int
    end_page: int
    page_span: int
    source: str
    snippet: str
    text: str = ""
    confidence: float = 0.0

    def to_dict(self, *, include_text: bool = True) -> dict:
        payload = asdict(self)
        if not include_text:
            payload.pop("text", None)
        return payload


@dataclass(slots=True)
class PdfSectioningResponse:
    source_path: str
    output_dir: str
    page_count: int
    toc_pages: list[int] = field(default_factory=list)
    section_count: int = 0
    sections: list[PdfSection] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self, *, include_text: bool = True) -> dict:
        return {
            "source_path": self.source_path,
            "output_dir": self.output_dir,
            "page_count": self.page_count,
            "toc_pages": self.toc_pages,
            "section_count": self.section_count,
            "sections": [section.to_dict(include_text=include_text) for section in self.sections],
            "warnings": self.warnings,
        }
