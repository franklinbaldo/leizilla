import asyncio
import sys
from pathlib import Path
from playwright.async_api import async_playwright

async def verify():
    print("🚀 Iniciando verificação do browser local com Playwright...")
    async with async_playwright() as p:
        # Abre o Chromium headless
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Captura mensagens de console do navegador
        page.on("console", lambda msg: print(f"🌐 [CONSOLE {msg.type.upper()}]: {msg.text}"))
        page.on("pageerror", lambda err: print(f"❌ [PAGE ERROR]: {err.message}"))
        
        url = "http://localhost:4321/leizilla"
        print(f"🔗 Navegando para {url}...")
        
        try:
            await page.goto(url, timeout=10000)
            print("⏳ Aguardando 6 segundos para carregamento do DuckDB-WASM e consulta SQL...")
            await asyncio.sleep(6)
            
            # Tira um screenshot
            screenshot_path = Path("data/verify_screenshot.png")
            screenshot_path.parent.mkdir(exist_ok=True, parents=True)
            await page.screenshot(path=str(screenshot_path))
            print(f"📸 Screenshot salvo em: {screenshot_path.resolve()}")
            
            # Pega o HTML da seção de estatísticas e da tabela
            stats = await page.locator(".stats").inner_text()
            print(f"📊 Estatísticas encontradas: {stats}")
            
            rows = await page.locator("tbody tr").all_inner_texts()
            print(f"📋 Linhas da tabela encontradas ({len(rows)}):")
            for idx, r in enumerate(rows[:5]):
                print(f"  [{idx + 1}]: {r.replace('\n', ' | ')}")
                
            main_html = await page.locator("main").inner_html()
            if "Carregando..." in main_html:
                print("⚠️  Aviso: O site ainda está em estado de 'Carregando...'!")
            elif "Nenhum resultado encontrado" in main_html:
                print("⚠️  Aviso: O site carregou mas retornou 0 resultados!")
            else:
                print("✅ Sucesso: O site carregou as normas perfeitamente!")
                
        except Exception as e:
            print(f"❌ Erro durante a navegação/verificação: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(verify())
