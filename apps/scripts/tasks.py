from django_eventstream import send_event
from django.utils import timezone
from .models import Run, Script
from celery import shared_task
from datetime import datetime
from .facebook_scraper.facebook_scraper_main import FacebookMarketplaceScraper
from .ai_product_analyzer.ai_product_analyzer import AIProductAnalyzer
from .utils import get_run_logger, ResultWriter
import traceback
import logging
import json
import time
import os

@shared_task(bind=True)
def execute_script_task(self, script_id, run_id, input_data, input_file_paths):
    run = Run.objects.select_related('script').get(id=run_id)
    script = Script.objects.get(id=script_id)

    # Setup logging
    log_path = run.logs_file_path
    logger = get_run_logger(run.id, log_path)

    output_path = run.result_file_path
    writer = ResultWriter(output_path, logger)

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
        result = None
        print(script.celery_task)
        if script.celery_task == "scrape_kleinanzeigen_brand_task":
            result = scrape_kleinanzeigen_brand_task(run_id, input_data, log_path)
        elif script.celery_task == "analyze_products":
            result = analyze_products(run, script, input_data, logger, writer)
        elif script.celery_task == "facebook_marketplace_scraper":
            result = scrape_facebook_marketplace(run, script, input_data, logger, writer)

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
    try:
        max_pages = int(input_data.get('maxPages', 5))
    except:
        max_pages = 5
    search_query = input_data.get('searchQuery', 'Druckerpatrone')

    if not brands:
        logger.error("No brands provided")
        raise ValueError("No brands provided")

    all_results = {}
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
            results = []

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

                    logger.debug(f"Found {len(ads)} product in the page: {page_num}")
                    for ad in ads:
                        try:
                            link_el = ad.select_one(".ellipsis")
                            link = "https://www.kleinanzeigen.de" + link_el.get('href') if link_el else ""
                            title = ad.select_one("h2").get_text(strip=True).replace(",", "") if ad.select_one("h2") else ""
                            price = ad.select_one("p.aditem-main--middle--price-shipping--price")
                            price = price.get_text(strip=True).split()[0] if price else ""

                            product = {"link": link, "brand": brand, "title": title, "price": price, "image_urls": [], "description": ""}

                            if link:
                                logger.debug(f"Fetching details: {link}")
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

                            results.append(product)

                            all_results[brand] = results
                            # SAVE AFTER EACH PRODUCT
                            with open(result_path, 'w') as f:
                                json.dump(all_results, f, indent=2)
                            
                            # run.result_data = partial
                            # run.save(update_fields=['result_data'])

                            logger.info(f"Product saved: {title[:50]}...")

                        except Exception as e:
                            logger.error(f"Ad parse error: {e}")
                            continue

                    page_num += 1
                    time.sleep(1)
            finally:
                page.close()
        browser.close()

    logger.info(f"Scraping complete: {len(all_results)} products")
    return all_results


@shared_task(bind=True)
def analyze_products(self, run, script, input_data, logger, writer):
    analyzer = AIProductAnalyzer(run, script, input_data, logger, writer)
    analyzer.start_processing()
    return analyzer.get_all_results()


@shared_task(bind=True)
def scrape_facebook_marketplace(self, run, script, input_data, logger, writer):
    facebook_scraper = FacebookMarketplaceScraper(run, script, input_data, logger, writer)
    return facebook_scraper.start_scraping()

@shared_task
def stream_logs(run_id, log_path, channel):
    # Start from end
    position = 0
    if os.path.exists(log_path):
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                f.seek(0, 2)  # SEEK_END
                position = f.tell()
        except:
            position = 0

    while True:
        try:
            run = Run.objects.get(pk=run_id)
        except Run.DoesNotExist:
            break

        # If finished → send final chunk + finish
        if run.is_finished():
            try:
                with open(log_path, 'r', encoding='utf-8') as f:
                    f.seek(position)
                    final_chunk = f.read()
                    if final_chunk:
                        send_event(channel, 'logs', {'logs': final_chunk})
                    send_event(channel, 'finished', {'finished': True})
            except Exception as e:
                send_event(channel, 'error', {'message': f'Final read error: {str(e)}'})
            break

        # Stream new data
        try:
            if os.path.exists(log_path):
                with open(log_path, 'r', encoding='utf-8') as f:
                    f.seek(position)
                    new_data = f.read().strip()
                    if new_data:
                        position = f.tell()
                        send_event(channel, 'logs', {'logs': new_data})
        except Exception as e:
            send_event(channel, 'error', {'message': f'Stream error: {str(e)}'})
            break

        time.sleep(1)