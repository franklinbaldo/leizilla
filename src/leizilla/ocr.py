"""Módulo para download e normalização do texto de OCR do Internet Archive."""

import re
import unicodedata
from typing import Optional
from leizilla.parser import fetch_ocr


def clean_ocr_text(text: str) -> str:
    """Limpa ruídos óbvios e formatações indesejadas do OCR bruto."""
    if not text:
        return ""
    # Remove caracteres de controle estranhos, mantendo quebras de linha comuns
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\xff]", "", text)
    return cleaned.strip()


def normalize_text(text: str) -> str:
    """Normaliza texto para a coluna texto_normalizado (busca rápida).

    Remove acentos, converte para minúsculo, remove pontuação e excesso de espaços.
    """
    if not text:
        return ""
    # Remove acentos e diacríticos
    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join([c for c in normalized if not unicodedata.combining(c)])
    # Minúsculo
    normalized = normalized.lower()
    # Substituir quebras de linha e múltiplos espaços por um espaço simples
    normalized = re.sub(r"\s+", " ", normalized)
    # Remover caracteres especiais mantendo apenas letras, números e espaços simples
    normalized = re.sub(r"[^a-z0-9\s]", "", normalized)
    return normalized.strip()


def fetch_and_clean_ocr(ia_id: str) -> Optional[str]:
    """Busca o texto de OCR do IA e limpa ruídos iniciais."""
    raw_text = fetch_ocr(ia_id)
    if raw_text is None:
        return None
    return clean_ocr_text(raw_text)
