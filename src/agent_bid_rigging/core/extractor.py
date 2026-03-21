from __future__ import annotations

import hashlib
import re
from collections import Counter

from agent_bid_rigging.models import ExtractedSignals, LoadedDocument

PHONE_RE = re.compile(r"(?<!\d)(?:1[3-9]\d{9}|0\d{2,3}-?\d{7,8})(?!\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
BANK_RE = re.compile(r"(?<!\d)\d{12,24}(?!\d)")
PRICE_INLINE_RE = re.compile(
    r"(?:投标报价|总报价|报价金额|投标总价|含税总价|不含税总价)\s*[:：]?\s*([0-9][0-9,]*(?:\.\d+)?)"
)
PRICE_TABLE_ANCHOR_RE = re.compile(r"(?:开标一览表|报价表|投标总报价（元）|投标总报价)")
FORMATTED_AMOUNT_RE = re.compile(r"([1-9]\d{0,2}(?:,\d{3})+(?:\.\d+)?)")
LEGAL_REP_RE = re.compile(r"(?:法定代表人|法人代表|法定代表)\s*[:：]?\s*([^\n，,；;]{2,20})")
ADDRESS_RE = re.compile(r"(?:地址|联系地址|办公地址)\s*[:：]?\s*([^\n]{6,80})")
GENERIC_LINE_PATTERNS = (
    "内蒙古自治区政府采购云平台",
    "法定代表人身份证",
    "授权委托人身份证",
    "身份证扫描件",
    "法定代表人授权委托书",
    "法定代表人身份证明",
    "签字并盖章",
    "投标文件格式",
    "中型、小型、微型企业",
    "请在投标文件中附此函",
    "没有重大违法记录的书面声明",
    "项目组成人员操作",
    "培训课程",
    "信息化管理方法论",
    "具体经营项目以相关部门",
)
GENERIC_LEGAL_VALUES = {
    "签字的",
    "身份证明",
    "法定代表人",
    "授权委托人",
}


def extract_signals(
    document: LoadedDocument,
    tender_lines: set[str] | None = None,
) -> ExtractedSignals:
    text = document.text
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    normalized_lines = [_normalize_line(line) for line in lines]
    tender_lines = tender_lines or set()
    line_ref_map = _build_line_ref_map(document.metadata.get("line_references", []))

    non_tender_lines = [
        line
        for line in normalized_lines
        if line and len(line) >= 8 and line not in tender_lines
    ]
    candidate_overlap_lines = [
        line for line in non_tender_lines if _is_candidate_overlap_line(line)
    ]
    candidate_overlap_refs = {
        line: line_ref_map.get(line, [])[:5]
        for line in candidate_overlap_lines
        if line_ref_map.get(line)
    }
    rare_lines = {
        hashlib.sha1(line.encode("utf-8")).hexdigest()[:12]: line
        for line, count in Counter(candidate_overlap_lines).items()
        if count == 1 and _is_informative_line(line)
    }

    return ExtractedSignals(
        document=document,
        text_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        line_count=len(lines),
        token_count=len(re.findall(r"\S+", text)),
        bid_amounts=_extract_amounts(text),
        phones=sorted(set(PHONE_RE.findall(text))),
        emails=sorted(set(match.lower() for match in EMAIL_RE.findall(text))),
        bank_accounts=sorted(set(BANK_RE.findall(text))),
        legal_representatives=sorted(
            set(_filter_legal_representatives(_clean_group(LEGAL_REP_RE.findall(text))))
        ),
        addresses=sorted(set(_clean_group(ADDRESS_RE.findall(text)))),
        non_tender_lines=non_tender_lines,
        rare_line_fingerprints=rare_lines,
        candidate_overlap_lines=candidate_overlap_lines,
        candidate_overlap_refs=candidate_overlap_refs,
    )


def build_tender_baseline(document: LoadedDocument) -> set[str]:
    return {
        _normalize_line(line)
        for line in document.text.splitlines()
        if _normalize_line(line)
    }


def _extract_amounts(text: str) -> list[float]:
    amounts: list[float] = []
    for match in PRICE_INLINE_RE.findall(text):
        value = _parse_amount(match)
        if value is not None:
            amounts.append(value)

    for anchor in PRICE_TABLE_ANCHOR_RE.finditer(text):
        window = text[anchor.start() : anchor.start() + 400]
        table_amounts = [
            value
            for raw in FORMATTED_AMOUNT_RE.findall(window)
            if (value := _parse_amount(raw)) is not None
        ]
        if table_amounts:
            amounts.append(max(table_amounts))

    deduped: list[float] = []
    for amount in amounts:
        if amount not in deduped:
            deduped.append(amount)
    return deduped


def _parse_amount(raw: str) -> float | None:
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        return None
    if value < 1000:
        return None
    return value


def _clean_group(values: list[str]) -> list[str]:
    return [value.strip(" ：:;；,.，") for value in values if value.strip()]


def _filter_legal_representatives(values: list[str]) -> list[str]:
    filtered: list[str] = []
    for value in values:
        if value in GENERIC_LEGAL_VALUES:
            continue
        if any(token in value for token in ("签字", "身份证", "授权", "盖章")):
            continue
        filtered.append(value)
    return filtered


def _normalize_line(line: str) -> str:
    line = re.sub(r"\s+", " ", line.strip())
    line = line.replace("（", "(").replace("）", ")")
    return line


def _is_informative_line(line: str) -> bool:
    if len(line) < 8:
        return False
    if len(set(line)) <= 2:
        return False
    return any(char.isalpha() or "\u4e00" <= char <= "\u9fff" for char in line)


def _is_candidate_overlap_line(line: str) -> bool:
    if len(line) < 20:
        return False
    if line.startswith("### 文档"):
        return False
    if any(pattern in line for pattern in GENERIC_LINE_PATTERNS):
        return False
    return _is_informative_line(line)


def _build_line_ref_map(line_references: list[dict]) -> dict[str, list[dict]]:
    mapping: dict[str, list[dict]] = {}
    for item in line_references:
        normalized = _normalize_line(str(item.get("normalized_line", "")))
        if not normalized:
            continue
        mapping.setdefault(normalized, []).append(
            {
                "source_document": item.get("source_document"),
                "source_page": item.get("source_page"),
                "source_line": item.get("source_line"),
                "component_index": item.get("component_index"),
                "component_title": item.get("component_title"),
            }
        )
    return mapping
