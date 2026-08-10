from __future__ import annotations

import html
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree


def load_audiobook_source(path: Path) -> str:
    source = Path(path)
    suffix = source.suffix.casefold()
    if suffix in {".txt", ".md"}:
        return source.read_text(encoding="utf-8-sig")
    if suffix == ".epub":
        return _load_epub(source)
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as error:
            raise RuntimeError("Đọc PDF cần cài thêm: pip install pypdf") from error
        pages = [str(page.extract_text() or "").strip() for page in PdfReader(source).pages]
        return "\n\n".join(page for page in pages if page)
    raise ValueError(f"Định dạng audiobook chưa hỗ trợ: {source.suffix}")


def _load_epub(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
        rootfile = next(
            element.attrib["full-path"]
            for element in container.iter()
            if element.tag.endswith("rootfile")
        )
        opf = ElementTree.fromstring(archive.read(rootfile))
        manifest = {
            item.attrib.get("id", ""): item.attrib.get("href", "")
            for item in opf.iter()
            if item.tag.endswith("item")
        }
        spine = [
            item.attrib.get("idref", "")
            for item in opf.iter()
            if item.tag.endswith("itemref")
        ]
        base = Path(rootfile).parent
        chapters: list[str] = []
        for item_id in spine:
            href = manifest.get(item_id)
            if not href:
                continue
            parser = _EpubTextParser()
            parser.feed(archive.read((base / href).as_posix()).decode("utf-8", errors="replace"))
            text = parser.text()
            if text:
                chapters.append(text)
    if not chapters:
        raise ValueError("EPUB không chứa chương văn bản có thể đọc.")
    return "\n\n".join(chapters)


class _EpubTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.heading = False

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.casefold()
        if lowered in {"h1", "h2", "h3"}:
            self.parts.append("\n# ")
            self.heading = True
        elif lowered in {"p", "div", "br", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"h1", "h2", "h3"}:
            self.heading = False
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        cleaned = re.sub(r"\s+", " ", html.unescape(data)).strip()
        if cleaned:
            self.parts.append(cleaned + ("" if self.heading else " "))

    def text(self) -> str:
        lines = [line.strip() for line in "".join(self.parts).splitlines()]
        return "\n".join(line for line in lines if line).strip()
