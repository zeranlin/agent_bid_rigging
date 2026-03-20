from __future__ import annotations

import json
import re
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from agent_bid_rigging.models import LoadedDocument


def load_document(name: str, role: str, path: str) -> LoadedDocument:
    file_path = Path(path).expanduser().resolve()
    suffix = file_path.suffix.lower()

    if suffix in {".txt", ".md"}:
        text = file_path.read_text(encoding="utf-8")
        parser = "plain-text"
    elif suffix == ".json":
        raw = json.loads(file_path.read_text(encoding="utf-8"))
        text = json.dumps(raw, ensure_ascii=False, indent=2)
        parser = "json"
    elif suffix == ".docx":
        text = _read_docx(file_path)
        parser = "docx-ooxml"
    elif suffix == ".pdf":
        text = _read_pdf(file_path)
        parser = "pdftotext"
    else:
        raise ValueError(f"Unsupported document format: {file_path.suffix}")

    metadata = {
        "size_bytes": file_path.stat().st_size,
        "suffix": suffix,
    }
    return LoadedDocument(
        name=name,
        role=role,
        path=str(file_path),
        parser=parser,
        text=_normalize_text(text),
        metadata=metadata,
    )


def _read_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    paragraphs: list[str] = []
    current: list[str] = []
    for element in root.iter():
        tag = _strip_namespace(element.tag)
        if tag == "t" and element.text:
            current.append(element.text)
        elif tag == "p":
            if current:
                paragraphs.append("".join(current))
            current = []
    if current:
        paragraphs.append("".join(current))
    return "\n".join(paragraphs)


def _read_pdf(path: Path) -> str:
    result = subprocess.run(
        ["pdftotext", "-layout", "-nopgbrk", str(path), "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Failed to extract PDF text with pdftotext. Install poppler and retry."
        )
    return result.stdout


def _strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
