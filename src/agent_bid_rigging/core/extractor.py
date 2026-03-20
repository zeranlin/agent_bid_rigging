from __future__ import annotations

import hashlib
import re
from collections import Counter

from agent_bid_rigging.models import ExtractedSignals, LoadedDocument

PHONE_RE = re.compile(r"(?<!\d)(?:1[3-9]\d{9}|0\d{2,3}-?\d{7,8})(?!\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
BANK_RE = re.compile(r"(?<!\d)\d{12,24}(?!\d)")
PRICE_RE = re.compile(
    r"(?:投标报价|总报价|报价金额|投标总价|含税总价|不含税总价)\s*[:：]?\s*([0-9][0-9,]*(?:\.\d+)?)"
)
LEGAL_REP_RE = re.compile(r"(?:法定代表人|法人代表|法定代表)\s*[:：]?\s*([^\n，,；;]{2,20})")
ADDRESS_RE = re.compile(r"(?:地址|联系地址|办公地址)\s*[:：]?\s*([^\n]{6,80})")


def extract_signals(
    document: LoadedDocument,
    tender_lines: set[str] | None = None,
) -> ExtractedSignals:
    text = document.text
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    normalized_lines = [_normalize_line(line) for line in lines]
    tender_lines = tender_lines or set()

    non_tender_lines = [
        line
        for line in normalized_lines
        if line and len(line) >= 8 and line not in tender_lines
    ]
    rare_lines = {
        hashlib.sha1(line.encode("utf-8")).hexdigest()[:12]: line
        for line, count in Counter(non_tender_lines).items()
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
        legal_representatives=sorted(set(_clean_group(LEGAL_REP_RE.findall(text)))),
        addresses=sorted(set(_clean_group(ADDRESS_RE.findall(text)))),
        non_tender_lines=non_tender_lines,
        rare_line_fingerprints=rare_lines,
    )


def build_tender_baseline(document: LoadedDocument) -> set[str]:
    return {
        _normalize_line(line)
        for line in document.text.splitlines()
        if _normalize_line(line)
    }


def _extract_amounts(text: str) -> list[float]:
    amounts: list[float] = []
    for match in PRICE_RE.findall(text):
        try:
            amounts.append(float(match.replace(",", "")))
        except ValueError:
            continue
    return amounts


def _clean_group(values: list[str]) -> list[str]:
    return [value.strip(" ：:;；,.，") for value in values if value.strip()]


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
