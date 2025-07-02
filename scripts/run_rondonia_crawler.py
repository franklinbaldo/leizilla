import asyncio
import os
from pathlib import Path
import logging

from src.crawler import LeisCrawler
from src.publisher import InternetArchivePublisher
from src.config import TEMP_DIR, IA_ACCESS_KEY, IA_SECRET_KEY

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration for the crawler
# For a real scenario, these might come from env variables or a config file
# For now, let's define a small range to avoid very long runs in CI.
# A more robust solution would involve storing the last crawled 'coddoc'
# or focusing on laws published within a certain recent timeframe.
START_CODDOC = 1
END_CODDOC = 5 # Small range for demonstration/testing in CI

async def main():
    """
    Main function to discover, download, and upload Rondônia laws.
    """
    logger.info("Starting Rondônia law crawler and publisher process...")

    if not IA_ACCESS_KEY or not IA_SECRET_KEY:
        logger.error("Internet Archive API keys (IA_ACCESS_KEY, IA_SECRET_KEY) are not set.")
        logger.error("Please set them as environment variables (e.g., in GitHub secrets).")
        return

    crawler = LeisCrawler(crawler_type="simple") # Using simple crawler for CI to avoid Playwright complexities unless necessary
    publisher = InternetArchivePublisher()

    try:
        await crawler.start() # Important if using Playwright, less so for 'simple'

        logger.info(f"Discovering laws for Rondônia with coddoc from {START_CODDOC} to {END_CODDOC}...")
        discovered_laws = await crawler.discover_rondonia_laws(
            start_coddoc=START_CODDOC,
            end_coddoc=END_CODDOC
        )

        if not discovered_laws:
            logger.info("No new laws discovered in the specified range.")
            return

        logger.info(f"Discovered {len(discovered_laws)} potential laws.")

        successful_uploads = 0
        for law_metadata in discovered_laws:
            pdf_url_found = law_metadata.get('metadados', {}).get('pdf_url_found')
            if not pdf_url_found:
                logger.warning(f"No PDF URL found for: {law_metadata.get('titulo', law_metadata.get('id'))}. Skipping.")
                continue

            # Define a unique filename for the PDF
            # Example: rondonia-coddoc-123.pdf
            pdf_filename = f"{law_metadata['id']}.pdf"
            pdf_output_path = TEMP_DIR / pdf_filename

            logger.info(f"Downloading PDF from {pdf_url_found} for {law_metadata.get('titulo')}...")
            download_success = await crawler.download_pdf(pdf_url_found, pdf_output_path)

            if download_success:
                logger.info(f"PDF downloaded successfully: {pdf_output_path}")

                # Enrich metadata for IA if needed (publisher already does a good job)
                # law_metadata['collection'] = 'leizilla-rondonia' # Example

                logger.info(f"Uploading {pdf_output_path.name} to Internet Archive...")
                upload_result = publisher.upload_pdf(pdf_output_path, law_metadata)

                if upload_result.get('success'):
                    logger.info(f"Successfully uploaded {pdf_output_path.name} to IA: {upload_result.get('ia_detail_url')}")
                    successful_uploads += 1
                    # Optionally, update database or state file here with IA URL
                    # For example: law_metadata['url_pdf_ia'] = upload_result.get('ia_pdf_url')
                    # await storage.update_law_ia_url(law_metadata['id'], upload_result.get('ia_pdf_url'))
                else:
                    logger.error(f"Failed to upload {pdf_output_path.name} to IA. Error: {upload_result.get('error')}")

                # Clean up downloaded PDF
                try:
                    os.remove(pdf_output_path)
                    logger.info(f"Cleaned up temporary file: {pdf_output_path}")
                except OSError as e:
                    logger.error(f"Error deleting temporary file {pdf_output_path}: {e}")
            else:
                logger.error(f"Failed to download PDF for {law_metadata.get('titulo')} from {pdf_url_found}.")

        logger.info(f"Process completed. Successfully uploaded {successful_uploads}/{len(discovered_laws)} laws.")

    except Exception as e:
        logger.error(f"An error occurred during the crawling/publishing process: {e}", exc_info=True)
    finally:
        await crawler.stop() # Important if using Playwright

if __name__ == "__main__":
    # Ensure TEMP_DIR exists (config.py tries to create it, but good to double-check)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    asyncio.run(main())
