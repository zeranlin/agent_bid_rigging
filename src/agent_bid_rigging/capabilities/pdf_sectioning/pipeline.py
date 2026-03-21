from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from pypdf import PdfReader

from agent_bid_rigging.capabilities.base import CapabilityContext, CapabilityResult, ReviewCapability
from agent_bid_rigging.capabilities.pdf_sectioning.schemas import PdfSection, PdfSectioningResponse

TOC_PAGE_SCAN_LIMIT = 12
TITLE_SEARCH_LIMIT = 10

TOC_LINE_PATTERN = re.compile(
    r"^\s*(?P<title>.+?)(?:\.{2,}|…{2,}|\. \. \.|-{2,}|\s{2,})\s*-?\s*(?P<page>\d{1,3})\s*-?\s*$"
)
TITLE_PREFIX_PATTERN = re.compile(
    r"^\s*(?:第[一二三四五六七八九十百]+[章节部分篇]\s*|[一二三四五六七八九十]+\s*[、.．]?\s*|"
    r"\d+(?:\.\d+){0,3}\s*[.．]?\s*|[（(]\d+[)）]\s*|[①②③④⑤⑥⑦⑧⑨⑩]\s*)"
)

SECTION_FAMILIES: list[tuple[str, tuple[str, ...]]] = [
    ("bid_letter", ("响应函", "投标函", "应答函")),
    ("quotation", ("开标一览表", "报价一览表", "报价表", "报价单", "比选报价表", "投标报价", "分项报价")),
    ("qualification", ("资格审查", "资格性审查", "符合性审查", "资格证明", "相关证明")),
    ("authorization", ("法定代表人", "授权委托书", "授权书", "身份证明")),
    ("business_deviation", ("商务条款响应偏离表", "商务偏离", "商务响应")),
    ("technical_deviation", ("技术偏离", "技术条款响应", "技术响应")),
    ("experience", ("业绩", "项目案例", "经验")),
    ("technical_plan", ("技术方案", "功能方案", "总体设计", "设计方案", "项目概述")),
    ("implementation_plan", ("实施方案", "项目实施", "部署方案", "服务方案")),
    ("operation_plan", ("运营方案", "运维方案", "运维服务")),
    ("training_plan", ("培训方案", "培训服务")),
]


class PdfSectioningCapability(ReviewCapability):
    name = "pdf_sectioning"

    def run(self, context: CapabilityContext, **kwargs: object) -> CapabilityResult:
        source_path = kwargs.get("source_path") or context.source_path
        if not source_path:
            raise ValueError("source_path is required for PDF sectioning capability")

        source = Path(str(source_path)).expanduser().resolve()
        if source.suffix.lower() != ".pdf":
            raise ValueError("PDF sectioning currently supports only .pdf inputs")

        output_dir = Path(str(kwargs.get("output_dir") or source.parent / f"{source.stem}_sectioning")).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        include_text = bool(kwargs.get("include_text", True))

        response = build_pdf_sectioning_response(source, output_dir=output_dir, include_text=include_text)
        payload = response.to_dict(include_text=include_text)

        section_catalog = {
            "source_path": payload["source_path"],
            "page_count": payload["page_count"],
            "toc_pages": payload["toc_pages"],
            "rows": payload["sections"],
            "warnings": payload["warnings"],
        }
        (output_dir / "section_catalog.json").write_text(
            json.dumps(section_catalog, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (output_dir / "sectioning_result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (output_dir / "sectioning_result.md").write_text(
            _build_markdown(response, include_text=include_text),
            encoding="utf-8",
        )
        return CapabilityResult(
            capability=self.name,
            backend="pypdf",
            status="completed",
            payload=payload,
            evidence=[f"{section.title}: 第{section.start_page}-{section.end_page}页" for section in response.sections],
            warnings=response.warnings,
        )


def build_pdf_sectioning_response(source: Path, *, output_dir: Path, include_text: bool = True) -> PdfSectioningResponse:
    reader = PdfReader(str(source))
    page_texts = [_normalize_page_text(page.extract_text() or "") for page in reader.pages]
    toc_pages, toc_entries = _extract_toc_entries(page_texts)
    warnings: list[str] = []

    if not toc_entries:
        warnings.append("No table-of-contents entries were detected; falling back to heading scan.")
        sections = _fallback_sections(page_texts, include_text=include_text)
    else:
        sections = _sections_from_toc_entries(page_texts, toc_entries, toc_pages=toc_pages, include_text=include_text)
        if not sections:
            warnings.append("TOC entries were detected but no sections could be resolved; falling back to heading scan.")
            sections = _fallback_sections(page_texts, include_text=include_text)

    response = PdfSectioningResponse(
        source_path=str(source),
        output_dir=str(output_dir),
        page_count=len(page_texts),
        toc_pages=toc_pages,
        section_count=len(sections),
        sections=sections,
        warnings=warnings,
    )
    return response


def _normalize_page_text(text: str) -> str:
    return text.replace("\x00", "").replace("\r", "")


def _extract_toc_entries(page_texts: list[str]) -> tuple[list[int], list[tuple[str, int]]]:
    toc_pages: list[int] = []
    entries: list[tuple[str, int]] = []
    for page_index, text in enumerate(page_texts[:TOC_PAGE_SCAN_LIMIT], start=1):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        page_entries = []
        score = 0
        if any("目录" == line or line.endswith("目录") for line in lines[:5]):
            score += 1
        for line in lines:
            parsed = _parse_toc_line(line)
            if parsed:
                page_entries.append(parsed)
        if len(page_entries) >= 3:
            score += 1
        if score >= 1 and page_entries:
            toc_pages.append(page_index)
            entries.extend(page_entries)
    deduped: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for title, page in entries:
        item = (title, page)
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return toc_pages, deduped


def _parse_toc_line(line: str) -> tuple[str, int] | None:
    match = TOC_LINE_PATTERN.match(line)
    if match:
        title = _clean_title(match.group("title"))
        page = int(match.group("page"))
        if title and page > 0:
            return title, page
    stripped = line.strip()
    match = re.match(r"^(?P<title>.+?)\s+(?P<page>\d{1,3})$", stripped)
    if not match:
        return None
    title = _clean_title(match.group("title"))
    page = int(match.group("page"))
    if not title or page <= 0:
        return None
    if not _looks_like_heading(title):
        return None
    return title, page


def _clean_title(title: str) -> str:
    cleaned = re.sub(r"[·•▪■]+", "", title).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(".-— ")
    return cleaned


def _looks_like_heading(value: str) -> bool:
    if len(value) > 120:
        return False
    if not any("\u4e00" <= char <= "\u9fff" or char.isalpha() for char in value):
        return False
    heading_tokens = (
        "函",
        "证明",
        "授权",
        "资格",
        "方案",
        "目录",
        "业绩",
        "报价",
        "偏离",
        "项目",
        "概述",
        "设计",
        "运营",
        "培训",
        "服务",
        "技术",
        "实施",
        "材料",
    )
    return any(token in value for token in heading_tokens) or bool(TITLE_PREFIX_PATTERN.match(value))


def _sections_from_toc_entries(
    page_texts: list[str],
    toc_entries: list[tuple[str, int]],
    *,
    toc_pages: list[int],
    include_text: bool,
) -> list[PdfSection]:
    candidates = []
    skip_pages = set(toc_pages)
    for title, logical_page in toc_entries:
        actual_page = _find_title_page(page_texts, title, skip_pages=skip_pages)
        candidates.append((title, logical_page, actual_page))

    offsets = [
        actual_page - logical_page
        for _, logical_page, actual_page in candidates[:TITLE_SEARCH_LIMIT]
        if actual_page is not None
    ]
    default_offset = Counter(offsets).most_common(1)[0][0] if offsets else 0

    starts: list[tuple[str, int, float]] = []
    seen_pages: set[int] = set()
    for title, logical_page, actual_page in candidates:
        resolved_page = actual_page if actual_page is not None else logical_page + default_offset
        resolved_page = max(1, min(len(page_texts), resolved_page))
        if resolved_page in seen_pages:
            continue
        seen_pages.add(resolved_page)
        confidence = 0.92 if actual_page is not None else 0.58
        starts.append((title, resolved_page, confidence))

    starts.sort(key=lambda item: item[1])
    sections: list[PdfSection] = []
    for index, (title, start_page, confidence) in enumerate(starts):
        next_start = starts[index + 1][1] if index + 1 < len(starts) else len(page_texts) + 1
        end_page = max(start_page, next_start - 1)
        text = "\n".join(page_texts[start_page - 1 : end_page]).strip()
        snippet = _build_snippet(text)
        sections.append(
            PdfSection(
                title=title,
                family=_infer_family(title),
                start_page=start_page,
                end_page=end_page,
                page_span=(end_page - start_page + 1),
                source="toc",
                snippet=snippet,
                text=text if include_text else "",
                confidence=round(confidence, 2),
            )
        )
    return sections


def _fallback_sections(page_texts: list[str], *, include_text: bool) -> list[PdfSection]:
    starts: list[tuple[str, int]] = []
    for page_index, text in enumerate(page_texts, start=1):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in lines[:6]:
            if _looks_like_heading(line):
                starts.append((_clean_title(line), page_index))
                break
    deduped: list[tuple[str, int]] = []
    seen = set()
    for title, page in starts:
        key = (title, page)
        if key not in seen:
            deduped.append(key)
            seen.add(key)
    sections: list[PdfSection] = []
    for index, (title, start_page) in enumerate(deduped):
        next_start = deduped[index + 1][1] if index + 1 < len(deduped) else len(page_texts) + 1
        end_page = max(start_page, next_start - 1)
        text = "\n".join(page_texts[start_page - 1 : end_page]).strip()
        sections.append(
            PdfSection(
                title=title,
                family=_infer_family(title),
                start_page=start_page,
                end_page=end_page,
                page_span=(end_page - start_page + 1),
                source="heading_scan",
                snippet=_build_snippet(text),
                text=text if include_text else "",
                confidence=0.45,
            )
        )
    return sections


def _find_title_page(page_texts: list[str], title: str, *, skip_pages: set[int] | None = None) -> int | None:
    compact_title = _compact(title)
    title_without_prefix = _compact(TITLE_PREFIX_PATTERN.sub("", title).strip())
    for page_index, text in enumerate(page_texts, start=1):
        if skip_pages and page_index in skip_pages:
            continue
        compact_text = _compact(text[:4000])
        if compact_title and compact_title in compact_text:
            return page_index
        if title_without_prefix and title_without_prefix in compact_text:
            return page_index
    return None


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _infer_family(title: str) -> str:
    for family, keywords in SECTION_FAMILIES:
        if any(keyword in title for keyword in keywords):
            return family
    return "other"


def _build_snippet(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    snippet = " ".join(lines[:4]).strip()
    return snippet[:240]


def _build_markdown(response: PdfSectioningResponse, *, include_text: bool) -> str:
    lines = [
        "# PDF Sectioning Result",
        "",
        f"- Source: {response.source_path}",
        f"- Page count: {response.page_count}",
        f"- TOC pages: {', '.join(str(item) for item in response.toc_pages) if response.toc_pages else 'N/A'}",
        f"- Section count: {response.section_count}",
        "",
    ]
    if response.warnings:
        lines.append("## Warnings")
        lines.append("")
        for warning in response.warnings:
            lines.append(f"- {warning}")
        lines.append("")
    for index, section in enumerate(response.sections, start=1):
        lines.append(f"## {index}. {section.title}")
        lines.append("")
        lines.append(f"- Family: {section.family}")
        lines.append(f"- Pages: {section.start_page}-{section.end_page}")
        lines.append(f"- Source: {section.source}")
        lines.append(f"- Confidence: {section.confidence}")
        lines.append(f"- Snippet: {section.snippet}")
        if include_text and section.text:
            lines.extend(["", "```text", section.text[:4000], "```"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
