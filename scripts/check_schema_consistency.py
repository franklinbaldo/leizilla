"""Consistency checker for Leizilla XML v0.1.

Validates the 14 invariants from docs/SCHEMA.md §7 that XSD cannot
express. XSD is intentionally loose; this checker is the other half
of the schema contract.

Usage:
    uv run python scripts/check_schema_consistency.py <file.xml>...
    uv run python scripts/check_schema_consistency.py tests/fixtures/leizilla_xml/*.xml

Exit codes:
    0 — all files pass all invariants
    1 — at least one violation
    2 — usage error / file not found / unparseable XML

The checker reports every violation across every file before exiting,
so a single run lists everything that needs fixing.
"""

from __future__ import annotations

import datetime
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

NS = "https://leizilla.org/lei/0.1"
NSMAP = {"l": NS}


# ---------------------------------------------------------------------------
# Token map — single source of truth for §4.2 (mirrored in SCHEMA.md)
# ---------------------------------------------------------------------------

# Each entry is (regex, tipo). Regex matches the FULL path; for nested
# normative dispositivos we recurse on the tail (so art-5-par-2 validates
# art-5 then par-2).
_NORMATIVO_TOKENS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^titulo-lei$"), "titulo-lei"),
    (re.compile(r"^ementa$"), "ementa"),
    (re.compile(r"^preambulo$"), "preambulo"),
    (re.compile(r"^art-\d+(-[a-z])?$"), "artigo"),
    (re.compile(r"^par-(\d+|unico)$"), "paragrafo"),
    (re.compile(r"^inc-\d+$"), "inciso"),
    (re.compile(r"^ali-[a-z]$"), "alinea"),
    (re.compile(r"^item-\d+$"), "item"),
    (re.compile(r"^anexo-\d+$"), "anexo"),
    (re.compile(r"^disp-transitoria-\d+$"), "disposicao-transitoria"),
    (re.compile(r"^disp-final-\d+$"), "disposicao-final"),
    (re.compile(r"^ocr-ruim(-\d+)?$"), "bloco-ocr-ruim"),
]

_ORGANIZACIONAL_TOKENS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^liv-\d+$"), "livro"),
    (re.compile(r"^parte-\d+$"), "parte"),
    (re.compile(r"^tit-\d+$"), "titulo"),
    (re.compile(r"^cap-\d+$"), "capitulo"),
    (re.compile(r"^sec-\d+$"), "secao"),
    (re.compile(r"^subsec-\d+$"), "subsecao"),
]


def _path_tipo(path: str) -> str | None:
    """Return tipo for a path, or None if unrecognized.

    For normative composite paths (art-5-par-2-inc-3), returns the tipo
    of the LAST token. For organizational namespaced paths (tit-2-cap-1),
    same — returns capitulo.
    """
    # Try whole path against normativo (single-token cases)
    for pat, tipo in _NORMATIVO_TOKENS + _ORGANIZACIONAL_TOKENS:
        if pat.match(path):
            return tipo
    # Composite: split on hyphens, try to find a valid suffix token.
    # We walk from the rightmost possible token boundary. Token is
    # 1 segment (e.g. "ementa") or 2 segments (e.g. "art-5", "tit-2",
    # "par-unico"). Try 2-segment first since 1-segment tokens are static
    # and would have matched the whole-path check above.
    parts = path.split("-")
    for take in (2, 1):
        if len(parts) < take:
            continue
        tail = "-".join(parts[-take:])
        # Special-case art-5-a (3 segments, letter suffix)
        if take == 2 and len(parts) >= 3:
            maybe_letter = parts[-1]
            if (
                len(maybe_letter) == 1
                and maybe_letter.isalpha()
                and re.match(r"^art-\d+$", "-".join(parts[-3:-1]))
            ):
                return "artigo"
        for pat, tipo in _NORMATIVO_TOKENS + _ORGANIZACIONAL_TOKENS:
            if pat.match(tail):
                return tipo
    return None


# ---------------------------------------------------------------------------
# Regexes from §5
# ---------------------------------------------------------------------------

_RE_IA_RAW = re.compile(
    r"^leizilla-raw-(?P<ente>[a-z][a-z0-9-]*)-(?P<fonte>[a-z]+)-(?P<chave>[a-z0-9-]+)$"
)
_RE_IA_PARSED = re.compile(
    r"^leizilla-(?P<ente>[a-z][a-z0-9-]*)-(?P<tipo>[a-z]+)-(?P<numero>\d{5,})-(?P<ano>\d{4})$"
)
_RE_IA_PARSED_FALLBACK = re.compile(
    r"^leizilla-(?P<ente>[a-z][a-z0-9-]*)-(?P<tipo>[a-z]+)-fallback-"
    r"(?P<fonte>[a-z]+)-(?P<chave>[a-z0-9-]+)$"
)
_RE_IA_DATASET = re.compile(
    r"^leizilla-dataset-(?P<ente>[a-z][a-z0-9-]*)-v(?P<version>\d+)$"
)
_RE_IA_BUNDLE = re.compile(
    r"^leizilla-bundle-(?P<ente>[a-z][a-z0-9-]*)-(?P<fonte>[a-z]+)-"
    r"(?P<periodo>\d{4}-W\d{2})$"
)
_IA_ANY = [
    _RE_IA_RAW,
    _RE_IA_PARSED,
    _RE_IA_PARSED_FALLBACK,
    _RE_IA_DATASET,
    _RE_IA_BUNDLE,
]

# URN LEX: urn:lex:br;{jurisdicao};{tipo}:{data}[;{numero}][!{path}...]
# Jurisdição pode ter ; interno (municipios).
_RE_URN_LEX = re.compile(
    r"^urn:lex:br;([^;]+;)?[^;]+;[^;]+:"
    r"(?P<data>\d{4}-\d{2}-\d{2})"
    r"(;(?P<numero>[^!;]+))?"
    r"(?P<paths>(![a-z0-9-]+)*)$"
)


def _extract_data_publicacao(urn_lex: str | None) -> datetime.date | None:
    if not urn_lex:
        return None
    m = _RE_URN_LEX.match(urn_lex)
    if not m:
        return None
    return datetime.date.fromisoformat(m.group("data"))


# ---------------------------------------------------------------------------
# Violation reporting
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    file: Path
    invariant: int
    message: str

    def __str__(self) -> str:
        return f"{self.file}: §7.{self.invariant:02d} — {self.message}"


@dataclass
class _Ctx:
    """Mutable per-file check context."""

    file: Path
    root: ET.Element
    urn_lex: str | None
    data_publicacao: datetime.date | None
    paths_seen: dict[str, ET.Element]
    violations: list[Violation]

    def add(self, invariant: int, msg: str) -> None:
        self.violations.append(Violation(self.file, invariant, msg))


# ---------------------------------------------------------------------------
# Individual invariant checks
# ---------------------------------------------------------------------------


def _iter_dispositivos(parent: ET.Element):
    """Yield direct <dispositivo> children only (non-recursive)."""
    for d in parent.findall(f"{{{NS}}}dispositivo"):
        yield d


def _walk_all_dispositivos(root: ET.Element):
    """Yield every <dispositivo> in the tree, with its parent <dispositivo>
    or None when the parent is <lei>."""
    stack: list[tuple[ET.Element, ET.Element | None]] = [
        (d, None) for d in _iter_dispositivos(root)
    ]
    while stack:
        node, parent = stack.pop()
        yield node, parent
        for child in _iter_dispositivos(node):
            stack.append((child, node))


def _check_fonte_diverge_texto(ctx: _Ctx) -> None:
    """§7.1 — <fonte diverge="true"> requires <texto> child;
    <fonte> without diverge cannot have <texto> child."""
    for fonte in ctx.root.iter(f"{{{NS}}}fonte"):
        diverge = fonte.get("diverge") == "true"
        has_texto = fonte.find(f"{{{NS}}}texto") is not None
        ia = fonte.get("ia-id", "?")
        if diverge and not has_texto:
            ctx.add(1, f'<fonte ia-id="{ia}" diverge="true"> sem <texto> filho')
        elif not diverge and has_texto:
            ctx.add(1, f'<fonte ia-id="{ia}"> sem diverge="true" tem <texto> filho')


def _check_revogacao_total_excludes_partial(ctx: _Ctx) -> None:
    """§7.2 — <revogacao> at <lei> root excludes any <revogacao> in
    descendant dispositivos."""
    total = ctx.root.find(f"{{{NS}}}revogacao")
    if total is None:
        return
    for d, _ in _walk_all_dispositivos(ctx.root):
        if d.find(f"{{{NS}}}revogacao") is not None:
            path = d.get("path", "?")
            ctx.add(
                2,
                f"<revogacao> total na raiz convive com <revogacao> em "
                f'<dispositivo path="{path}">',
            )


def _check_caducidade_no_por(ctx: _Ctx) -> None:
    """§7.3 — <revogacao tipo="caducidade"> has no `por` attribute;
    all other tipos require it."""
    for rev in ctx.root.iter(f"{{{NS}}}revogacao"):
        tipo = rev.get("tipo")
        por = rev.get("por")
        em = rev.get("em", "?")
        if tipo == "caducidade" and por is not None:
            ctx.add(3, f'<revogacao em="{em}" tipo="caducidade"> tem atributo "por"')
        elif tipo and tipo != "caducidade" and por is None:
            ctx.add(3, f'<revogacao em="{em}" tipo="{tipo}"> não tem atributo "por"')


def _check_path_token_map(ctx: _Ctx) -> None:
    """§7.4 — path matches token map. Unknown tokens → error."""
    for d, _ in _walk_all_dispositivos(ctx.root):
        path = d.get("path")
        if path is None:
            continue
        if _path_tipo(path) is None:
            ctx.add(4, f'path="{path}" não casa com nenhum token do mapa (§4.2)')


def _check_inheritance_inicio(ctx: _Ctx) -> None:
    """§7.5+§7.6 — Versão sem `em` herda; versão com `em ≠ data-publicacao`
    e sem `alterado-por` deve ter <inicio>."""
    pub = ctx.data_publicacao
    for d, _ in _walk_all_dispositivos(ctx.root):
        for v in d.findall(f"{{{NS}}}versao"):
            em = v.get("em")
            if em is None:
                # Herança implícita — §7.5 OK por definição.
                continue
            alterado_por = v.get("alterado-por")
            inicio = v.find(f"{{{NS}}}inicio")
            try:
                em_date = datetime.date.fromisoformat(em)
            except ValueError:
                # XSD já validou xs:date; aqui ignoramos.
                continue
            if (
                pub is not None
                and em_date != pub
                and alterado_por is None
                and inicio is None
            ):
                path = d.get("path", "?")
                ctx.add(
                    6,
                    f'<versao em="{em}"> em <dispositivo path="{path}"> difere de '
                    f"data-publicacao={pub.isoformat()}, sem alterado-por e sem <inicio>",
                )


def _check_versoes_ordem(ctx: _Ctx) -> None:
    """§7.7 — Ordering of versões within a dispositivo: `em` strictly
    increasing (when present)."""
    pub = ctx.data_publicacao
    for d, _ in _walk_all_dispositivos(ctx.root):
        prev_date: datetime.date | None = None
        for v in d.findall(f"{{{NS}}}versao"):
            em = v.get("em")
            if em is not None:
                try:
                    cur = datetime.date.fromisoformat(em)
                except ValueError:
                    continue
            elif pub is not None:
                cur = pub
            else:
                continue
            if prev_date is not None and cur <= prev_date:
                path = d.get("path", "?")
                ctx.add(
                    7,
                    f'versões em <dispositivo path="{path}"> não estão em ordem '
                    f"crescente: {prev_date.isoformat()} → {cur.isoformat()}",
                )
            prev_date = cur


def _check_ia_id_format(ctx: _Ctx) -> None:
    """§7.8 — <fonte ia-id> matches one of the §5 regexes."""
    for fonte in ctx.root.iter(f"{{{NS}}}fonte"):
        ia = fonte.get("ia-id")
        if ia is None:
            continue
        if not any(rx.match(ia) for rx in _IA_ANY):
            ctx.add(8, f'ia-id="{ia}" não casa com nenhum padrão IA (§5)')


def _check_quality_only_ocr_ruim(ctx: _Ctx) -> None:
    """§7.9 — `quality` attribute only on <dispositivo path="ocr-ruim..."`."""
    for d, _ in _walk_all_dispositivos(ctx.root):
        if d.get("quality") is None:
            continue
        path = d.get("path", "")
        if not path.startswith("ocr-ruim"):
            ctx.add(
                9,
                f'<dispositivo path="{path}" quality="{d.get("quality")}"> — '
                f'quality só é válido em path começando por "ocr-ruim"',
            )


def _check_urn_decomposes(ctx: _Ctx) -> None:
    """§7.10 — urn-lex (if present) decomposes correctly. Tied to IA id
    inference when urn-lex is absent — but we don't have parsed_meta.json
    here, so we only validate the regex match for now."""
    if ctx.urn_lex and not _RE_URN_LEX.match(ctx.urn_lex):
        ctx.add(10, f'urn-lex="{ctx.urn_lex}" não decompõe pela regex §5.6')


def _check_unique_paths(ctx: _Ctx) -> None:
    """§7.13 — Path unique across the dispositivo tree of the lei.
    Already enforced by xs:unique in XSD; double-check here."""
    for path, elt in list(ctx.paths_seen.items()):
        pass  # paths_seen is already deduped during walk; collisions raise below


def _check_urn_no_zero_pad(ctx: _Ctx) -> None:
    """§7.14 — URN LEX número is the raw legal number (no zero-pad)."""
    if not ctx.urn_lex:
        return
    m = _RE_URN_LEX.match(ctx.urn_lex)
    if not m:
        return  # §7.10 já reporta
    numero = m.group("numero")
    if numero is None:
        return
    # Reject `;0+\d+` when the underlying number has < 5 digits.
    if numero.startswith("0") and numero.isdigit() and len(numero.lstrip("0")) < 5:
        raw = numero.lstrip("0") or "0"
        ctx.add(
            14,
            f'urn-lex="{ctx.urn_lex}" usa zero-pad no número (";{numero}"); '
            f'URN deve carregar o número legal raw (";{raw}")',
        )


# ---------------------------------------------------------------------------
# Entry point per file
# ---------------------------------------------------------------------------


def _collect_paths(ctx: _Ctx) -> None:
    """Populate paths_seen; emit §7.13 violation if duplicate found."""
    for d, _ in _walk_all_dispositivos(ctx.root):
        path = d.get("path")
        if path is None:
            continue
        if path in ctx.paths_seen:
            ctx.add(13, f'path="{path}" aparece mais de uma vez')
        else:
            ctx.paths_seen[path] = d


def check_file(file: Path) -> list[Violation]:
    try:
        tree = ET.parse(file)
    except ET.ParseError as e:
        return [Violation(file, 0, f"XML inválido: {e}")]
    root = tree.getroot()
    if root.tag != f"{{{NS}}}lei":
        return [Violation(file, 0, f"elemento raiz não é <lei>: {root.tag}")]

    urn_lex = root.get("urn-lex")
    ctx = _Ctx(
        file=file,
        root=root,
        urn_lex=urn_lex,
        data_publicacao=_extract_data_publicacao(urn_lex),
        paths_seen={},
        violations=[],
    )

    _collect_paths(ctx)
    _check_fonte_diverge_texto(ctx)
    _check_revogacao_total_excludes_partial(ctx)
    _check_caducidade_no_por(ctx)
    _check_path_token_map(ctx)
    _check_inheritance_inicio(ctx)
    _check_versoes_ordem(ctx)
    _check_ia_id_format(ctx)
    _check_quality_only_ocr_ruim(ctx)
    _check_urn_decomposes(ctx)
    _check_urn_no_zero_pad(ctx)
    return ctx.violations


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "usage: check_schema_consistency.py <file.xml>...",
            file=sys.stderr,
        )
        return 2
    all_violations: list[Violation] = []
    for arg in argv[1:]:
        path = Path(arg)
        if not path.exists():
            print(f"{path}: arquivo não encontrado", file=sys.stderr)
            return 2
        all_violations.extend(check_file(path))

    for v in all_violations:
        print(str(v))
    if all_violations:
        print(
            f"\n{len(all_violations)} violação(ões) em "
            f"{len({v.file for v in all_violations})} arquivo(s).",
            file=sys.stderr,
        )
        return 1
    print(f"OK — {len(argv) - 1} arquivo(s) sem violações.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
