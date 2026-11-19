"""Document parsing + recursive, sentence-aware chunking with citation metadata."""
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from . import config


@dataclass
class Section:
    text: str
    heading: str = ""
    page: Optional[int] = None


@dataclass
class Chunk:
    text: str
    heading: str = ""
    page: Optional[int] = None


# ---------- parsers ----------

def _group_by_heading(lines) -> List[Section]:
    """lines: iterable of (is_heading, text). Groups body text under the latest heading."""
    sections, heading, buf = [], "", []
    for is_h, text in lines:
        if is_h:
            if buf:
                sections.append(Section("\n".join(buf), heading))
                buf = []
            heading = text.strip()
        elif text.strip():
            buf.append(text)
    if buf:
        sections.append(Section("\n".join(buf), heading))
    return sections


def parse_pdf(data: bytes) -> List[Section]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    out = []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            out.append(Section(text, "", i))
    return out


def parse_docx(data: bytes) -> List[Section]:
    import docx

    d = docx.Document(io.BytesIO(data))
    lines = [
        (p.style is not None and p.style.name.lower().startswith("heading"), p.text)
        for p in d.paragraphs
    ]
    # tables -> pipe-joined rows so tabular facts stay retrievable
    for t in d.tables:
        for row in t.rows:
            lines.append((False, " | ".join(c.text.strip() for c in row.cells)))
    return _group_by_heading(lines)


def parse_html(data: bytes) -> List[Section]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(data, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "noscript"]):
        tag.decompose()
    lines = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "pre"]):
        lines.append((el.name.startswith("h"), el.get_text(" ", strip=True)))
    return _group_by_heading(lines)


def parse_markdown(data: bytes) -> List[Section]:
    text = data.decode("utf-8", errors="ignore")
    lines = []
    for ln in text.splitlines():
        m = re.match(r"^#{1,6}\s+(.*)", ln)
        lines.append((True, m.group(1)) if m else (False, ln))
    return _group_by_heading(lines)


def parse_text(data: bytes) -> List[Section]:
    text = data.decode("utf-8", errors="ignore").strip()
    return [Section(text)] if text else []


def parse_file(filename: str, data: bytes) -> List[Section]:
    ext = Path(filename).suffix.lower()
    if ext not in config.ALLOWED_EXT:
        raise ValueError(f"Unsupported file type: {ext}")
    parser = {
        ".pdf": parse_pdf, ".docx": parse_docx, ".html": parse_html, ".htm": parse_html,
        ".md": parse_markdown, ".markdown": parse_markdown, ".txt": parse_text,
    }[ext]
    sections = parser(data)
    if not sections:
        raise ValueError("No extractable text found (scanned PDF? OCR is out of scope)")
    return sections


# ---------- chunking ----------

_SENT = re.compile(r"(?<=[.!?])\s+")


def _sentences(text: str, size: int) -> List[str]:
    out = []
    for para in re.split(r"\n\s*\n", text):
        para = re.sub(r"[ \t]+", " ", para).strip()
        if not para:
            continue
        for s in _SENT.split(para):
            s = s.strip()
            while len(s) > size:  # hard split very long "sentences"
                cut = s.rfind(" ", 0, size)
                cut = cut if cut > size // 2 else size
                out.append(s[:cut].strip())
                s = s[cut:].strip()
            if s:
                out.append(s)
    return out


def split_text(text: str, size: int = None, overlap: int = None) -> List[str]:
    size = size or config.CHUNK_SIZE
    overlap = config.CHUNK_OVERLAP if overlap is None else overlap
    sents = _sentences(text, size)
    chunks, cur, cur_len = [], [], 0
    for s in sents:
        if cur and cur_len + len(s) + 1 > size:
            chunks.append(" ".join(cur))
            # carry trailing sentences as overlap
            carry, n = [], 0
            for prev in reversed(cur):
                if n + len(prev) > overlap:
                    break
                carry.insert(0, prev)
                n += len(prev) + 1
            cur, cur_len = carry, n
        cur.append(s)
        cur_len += len(s) + 1
    if cur:
        tail = " ".join(cur)
        if not chunks or tail != chunks[-1]:
            chunks.append(tail)
    return chunks


def chunk_sections(sections: List[Section]) -> List[Chunk]:
    out = []
    for sec in sections:
        for piece in split_text(sec.text):
            if len(piece.strip()) >= 20:
                out.append(Chunk(piece, sec.heading, sec.page))
    return out
