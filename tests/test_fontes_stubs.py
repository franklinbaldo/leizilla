"""Testes de sanidade para fontes/sp.py e fontes/federal.py."""

from leizilla.fontes import federal, sp


class TestFontesSP:
    def test_fontes_list_not_empty(self) -> None:
        assert sp.FONTES

    def test_fonte_canonica_in_fontes(self) -> None:
        assert sp.FONTE_CANONICA in sp.FONTES

    def test_urls_keys_match_fontes(self) -> None:
        for fonte in sp.FONTES:
            assert fonte in sp.URLS, f"Fonte '{fonte}' sem URL declarada"

    def test_urls_are_https(self) -> None:
        for fonte, url in sp.URLS.items():
            assert url.startswith("https://"), f"URL de '{fonte}' não usa HTTPS: {url}"

    def test_legisp_is_canonica(self) -> None:
        assert sp.FONTE_CANONICA == "legisp"


class TestFontesFederal:
    def test_fontes_list_not_empty(self) -> None:
        assert federal.FONTES

    def test_fonte_canonica_in_fontes(self) -> None:
        assert federal.FONTE_CANONICA in federal.FONTES

    def test_urls_keys_match_fontes(self) -> None:
        for fonte in federal.FONTES:
            assert fonte in federal.URLS, f"Fonte '{fonte}' sem URL declarada"

    def test_urls_are_https(self) -> None:
        for fonte, url in federal.URLS.items():
            assert url.startswith("https://"), f"URL de '{fonte}' não usa HTTPS: {url}"

    def test_planalto_is_canonica(self) -> None:
        assert federal.FONTE_CANONICA == "planalto"

    def test_apis_subset_of_fontes(self) -> None:
        for api_fonte in federal.APIS:
            assert api_fonte in federal.FONTES, (
                f"API declarada para fonte desconhecida: {api_fonte}"
            )
