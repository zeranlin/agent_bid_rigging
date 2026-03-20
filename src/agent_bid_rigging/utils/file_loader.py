from __future__ import annotations

import json
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from pypdf import PdfReader

from agent_bid_rigging.models import LoadedDocument

SUPPORTED_SUFFIXES = {".txt", ".md", ".json", ".docx", ".pdf"}


def load_document(name: str, role: str, path: str) -> LoadedDocument:
    file_path = Path(path).expanduser().resolve()
    if file_path.is_dir():
        return _load_collection(name, role, file_path, source_type="directory")

    suffix = file_path.suffix.lower()
    if suffix == ".zip":
        return _load_archive(name, role, file_path)

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
        parser = _pdf_parser_name()
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


def _load_archive(name: str, role: str, path: Path) -> LoadedDocument:
    temp_dir = Path(tempfile.mkdtemp(prefix="agent_bid_rigging_archive_"))
    with zipfile.ZipFile(path) as archive:
        archive.extractall(temp_dir)
    loaded = _load_collection(name, role, temp_dir, source_type="zip-archive")
    loaded.path = str(path)
    loaded.metadata["archive_extracted_to"] = str(temp_dir)
    loaded.metadata["archive_name"] = path.name
    return loaded


def _load_collection(name: str, role: str, root: Path, source_type: str) -> LoadedDocument:
    files = [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and _should_ingest(path)
    ]
    if not files:
        raise ValueError(f"No supported documents found under: {root}")

    sections: list[str] = []
    components: list[dict[str, str | int]] = []
    for index, path in enumerate(files, start=1):
        suffix = path.suffix.lower()
        if suffix in {".txt", ".md"}:
            text = path.read_text(encoding="utf-8")
            parser = "plain-text"
        elif suffix == ".json":
            raw = json.loads(path.read_text(encoding="utf-8"))
            text = json.dumps(raw, ensure_ascii=False, indent=2)
            parser = "json"
        elif suffix == ".docx":
            text = _read_docx(path)
            parser = "docx-ooxml"
        elif suffix == ".pdf":
            text = _read_pdf(path)
            parser = _pdf_parser_name()
        else:
            continue

        normalized = _normalize_text(text)
        if not normalized:
            continue

        display_name = _safe_display_name(path, index)
        sections.append(f"### 文档{index}: {display_name}\n{normalized}")
        components.append(
            {
                "index": index,
                "display_name": display_name,
                "relative_path": _safe_relpath(path, root),
                "suffix": suffix,
                "parser": parser,
                "chars": len(normalized),
            }
        )

    if not sections:
        raise ValueError(f"No extractable text found under: {root}")

    return LoadedDocument(
        name=name,
        role=role,
        path=str(root),
        parser=source_type,
        text="\n\n".join(sections),
        metadata={
            "source_type": source_type,
            "component_count": len(components),
            "components": components,
        },
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
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", "-nopgbrk", str(path), "-"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except FileNotFoundError:
        pass
    return _read_pdf_with_pypdf(path)


def _read_pdf_with_pypdf(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _pdf_parser_name() -> str:
    try:
        result = subprocess.run(
            ["pdftotext", "-v"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return "pdftotext"
    except FileNotFoundError:
        pass
    return "pypdf"


def _strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _should_ingest(path: Path) -> bool:
    if path.name.startswith("._"):
        return False
    if "__MACOSX" in path.parts:
        return False
    return path.suffix.lower() in SUPPORTED_SUFFIXES


def _safe_display_name(path: Path, index: int) -> str:
    name = path.stem.strip()
    if _looks_readable(name):
        return name
    return f"文档{index}{path.suffix.lower()}"


def _safe_relpath(path: Path, root: Path) -> str:
    rel_path = str(path.relative_to(root))
    if _looks_readable(rel_path):
        return rel_path
    return f"文档{path.suffix.lower()}"


def _looks_readable(text: str) -> bool:
    if not text:
        return False
    total = 0
    readable = 0
    for char in text:
        if char.isspace():
            continue
        total += 1
        if char.isalnum() or "\u4e00" <= char <= "\u9fff" or char in "-_().（）[]【】":
            readable += 1
    return total > 0 and readable / total >= 0.65
