from celery import shared_task
from django.utils import timezone
from .models import Run, Script
import os
import json
import traceback
from datetime import datetime


@shared_task(bind=True)
def execute_script_task(self, script_id, run_id, input_data):
    run = Run.objects.get(id=run_id)
    script = Script.objects.get(id=script_id)

    # Setup logging
    log_path = run.logs_file_path
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    logger = logging.getLogger(f"run_{run_id}")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        handler = logging.handlers.RotatingFileHandler(log_path, maxBytes=10*1024*1024, backupCount=5)
        formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    try:
        run.status = 'RECEIVED'
        run.celery_task_id = self.request.id
        run.save()

        logger.info("Task received by worker")
        logger.info(f"Starting task: {script.name}")
        logger.debug(f"Input data: {json.dumps(input_data, indent=2)}")

        run.status = 'STARTED'
        run.save()

        # Call as regular function
        result = scrape_kleinanzeigen_brand_task(run_id, input_data, log_path)

        # Save final result
        result_path = run.result_file_path
        os.makedirs(os.path.dirname(result_path), exist_ok=True)
        with open(result_path, 'w') as f:
            json.dump(result, f, indent=2)

        run.result_data = result
        run.status = 'SUCCESS'
        run.finished_at = timezone.now()
        run.save()

        logger.info("Task completed successfully")
        return {'status': 'success', 'run_id': run_id}

    except Exception as e:
        logger.error(f"Task failed: {str(e)}\n{traceback.format_exc()}")
        run.status = 'FAILURE'
        run.error_message = str(e)
        run.finished_at = timezone.now()
        run.save()
        raise

def scrape_kleinanzeigen_brand_task(run_id, input_data, log_path):
    from playwright.sync_api import sync_playwright
    from bs4 import BeautifulSoup
    import time
    import urllib.parse

    # Setup logger
    logger = logging.getLogger(f"scrape_{run_id}")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        handler = logging.handlers.RotatingFileHandler(log_path, maxBytes=10*1024*1024, backupCount=5)
        formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    brands = [item['brand'] for item in input_data.get('brands', []) if item.get('brand')]
    max_pages = input_data.get('maxPages', 50)
    search_query = input_data.get('searchQuery', 'Druckerpatrone')

    if not brands:
        logger.error("No brands provided")
        raise ValueError("No brands provided")

    all_results = []
    run = Run.objects.get(id=run_id)
    result_path = run.result_file_path
    os.makedirs(os.path.dirname(result_path), exist_ok=True)

    logger.info(f"Scraping {len(brands)} brand(s): {', '.join(brands)}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for brand in brands:
            logger.info(f"Processing brand: {brand}")
            page = browser.new_page()
            page_num = 1

            try:
                while page_num <= max_pages:
                    search_term = f"{search_query} {brand}"
                    encoded = urllib.parse.quote(search_term.replace(" ", "-"))
                    url = f"https://www.kleinanzeigen.de/s-{encoded}/k0" if page_num == 1 else f"https://www.kleinanzeigen.de/s-seite:{page_num}/{encoded}/k0"

                    logger.debug(f"Loading page {page_num}: {url}")
                    try:
                        page.goto(url, timeout=30000)
                        page.wait_for_selector("article", timeout=30000)
                    except Exception as e:
                        logger.warning(f"Page load failed: {e}")
                        break

                    soup = BeautifulSoup(page.content(), "html.parser")
                    ads = soup.select("article")
                    if not ads:
                        logger.info(f"No ads on page {page_num}")
                        break

                    for ad in ads:
                        try:
                            link_el = ad.select_one(".ellipsis")
                            link = "https://www.kleinanzeigen.de" + link_el["href"] if link_el else ""
                            title = ad.select_one("h2").get_text(strip=True).replace(",", "") if ad.select_one("h2") else ""
                            price = ad.select_one("p.aditem-main--middle--price-shipping--price")
                            price = price.get_text(strip=True).split()[0] if price else ""

                            product = {"link": link, "brand": brand, "title": title, "price": price, "image_urls": [], "description": ""}

                            if link:
                                page.goto(link, timeout=30000)
                                # Images
                                try:
                                    page.wait_for_selector("#viewad-image", timeout=10000)
                                    product["image_urls"] = [img.get_attribute("src") for img in page.query_selector_all("#viewad-image") if img.get_attribute("src")]
                                except: pass
                                # Description
                                try:
                                    page.wait_for_selector("#viewad-description-text", timeout=10000)
                                    desc = page.query_selector("#viewad-description-text")
                                    product["description"] = desc.inner_text().strip().replace(",", " ") if desc else ""
                                except: pass

                            all_results.append(product)

                            # SAVE AFTER EACH PRODUCT
                            with open(result_path, 'w') as f:
                                json.dump(all_results, f, indent=2)
                            
                            run.result_data = partial
                            run.save(update_fields=['result_data'])

                            logger.info(f"Product saved: {title[:50]}...")

                        except Exception as e:
                            logger.error(f"Ad parse error: {e}")
                            continue

                    page_num += 1
                    time.sleep(1)
            finally:
                page.close()
        browser.close()

    final_result = {
        'results': all_results,
        'total_count': len(all_results),
        'timestamp': datetime.now().isoformat(),
        'partial': False
    }
    logger.info(f"Scraping complete: {len(all_results)} products")
    return final_result