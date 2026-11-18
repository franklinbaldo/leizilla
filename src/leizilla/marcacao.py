"""The marked document ("documento marcado"): preserved text with tags inserted.

A second XML layer next to Leizilla XML v0.1 (docs/SCHEMA.md §4), which stays as it is.
v0.1 describes a norm through time (versions, vigência, revogação, sources). The marked
document is the other thing: the raw text of one norm, untouched, with tags inserted
where its parts are. Nothing is rewritten, copied or normalised. Nesting expresses the
hierarchy at any depth (art ⊃ par ⊃ inc ⊃ ali ⊃ item).

The one invariant, checked by `verify`:

    removing every tag (and the content of ``<nota>``) yields the original text,
    character for character, and its sha256 is the one recorded on the root.

The invariant lives on the *parsed* character data, not on the serialized bytes. XML 1.0
cannot carry most C0 controls (form feeds are common between OCR pages), and parsers
rewrite ``\\r\\n`` to ``\\n``; so every code point XML cannot carry or preserve is written as
an empty element ``<c v="0C"/>`` (hex code point) that `strip` restores. ``&``, ``<`` and
``>`` use the ordinary entities.

Offsets are Unicode code points over the text, the unit `ancoras` uses
(`leizilla.textlayer`). The design, the element list and the open choices are in
docs/okf/documento-marcado.md; the grammar is docs/schemas/leizilla-doc-v0.xsd, which
cannot check the invariant or the numbering: `verify` does.

Entry points: `build`, `strip`, `verify`, `parse`, `to_rows` and the adapter from the
sequence reader, `from_hierarchy` / `from_hierarchy_ex`.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from leizilla.hierarchy_sequence import _LEAD, HierarchyReport, Node

VERSION = "0"

# --- vocabulary -------------------------------------------------------------------
# Organisational levels, outermost first (Parte > Livro > Título > Capítulo > Seção >
# Subseção). Declared in the schema; the reader does not emit them yet.
ORG: tuple[str, ...] = ("parte", "liv", "tit", "cap", "sec", "subsec")
DEVICES: tuple[str, ...] = ("art", "par", "inc", "ali", "item")
PARTS: tuple[str, ...] = (
    "epigrafe",
    "ementa",
    "preambulo",
    "fecho",
    "assinatura",
    "anexo",
)
INLINE: tuple[str, ...] = ("ruido", "ref", "nota")
KINDS: frozenset[str] = frozenset(("lei", "alteracao", *ORG, *DEVICES, *PARTS, *INLINE))
STRUCTURAL: frozenset[str] = frozenset((*ORG, *DEVICES))
# Elements that may carry a marker (``<m>``) and the evidence attributes.
ESTADOS: frozenset[str] = frozenset(("vetado", "ausente", "superado"))
# ``estado="superado"``: an older printed version of a device in a compiled act (the
# Casa Civil prints the superseded wording, then the new one with "(Redação dada pela
# Lei ..."). Same ``n`` as the current device, which carries no ``estado``. ADR-0020
# (accepted 2026-11-18); docs/okf/textos-compilados.md.
# ``<ref rel=...>``: the parenthetical official note of a compiled act, as printed.
RELS: frozenset[str] = frozenset(
    ("redacao", "acrescimo", "revogacao", "veto", "vide", "outra")
)

_ORG_RANK = {k: i for i, k in enumerate(ORG)}


def children_allowed(parent: str) -> frozenset[str]:
    """Kinds that may sit directly inside ``parent`` (``"documento"`` is the root).

    Level grammar: art ⊃ par|inc|ali|item; par ⊃ inc|ali|item; inc ⊃ ali|item;
    ali ⊃ item; ``alteracao`` may sit inside any device and holds any device or
    organisational block; ``anexo`` may also sit inside a device (a table between two
    paragraphs of an article: the model's marked documents, see teacher_mark);
    ``ruido``/``ref``/``nota`` anywhere (a ``nota`` holds only its own content). Organisational blocks nest outermost first and hold articles.
    ``lei`` sits only on the root, and devices only inside a ``lei`` (or an
    ``alteracao``/``anexo``).
    """
    if parent == "documento":
        return frozenset(("lei", *PARTS, *INLINE))
    if parent == "lei":
        return frozenset((*ORG, "art", *PARTS, *INLINE))
    if parent in _ORG_RANK:
        lower = ORG[_ORG_RANK[parent] + 1 :]
        return frozenset((*lower, "art", *INLINE))
    if parent in DEVICES:
        below = DEVICES[DEVICES.index(parent) + 1 :]
        return frozenset((*below, "alteracao", "anexo", *INLINE))
    if parent in ("alteracao", "anexo"):
        return frozenset((*ORG, *DEVICES, *INLINE))
    if parent in ("epigrafe", "ementa", "preambulo", "fecho", "assinatura", "ruido"):
        return frozenset(INLINE)
    if parent == "ref":
        return frozenset(("nota",))
    return frozenset()  # nota


# --- model ------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Mark:
    """One element of the marked document, as offsets into the text.

    ``[start, end)`` is the span the element wraps; ``start == end`` is a zero-width
    element (an empty element, or a ``nota``). ``marker`` is the span of the printed
    marker (``<m>``), inside the element; ``None`` when no marker was readable.
    ``note`` is the content of a ``nota`` (the only content that is ours).
    """

    kind: str
    start: int
    end: int
    attrs: dict[str, str] = field(default_factory=dict)
    marker: tuple[int, int] | None = None
    note: str = ""


def describe(mark: Mark) -> str:
    """A short label that names a mark in an error message."""
    extra = ""
    if "n" in mark.attrs:
        extra = f" n={mark.attrs['n']}" + mark.attrs.get("sufixo", "")
    return f"{mark.kind}{extra} [{mark.start}:{mark.end}]"


class MarcacaoError(ValueError):
    """The marks (or the marked document) are not valid."""

    def __init__(
        self, message: str, a: Mark | None = None, b: Mark | None = None
    ) -> None:
        super().__init__(message)
        self.a = a
        self.b = b


class OverlapError(MarcacaoError):
    """Two marks overlap without one containing the other."""


class GrammarError(MarcacaoError):
    """A mark sits where the level grammar does not allow it."""


# --- nesting ----------------------------------------------------------------------
@dataclass(slots=True)
class _Node:
    mark: Mark | None  # None for the root
    children: list[_Node] = field(default_factory=list)


def _check_bounds(mark: Mark, size: int) -> None:
    if mark.kind not in KINDS:
        raise MarcacaoError(f"tipo de marca desconhecido: {describe(mark)}", mark)
    if not 0 <= mark.start <= mark.end <= size:
        raise MarcacaoError(
            f"marca fora do texto (tamanho {size}): {describe(mark)}", mark
        )
    if mark.kind == "nota" and mark.start != mark.end:
        raise MarcacaoError(f"nota tem largura zero: {describe(mark)}", mark)
    if mark.marker is not None:
        ms, me = mark.marker
        if mark.kind not in STRUCTURAL:
            raise GrammarError(f"só dispositivos têm marcador: {describe(mark)}", mark)
        if not mark.start <= ms <= me <= mark.end:
            raise MarcacaoError(f"marcador fora da marca: {describe(mark)}", mark)


def _nest(marks: list[Mark], size: int) -> _Node:
    """Arrange the marks as a tree, or raise naming the two marks that conflict.

    Order: start ascending, end descending; equal spans keep the order given (outer
    first). A zero-width mark belongs to the innermost mark that contains its position,
    boundaries included: at the start of a mark it is that mark's first child, at the
    end of one it is the last. Zero-width marks never hold anything.
    """
    root = _Node(None)
    stack = [root]
    for mark in sorted(marks, key=lambda m: (m.start, -m.end)):
        _check_bounds(mark, size)
        zero = mark.start == mark.end
        while len(stack) > 1:
            top = stack[-1].mark
            assert top is not None
            if top.end < mark.start or (top.end == mark.start and not zero):
                stack.pop()
            else:
                break
        pos = len(stack) - 1
        parent = stack[pos]
        if zero:
            # innermost open element whose grammar admits it (boundaries included)
            while pos > 0 and mark.kind not in children_allowed(
                stack[pos].mark.kind  # type: ignore[union-attr]
            ):
                pos -= 1
            parent = stack[pos]
        if parent.mark is not None and mark.end > parent.mark.end:
            raise OverlapError(
                f"sobreposição parcial: {describe(parent.mark)} e {describe(mark)}",
                parent.mark,
                mark,
            )
        parent_kind = parent.mark.kind if parent.mark else "documento"
        if mark.kind not in children_allowed(parent_kind):
            top_mark = stack[-1].mark
            raise GrammarError(
                f"{mark.kind} não cabe em {parent_kind}: "
                + (
                    f"{describe(top_mark)} contém {describe(mark)}"
                    if top_mark
                    else describe(mark)
                ),
                top_mark,
                mark,
            )
        node = _Node(mark)
        parent.children.append(node)
        if mark.start != mark.end:
            stack.append(node)
    _check_markers(root)
    return root


def _check_markers(node: _Node) -> None:
    mark = node.mark
    if mark is not None and mark.marker is not None:
        ms, me = mark.marker
        for child in node.children:
            c = child.mark
            assert c is not None
            if c.start == c.end:
                if ms < c.start < me:
                    raise GrammarError(
                        f"{describe(c)} dentro do marcador de {describe(mark)}", mark, c
                    )
            elif not (c.end <= ms or c.start >= me):
                raise GrammarError(
                    f"{describe(c)} cruza o marcador de {describe(mark)}", mark, c
                )
    for child in node.children:
        _check_markers(child)


# --- XML text ---------------------------------------------------------------------
# What XML 1.0 cannot carry or a parser would rewrite: C0 controls except tab and line
# feed (carriage return included, or "\r\n" would become "\n"), U+FFFE/U+FFFF and lone
# surrogates. They become <c v="HEX"/>.
_TEXT_ESCAPE = re.compile("[&<>\x00-\x08\x0b-\x1f\ud800-\udfff￾￿]")
_ATTR_ESCAPE = re.compile('[&<>"\x00-\x1f\ud800-\udfff￾￿]')


def _escape_text(s: str) -> str:
    def rep(m: re.Match[str]) -> str:
        ch = m.group()
        if ch == "&":
            return "&amp;"
        if ch == "<":
            return "&lt;"
        if ch == ">":
            return "&gt;"
        return f'<c v="{ord(ch):02X}"/>'

    return _TEXT_ESCAPE.sub(rep, s)


_ATTR_NAMED = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}


def _escape_attr(s: str) -> str:
    return _ATTR_ESCAPE.sub(
        lambda m: _ATTR_NAMED.get(m.group(), f"&#{ord(m.group())};"), s
    )


def sha256_text(text: str) -> str:
    """The hash recorded on the root: sha256 of the text as UTF-8."""
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def _open_tag(kind: str, attrs: dict[str, str], *, empty: bool) -> str:
    body = "".join(f' {k}="{_escape_attr(v)}"' for k, v in attrs.items())
    return f"<{kind}{body}{'/' if empty else ''}>"


def _emit(node: _Node, text: str, out: list[str]) -> None:
    mark = node.mark
    assert mark is not None
    if mark.kind == "nota":
        if mark.note:
            out.append(_open_tag("nota", mark.attrs, empty=False))
            out.append(_escape_text(mark.note))
            out.append("</nota>")
        else:
            out.append(_open_tag("nota", mark.attrs, empty=True))
        return
    if mark.start == mark.end:
        out.append(_open_tag(mark.kind, mark.attrs, empty=True))
        return
    out.append(_open_tag(mark.kind, mark.attrs, empty=False))
    _emit_content(node, text, out, mark.start, mark.end)
    out.append(f"</{mark.kind}>")


def _emit_content(node: _Node, text: str, out: list[str], lo: int, hi: int) -> None:
    items: list[tuple[int, int, int, _Node | None]] = []
    mark = node.mark
    if mark is not None and mark.marker is not None:
        items.append((mark.marker[0], mark.marker[1], 1, None))
    for child in node.children:
        c = child.mark
        assert c is not None
        items.append((c.start, c.end, 0 if c.start == c.end else 1, child))
    items.sort(key=lambda it: (it[0], it[2]))
    cursor = lo
    for start, end, _, sub in items:
        out.append(_escape_text(text[cursor:start]))
        if sub is None:
            out.append("<m>" + _escape_text(text[start:end]) + "</m>")
        else:
            _emit(sub, text, out)
        cursor = end
    out.append(_escape_text(text[cursor:hi]))


def build(text: str, marks: list[Mark], *, texto_id: str | None = None) -> str:
    """Serialize the marked document: ``text`` untouched, ``marks`` inserted as tags.

    Raises `OverlapError` (naming the two marks) when two marks overlap without
    nesting, `GrammarError` when a mark sits where the level grammar forbids it, and
    `MarcacaoError` for marks outside the text. Never closes and reopens an element.
    """
    root = _nest(list(marks), len(text))
    attrs = {"versao": VERSION, "sha256-texto": sha256_text(text)}
    if texto_id:
        attrs["texto-id"] = texto_id
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>\n',
        _open_tag("documento", attrs, empty=False),
    ]
    _emit_content(root, text, out, 0, len(text))
    out.append("</documento>\n")
    return "".join(out)


# --- reading back -----------------------------------------------------------------
def _parse_root(xml: str) -> ET.Element:
    if "<!DOCTYPE" in xml or "<!ENTITY" in xml:
        raise MarcacaoError("DOCTYPE/ENTITY não é permitido no documento marcado")
    try:
        root = ET.fromstring(xml.encode("utf-8", "surrogatepass"))
    except ET.ParseError as e:
        raise MarcacaoError(f"XML mal formado: {e}") from e
    if root.tag != "documento":
        raise MarcacaoError(f"raiz deve ser <documento>, não <{root.tag}>")
    return root


def _code_point(el: ET.Element) -> str:
    v = el.get("v", "")
    try:
        return chr(int(v, 16))
    except (ValueError, OverflowError) as e:
        raise MarcacaoError(f'<c v="{v}"/> inválido') from e


def _note_text(el: ET.Element) -> str:
    parts = [el.text or ""]
    for ch in el:
        parts.append(_code_point(ch) if ch.tag == "c" else "")
        parts.append(ch.tail or "")
    return "".join(parts)


def _strip_into(el: ET.Element, parts: list[str]) -> None:
    if el.text:
        parts.append(el.text)
    for ch in el:
        if ch.tag == "nota":
            pass
        elif ch.tag == "c":
            parts.append(_code_point(ch))
        else:
            _strip_into(ch, parts)
        if ch.tail:
            parts.append(ch.tail)


def strip(xml: str) -> str:
    """The inverse of `build`: tags removed, ``<nota>`` content removed, ``<c/>`` restored."""
    parts: list[str] = []
    _strip_into(_parse_root(xml), parts)
    return "".join(parts)


class _Reader:
    def __init__(self) -> None:
        self.pos = 0
        self.marks: list[Mark | None] = []

    def add(self, s: str) -> None:
        self.pos += len(s)

    def walk(self, el: ET.Element) -> tuple[int, int] | None:
        """Walk the children of ``el``; return the span of its ``<m>``, if any."""
        marker: tuple[int, int] | None = None
        if el.text:
            self.add(el.text)
        for ch in el:
            if ch.tag == "c":
                self.add(_code_point(ch))
            elif ch.tag == "nota":
                self.marks.append(
                    Mark(
                        "nota",
                        self.pos,
                        self.pos,
                        dict(ch.attrib),
                        None,
                        _note_text(ch),
                    )
                )
            elif ch.tag == "m":
                if marker is not None:
                    raise MarcacaoError(f"mais de um <m> em <{el.tag}>")
                s = self.pos
                self.walk(ch)
                marker = (s, self.pos)
            else:
                idx = len(self.marks)
                self.marks.append(None)
                start = self.pos
                inner = self.walk(ch)
                self.marks[idx] = Mark(ch.tag, start, self.pos, dict(ch.attrib), inner)
            if ch.tail:
                self.add(ch.tail)
        return marker


def _parse_root_marks(root: ET.Element) -> tuple[int, list[Mark]]:
    reader = _Reader()
    reader.walk(root)
    return reader.pos, [m for m in reader.marks if m is not None]


def parse(xml: str) -> tuple[str, list[Mark]]:
    """Back to offsets: the text (as `strip` gives it) and the marks, in document order."""
    root = _parse_root(xml)
    parts: list[str] = []
    _strip_into(root, parts)
    _, marks = _parse_root_marks(root)
    return "".join(parts), marks


def root_attributes(xml: str) -> dict[str, str]:
    """The attributes of ``<documento>`` (``sha256-texto``, ``texto-id``, ``versao``)."""
    return dict(_parse_root(xml).attrib)


# --- verify -----------------------------------------------------------------------
_N_PATTERN = {
    "art": re.compile(r"[0-9]+"),
    "par": re.compile(r"[0-9]+|unico"),
    "inc": re.compile(r"[0-9]+"),
    "ali": re.compile(r"[a-z]+"),
    "item": re.compile(r"[0-9]+"),
}
_ORG_N = re.compile(r"[0-9]+|unico")
_SUFFIX = re.compile(r"[A-Za-z]{1,3}")


def _grammar_problems(el: ET.Element, problems: list[str], where: str) -> None:
    kind = el.tag
    allowed = children_allowed(kind)
    markers = 0
    for i, ch in enumerate(el):
        tag = ch.tag
        here = f"{where}/{tag}[{i}]"
        if tag == "c":
            if ch.get("v") is None or len(ch):
                problems.append(f"{here}: <c> precisa de v e deve ser vazio")
            continue
        if tag == "m":
            markers += 1
            if kind not in STRUCTURAL:
                problems.append(f"{here}: <m> só em dispositivo, não em <{kind}>")
            elif markers > 1:
                problems.append(f"{here}: mais de um <m> em <{kind}>")
            if any(x.tag != "c" for x in ch):
                problems.append(f"{here}: <m> só contém texto")
            continue
        if tag not in KINDS:
            problems.append(f"{here}: elemento desconhecido <{tag}>")
            continue
        if tag not in allowed:
            problems.append(f"{here}: <{tag}> não cabe em <{kind}>")
        _element_problems(ch, problems, here)
        _grammar_problems(ch, problems, here)


def _element_problems(el: ET.Element, problems: list[str], here: str) -> None:
    kind = el.tag
    attrs = el.attrib
    if kind in _N_PATTERN or kind in _ORG_RANK:
        n = attrs.get("n")
        pattern = _N_PATTERN.get(kind, _ORG_N)
        if n is None:
            problems.append(f"{here}: <{kind}> sem n")
        elif not pattern.fullmatch(n):
            problems.append(f'{here}: n="{n}" inválido para <{kind}>')
        suffix = attrs.get("sufixo")
        if suffix is not None and not _SUFFIX.fullmatch(suffix):
            problems.append(f'{here}: sufixo="{suffix}" inválido')
        if attrs.get("corrigido", "true") != "true":
            problems.append(f"{here}: corrigido só vale true")
    rel = attrs.get("rel")
    if rel is not None and (kind != "ref" or rel not in RELS):
        problems.append(f'{here}: rel="{rel}" inválido em <{kind}>')
    estado = attrs.get("estado")
    if estado is not None and estado not in ESTADOS:
        problems.append(f'{here}: estado="{estado}" inválido')
    empty = not len(el) and not (el.text or "").strip() and not el.text
    if empty and kind != "nota" and estado is None:
        problems.append(f"{here}: elemento vazio sem estado")
    if estado == "ausente" and not empty:
        problems.append(f'{here}: estado="ausente" só em elemento vazio')


def _first_difference(a: str, b: str) -> int:
    n = min(len(a), len(b))
    lo, hi = 0, n
    while lo < hi:  # longest common prefix by bisection on slice equality
        mid = (lo + hi + 1) // 2
        if a[:mid] == b[:mid]:
            lo = mid
        else:
            hi = mid - 1
    return lo


def verify(xml: str, text: str) -> list[str]:
    """Problems found in a marked document, against the text it should hold.

    Checks what the schema cannot: the strip invariant (first differing offset, with
    40 characters of context on each side), the sha256 on the root, the nesting
    grammar, numbering shape, ``<m>`` position and empty elements. ``[]`` is a pass.
    """
    try:
        root = _parse_root(xml)
        stripped_parts: list[str] = []
        _strip_into(root, stripped_parts)
    except MarcacaoError as e:
        return [str(e)]
    problems: list[str] = []
    stripped = "".join(stripped_parts)
    if stripped != text:
        i = _first_difference(stripped, text)
        lo = max(0, i - 40)
        problems.append(
            f"strip difere do texto no offset {i} "
            f"(strip {len(stripped)} caracteres, texto {len(text)}): "
            f"texto {text[lo : i + 40]!r} / strip {stripped[lo : i + 40]!r}"
        )
    recorded = root.get("sha256-texto")
    if recorded is None:
        problems.append("raiz sem sha256-texto")
    else:
        if recorded != sha256_text(text):
            problems.append(
                f"sha256-texto da raiz ({recorded[:12]}…) não é o do texto "
                f"({sha256_text(text)[:12]}…)"
            )
        if recorded != sha256_text(stripped):
            problems.append("sha256-texto da raiz não é o do que o strip devolve")
    if root.get("versao") != VERSION:
        problems.append(f"versao deve ser {VERSION!r}, não {root.get('versao')!r}")
    _grammar_problems(root, problems, "documento")
    return problems


# --- tabular view -----------------------------------------------------------------
_TOKEN = {"art": "art", "par": "par", "inc": "inc", "ali": "ali", "item": "item"}


def _token(kind: str, n: str, suffix: str | None) -> str:
    tok = "par-unico" if kind == "par" and n == "unico" else f"{kind}-{n}"
    return f"{tok}-{suffix.lower()}" if suffix else tok


def to_rows(xml: str) -> list[dict[str, Any]]:
    """One row per device (and organisational block), in document order.

    Columns: ``path`` (v0.1 token map, docs/SCHEMA.md §4.2: devices carry the path of
    the nearest device ancestor, global in the norm; an ``alteracao`` starts a fresh
    scope, so a quoted ``art-3`` is told from an own one by ``quoted``; organisational
    blocks are namespaced by nesting), ``kind`` (the tag), ``n``, ``sufixo``,
    ``parent_path``, ``ordem``, ``start``, ``text_start``, ``text_end``, ``end``
    (character offsets; ``text_end`` is the start of the first child device or
    ``alteracao``, trailing whitespace dropped), ``quoted``, ``read_by``,
    ``corrected``, ``estado`` and ``marker`` (the printed marker).
    """
    text, marks = parse(xml)
    root = _nest(marks, len(text))
    rows: list[dict[str, Any]] = []

    def visit(
        node: _Node, base: str | None, org: str | None, quoted: bool, parent: str | None
    ) -> None:
        for child in node.children:
            mark = child.mark
            assert mark is not None
            kind = mark.kind
            if kind in DEVICES or kind in _ORG_RANK:
                n = mark.attrs.get("n", "")
                suffix = mark.attrs.get("sufixo")
                new_base: str | None
                new_org: str | None
                new_parent: str | None
                if kind in DEVICES:
                    tok = _token(kind, n, suffix)
                    path = f"{base}-{tok}" if base else tok
                    new_base, new_org, new_parent = path, org, path
                else:
                    tok = _token(kind, n, suffix) if kind in _ORG_RANK else kind
                    path = f"{org}-{tok}" if org else tok
                    new_base, new_org, new_parent = base, path, parent
                kids = [
                    c.mark.start
                    for c in child.children
                    if c.mark is not None
                    and c.mark.start != c.mark.end
                    and (c.mark.kind in STRUCTURAL or c.mark.kind == "alteracao")
                ]
                if mark.marker is not None:
                    lead = _LEAD.match(text, mark.marker[1], mark.end)
                    text_start = lead.end() if lead else mark.marker[1]
                    raw = text[mark.marker[0] : mark.marker[1]]
                else:
                    text_start, raw = mark.start, ""
                text_end = min(kids) if kids else mark.end
                text_end = max(text_end, text_start)
                while text_end > text_start and text[text_end - 1].isspace():
                    text_end -= 1
                rows.append(
                    {
                        "path": path,
                        "kind": kind,
                        "n": n,
                        "sufixo": suffix,
                        "parent_path": parent if kind in DEVICES else None,
                        "ordem": len(rows),
                        "start": mark.start,
                        "text_start": text_start,
                        "text_end": text_end,
                        "end": mark.end,
                        "quoted": quoted,
                        "read_by": mark.attrs.get("lido-por"),
                        "corrected": mark.attrs.get("corrigido") == "true",
                        "estado": mark.attrs.get("estado"),
                        "marker": raw,
                    }
                )
                visit(child, new_base, new_org, quoted, new_parent)
            elif kind == "alteracao":
                visit(child, None, None, True, None)
            else:
                visit(child, base, org, quoted, parent)

    visit(root, None, None, False, None)
    return rows


# --- adapter from the sequence reader ---------------------------------------------
_KIND = {
    "artigo": "art",
    "paragrafo": "par",
    "inciso": "inc",
    "alinea": "ali",
    "item": "item",
}


@dataclass(slots=True)
class Adaptation:
    """The marks from one reader report, and what had to be left out.

    ``dropped`` records every ``alteracao`` (with its quoted devices) left out
    because it overlaps another element, as ``(alteracao mark, other mark)``.
    ``bad_markers`` counts markers whose ``raw`` text is not where the reader says.
    """

    marks: list[Mark]
    dropped: list[tuple[Mark, Mark]] = field(default_factory=list)
    bad_markers: int = 0


def _trim_end(text: str, start: int, end: int) -> int:
    while end > start and text[end - 1].isspace():
        end -= 1
    return end


_UNICO = re.compile(r"(?:^|-)par-unico(?:-[a-z]+)?$")


def _number_attr(node: Node) -> str | None:
    """``n`` as interpreted: arabic, ``unico``, or the letter of an alínea."""
    number = node["number"]
    if number is None:
        return None
    if node["kind"] == "paragrafo" and _UNICO.search(node["path"] or ""):
        return "unico"
    if node["kind"] == "alinea":
        return chr(96 + number)
    return str(number)


# The official notes of a compiled act: a parenthetical that opens with the vocabulary of
# the Casa Civil's annotations ("(Redação dada pela Lei n. 1.591, de 31/03/2006)",
# "(Revogado pela ...)", "(Acrescido pela ...)", "(NR)"), never a citation in prose.
_NOTE = re.compile(
    r"\(\s*(?:"
    r"Reda[cç][aã]o|Nova\s+reda[cç][aã]o|Altera[cç][aã]o|Nomenclatura|Primitiv|"
    r"Renumerad|NR\b|AC\b|Revogad|Suprimid|Acrescid|Inclu[ií]d|Vide\b|Vetad|"
    r"Republicad|Declarad|Com\s+efeitos|Mat[eé]ria\s+vetada|Dispositivo\s+vetado|"
    r"(?:Inciso|Al[ií]nea|Item|Dispositivo|Artigo|Par[aá]grafo(?:\s+[uú]nico)?)\s+"
    r"(?:acrescid|inclu[ií]d|vetad|revogad|alterad|suprimid)"
    r")[^()]{0,300}\)",
    re.IGNORECASE,
)
_REL_WORDS = (
    ("veto", re.compile(r"vetad|mantido\s+o\s+texto", re.IGNORECASE)),
    ("revogacao", re.compile(r"^\(\s*(?:Revogad|Suprimid)", re.IGNORECASE)),
    (
        "acrescimo",
        re.compile(
            r"^\(\s*(?:Acrescid|Inclu|AC\b|\w+\s+(?:\w+\s+)?(?:acrescid|inclu))",
            re.IGNORECASE,
        ),
    ),
    ("vide", re.compile(r"^\(\s*Vide", re.IGNORECASE)),
    (
        "redacao",
        re.compile(
            r"^\(\s*(?:Reda|Nova|Altera|Nomenclatura|Primitiv|Renumerad|NR\b)",
            re.IGNORECASE,
        ),
    ),
)


def official_notes(text: str) -> list[tuple[int, int, str]]:
    """``(start, end, rel)`` of every official note of a compiled act, in text order.

    ``rel`` is one of `RELS`: ``redacao`` (wording given, "(NR)", renumbering),
    ``acrescimo``, ``revogacao`` (revoked or suppressed), ``veto``, ``vide`` or
    ``outra``. The span is the whole parenthetical, as printed.
    """
    out: list[tuple[int, int, str]] = []
    for m in _NOTE.finditer(text):
        rel = next((r for r, rx in _REL_WORDS if rx.search(m.group(0))), "outra")
        out.append((m.start(), m.end(), rel))
    return out


def _add_notes(marks: list[Mark], text: str) -> list[Mark]:
    """``marks`` plus a ``ref`` for each official note that nests cleanly, else as given.

    A note is kept when every mark it touches contains it entirely (it sits inside one
    device's text, or in the lei, never straddling two devices or a quoted block edge).
    """
    notes = official_notes(text)
    if not notes:
        return marks
    extra: list[Mark] = []
    for start, end, rel in notes:
        if any(
            m.start < end and start < m.end and not (m.start <= start and end <= m.end)
            for m in marks
        ):
            continue
        extra.append(Mark("ref", start, end, {"rel": rel}))
    if not extra:
        return marks
    try:
        _nest([*marks, *extra], len(text))
    except MarcacaoError:
        return marks
    return sorted([*marks, *extra], key=lambda m: (m.start, -m.end))


def from_hierarchy_ex(
    text: str,
    report: HierarchyReport,
    *,
    tipo: str | None = None,
    numero: int | str | None = None,
    notes: bool = True,
) -> Adaptation:
    """Marks for one norm from `read_hierarchy`'s report.

    Conventions:

    - the marker ``<m>`` is ``[start, start + len(raw))``; a device whose ``raw`` is
      empty (an article recovered from a closing sentence whose marker was lost) has no
      ``<m>``; its element starts where the reader's ``start`` is (the sentence);
    - element spans are the reader's ``[start, end)`` with trailing whitespace dropped,
      so the whitespace between two devices belongs to the parent;
    - a reader quoted block becomes an ``alteracao`` under the device that holds it, and
      its quoted devices nest inside; if it overlaps anything it is left out together
      with its devices (they are quoted by construction) and reported in ``dropped``;
    - one ``lei`` spans from the first non-blank character to the end of the body (the
      last own device); nothing is emitted for a text with no own article;
    - evidence: ``lido-por`` (the reader's ``read_by``, own devices), ``corrigido``;
    - an older printed version of a device in a compiled act (reader status
      ``superseded``) is a device like any other with ``estado="superado"``;
    - with ``notes`` the official notes of a compiled act ("(Redação dada pela Lei
      ...)", "(NR)") become ``<ref rel=...>`` when they nest cleanly (`_add_notes`).
    """
    nodes = report["nodes"]
    own_art = [n for n in nodes if n["kind"] == "artigo" and n["status"] == "own"]
    if not own_art:
        return Adaptation([])
    depth: dict[int, int] = {}

    def depth_of(i: int) -> int:
        if i not in depth:
            parent = nodes[i]["parent"]
            depth[i] = 0 if parent is None else depth_of(parent) + 1
        return depth[i]

    built: dict[int, tuple[Mark, int]] = {}
    bad = 0
    for node in nodes:
        kind = node["kind"]
        if kind == "quoted_block":
            built[node["id"]] = (
                Mark(
                    "alteracao",
                    node["start"],
                    _trim_end(text, node["start"], node["end"]),
                ),
                depth_of(node["id"]),
            )
            continue
        if kind not in _KIND or node["status"] not in ("own", "quoted", "superseded"):
            continue
        attrs: dict[str, str] = {}
        n = _number_attr(node)
        if n is not None:
            attrs["n"] = n
        if node["suffix"]:
            attrs["sufixo"] = node["suffix"]
        if node["status"] in ("own", "superseded"):
            attrs["lido-por"] = node["read_by"]
        if node["status"] == "superseded":
            attrs["estado"] = "superado"
        if node["corrected"]:
            attrs["corrigido"] = "true"
        marker: tuple[int, int] | None = None
        raw = node["raw"]
        if raw:
            ms = node["start"]
            if text[ms : ms + len(raw)] == raw:
                marker = (ms, ms + len(raw))
            else:
                bad += 1
        end = max(
            _trim_end(text, node["start"], node["end"]), marker[1] if marker else 0
        )
        built[node["id"]] = (
            Mark(_KIND[kind], node["start"], end, attrs, marker),
            depth_of(node["id"]),
        )

    first = min(m.start for m, _ in built.values())
    lead_ws = len(text) - len(text.lstrip())
    lei_start = min(lead_ws, first)
    lei_end = max(
        _trim_end(text, lei_start, report["body_end"]),
        *(m.end for m, _ in built.values()),
    )
    lei_attrs: dict[str, str] = {}
    if tipo:
        lei_attrs["tipo"] = tipo
    if numero is not None:
        lei_attrs["numero"] = str(numero)
    lei = Mark("lei", lei_start, lei_end, lei_attrs)

    ancestors: dict[int, list[int]] = {}
    for i in built:
        chain = []
        p = nodes[i]["parent"]
        while p is not None:
            chain.append(p)
            p = nodes[p]["parent"]
        ancestors[i] = chain

    dropped: list[tuple[Mark, Mark]] = []
    alive = dict(built)
    while True:
        entries = sorted(
            alive.items(), key=lambda kv: (kv[1][0].start, -kv[1][0].end, kv[1][1])
        )
        marks = [lei] + [m for _, (m, _) in entries]
        try:
            _nest(marks, len(text))
        except MarcacaoError as e:
            culprit = None
            for mk in (e.b, e.a):
                for i, (m, _) in alive.items():
                    if m is mk and m.kind == "alteracao":
                        culprit = i
            if culprit is None:
                # Not an alteracao: the reader's own spans do not nest. Leave it to the
                # caller (build will raise) — it is a reader inconsistency to report.
                break
            other = e.a if alive[culprit][0] is e.b else e.b
            dropped.append((alive[culprit][0], other or alive[culprit][0]))
            for i in [culprit, *[j for j in alive if culprit in ancestors[j]]]:
                alive.pop(i, None)
            continue
        break
    if notes:
        marks = _add_notes(marks, text)
    return Adaptation(marks, dropped, bad)


def from_hierarchy(
    text: str,
    report: HierarchyReport,
    *,
    tipo: str | None = None,
    numero: int | str | None = None,
) -> list[Mark]:
    """`from_hierarchy_ex` without the bookkeeping: just the marks."""
    return from_hierarchy_ex(text, report, tipo=tipo, numero=numero).marks


def marcar(
    text: str,
    *,
    texto_id: str | None = None,
    tipo: str | None = None,
    numero: int | str | None = None,
) -> str:
    """Reader → marks → marked document, for one text."""
    from leizilla.hierarchy_sequence import read_hierarchy

    marks = from_hierarchy(text, read_hierarchy(text), tipo=tipo, numero=numero)
    return build(text, marks, texto_id=texto_id)
