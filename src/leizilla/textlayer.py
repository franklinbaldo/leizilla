"""Camada de texto (ADR-0015) — tabela ``textos``: leitura sem PDF, desacoplada de S4.

Toda norma em S3 (identificada e com ``_djvu.txt`` derivado pelo Internet Archive)
vira uma linha da tabela ``textos``, independente de já ter sido estruturada
(``versoes``, S4). O texto é guardado **verbatim** — nunca reescrito; as âncoras de
artigo são dado derivado (offsets calculados por
``leizilla.hierarchy_sequence.read_hierarchy``, nível dos artigos) e só viram navegação no portal quando a
sequência fecha (``artigos_fecham``).

Chave: identidade raw ``(ente, fonte, tipo, numero)`` — uma linha por norma, a
captura mais recente **com texto** vence — mais o hash do arquivo de origem
(``sha256_fonte``), que diz exatamente de qual captura o texto veio.

Enumeração igual à de ``coverage.compute_fonte_coverage``: itens de range por
prefixo → ``index.csv`` → arquivos do item. Aqui o ``archive.org/metadata`` é lido
inteiro (uma requisição por item) porque, além dos nomes, ele traz a proveniência
do OCR por arquivo (motor, versão do módulo, parâmetros, sha1 e mtime do texto).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from leizilla import publisher
from leizilla.hierarchy_sequence import (
    article_closes,
    article_closure,
    own_articles,
    read_hierarchy,
)
from leizilla.ia_utils import download_url

logger = logging.getLogger(__name__)

_USER_AGENT = "leizilla-crawler/0.1"
_IA_METADATA_URL = "https://archive.org/metadata"
_UNIDENTIFIED_SUFFIX = "_unidentified"
_DJVU_SUFFIX = "_djvu.txt"
_CHOCR_SUFFIX = "_chocr.html.gz"

QUALIDADE_NAO_ESTRUTURADO = "texto-nao-estruturado"
TRECHO_MAX_CHARS = 280
DEFAULT_SLEEP_S = 0.4
_FETCH_TRIES = 3
_FETCH_TIMEOUT_S = 40

# Ordem e tipos das colunas do Parquet ``textos`` (docs/SCHEMA.md §3.5).
TEXTOS_SCHEMA: dict[str, str] = {
    "texto_id": "VARCHAR",
    "ente": "VARCHAR",
    "fonte": "VARCHAR",
    "tipo": "VARCHAR",
    "numero": "INTEGER",
    "rendicao": "VARCHAR",
    "qualidade": "VARCHAR",
    "sha256_fonte": "VARCHAR",
    "capturado_em": "VARCHAR",
    "ia_item": "VARCHAR",
    "pdf_url": "VARCHAR",
    "texto_url": "VARCHAR",
    "ocr_motor": "VARCHAR",
    "ocr_modulo_versao": "VARCHAR",
    "ocr_parametros": "VARCHAR",
    "ocr_derivado_em": "VARCHAR",
    "sha1_texto_ia": "VARCHAR",
    "sha256_texto": "VARCHAR",
    "num_caracteres": "INTEGER",
    "artigos_fecham": "BOOLEAN",
    "artigos_total": "INTEGER",
    "artigos_ultimo": "INTEGER",
    "ancoras": "VARCHAR",
    "trecho": "VARCHAR",
    "texto": "VARCHAR",
}

Fetcher = Callable[[str], Optional[bytes]]


def texto_id(ente: str, fonte: str, tipo: str, numero: int) -> str:
    """Identificador da linha: o raw_id legado da norma (SCHEMA.md §5.1).

    ``leizilla-raw-{ente}-{fonte}-{tipo}-{numero:05d}`` — a mesma chave que
    ``versoes.fontes[].ia_id`` registra, o que permite ao portal saber, sem
    tabela auxiliar, quais textos já têm versão estruturada.
    """
    return f"leizilla-raw-{ente.lower()}-{fonte.lower()}-{tipo.lower()}-{numero:05d}"


_FIRST_WORD = re.compile(r"\S+")


def article_anchors(text: str) -> tuple[list[dict[str, Any]], bool, int]:
    """Âncoras dos artigos próprios da norma: ``(âncoras, fecha, último)``.

    Lidos por ``read_hierarchy`` (nível dos artigos; ADR-0015, adendo 2026-11-17).
    Cada âncora é ``{"n", "sufixo", "ini", "fim"}`` com offsets em **code points
    Unicode** dentro do texto verbatim (o marcador, ex. ``Art. 4º``, ocupa
    ``[ini, fim)``). Só entram artigos próprios; citados, referências e não
    explicados ficam de fora. ``fecha`` é ``article_closes`` (a mesma noção do
    placar do ratchet). Um artigo recuperado de uma frase de encerramento sem
    marcador (``orphan_closings``) não tem marcador no texto: a âncora começa na
    frase e ``fim`` cobre a primeira palavra, para que ``ini < fim`` valha sempre.
    Dado derivado: o texto não é tocado.
    """
    report = read_hierarchy(text)
    own = own_articles(report)
    anchors: list[dict[str, Any]] = []
    for i, node in enumerate(own):
        ini = node["start"]
        fim = ini + len(node["raw"])
        if fim <= ini:  # marcador de largura zero (artigo recuperado)
            word = _FIRST_WORD.match(text, ini)
            fim = word.end() if word else min(ini + 1, len(text))
            if i + 1 < len(own):
                fim = min(fim, own[i + 1]["start"])
        anchors.append(
            {"n": node["number"], "sufixo": node["suffix"], "ini": ini, "fim": fim}
        )
    last = max((a["n"] for a in anchors), default=0)
    return anchors, article_closes(report), int(last)


def make_trecho(text: str, max_chars: int = TRECHO_MAX_CHARS) -> str:
    """Prefixo do texto com espaços colapsados — só para cartões de listagem."""
    return re.sub(r"\s+", " ", text).strip()[:max_chars]


def build_row(
    *,
    ente: str,
    fonte: str,
    tipo: str,
    numero: int,
    rendicao: str,
    sha256_fonte: str,
    capturado_em: str,
    ia_item: str,
    pdf_name: str,
    texto_name: str,
    text_bytes: bytes,
    ocr_motor: Optional[str] = None,
    ocr_modulo_versao: Optional[str] = None,
    ocr_parametros: Optional[str] = None,
    ocr_derivado_em: Optional[str] = None,
    sha1_texto_ia: Optional[str] = None,
) -> dict[str, Any]:
    """Monta uma linha de ``textos`` a partir dos bytes do ``_djvu.txt``."""
    text = text_bytes.decode("utf-8", errors="replace")
    anchors, closes, last = article_anchors(text)
    return {
        "texto_id": texto_id(ente, fonte, tipo, numero),
        "ente": ente.lower(),
        "fonte": fonte.lower(),
        "tipo": tipo,
        "numero": numero,
        "rendicao": rendicao,
        "qualidade": QUALIDADE_NAO_ESTRUTURADO,
        "sha256_fonte": sha256_fonte,
        "capturado_em": capturado_em,
        "ia_item": ia_item,
        "pdf_url": download_url(ia_item, pdf_name),
        "texto_url": download_url(ia_item, texto_name),
        "ocr_motor": ocr_motor,
        "ocr_modulo_versao": ocr_modulo_versao,
        "ocr_parametros": ocr_parametros,
        "ocr_derivado_em": ocr_derivado_em,
        "sha1_texto_ia": sha1_texto_ia,
        "sha256_texto": hashlib.sha256(text_bytes).hexdigest(),
        "num_caracteres": len(text),
        "artigos_fecham": closes,
        "artigos_total": len(anchors),
        "artigos_ultimo": last,
        "ancoras": json.dumps(anchors, ensure_ascii=False, separators=(",", ":")),
        "trecho": make_trecho(text),
        "texto": text,
    }


def refresh_anchors(row: dict[str, Any]) -> dict[str, Any]:
    """Recalcula as colunas derivadas de uma linha reaproveitada (texto intacto)."""
    text = str(row["texto"])
    anchors, closes, last = article_anchors(text)
    out = {k: row.get(k) for k in TEXTOS_SCHEMA}
    out["artigos_fecham"] = closes
    out["artigos_total"] = len(anchors)
    out["artigos_ultimo"] = last
    out["ancoras"] = json.dumps(anchors, ensure_ascii=False, separators=(",", ":"))
    out["trecho"] = make_trecho(text)
    return out


def http_get(url: str) -> Optional[bytes]:
    """GET com retry e backoff linear. ``None`` se todas as tentativas falharem.

    404 não é repetido (ausência confirmada); demais erros de rede/5xx são.
    """
    for attempt in range(1, _FETCH_TRIES + 1):
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_S) as resp:
                return resp.read()  # type: ignore[no-any-return]
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            logger.warning("GET %s: HTTP %s (tentativa %d)", url, e.code, attempt)
        except (urllib.error.URLError, OSError) as e:
            logger.warning("GET %s: %s (tentativa %d)", url, e, attempt)
        if attempt < _FETCH_TRIES:
            time.sleep(2.0 * attempt)
    return None


def fetch_item_files(
    item_id: str, fetch: Optional[Fetcher] = None
) -> Optional[dict[str, dict[str, Any]]]:
    """Arquivos de um item IA (nome → entrada do metadata). ``None`` em falha."""
    raw = (fetch or http_get)(f"{_IA_METADATA_URL}/{item_id}")
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return {
        str(f["name"]): f
        for f in data.get("files", [])
        if isinstance(f, dict) and f.get("name")
    }


def captures_by_identity(index_csv: str) -> dict[tuple[str, int], list[dict[str, str]]]:
    """Capturas PDF por ``(tipo, número)``, da mais recente para a mais antiga.

    O índice é append-only (ADR-0011): a ordem é ``captured_at`` e, no empate, a
    posição no arquivo. Linhas malformadas ou de outros formatos são ignoradas —
    a camada de texto cobre só o OCR derivado de PDF.
    """
    grouped: dict[tuple[str, int], list[tuple[str, int, dict[str, str]]]] = {}
    for pos, row in enumerate(csv.DictReader(io.StringIO(index_csv))):
        tipo = row.get("tipo") or ""
        numero_s = row.get("numero") or ""
        if not tipo or not numero_s.isdigit() or row.get("formato") != "pdf":
            continue
        if not row.get("uuid5"):
            continue
        grouped.setdefault((tipo, int(numero_s)), []).append(
            (row.get("captured_at") or "", pos, row)
        )
    return {
        key: [r for _, _, r in sorted(rows, key=lambda t: (t[0], t[1]), reverse=True)]
        for key, rows in grouped.items()
    }


#: Valor de ``ocr_motor`` quando o IA não fez OCR: o PDF já trazia uma camada de
#: texto (formato "Text PDF") e o ``_djvu.txt`` é a conversão dela. Não há arquivo
#: ``_chocr`` nesse caso. Distinguir as duas origens importa: a camada embutida por
#: scanner foi a pior fonte medida (docs/okf, ocr-engine-benchmark).
TEXT_LAYER_CONVERSION = "pdf-to-hocr (camada de texto do PDF, sem OCR)"


#: Valor de ``ocr_motor`` quando o texto da linha é um re-OCR direcionado aceito
#: (ADR-0019) e não o ``_djvu.txt`` do IA. ``ocr_modulo_versao`` carrega a versão do
#: Kreuzberg, ``ocr_parametros`` os parâmetros e ``ocr_derivado_em`` a data da
#: tentativa; ``sha1_texto_ia`` fica vazio (o texto não é o do IA) e ``texto_url``
#: continua apontando para o ``_djvu.txt`` original.
REOCR_MOTOR = "kreuzberg+paddleocr (re-OCR direcionado, ADR-0019)"

#: Filas do re-OCR (ADR-0019): ``nao-fecha`` (há texto do IA que o leitor não fecha)
#: e ``sem-texto`` (PDF preservado sem texto do IA). Linhas de ``reocr.parquet``
#: anteriores à coluna ``fila`` são ``nao-fecha``.
FILA_NAO_FECHA = "nao-fecha"
FILA_SEM_TEXTO = "sem-texto"

FONTE_IA = "ia"
FONTE_PROPRIA = "propria"


def read_closure(text: str) -> tuple[bool, int]:
    """``(nível dos artigos fecha, nº de artigos próprios)`` segundo o leitor.

    Atalho de ``hierarchy_sequence.article_closure``: a mesma noção de "fecha" do
    placar do ratchet e da camada de texto.
    """
    return article_closure(text)


def choose_text_source(ia_text: str, own_text: str) -> str:
    """Qual texto vale quando uma norma tem o do IA **e** um OCR próprio ``sem-texto``.

    O OCR próprio entrou porque o IA não tinha texto; agora tem. O do IA vence,
    salvo se o nosso fecha o nível dos artigos e o do IA não (ADR-0019, fila
    ``sem-texto``). Quatro combinações (IA fecha, nosso fecha):

    - (sim, sim) → IA; (sim, não) → IA; (não, não) → IA;
    - (não, sim) → nosso.

    Devolve ``FONTE_IA`` ou ``FONTE_PROPRIA``. Determinístico, sem LLM.
    """
    ia_closes, _ = read_closure(ia_text)
    if ia_closes:
        return FONTE_IA
    own_closes, _ = read_closure(own_text)
    return FONTE_PROPRIA if own_closes else FONTE_IA


def _converted_text_layer(pdf_entry: dict[str, Any]) -> Optional[str]:
    """``TEXT_LAYER_CONVERSION`` se o PDF de origem é um "Text PDF" no IA."""
    return TEXT_LAYER_CONVERSION if pdf_entry.get("format") == "Text PDF" else None


def _mtime_iso(entry: dict[str, Any]) -> Optional[str]:
    try:
        return datetime.fromtimestamp(int(entry["mtime"]), tz=timezone.utc).isoformat()
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return None


@dataclass
class BuildStats:
    """Resultado de uma construção de ``textos``.

    ``failures`` lista o que não pôde ser lido agora; com qualquer falha o
    resultado é **parcial** (``complete`` False) e não deve substituir uma
    publicação anterior sem decisão explícita.
    """

    itens: int = 0
    identidades: int = 0
    com_texto: int = 0
    baixados: int = 0
    reaproveitados: int = 0
    #: Linhas do release anterior mantidas porque o texto não está no IA agora
    #: (derive em refação) e o arquivo de origem não mudou.
    mantidos: int = 0
    #: Linhas cujo texto foi trocado por um re-OCR aceito (ADR-0019).
    reocr_aplicados: int = 0
    #: Linhas criadas só com o OCR próprio (fila ``sem-texto``): o IA ainda não
    #: tem ``_djvu.txt`` da norma.
    reocr_sem_texto: int = 0
    truncated: bool = False
    failures: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.failures and not self.truncated


def _iter_identidades(
    ente: str,
    fonte: str,
    *,
    stats: BuildStats,
    fetch: Optional[Fetcher] = None,
) -> Iterator[
    tuple[
        str,
        str,
        int,
        list[dict[str, str]],
        dict[str, dict[str, Any]],
    ]
]:
    """Enumeração das normas preservadas de uma fonte (compartilhada).

    Itens de range por prefixo → ``index.csv`` → arquivos do item. Produz
    ``(item_id, tipo, numero, capturas, arquivos)`` por identidade, ordenado, e
    registra falhas e contadores em ``stats``. Quem consome decide o que fazer com
    cada identidade (``collect_fonte``: linhas de ``textos``; ``collect_sem_texto``:
    PDFs sem texto do IA).
    """
    prefix = f"leizilla_{ente.lower()}_{fonte.lower()}_"
    item_ids = publisher.scrape_identifiers(prefix)
    if item_ids is None:
        stats.failures.append(f"{fonte}: falha ao listar itens ({prefix}*)")
        return

    for item_id in sorted(item_ids):
        if item_id.endswith(_UNIDENTIFIED_SUFFIX):
            continue  # área de espera: sem identidade, fora do catálogo (ADR-0011)
        try:
            index_csv = publisher.fetch_existing_index(item_id)
        except publisher.IndexFetchError as e:
            stats.failures.append(f"{item_id}: index.csv indisponível ({e})")
            continue
        if index_csv is None:
            continue  # item sem índice ainda
        stats.itens += 1
        captures = captures_by_identity(index_csv)
        stats.identidades += len(captures)
        files = fetch_item_files(item_id, fetch)
        if files is None:
            stats.failures.append(f"{item_id}: metadata indisponível")
            continue
        for (tipo, numero), candidates in sorted(captures.items()):
            yield item_id, tipo, numero, candidates, files


def _pdf_name(
    capture: dict[str, str], files: dict[str, dict[str, Any]]
) -> Optional[str]:
    """Nome do PDF da captura dentro do item (``…{uuid5}.pdf``), se está no item."""
    suffix = f"{capture['uuid5']}.pdf"
    names = sorted(n for n in files if n.endswith(suffix) and "/" not in n)
    return names[0] if names else None


def collect_fonte(
    ente: str,
    fonte: str,
    *,
    stats: BuildStats,
    sleep_s: float = DEFAULT_SLEEP_S,
    limit: Optional[int] = None,
    previous: Optional[dict[str, dict[str, Any]]] = None,
    fetch: Optional[Fetcher] = None,
    reocr: Optional[dict[str, dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Linhas de ``textos`` de uma fonte. Sequencial, com pausa entre downloads."""
    fetch = fetch or http_get
    rows: list[dict[str, Any]] = []
    for item_id, tipo, numero, candidates, files in _iter_identidades(
        ente, fonte, stats=stats, fetch=fetch
    ):
        if limit is not None and len(rows) >= limit:
            stats.truncated = True
            return rows
        chosen = _first_with_text(candidates, files)
        if chosen is None:
            # S2 sem S3 agora. Se a norma já esteve legível e os bytes de
            # origem são os mesmos, o texto continua valendo: o IA apaga o
            # ``_djvu.txt`` enquanto refaz o derive de um arquivo reenviado
            # (achado de 2026-11-15: a Lei 1738 sumiu de um release assim).
            tid = texto_id(ente, fonte, tipo, numero)
            kept = _keep_previous((previous or {}).get(tid), candidates)
            own = _own_row(
                ente, fonte, tipo, numero, item_id, candidates, files, (reocr or {})
            )
            if own is not None and (
                kept is None or kept.get("ocr_motor") == REOCR_MOTOR
            ):
                # Fila ``sem-texto`` (ADR-0019): o IA ainda não tem o texto, o
                # nosso OCR tem. Se o que se manteria é um texto do IA do release
                # anterior, ele fica e o overlay decide.
                rows.append(own)
                stats.reocr_sem_texto += 1
            elif kept is not None:
                rows.append(kept)
                stats.mantidos += 1
            continue
        capture, texto_name = chosen
        stats.com_texto += 1
        entry = files[texto_name]
        sha1_ia = str(entry.get("sha1") or "") or None
        tid = texto_id(ente, fonte, tipo, numero)

        old = (previous or {}).get(tid)
        if (
            old is not None
            and sha1_ia is not None
            and old.get("sha1_texto_ia") == sha1_ia
            and old.get("sha256_fonte") == capture.get("sha256")
            and old.get("texto")
        ):
            rows.append(refresh_anchors(old))
            stats.reaproveitados += 1
            continue

        text_bytes = fetch(download_url(item_id, texto_name))
        time.sleep(sleep_s)
        if text_bytes is None:
            stats.failures.append(f"{item_id}/{texto_name}: download falhou")
            continue
        if sha1_ia and hashlib.sha1(text_bytes).hexdigest() != sha1_ia:
            stats.failures.append(f"{item_id}/{texto_name}: sha1 diverge do IA")
            continue
        if not text_bytes.strip():
            continue  # OCR vazio não é texto legível
        stats.baixados += 1
        stem = texto_name[: -len(_DJVU_SUFFIX)]
        ocr = files.get(f"{stem}{_CHOCR_SUFFIX}", {})
        rows.append(
            build_row(
                ente=ente,
                fonte=fonte,
                tipo=tipo,
                numero=numero,
                rendicao=capture.get("rendicao") or "",
                sha256_fonte=capture.get("sha256") or "",
                capturado_em=capture.get("captured_at") or "",
                ia_item=item_id,
                pdf_name=f"{stem}.pdf",
                texto_name=texto_name,
                text_bytes=text_bytes,
                ocr_motor=ocr.get("ocr")
                or _converted_text_layer(files.get(f"{stem}.pdf", {})),
                ocr_modulo_versao=ocr.get("ocr_module_version"),
                ocr_parametros=ocr.get("ocr_parameters"),
                ocr_derivado_em=_mtime_iso(entry),
                sha1_texto_ia=sha1_ia,
            )
        )
    return rows


def _own_row(
    ente: str,
    fonte: str,
    tipo: str,
    numero: int,
    item_id: str,
    candidates: list[dict[str, str]],
    files: dict[str, dict[str, Any]],
    accepted: dict[str, dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Linha de ``textos`` só com o OCR próprio aceito (fila ``sem-texto``).

    Vale se há um re-OCR aceito da fila ``sem-texto`` cujo ``sha256_fonte`` é o de
    uma captura da norma que está no item. ``texto_url`` e ``sha1_texto_ia`` ficam
    vazios: não há ``_djvu.txt`` do IA. Rendição e data de captura vêm do
    ``index.csv``, como nas linhas do IA.
    """
    hit = accepted.get(texto_id(ente, fonte, tipo, numero))
    if hit is None or hit.get("fila") != FILA_SEM_TEXTO or not hit.get("texto"):
        return None
    capture = next(
        (c for c in candidates if c.get("sha256") == hit.get("sha256_fonte")), None
    )
    pdf_name = _pdf_name(capture, files) if capture is not None else None
    if capture is None or pdf_name is None:
        return None
    row = build_row(
        ente=ente,
        fonte=fonte,
        tipo=tipo,
        numero=numero,
        rendicao=capture.get("rendicao") or "",
        sha256_fonte=capture.get("sha256") or "",
        capturado_em=capture.get("captured_at") or "",
        ia_item=item_id,
        pdf_name=pdf_name,
        texto_name="",
        text_bytes=str(hit["texto"]).encode("utf-8"),
    )
    _set_own_text(row, hit)
    row["texto_url"] = None
    return row


def collect_sem_texto(
    ente: str,
    fonte: str,
    *,
    stats: BuildStats,
    com_texto: set[str],
    fetch: Optional[Fetcher] = None,
) -> list[dict[str, Any]]:
    """PDFs preservados sem texto do IA e fora de ``textos`` (fila ``sem-texto``).

    Mesma enumeração de ``collect_fonte``. Uma norma entra se **nenhuma** captura
    tem ``_djvu.txt`` no item agora e seu ``texto_id`` não está em ``com_texto``
    (os ``texto_id`` com texto no ``textos`` publicado — o texto "mantido" de um
    derive em refação conta). A captura escolhida é a mais recente cujo PDF está
    no item. Cada item: identidade, ``ia_item``, ``pdf_url``, ``sha256_fonte``,
    ``capturado_em``, ``rendicao``.
    """
    out: list[dict[str, Any]] = []
    for item_id, tipo, numero, candidates, files in _iter_identidades(
        ente, fonte, stats=stats, fetch=fetch
    ):
        tid = texto_id(ente, fonte, tipo, numero)
        if tid in com_texto or _first_with_text(candidates, files) is not None:
            continue
        for capture in candidates:
            pdf_name = _pdf_name(capture, files)
            if pdf_name is None or not capture.get("sha256"):
                continue
            out.append(
                {
                    "texto_id": tid,
                    "ente": ente.lower(),
                    "fonte": fonte.lower(),
                    "tipo": tipo,
                    "numero": numero,
                    "ia_item": item_id,
                    "pdf_url": download_url(item_id, pdf_name),
                    "sha256_fonte": capture["sha256"],
                    "capturado_em": capture.get("captured_at") or "",
                    "rendicao": capture.get("rendicao") or "",
                }
            )
            break
    return out


def _first_with_text(
    candidates: list[dict[str, str]], files: dict[str, dict[str, Any]]
) -> Optional[tuple[dict[str, str], str]]:
    """Captura mais recente cujo ``_djvu.txt`` já existe no item, e o nome dele."""
    for capture in candidates:
        suffix = f"{capture['uuid5']}{_DJVU_SUFFIX}"
        names = sorted(n for n in files if n.endswith(suffix) and "/" not in n)
        if names:
            return capture, names[0]
    return None


def _keep_previous(
    old: Optional[dict[str, Any]], candidates: list[dict[str, str]]
) -> Optional[dict[str, Any]]:
    """Linha anterior de uma norma cujo texto não está disponível agora, ou None.

    Só é mantida se o ``sha256`` do arquivo de origem daquela linha ainda é uma
    captura da norma: mesmo documento, só o OCR temporariamente ausente. Se a
    origem mudou, o texto antigo não descreve mais o que está preservado.
    """
    if not old or not old.get("texto") or not old.get("sha256_fonte"):
        return None
    if old["sha256_fonte"] not in {c.get("sha256") for c in candidates}:
        return None
    return refresh_anchors(old)


def _set_own_text(row: dict[str, Any], hit: dict[str, Any]) -> None:
    """Põe em ``row`` o texto de um re-OCR aceito e tudo o que deriva dele.

    Identidade, elo com o PDF e ``texto_url`` não mudam. ``ocr_motor`` /
    ``ocr_modulo_versao`` / ``ocr_parametros`` / ``ocr_derivado_em`` dizem de onde o
    texto veio; ``sha1_texto_ia`` fica vazio (o texto não é o do IA).
    """
    text = str(hit["texto"])
    anchors, closes, last = article_anchors(text)
    row.update(
        ocr_motor=REOCR_MOTOR,
        ocr_modulo_versao=hit.get("kreuzberg_version"),
        ocr_parametros=hit.get("parametros"),
        ocr_derivado_em=hit.get("tentado_em"),
        sha1_texto_ia=None,
        sha256_texto=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        num_caracteres=len(text),
        artigos_fecham=closes,
        artigos_total=len(anchors),
        artigos_ultimo=last,
        ancoras=json.dumps(anchors, ensure_ascii=False, separators=(",", ":")),
        trecho=make_trecho(text),
        texto=text,
    )


def apply_reocr_overlay(
    rows: list[dict[str, Any]], accepted: dict[str, dict[str, Any]]
) -> int:
    """Troca, in loco, o texto das linhas que têm re-OCR aceito (ADR-0019).

    ``accepted`` é ``texto_id`` → linha aceita de ``reocr.parquet``. Só vale se o
    ``sha256_fonte`` do re-OCR é o do arquivo de origem da linha: PDF novo, texto
    do IA de novo. O que muda é o texto e o que deriva dele; a identidade, o elo
    com o PDF e ``texto_url`` (o ``_djvu.txt`` original) ficam. Devolve quantas
    linhas foram trocadas.

    - Fila ``nao-fecha``: o texto aceito já passou no portão contra o do IA e
      substitui o dele.
    - Fila ``sem-texto``: o OCR próprio foi aceito quando o IA não tinha texto; se
      o IA já tem, ``choose_text_source`` decide (o do IA, salvo se só o nosso
      fecha). Linha que já é o OCR próprio (mesmo ``sha256_texto``) não conta.
    """
    applied = 0
    for row in rows:
        hit = accepted.get(str(row["texto_id"]))
        if hit is None or hit.get("sha256_fonte") != row.get("sha256_fonte"):
            continue
        if row.get("ocr_motor") == REOCR_MOTOR and (
            row.get("sha256_texto") == hit.get("sha256_texto")
        ):
            continue  # já é este texto (linha criada de ``sem-texto``)
        if hit.get("fila") == FILA_SEM_TEXTO and (
            choose_text_source(str(row["texto"]), str(hit["texto"])) == FONTE_IA
        ):
            continue
        _set_own_text(row, hit)
        applied += 1
    return applied


def build_textos(
    ente: str,
    fontes: list[str],
    *,
    sleep_s: float = DEFAULT_SLEEP_S,
    limit: Optional[int] = None,
    previous: Optional[dict[str, dict[str, Any]]] = None,
    fetch: Optional[Fetcher] = None,
    reocr: Optional[dict[str, dict[str, Any]]] = None,
) -> tuple[list[dict[str, Any]], BuildStats]:
    """Constrói as linhas de ``textos`` de um ente (todas as fontes pedidas).

    ``reocr`` (opcional) são os re-OCRs aceitos (``reocr.load_accepted``): quando há,
    o texto aceito de uma norma da fila ``nao-fecha`` substitui o do IA; o da fila
    ``sem-texto`` vira uma linha nova se o IA ainda não tem texto da norma e, se já
    tem, ``choose_text_source`` decide. Sem ele, o comportamento é o de sempre. Uma linha com texto sobreposto não é reaproveitada de ``previous``
    (seu ``sha1_texto_ia`` é vazio): o texto do IA é baixado de novo e a
    sobreposição reaplicada, o que também desfaz uma sobreposição que deixou de valer.
    """
    stats = BuildStats()
    rows: list[dict[str, Any]] = []
    for fonte in fontes:
        remaining = None if limit is None else max(0, limit - len(rows))
        rows.extend(
            collect_fonte(
                ente,
                fonte,
                stats=stats,
                sleep_s=sleep_s,
                limit=remaining,
                previous=previous,
                fetch=fetch,
                reocr=reocr,
            )
        )
    if reocr:
        stats.reocr_aplicados = apply_reocr_overlay(rows, reocr)
    rows.sort(key=lambda r: str(r["texto_id"]))
    return rows, stats


def write_textos_parquet(rows: list[dict[str, Any]], output_path: Path) -> None:
    """Grava ``textos`` em Parquet (ZSTD), ordenado por ``texto_id``."""
    import duckdb

    if not rows:
        raise ValueError("rows is empty — nothing to write")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(TEXTOS_SCHEMA)
    conn = duckdb.connect()
    try:
        conn.execute(
            "CREATE TABLE textos ("
            + ", ".join(f"{c} {t}" for c, t in TEXTOS_SCHEMA.items())
            + ")"
        )
        conn.executemany(
            f"INSERT INTO textos VALUES ({', '.join('?' for _ in cols)})",
            [[row.get(c) for c in cols] for row in rows],
        )
        target = str(output_path).replace("'", "''")
        conn.execute(
            f"COPY (SELECT * FROM textos ORDER BY texto_id) TO '{target}' "
            "(FORMAT parquet, COMPRESSION zstd)"
        )
    finally:
        conn.close()


def read_textos_parquet(path: Path) -> dict[str, dict[str, Any]]:
    """Lê um ``textos.parquet`` anterior como ``texto_id → linha`` (reuso)."""
    import duckdb

    conn = duckdb.connect()
    try:
        cur = conn.execute("SELECT * FROM read_parquet(?)", [str(path)])
        names = [d[0] for d in cur.description or []]
        return {
            str(rec["texto_id"]): rec
            for rec in (dict(zip(names, values)) for values in cur.fetchall())
        }
    finally:
        conn.close()


def validate_textos_parquet(path: Path) -> list[str]:
    """Gate próprio de ``textos`` (ADR-0015): lista de violações, vazia se OK.

    Checa o contrato de colunas, unicidade da identidade, texto não vazio, a
    marca de qualidade e que toda âncora cabe no texto e aponta para um
    marcador de artigo — sem reinterpretar o conteúdo.
    """
    import duckdb

    problems: list[str] = []
    conn = duckdb.connect()
    try:
        src = "read_parquet(?)"
        described = conn.execute(f"DESCRIBE SELECT * FROM {src}", [str(path)])
        actual = {r[0]: r[1] for r in described.fetchall()}
        if actual != TEXTOS_SCHEMA:
            return [
                f"colunas divergem do contrato: {sorted(set(actual) ^ set(TEXTOS_SCHEMA)) or 'tipos'}"
            ]
        dup = conn.execute(
            f"SELECT count(*) - count(DISTINCT texto_id) FROM {src}", [str(path)]
        ).fetchone()
        if dup and dup[0]:
            problems.append(f"{dup[0]} texto_id duplicado(s)")
        bad = conn.execute(
            f"SELECT count(*) FROM {src} WHERE texto IS NULL OR trim(texto) = '' "
            "OR qualidade IS DISTINCT FROM ? OR pdf_url IS NULL OR ia_item IS NULL "
            "OR sha256_fonte IS NULL OR sha256_fonte = '' "
            "OR texto_id IS DISTINCT FROM 'leizilla-raw-' || ente || '-' || fonte "
            "|| '-' || tipo || '-' || lpad(CAST(numero AS VARCHAR), 5, '0')",
            [str(path), QUALIDADE_NAO_ESTRUTURADO],
        ).fetchone()
        if bad and bad[0]:
            problems.append(f"{bad[0]} linha(s) violam os campos obrigatórios")
        rows = conn.execute(
            f"SELECT texto_id, texto, ancoras FROM {src}", [str(path)]
        ).fetchall()
    finally:
        conn.close()

    for tid, text, anchors_json in rows:
        try:
            anchors = json.loads(anchors_json or "[]")
        except json.JSONDecodeError:
            problems.append(f"{tid}: ancoras não é JSON")
            continue
        prev_end = 0
        for a in anchors:
            ini, fim = a.get("ini"), a.get("fim")
            if (
                not isinstance(ini, int)
                or not isinstance(fim, int)
                or not (prev_end <= ini < fim <= len(text or ""))
            ):
                problems.append(f"{tid}: âncora fora do texto ou fora de ordem")
                break
            prev_end = fim
    return problems


def build_textos_meta(
    parquet_path: Path,
    ente: str,
    version: int,
    revision: str,
    git_sha: Optional[str] = None,
) -> dict[str, Any]:
    """``dataset_meta.json`` do item de ``textos`` (mesma forma do de ``versoes``)."""
    import duckdb

    conn = duckdb.connect()
    try:
        counts = conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE artigos_fecham) "
            "FROM read_parquet(?)",
            [str(parquet_path)],
        ).fetchone() or (0, 0)
    finally:
        conn.close()
    meta: dict[str, Any] = {
        "leizilla_meta_version": "0.1",
        "schema_version": "0.1",
        "ente": ente,
        "version": version,
        "revision": revision,
        "table": "textos",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "row_count": int(counts[0]),
        "rows_artigos_fecham": int(counts[1]),
        "file_size_bytes": parquet_path.stat().st_size,
        "hash_parquet": (
            f"sha256:{hashlib.sha256(parquet_path.read_bytes()).hexdigest()}"
        ),
    }
    if git_sha:
        meta["git_sha"] = git_sha
    return meta
