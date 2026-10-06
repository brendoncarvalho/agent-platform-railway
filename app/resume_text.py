"""
Resume Text Extraction
======================

Pure helpers that turn resume bytes (PDF, DOCX, plain text) into clean text.
No agno imports and no I/O besides parsing the bytes handed in.

- DOCX: stdlib only (zipfile + ElementTree). Walks the WordprocessingML tree in
  document order, so tables, content controls, text boxes, tracked insertions,
  hyperlink targets, headers and footers are all captured. Runs formatted as
  hidden (or in a font of 2pt or less) are left out and reported as a warning.
- PDF: pypdf, imported lazily so a missing wheel can never break app start-up.
  No OCR: a scanned PDF is reported as such instead of returning empty text.
  Filled form fields are appended; stream size and extraction time are capped.
- Text: UTF-16 BOM / UTF-8 / cp1252 / latin-1 decoding chain.
"""

import codecs
import io
import logging
import re
import time
import unicodedata
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree

MAX_FILE_BYTES = 15 * 1024 * 1024
MAX_XML_PART_BYTES = 8 * 1024 * 1024
MAX_HEADER_FOOTER_PARTS = 6
MAX_PDF_PAGES = 30
# What a single PDF stream may inflate to, and how long one PDF may take to extract.
MAX_PDF_STREAM_BYTES = 8 * 1024 * 1024
MAX_PDF_SECONDS = 20.0
MAX_TEXT_CHARS = 60_000
# A PDF page with fewer visible characters than this is treated as having no usable text layer.
MIN_PDF_CHARS_PER_PAGE = 80
# Font size (in half-points) at or below which a DOCX run counts as hidden text.
HIDDEN_FONT_HALF_POINTS = 4
HIDDEN_SNIPPET_CHARS = 200

_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_W_NAMESPACES = frozenset(
    {
        "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "http://purl.oclc.org/ooxml/wordprocessingml/main",  # ISO "Strict" flavour
    }
)
_MC_NAMESPACE = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_DOCX_BLOCKS = frozenset({"p", "tbl"})
_DOCX_ROWS = frozenset({"tr"})
_DOCX_CELLS = frozenset({"tc"})
# Elements that only wrap real content: content controls, tracked insertions/moves, smart tags.
_DOCX_WRAPPERS = frozenset({"sdt", "sdtContent", "ins", "moveTo", "customXml", "smartTag"})
_DOCX_SKIPPED = frozenset({"pPr", "rPr", "del", "moveFrom", "instrText", "delText"})
_DOCX_FALSE = frozenset({"0", "false", "off"})

_TRANSLATION = str.maketrans(
    {
        0xFB00: "ff",  # Latin ligatures emitted by PDF fonts
        0xFB01: "fi",
        0xFB02: "fl",
        0xFB03: "ffi",
        0xFB04: "ffl",
        0x00A0: " ",  # no-break space
        0x00AD: "",  # soft hyphen
        0x000B: "\n",  # vertical tab
        0x000C: "\n",  # form feed
    }
)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0e-\x1f\x7f]")
_SPACE_RUNS = re.compile(r"[ \t]+")
_BLANK_RUNS = re.compile(r"\n{3,}")


class ResumeExtractionError(Exception):
    """Extraction failed for a reason worth relaying to the user. `str(exc)` is a pt-BR message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ResumeText:
    kind: str  # "pdf" | "docx" | "text"
    text: str
    warnings: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------
def normalize_text(text: str) -> str:
    """NFC-normalise, drop control chars (NUL breaks Postgres JSONB), collapse space and blank-line runs."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").translate(_TRANSLATION)
    text = unicodedata.normalize("NFC", text)
    text = _CONTROL_CHARS.sub("", text)
    text = text.encode("utf-8", "ignore").decode("utf-8")  # drops lone surrogates
    text = "\n".join(_SPACE_RUNS.sub(" ", line).strip() for line in text.split("\n"))
    return _BLANK_RUNS.sub("\n\n", text).strip()


def _visible_chars(text: str) -> int:
    return sum(1 for char in text if not char.isspace())


def sniff_kind(data: bytes) -> str:
    """Classify by content, never by file name: pdf, docx, zip, broken-zip, ole, rtf, text or binary."""
    if b"%PDF-" in data[:1024]:
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as package:
                names = package.namelist()
        except (zipfile.BadZipFile, ValueError, RuntimeError, OSError):  # ValueError: undecodable entry name
            return "broken-zip"
        return "docx" if any(name.startswith("word/") for name in names) else "zip"
    if data.startswith(_OLE2_MAGIC):
        return "ole"  # legacy .doc, or a password-protected .docx
    if data[:64].lstrip().startswith(b"{\\rtf"):
        return "rtf"
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) or b"\x00" not in data[:8192]:
        return "text"
    return "binary"


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------
def decode_text(data: bytes) -> str:
    """Decode text bytes: UTF-16 BOM, then UTF-8 (BOM tolerated), then cp1252, then latin-1."""
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", errors="replace")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------
def _docx_name(element: ElementTree.Element) -> str:
    """'{w-namespace}p' -> 'p', '{mc-namespace}Choice' -> 'mc:Choice', anything else -> ''."""
    tag = element.tag
    if not isinstance(tag, str) or not tag.startswith("{"):
        return ""
    namespace, _, local = tag[1:].partition("}")
    if namespace in _W_NAMESPACES:
        return local
    if namespace == _MC_NAMESPACE:
        return f"mc:{local}"
    return ""


def _docx_attr(element: ElementTree.Element, local_name: str) -> str | None:
    """Value of the attribute with this local name, whatever its namespace."""
    for key, value in element.attrib.items():
        if key == local_name or key.endswith("}" + local_name):
            return value
    return None


def _docx_alternate(element: ElementTree.Element) -> ElementTree.Element | None:
    """mc:AlternateContent carries the same content twice; take mc:Choice, else mc:Fallback."""
    for wanted in ("mc:Choice", "mc:Fallback"):
        for child in element:
            if _docx_name(child) == wanted:
                return child
    return None


def _docx_children(parent: ElementTree.Element, wanted: frozenset[str]) -> Iterator[ElementTree.Element]:
    """Children named in `wanted`, looking through wrappers (w:sdt, w:ins, ...) and mc:AlternateContent."""
    for child in parent:
        name = _docx_name(child)
        if name in wanted:
            yield child
        elif name in _DOCX_WRAPPERS:
            yield from _docx_children(child, wanted)
        elif name == "mc:AlternateContent":
            branch = _docx_alternate(child)
            if branch is not None:
                yield from _docx_children(branch, wanted)


def _docx_run_hiding(run: ElementTree.Element) -> str:
    """How the run's own formatting hides it: 'vanish' (w:vanish), 'tiny' (font of 2pt or less) or ''.

    w:webHidden is not hiding: it only applies to Web Layout view and Word writes it on every TOC page number.
    """
    hiding = ""
    for child in run:
        if _docx_name(child) != "rPr":
            continue
        for prop in child:
            name = _docx_name(prop)
            value = (_docx_attr(prop, "val") or "").strip().lower()
            if name == "vanish" and value not in _DOCX_FALSE:
                return "vanish"
            if name == "sz" and value.isdigit() and int(value) <= HIDDEN_FONT_HALF_POINTS:
                hiding = "tiny"
    return hiding


def _docx_strip_hidden_runs(root: ElementTree.Element, hidden: list[str]) -> None:
    """Blank the text of hidden runs so it cannot count as resume content; keep it in `hidden` for reporting.

    One pass over the tree. A run's font size only affects its own w:t children (a text box anchored in the
    run has its own formatting), while w:vanish also hides whatever is anchored in the run.
    """
    stack: list[tuple[ElementTree.Element, bool]] = [(root, False)]
    while stack:
        element, vanished = stack.pop()
        if _docx_name(element) == "r":
            hiding = _docx_run_hiding(element)
            vanished = vanished or hiding == "vanish"
            if vanished or hiding:
                for node in element:
                    if _docx_name(node) == "t" and node.text and node.text.strip():
                        hidden.append(node.text)
                        node.text = ""
        stack.extend((child, vanished) for child in reversed(element))


def _docx_inline(node: ElementTree.Element, links: dict[str, str], parts: list[str], anchored: list[str]) -> None:
    """Collect the text of one paragraph into `parts`; text boxes anchored to it go to `anchored`."""
    for child in node:
        name = _docx_name(child)
        if name == "t":
            parts.append(child.text or "")
        elif name in ("tab", "ptab"):
            parts.append("\t")
        elif name in ("br", "cr"):
            parts.append("\n")
        elif name == "noBreakHyphen":
            parts.append("-")
        elif name in _DOCX_SKIPPED:
            continue
        elif name == "txbxContent":
            anchored.extend(_docx_blocks(child, links))
        elif name == "mc:AlternateContent":
            branch = _docx_alternate(child)
            if branch is not None:
                _docx_inline(branch, links, parts, anchored)
        elif name == "hyperlink":
            start = len(parts)
            _docx_inline(child, links, parts, anchored)
            url = links.get(_docx_attr(child, "id") or "", "")
            if url and url.removeprefix("mailto:") not in "".join(parts[start:]):
                parts.append(f" <{url}>")
        else:  # w:r, inline w:sdt, w:ins, w:smartTag, w:fldSimple, w:drawing, w:pict, ...
            _docx_inline(child, links, parts, anchored)


def _docx_is_list_item(paragraph: ElementTree.Element) -> bool:
    for child in paragraph:
        if _docx_name(child) == "pPr":
            return any(_docx_name(prop) == "numPr" for prop in child)
    return False


def _docx_paragraph(paragraph: ElementTree.Element, links: dict[str, str]) -> list[str]:
    parts: list[str] = []
    anchored: list[str] = []
    _docx_inline(paragraph, links, parts, anchored)
    text = "".join(parts).strip()
    if text and _docx_is_list_item(paragraph):
        text = f"- {text}"
    return ([text] if text else []) + anchored


def _docx_row(cells: list[list[str]]) -> list[str]:
    """Data rows become 'a | b | c'; layout rows (multi-paragraph cells) are emitted cell by cell."""
    if not any(cells):
        return []
    if all(len(cell) <= 1 for cell in cells):
        return [" | ".join(cell[0].replace("\n", " / ") if cell else "" for cell in cells).rstrip(" |")]
    lines: list[str] = []
    for cell in cells:
        if cell:
            lines.extend([*cell, ""])
    return lines


def _docx_table(table: ElementTree.Element, links: dict[str, str]) -> list[str]:
    lines: list[str] = []
    for row in _docx_children(table, _DOCX_ROWS):
        lines.extend(_docx_row([_docx_blocks(cell, links) for cell in _docx_children(row, _DOCX_CELLS)]))
    return lines


def _docx_blocks(container: ElementTree.Element, links: dict[str, str]) -> list[str]:
    """Paragraphs and tables of a body / cell / text box / header, in document order."""
    lines: list[str] = []
    for block in _docx_children(container, _DOCX_BLOCKS):
        if _docx_name(block) == "p":
            lines.extend(_docx_paragraph(block, links))
        else:
            lines.extend(_docx_table(block, links))
    return lines


def _zip_xml(package: zipfile.ZipFile, name: str) -> ElementTree.Element:
    info = package.getinfo(name)
    if info.file_size > MAX_XML_PART_BYTES:
        raise ResumeExtractionError("too_large", "O documento Word é grande demais para ser processado.")
    if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):  # others inflate with no output cap
        raise ResumeExtractionError("unsupported", "O arquivo não é um documento Word (.docx) válido.")
    # The declared size is attacker-controlled and package.read() inflates the whole stream before
    # truncating to it; a bounded read keeps the inflated output capped.
    with package.open(info) as handle:
        payload = handle.read(MAX_XML_PART_BYTES + 1)
    if len(payload) > MAX_XML_PART_BYTES:
        raise ResumeExtractionError("too_large", "O documento Word é grande demais para ser processado.")
    # OOXML never needs a DTD; refuse entity tricks. A UTF-16 part spells the same markup with NUL bytes between.
    probe = payload.replace(b"\x00", b"")
    if b"<!DOCTYPE" in probe or b"<!ENTITY" in probe:
        raise ResumeExtractionError("corrupt", "O documento Word contém XML inválido.")
    return ElementTree.fromstring(payload)


def _docx_main_part(package: zipfile.ZipFile, names: set[str]) -> str:
    if "_rels/.rels" in names:
        for relationship in _zip_xml(package, "_rels/.rels"):
            target = relationship.get("Target", "").lstrip("/")
            if relationship.get("Type", "").endswith("/officeDocument") and target in names:
                return target
    if "word/document.xml" in names:
        return "word/document.xml"
    raise ResumeExtractionError("unsupported", "O arquivo não é um documento Word (.docx) válido.")


def _docx_part_lines(package: zipfile.ZipFile, names: set[str], part: str, hidden: list[str]) -> list[str]:
    folder, _, base = part.rpartition("/")
    rels = f"{folder}/_rels/{base}.rels" if folder else f"_rels/{base}.rels"
    links: dict[str, str] = {}
    if rels in names:
        for relationship in _zip_xml(package, rels):
            if relationship.get("TargetMode") == "External" and relationship.get("Type", "").endswith("/hyperlink"):
                links[relationship.get("Id", "")] = relationship.get("Target", "")
    root = _zip_xml(package, part)
    _docx_strip_hidden_runs(root, hidden)
    if _docx_name(root) in ("hdr", "ftr"):
        return _docx_blocks(root, links)
    lines: list[str] = []
    for child in root:
        if _docx_name(child) == "body":
            lines.extend(_docx_blocks(child, links))
    return lines


def extract_docx_text(data: bytes) -> tuple[str, str]:
    """Text of a .docx in reading order (headers, body, footers), plus any text found in hidden runs."""
    hidden: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            names = set(package.namelist())
            main = _docx_main_part(package, names)
            folder = main.rpartition("/")[0]
            prefix = f"{re.escape(folder)}/" if folder else ""
            sections: dict[str, list[str]] = {"header": [], "footer": []}
            for kind, lines in sections.items():
                seen: set[str] = set()
                parts = [name for name in sorted(names) if re.fullmatch(rf"{prefix}{kind}\d*\.xml", name)]
                for name in parts[:MAX_HEADER_FOOTER_PARTS]:
                    for line in _docx_part_lines(package, names, name, hidden):
                        if line not in seen:  # default / first-page / even-page parts often repeat
                            seen.add(line)
                            lines.append(line)
            body = _docx_part_lines(package, names, main, hidden)
    except ResumeExtractionError:
        raise
    except Exception as exc:  # zipfile also raises zlib.error, RuntimeError, NotImplementedError, EOFError, ...
        raise ResumeExtractionError("corrupt", "Não foi possível ler o documento Word (arquivo corrompido).") from exc
    text = normalize_text("\n".join([*sections["header"], "", *body, "", *sections["footer"]]))
    return text, normalize_text(" ".join(hidden))


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def _pdf_page_has_image(page: Any) -> bool:
    """True when the page draws an image (what a scanned page is made of). Unknown counts as yes."""
    try:
        return len(page.images) > 0  # ids only, nothing is decoded
    except Exception:
        return True


def _pdf_form_lines(reader: Any) -> list[str]:
    """'field: value' for a filled AcroForm: typed answers live in the fields, not in the page text."""
    try:
        fields = reader.get_fields() or {}
    except Exception:
        return []
    lines: list[str] = []
    for name, entry in fields.items():
        value = entry.get("/V")
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value)
        if isinstance(value, str) and value.strip() and value != "/Off":
            lines.append(f"{name}: {value.removeprefix('/')}")
    return lines


class _PdfBudgetExceeded(Exception):
    """Raised from pypdf's operand visitor once a PDF has used up its time budget."""


@dataclass
class PdfContent:
    pages: list[str]  # text per page read; "" = nothing extracted
    page_count: int = 0  # pages in the file (can exceed len(pages))
    scanned: list[int] = field(default_factory=list)  # page numbers with next to no text and an image
    failed: list[int] = field(default_factory=list)  # page numbers pypdf could not process
    form_lines: list[str] = field(default_factory=list)  # "field: value" of a filled form
    timed_out: bool = False


def extract_pdf_content(data: bytes, max_pages: int = MAX_PDF_PAGES) -> PdfContent:
    """Per-page text of a PDF, with the pages that look scanned, the pages that failed and the form fields."""
    try:
        from pypdf import PdfReader, apply_configuration
    except ImportError as exc:
        raise ResumeExtractionError(
            "missing_dependency", "Leitura de PDF indisponível: a biblioteca `pypdf` não está instalada no servidor."
        ) from exc

    logging.getLogger("pypdf").setLevel(logging.ERROR)  # malformed-but-readable PDFs are noisy
    deadline = time.monotonic() + MAX_PDF_SECONDS

    def within_budget(*_: object) -> None:
        if time.monotonic() > deadline:
            raise _PdfBudgetExceeded

    content = PdfContent(pages=[])
    try:
        # Content streams come from the candidate: cap what a single stream may inflate to (pypdf allows
        # 75 MB by default, interpreted in pure Python) and stop once the file has used its time budget.
        with apply_configuration(
            zlib_maximum_output_length=MAX_PDF_STREAM_BYTES,
            lzw_maximum_output_length=MAX_PDF_STREAM_BYTES,
            run_length_maximum_output_length=MAX_PDF_STREAM_BYTES,
            array_based_stream_maximum_output_length=MAX_PDF_STREAM_BYTES,
        ):
            reader = PdfReader(io.BytesIO(data))
            # Many PDFs are "encrypted" with a blank user password (print/copy restrictions only);
            # decrypt("") opens those. Anything else needs a password we never ask for.
            if reader.is_encrypted and not reader.decrypt(""):
                raise ResumeExtractionError(
                    "encrypted",
                    "O PDF está protegido por senha. Envie uma versão sem senha ou cole o texto do currículo.",
                )
            content.page_count = len(reader.pages)
            for number in range(1, min(content.page_count, max_pages) + 1):
                if time.monotonic() > deadline:
                    content.timed_out = True
                    break
                try:
                    page = reader.pages[number - 1]
                    text = normalize_text(page.extract_text(visitor_operand_before=within_budget) or "")
                    looks_scanned = _visible_chars(text) < MIN_PDF_CHARS_PER_PAGE and _pdf_page_has_image(page)
                except _PdfBudgetExceeded:
                    content.timed_out = True
                    break
                except Exception:  # one broken page must not sink the whole resume
                    content.pages.append("")
                    content.failed.append(number)
                    continue
                content.pages.append(text)
                if looks_scanned:
                    content.scanned.append(number)
            if not content.timed_out:
                content.form_lines = _pdf_form_lines(reader)
    except ResumeExtractionError:
        raise
    except Exception as exc:  # pypdf raises many types on corrupt input (and DependencyError for AES without a backend)
        raise ResumeExtractionError(
            "corrupt", f"Não foi possível ler o PDF (arquivo corrompido ou não suportado): {type(exc).__name__}."
        ) from exc
    return content


def _looks_garbled(text: str) -> bool:
    """Fonts without a Unicode map extract as symbol soup; flag it instead of analysing nonsense."""
    visible = [char for char in text if not char.isspace()]
    if len(visible) < 200:
        return False
    readable = sum(1 for char in visible if char.isalnum())
    return readable / len(visible) < 0.5 or text.count(chr(0xFFFD)) / len(visible) > 0.05


def _page_numbers(numbers: list[int]) -> str:
    return ", ".join(str(number) for number in numbers)


def _extract_pdf_text(data: bytes, warnings: list[str]) -> str:
    content = extract_pdf_content(data)
    pages = content.pages
    text = "\n\n".join(page for page in pages if page)
    if content.form_lines:
        fields = "\n".join(content.form_lines)
        text = normalize_text(f"{text}\n\nCampos de formulário preenchidos no PDF:\n{fields}")
    if not text and (content.timed_out or content.failed):
        raise ResumeExtractionError(
            "unreadable",
            "Não foi possível extrair o texto do PDF (arquivo complexo demais ou danificado). "
            "Envie o currículo em DOCX ou cole o texto.",
        )
    # Scanned = nothing readable at all, or every page is an image with next to no text. A short page
    # without an image (spill-over last page, cover, blank trailing page) is just a short page.
    if not text or (len(content.scanned) == len(pages) and not content.form_lines):
        raise ResumeExtractionError(
            "no_text_layer",
            "O PDF não tem camada de texto (provavelmente é um currículo digitalizado/escaneado) e este agente "
            "não faz OCR. Envie o arquivo original (PDF exportado do editor de texto ou DOCX) "
            "ou cole o texto do currículo.",
        )
    if content.scanned:
        warnings.append(
            f"Páginas com pouco ou nenhum texto extraível (podem ser digitalizadas): {_page_numbers(content.scanned)}."
        )
    if content.failed:
        warnings.append(
            f"Páginas que não puderam ser lidas (complexas demais ou danificadas): {_page_numbers(content.failed)}."
        )
    if content.timed_out:
        warnings.append(
            "A leitura foi interrompida por tempo de processamento: "
            f"apenas {len(pages)} de {content.page_count} páginas foram lidas."
        )
    elif content.page_count > len(pages):
        warnings.append(f"Apenas {len(pages)} de {content.page_count} páginas foram lidas.")
    if _looks_garbled(text):
        warnings.append("O texto extraído parece ilegível (fonte sem mapeamento Unicode); pode ser necessário OCR.")
    return text


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def extract_resume_text(data: bytes, *, max_chars: int = MAX_TEXT_CHARS) -> ResumeText:
    """Turn resume bytes into text. Raises ResumeExtractionError (pt-BR message) when it cannot."""
    if not data or not data.strip():
        raise ResumeExtractionError("empty", "O arquivo está vazio.")
    if len(data) > MAX_FILE_BYTES:
        raise ResumeExtractionError("too_large", "O arquivo excede o limite de 15 MB para currículos.")

    kind = sniff_kind(data)
    warnings: list[str] = []

    if kind == "pdf":
        text = _extract_pdf_text(data, warnings)
    elif kind == "docx":
        text, hidden = extract_docx_text(data)
        if hidden:
            snippet = hidden[:HIDDEN_SNIPPET_CHARS] + ("…" if len(hidden) > HIDDEN_SNIPPET_CHARS else "")
            warnings.append(
                "O arquivo contém texto com formatação oculta (invisível ou em fonte de 2 pt ou menos), "
                f"que foi excluído da leitura. Trecho: «{snippet}»"
            )
    elif kind == "text":
        text = normalize_text(decode_text(data))
    elif kind == "ole":
        raise ResumeExtractionError(
            "unsupported",
            "Arquivo Word no formato antigo (.doc) ou protegido por senha não é suportado. "
            "Salve como .docx ou PDF e envie novamente.",
        )
    elif kind == "rtf":
        raise ResumeExtractionError(
            "unsupported", "Arquivos RTF não são suportados. Salve como .docx ou PDF e envie novamente."
        )
    elif kind == "broken-zip":
        raise ResumeExtractionError("corrupt", "O arquivo está corrompido ou incompleto. Envie novamente.")
    else:
        raise ResumeExtractionError(
            "unsupported", "Formato de arquivo não suportado. Envie o currículo em PDF, DOCX ou texto."
        )

    if not text:
        raise ResumeExtractionError("empty", "Nenhum texto foi encontrado no arquivo.")
    if len(text) > max_chars:
        text = text[:max_chars].rstrip()
        warnings.append(f"Texto truncado em {max_chars} caracteres.")
    return ResumeText(kind=kind, text=text, warnings=tuple(warnings))
