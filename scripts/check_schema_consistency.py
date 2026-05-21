"""Consistency checker for Leizilla XML v0.1.

Validates the invariants from docs/SCHEMA.md §7 that XSD cannot
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
]

_ORGANIZACIONAL_TOKENS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^liv-\d+$"), "livro"),
    (re.compile(r"^parte-\d+$"), "parte"),
    (re.compile(r"^tit-\d+$"), "titulo"),
    (re.compile(r"^cap-\d+$"), "capitulo"),
    (re.compile(r"^sec-\d+$"), "secao"),
    (re.compile(r"^subsec-\d+$"), "subsecao"),
]

# Token class — §4.2 forbids mixed composites (e.g. tit-1-art-2).
_NORMATIVO_TIPOS = {t for _, t in _NORMATIVO_TOKENS}
_ORGANIZACIONAL_TIPOS = {t for _, t in _ORGANIZACIONAL_TOKENS}


def _path_tipo(path: str) -> str | None:
    """Return tipo for a path, or None if unrecognized.

    For normative composite paths (art-5-par-2-inc-3), returns the tipo
    of the LAST token. For organizational namespaced paths (tit-2-cap-1),
    same — returns capitulo.

    Validates the FULL composition chain — `foo-art-1` is rejected (the
    `foo` prefix matches no token), even though `art-1` alone would be
    valid as an artigo.
    """
    if not path:
        return None
    # Whole-path tokens (paths that ARE a single token, e.g. "ementa",
    # "titulo-lei", "art-5", "art-5-a", "ocr-ruim-3", "tit-1").
    for pat, tipo in _NORMATIVO_TOKENS + _ORGANIZACIONAL_TOKENS:
        if pat.match(path):
            return tipo
    # Composite walk: consume tokens left-to-right. At each position try
    # longest-fitting token first (3-seg `disp-transitoria-N`, `art-N-X`)
    # then 2-seg (`art-N`, `par-N`, `tit-N`, etc.). Single-segment tokens
    # like "ementa" are static and cannot appear mid-composite.
    #
    # Per §4.2 path rules, composites are EITHER all-organizational
    # (`tit-1-cap-1-sec-3`) OR all-normative (`art-5-par-2-inc-3`) —
    # never mixed. Mixed chains like `tit-1-art-2` or `art-2-cap-1` are
    # invalid (organizational nesting is XML structure, not path).
    parts = path.split("-")
    i = 0
    last_tipo: str | None = None
    composite_class: str | None = None  # "organizacional" | "normativo"
    while i < len(parts):
        matched = False
        for take in (3, 2):
            if i + take > len(parts):
                continue
            candidate = "-".join(parts[i : i + take])
            for pat, tipo in _NORMATIVO_TOKENS + _ORGANIZACIONAL_TOKENS:
                if pat.match(candidate):
                    this_class = (
                        "organizacional"
                        if tipo in _ORGANIZACIONAL_TIPOS
                        else "normativo"
                    )
                    if composite_class is not None and this_class != composite_class:
                        # Mixed chain — §4.2 violation.
                        return None
                    composite_class = this_class
                    last_tipo = tipo
                    i += take
                    matched = True
                    break
            if matched:
                break
        if not matched:
            return None
    return last_tipo


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
# URN LEX: urn:lex:br;{jurisdicao};{tipo}:{data}[;{numero}][!{path}...]
# Jurisdição pode ter ; interno (municipios).
_RE_URN_LEX = re.compile(
    r"^urn:lex:br;([^;]+;)?[^;]+;(?P<tipo>[^;]+):"
    r"(?P<data>\d{4}-\d{2}-\d{2})"
    r"(;(?P<numero>[^!;]+))?"
    r"(?P<paths>(![a-z0-9-]+)*)$"
)


def _extract_data_publicacao(urn_lex: str | None) -> datetime.date | None:
    """Decompose URN LEX → publication date.

    Returns None when urn-lex is absent, fails the regex, or carries a
    regex-valid but calendar-invalid date (e.g. `2020-13-01`). Calendar
    validity is best-effort here; §7.10 reports the regex-level rejection
    separately, and an invalid calendar slips through XSD too (the
    pattern only enforces digit shape).
    """
    if not urn_lex:
        return None
    m = _RE_URN_LEX.match(urn_lex)
    if not m:
        return None
    try:
        return datetime.date.fromisoformat(m.group("data"))
    except ValueError:
        return None


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
    """Yield every <dispositivo> in the tree, with its full ancestor chain.

    Chain is ordered root → nearest, i.e. for art-3-par-1 the chain is
    [<dispositivo path="art-3">]. Empty chain means the dispositivo is
    a direct child of <lei>.
    """
    stack: list[tuple[ET.Element, list[ET.Element]]] = [
        (d, []) for d in _iter_dispositivos(root)
    ]
    while stack:
        node, chain = stack.pop()
        yield node, chain
        new_chain = chain + [node]
        for child in _iter_dispositivos(node):
            stack.append((child, new_chain))


def _inherited_em(chain: list[ET.Element]) -> datetime.date | None:
    """Walk ancestor chain (nearest first) looking for the first dispositivo
    whose own first <versao> declares `em`. Returns None if no ancestor
    has a declared `em` — caller falls back to data-publicacao da URN.

    Per §4.3 step 2: missing `em` inherits from "ancestral mais próximo
    que tem uma <versao> com `em` declarado".

    A regex-valid but calendar-invalid `em` (e.g. "2020-13-01") is
    skipped, not treated as fatal — same pattern as _check_versoes_ordem.
    """
    for ancestor in reversed(chain):
        for av in ancestor.findall(f"{{{NS}}}versao"):
            aem = av.get("em")
            if aem is None:
                continue
            try:
                return datetime.date.fromisoformat(aem)
            except ValueError:
                continue
    return None


def _parse_xs_boolean(value: str | None) -> bool | None:
    """Parse an xs:boolean lexical value.

    xs:boolean accepts {true, false, 1, 0} after whitespace collapse.
    Returns None for missing or invalid (caller can decide treatment).
    """
    if value is None:
        return None
    v = value.strip()
    if v in ("true", "1"):
        return True
    if v in ("false", "0"):
        return False
    return None


def _check_fonte_diverge_texto(ctx: _Ctx) -> None:
    """§7.1 — <fonte diverge="true"> requires <texto> child;
    <fonte> without diverge=true cannot have <texto> child.

    Accepts all xs:boolean lexical forms ("true", "1", "false", "0",
    whitespace-collapsed) — XSD defines `diverge` as xs:boolean, so a
    schema-valid `diverge="1"` must behave identically to `diverge="true"`.

    Codex P2: `diverge` é semanticamente válido APENAS em <fonte> filha
    de <versao>. Em <inicio> e <revogacao>, `diverge` não tem significado
    (não há "texto canônico da versão" pra divergir) — reportamos
    independente do valor de diverge.
    """
    # Fontes em <versao>: aplica regra padrão diverge/texto.
    for versao in ctx.root.iter(f"{{{NS}}}versao"):
        for fonte in versao.findall(f"{{{NS}}}fonte"):
            diverge = _parse_xs_boolean(fonte.get("diverge")) is True
            has_texto = fonte.find(f"{{{NS}}}texto") is not None
            ia = fonte.get("ia-id", "?")
            if diverge and not has_texto:
                ctx.add(1, f'<fonte ia-id="{ia}" diverge="true"> sem <texto> filho')
            elif not diverge and has_texto:
                ctx.add(1, f'<fonte ia-id="{ia}"> sem diverge="true" tem <texto> filho')

    # Fontes em <inicio> ou <revogacao>: diverge não faz sentido. Reportamos
    # uso indevido independentemente do valor de diverge.
    for container_tag in ("inicio", "revogacao"):
        for container in ctx.root.iter(f"{{{NS}}}{container_tag}"):
            for fonte in container.findall(f"{{{NS}}}fonte"):
                if fonte.get("diverge") is not None:
                    ia = fonte.get("ia-id", "?")
                    ctx.add(
                        1,
                        f'<fonte ia-id="{ia}" diverge="..."> em <{container_tag}> — '
                        f"atributo diverge só é válido em <fonte> filha de <versao>",
                    )


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


def _path_class(path: str) -> str | None:
    """Return "organizacional" / "normativo" / None for a path."""
    tipo = _path_tipo(path)
    if tipo is None:
        return None
    return "organizacional" if tipo in _ORGANIZACIONAL_TIPOS else "normativo"


def _check_path_token_map(ctx: _Ctx) -> None:
    """§7.4 — path matches token map AND (when nested under same-class
    parent) composes from parent's path.

    Per §4.2 path rules:
    - Sub-dispositivos normativos compõem o path do ancestral normativo:
      `art-5-par-2`, `art-5-par-2-inc-3`.
    - Organizacionais têm path namespaceado pelo nesting:
      `tit-2`, `tit-2-cap-1`.
    - Quando normativo está dentro de organizacional, path do normativo
      permanece global (não compõe com pai organizacional).

    So a child path must start with `parent.path + "-"` IFF child and
    parent share the same class. Mixed parent/child (org → norm) is OK
    and the normative keeps its global form.
    """
    for d, chain in _walk_all_dispositivos(ctx.root):
        path = d.get("path")
        if path is None:
            continue
        if _path_tipo(path) is None:
            ctx.add(4, f'path="{path}" não casa com nenhum token do mapa (§4.2)')
            continue
        # Composition check: when nested under a same-class parent,
        # child path must start with `parent.path + "-"`.
        if not chain:
            continue  # top-level — no parent constraint.
        parent = chain[-1]
        parent_path = parent.get("path") or ""
        if not parent_path or _path_tipo(parent_path) is None:
            continue  # parent already flagged separately.
        if _path_class(path) != _path_class(parent_path):
            # Mixed classes: APENAS organizational → normative é
            # permitido (§4.2: "Quando normativo está dentro de
            # organizacional, path do normativo permanece global").
            # Inversão (normativo → organizacional) é hierarquicamente
            # inválida — capítulos não vivem dentro de artigos.
            if (
                _path_class(parent_path) == "normativo"
                and _path_class(path) == "organizacional"
            ):
                ctx.add(
                    4,
                    f'<dispositivo path="{path}"> (organizacional) aninhado '
                    f'em parent path="{parent_path}" (normativo) — inversão '
                    f"hierárquica não permitida (§4.2)",
                )
            continue  # mixed but valid (org → norm) — no composition required.
        if not path.startswith(parent_path + "-"):
            ctx.add(
                4,
                f'path="{path}" não compõe do parent path="{parent_path}" '
                f'(mesma classe, deveria começar com "{parent_path}-") §4.2',
            )


def _check_inheritance_inicio(ctx: _Ctx) -> None:
    """§7.5+§7.6 — Versão sem `em` herda; versão com `em ≠ data-publicacao`
    e sem `alterado-por` deve ter <inicio>.

    Carve-out (§7.5): quando `urn-lex` é ausente, vigência não tem âncora
    nenhuma (data-publicacao indisponível) — é o caso fallback OCR-ruim.
    Verificação estrita de §7.5 fica suspensa nesse caso. Reportamos
    §7.5 apenas quando URN é presente porém não decodificável (caso em
    que §7.10 também reporta).

    Escopo do §7.6: a regra só dispara em versões com `em` declarado.
    Versões que herdam `em ≠ data-publicacao` do ancestral não disparam
    §7.6 aqui — o ancestral é quem deveria ter `<inicio>` ou
    `alterado-por`, e se ele não tem, §7.6 já reportou nele. Evita
    duplicar a mesma violação em todos os descendentes que herdam.
    """
    pub = ctx.data_publicacao
    if ctx.urn_lex is not None and pub is None:
        # urn-lex presente mas regex não casou — §7.10 já reporta;
        # vigência fica irresolvível, registramos uma vez pela lei.
        ctx.add(
            5,
            f'urn-lex="{ctx.urn_lex}" não decompõe → vigência herdada '
            f"não consegue resolver pra nenhuma versão sem `em`",
        )
    for d, _ in _walk_all_dispositivos(ctx.root):
        for v in d.findall(f"{{{NS}}}versao"):
            em = v.get("em")
            if em is None:
                # Herança implícita — §7.5 OK quando pub disponível
                # (ou quando urn-lex ausente, caso fallback exempto).
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
    increasing (when present).

    Missing `em` resolves via §4.3 inheritance chain: own > nearest
    ancestor with declared `em` > data-publicacao. Comparing inherited
    dates catches cases where a nested dispositivo declares an `em`
    earlier than its parent's first versão.
    """
    pub = ctx.data_publicacao
    for d, chain in _walk_all_dispositivos(ctx.root):
        prev_date: datetime.date | None = None
        for v in d.findall(f"{{{NS}}}versao"):
            em = v.get("em")
            cur: datetime.date | None
            if em is not None:
                try:
                    cur = datetime.date.fromisoformat(em)
                except ValueError:
                    continue
            else:
                # §4.3 inheritance: ancestor first, then pub.
                cur = _inherited_em(chain) or pub
                if cur is None:
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
    """§7.8 — <fonte ia-id> matches the RAW IA identifier regex (§5.1).

    `<fonte>` references raw items only (PDF originals that triggered IA's
    automatic OCR). Parsed, dataset, and bundle identifiers don't belong
    in `<fonte>` — they live in other contexts (parsed_meta.json sidecar,
    Parquet KV metadata, dataset releases). Accepting them here would
    silently let downstream consumers fetch non-raw items expecting raw
    content (PDF + OCR).
    """
    for fonte in ctx.root.iter(f"{{{NS}}}fonte"):
        ia = fonte.get("ia-id")
        if ia is None:
            continue
        if not _RE_IA_RAW.match(ia):
            ctx.add(8, f'ia-id="{ia}" não casa com regex de raw IA identifier (§5.1)')


def _check_urn_decomposes(ctx: _Ctx) -> None:
    """§7.10 — urn-lex (if present) decomposes correctly AND its
    components match the parsed-item identifier in the filename.

    Two-part check:
    (a) Regex: urn-lex matches §5.6 pattern. Empty string fires too
        (treated as malformed, not absent).
    (b) Cross-check: when filename stem matches §5.3 (parsed canonical),
        decomposed urn-lex tipo/ano/numero must match the filename's
        components. `ente` comparison is deferred until entes.py mapping
        (M1) — slug `ro` ↔ jurisdição `estado:rondonia` needs the table.
        Fallback identifiers (§5.4) and arbitrary filenames skip (b).

    Workflow contract: the cross-check assumes the XML filename stem
    IS the parsed item's IA identifier (`leizilla-{ente}-{tipo}-{numero:05d}-{ano}.xml`).
    Production flow: download `law.xml` from `https://archive.org/download/{id}/`
    and save it as `{id}.xml` before running the checker. Local fixtures
    use arbitrary names (simple.xml, with-revogacoes.xml, etc.) and
    therefore skip (b) — they only exercise (a).

    (c) URN ausente: permitido para fallback parsed items (§5.4 pattern
    `-fallback-` carrega lei sem data extraível), mas filename canônico
    (§5.3) implica identidade recuperada → URN é esperada (Codex P2).
    """
    if ctx.urn_lex is None:
        stem = ctx.file.stem
        if _RE_IA_PARSED.match(stem):
            ctx.add(
                10,
                f'filename "{stem}" é canônico (§5.3) mas urn-lex ausente — '
                f"parsed item canônico requer URN (use pattern fallback "
                f"§5.4 se identidade não foi recuperada)",
            )
        return
    m = _RE_URN_LEX.match(ctx.urn_lex)
    if not m:
        ctx.add(10, f'urn-lex="{ctx.urn_lex}" não decompõe pela regex §5.6')
        return

    # Cross-check filename ↔ urn-lex components.
    stem = ctx.file.stem
    file_m = _RE_IA_PARSED.match(stem)
    if file_m is None:
        return  # arbitrary filename (fixtures, fallback) — skip cross-check.

    urn_tipo = m.group("tipo")
    urn_ano = m.group("data")[:4]
    urn_numero = m.group("numero")
    file_tipo = file_m.group("tipo")
    file_ano = file_m.group("ano")
    file_numero = file_m.group("numero")

    if urn_tipo != file_tipo:
        ctx.add(
            10,
            f'urn-lex tipo="{urn_tipo}" não bate com filename '
            f'tipo="{file_tipo}" ({stem})',
        )
    if urn_ano != file_ano:
        ctx.add(
            10,
            f'urn-lex ano="{urn_ano}" não bate com filename ano="{file_ano}" ({stem})',
        )
    # Compare numbers after stripping zero-pad on both sides.
    if urn_numero is None:
        ctx.add(
            10,
            f"urn-lex sem ;numero mas filename canônico tem "
            f'numero="{file_numero}" ({stem})',
        )
    else:
        urn_n = urn_numero.lstrip("0") or "0"
        file_n = file_numero.lstrip("0") or "0"
        if urn_n != file_n:
            ctx.add(
                10,
                f'urn-lex numero="{urn_numero}" não bate com filename '
                f'numero="{file_numero}" (canonical: {urn_n} vs {file_n})',
            )


def _check_urn_no_zero_pad(ctx: _Ctx) -> None:
    """§7.14 — URN LEX número is the raw legal number (no zero-pad).

    Uses `is None` (not truthiness) so empty `urn-lex=""` is handled
    consistently with _check_urn_decomposes — empty falls through to the
    regex match (which fails) and §7.10 reports it; §7.14 stays silent
    (no number to zero-pad-check).
    """
    if ctx.urn_lex is None:
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
        # invariant=0 reserved for fatal parse failures (CLI exit 2).
        return [Violation(file, 0, f"XML inválido: {e}")]
    except OSError as e:
        # File I/O failure (directory, permission denied, unreadable). Same
        # exit-code semantics as a parse failure — the file is unusable.
        return [Violation(file, 0, f"I/O falhou: {e}")]
    root = tree.getroot()
    if root.tag != f"{{{NS}}}lei":
        # XML parsed but root is wrong — §7.15 structural violation,
        # not a parse error. CLI exits 1 (consistency violation).
        return [
            Violation(
                file,
                15,
                f"elemento raiz deve ser <lei> no namespace {NS}; recebido: {root.tag}",
            )
        ]

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

    # Parse errors are encoded as `invariant=0` by check_file (see docstring).
    # Per the CLI contract, unparseable XML → exit 2, distinct from
    # consistency violations → exit 1. Automation needs to distinguish
    # broken input from valid-but-invalid XML.
    parse_errors = [v for v in all_violations if v.invariant == 0]
    if parse_errors:
        print(
            f"\n{len(parse_errors)} arquivo(s) com XML inválido — "
            f"não foi possível executar checagens.",
            file=sys.stderr,
        )
        return 2
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
