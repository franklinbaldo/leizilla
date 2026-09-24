"""Instrumentação de cobertura S1-S4 (issue #174) — funil de processamento por
fonte e tipo normativo, reproduzível sem heurística manual.

Estágios (PRD §6 / §10.4, mesma semântica de ``web/src/lib/format.ts:STAGES``):

- **S1 arquivado**    — bytes preservados no IA: toda linha de ``index.csv`` de
  um item de range, identificada ou não (ADR-0011 §1 — a área de espera
  ``_unidentified`` também é S1, só não é S2).
- **S2 identificado**  — ``(tipo, número)`` resolvido a partir do contexto de
  descoberta; entra no catálogo navegável (linhas de um item de range, nunca da
  área de espera).
- **S3 com texto**    — HTML nativo (o próprio arquivo já é texto) ou
  ``_djvu.txt`` derivado pelo IA a partir do PDF, quando já disponível.
- **S4 estruturado**  — parseado em Leizilla XML e publicado no item parsed
  (M3-M4); contado via ``publisher.list_parsed_raw_ids``.

Cada contador é ``Optional[int]``: ``None`` significa "não foi possível medir"
(erro de rede/timeout), nunca confundido com um 0 real — ausência de dado não
vira zero silencioso (critério de aceite da issue #174).
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from leizilla import publisher

_UNIDENTIFIED_SUFFIX = "_unidentified"

# Sufixo de um raw_id legado após `leizilla-raw-{ente}-{fonte}-`: `{tipo}-{numero}`
# (ia_utils._raw_identifier + list_identities). Mesma forma de ia_utils.parse_identity.
_CHAVE_RE = re.compile(r"^(?P<tipo>[a-z][a-z0-9-]*)-(?P<numero>\d+)$")


def _tipo_from_raw_id(raw_id: str, ente: str, fonte: str) -> Optional[str]:
    """Extrai o `tipo` de um raw_id legado desta fonte, ou ``None`` se não casar."""
    prefix = f"leizilla-raw-{ente.lower()}-{fonte.lower()}-"
    if not raw_id.startswith(prefix):
        return None
    m = _CHAVE_RE.match(raw_id[len(prefix) :])
    return m.group("tipo") if m else None


@dataclass
class TipoCoverage:
    """Contadores S1-S4 para um ``(fonte, tipo)`` — ex. (casacivil, lei)."""

    tipo: str
    s1_arquivadas: int = 0
    s2_identificadas: int = 0
    s3_com_texto: int = 0
    s4_estruturadas: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tipo": self.tipo,
            "s1_arquivadas": self.s1_arquivadas,
            "s2_identificadas": self.s2_identificadas,
            "s3_com_texto": self.s3_com_texto,
            "s4_estruturadas": self.s4_estruturadas,
        }


@dataclass
class FonteCoverage:
    """Cobertura de uma fonte (ex. casacivil), agregada e por tipo.

    S1-S3 (index.csv + metadata do IA) e S4 (itens parsed) vêm de consultas
    independentes — uma falha transitória numa não deve descartar a outra que
    já tinha sucedido. Por isso o "não foi possível medir" é rastreado por
    grupo: ``ok_s1_s3`` cobre arquivado/identificado/com-texto, ``ok_s4`` cobre
    estruturado. Quando um grupo falha, seu(s) agregado(s) ficam ``None`` em
    vez de um total parcial silencioso; o detalhe por tipo mostra o que foi
    medido com sucesso antes da falha, mas não deve ser tratado como completo.
    """

    fonte: str
    ok_s1_s3: bool = True
    ok_s4: bool = True
    unidentified_arquivadas: int = 0
    por_tipo: Dict[str, TipoCoverage] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.ok_s1_s3 and self.ok_s4

    def _tipo(self, tipo: str) -> TipoCoverage:
        return self.por_tipo.setdefault(tipo, TipoCoverage(tipo=tipo))

    @property
    def s1_total(self) -> Optional[int]:
        if not self.ok_s1_s3:
            return None
        return self.unidentified_arquivadas + sum(
            t.s1_arquivadas for t in self.por_tipo.values()
        )

    @property
    def s2_total(self) -> Optional[int]:
        if not self.ok_s1_s3:
            return None
        return sum(t.s2_identificadas for t in self.por_tipo.values())

    @property
    def s3_total(self) -> Optional[int]:
        if not self.ok_s1_s3:
            return None
        return sum(t.s3_com_texto for t in self.por_tipo.values())

    @property
    def s4_total(self) -> Optional[int]:
        if not self.ok_s4:
            return None
        return sum(t.s4_estruturadas for t in self.por_tipo.values())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fonte": self.fonte,
            "ok": self.ok,
            "ok_s1_s3": self.ok_s1_s3,
            "ok_s4": self.ok_s4,
            "unidentified_arquivadas": self.unidentified_arquivadas,
            "s1_arquivadas": self.s1_total,
            "s2_identificadas": self.s2_total,
            "s3_com_texto": self.s3_total,
            "s4_estruturadas": self.s4_total,
            "por_tipo": [t.to_dict() for t in self.por_tipo.values()],
        }


@dataclass
class CoverageReport:
    """Relatório de cobertura S1-S4 de um ente, com timestamp e proveniência."""

    ente: str
    generated_at: str
    git_sha: Optional[str]
    fontes: List[FonteCoverage] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "leizilla_coverage_version": "0.1",
            "ente": self.ente,
            "generated_at": self.generated_at,
            "git_sha": self.git_sha,
            "fontes": [f.to_dict() for f in self.fontes],
        }


def _has_text(formato: str, uuid5: str, files: Optional[set[str]]) -> Optional[bool]:
    """True/False se dá para determinar; ``None`` se precisaria do metadata do
    item (PDF ainda sem OCR verificável) e o fetch de metadata falhou."""
    if formato == "html":
        return True
    if files is None:
        return None
    return any(name.endswith(f"{uuid5}_djvu.txt") for name in files)


def compute_fonte_coverage(ente: str, fonte: str) -> FonteCoverage:
    """Agrega S1-S3 (dos itens de range do IA) + S4 (itens parsed) para uma fonte.

    S1-S3 e S4 vêm de consultas independentes ao IA — ambas são sempre
    tentadas, e cada uma é all-or-nothing dentro do seu próprio grupo (mesmo
    princípio de ``publisher.list_raw_ids``): uma falha transitória marca só o
    grupo afetado (``ok_s1_s3``/``ok_s4``) como incompleto, sem descartar o
    outro grupo que já tinha sucedido.
    """
    fc = FonteCoverage(fonte=fonte)

    item_ids = publisher.scrape_identifiers(f"leizilla_{ente.lower()}_{fonte.lower()}_")
    if item_ids is None:
        fc.ok_s1_s3 = False
        item_ids = []

    for item_id in item_ids:
        try:
            index_csv = publisher.fetch_existing_index(item_id)
        except publisher.IndexFetchError:
            fc.ok_s1_s3 = False
            continue
        if index_csv is None:
            continue  # 404 confirmado: item sem index ainda, não contribui

        is_unidentified_item = item_id.endswith(_UNIDENTIFIED_SUFFIX)
        rows = list(csv.DictReader(io.StringIO(index_csv)))

        if is_unidentified_item:
            fc.unidentified_arquivadas += len(rows)
            continue

        files = publisher.fetch_item_filenames(item_id)
        if files is None:
            fc.ok_s1_s3 = (
                False  # não dá pra confirmar S3 pdf deste item — marca e segue
            )

        seen: set[tuple[str, int]] = set()
        text_by_identity: Dict[tuple[str, int], bool] = {}
        for row in rows:
            tipo = row.get("tipo", "")
            numero_s = row.get("numero", "")
            if not tipo or not numero_s or not numero_s.isdigit():
                continue  # linha malformada — não deveria ocorrer num item de range
            key = (tipo, int(numero_s))
            seen.add(key)
            has_text = _has_text(row.get("formato", ""), row.get("uuid5", ""), files)
            if has_text:
                text_by_identity[key] = True
            elif key not in text_by_identity:
                text_by_identity[key] = False

        for tipo, numero in seen:
            t = fc._tipo(tipo)
            t.s1_arquivadas += 1
            t.s2_identificadas += 1
            if text_by_identity.get((tipo, numero)):
                t.s3_com_texto += 1

    parsed_raw_ids = publisher.list_parsed_raw_ids_strict(ente, fonte)
    if parsed_raw_ids is None:
        fc.ok_s4 = False
        parsed_raw_ids = set()
    for raw_id in parsed_raw_ids:
        tipo = _tipo_from_raw_id(raw_id, ente, fonte)
        if tipo is None:
            continue
        fc._tipo(tipo).s4_estruturadas += 1

    return fc


def compute_coverage(ente: str, fontes: List[str]) -> CoverageReport:
    """Relatório completo de cobertura S1-S4 de um ente, por fonte."""
    return CoverageReport(
        ente=ente,
        generated_at=datetime.now(tz=timezone.utc).isoformat(),
        git_sha=publisher.get_git_sha(),
        fontes=[compute_fonte_coverage(ente, fonte) for fonte in fontes],
    )
