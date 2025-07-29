import dlt
from playwright.sync_api import sync_playwright

@dlt.resource(name="leis_rondonia")
def get_leis_rondonia(start_coddoc: int, end_coddoc: int):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        for coddoc in range(start_coddoc, end_coddoc + 1):
            try:
                url = f"https://sapl.al.ro.leg.br/norma/texto?norma={coddoc}"
                page.goto(url, wait_until="domcontentloaded")

                # Extrai o título da lei
                titulo_element = page.query_selector("h5.modal-title")
                titulo = titulo_element.inner_text().strip() if titulo_element else "Título não encontrado"

                # Extrai o texto da lei
                texto_element = page.query_selector("div.modal-body")
                texto = texto_element.inner_text().strip() if texto_element else "Texto não encontrado"

                if "não encontrada" not in titulo:
                    lei_data = {
                        "coddoc": coddoc,
                        "url": url,
                        "titulo": titulo,
                        "texto": texto,
                    }
                    yield lei_data
            except Exception as e:
                print(f"Erro ao processar coddoc {coddoc}: {e}")
        browser.close()
