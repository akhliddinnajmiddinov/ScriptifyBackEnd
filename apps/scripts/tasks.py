from celery import shared_task
from django.utils import timezone
from .models import Run, Script
import os
import json
import traceback
from datetime import datetime


@shared_task(bind=True)
def execute_script_task(self, script_id, run_id, input_data):
    """
    Main celery task dispatcher that routes to the appropriate script task.
    This handles logging, status updates, and error handling.
    """
    run = Run.objects.get(id=run_id)
    script = Script.objects.get(id=script_id)
    
    try:
        # Log start
        log_path = run.logs_file_path
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        
        run.status = 'RECEIVED'
        run.celery_task_id = self.request.id
        run.save()
        
        with open(log_path, 'a') as f:
            f.write(f"[{datetime.now().isoformat()}] Task received by worker\n")
            f.write(f"[{datetime.now().isoformat()}] Starting task: {script.name}\n")
            f.write(f"[{datetime.now().isoformat()}] Input data: {json.dumps(input_data, indent=2)}\n\n")
        
        run.status = 'STARTED'
        run.save()
        
        # Execute the actual script task
        # Route to the appropriate task based on celery_task name
        task_name = script.celery_task
        
        if task_name == 'scripts.tasks.scrape_kleinanzeigen_brand':
            result = scrape_kleinanzeigen_brand_task(run_id, input_data, log_path)
        else:
            raise ValueError(f"Unknown task: {task_name}")
        
        # Save result
        result_path = run.result_file_path
        os.makedirs(os.path.dirname(result_path), exist_ok=True)
        with open(result_path, 'w') as f:
            json.dump(result, f, indent=2)
        
        run.result_data = result
        run.status = 'SUCCESS'
        run.finished_at = timezone.now()
        run.save()
        
        with open(log_path, 'a') as f:
            f.write(f"\n[{datetime.now().isoformat()}] Task completed successfully\n")
        
        return {'status': 'success', 'run_id': run_id}
    
    except Exception as e:
        # Log error
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        with open(log_path, 'a') as f:
            f.write(f"\n[{datetime.now().isoformat()}] ERROR: {error_msg}\n")
        
        run.status = 'FAILURE'
        run.error_message = str(e)
        run.finished_at = timezone.now()
        run.save()
        
        raise


def scrape_kleinanzeigen_brand_task(run_id, input_data, log_path):
    """
    Celery task for scraping Kleinanzeigen (German classifieds) for products.
    Input: { brands: [...], max_pages: int }
    Output: { results: [...] }
    """
    from playwright.sync_api import sync_playwright
    from bs4 import BeautifulSoup
    import pandas as pd
    import time
    import urllib.parse
    
    def log_msg(msg):
        with open(log_path, 'a') as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    
    brands = input_data.get('brands', [])
    max_pages = input_data.get('maxPages', 50)
    search_query = input_data.get('searchQuery', 'Druckerpatrone')
    
    if not brands:
        raise ValueError("No brands provided in input")
    
    all_results = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        
        for brand in brands:
            log_msg(f"Starting to scrape brand: {brand}")
            page = browser.new_page()
            page_num = 1
            
            try:
                while page_num <= max_pages:
                    search_term = f"{search_query} {brand}"
                    encoded_query = urllib.parse.quote_plus(search_term)
                    
                    if page_num == 1:
                        search_url = f"https://www.kleinanzeigen.de/s-{encoded_query}/k0"
                    else:
                        search_url = f"https://www.kleinanzeigen.de/s-seite:{page_num}/{encoded_query}/k0"
                    
                    log_msg(f"Scraping {brand} - Page {page_num}")
                    
                    try:
                        page.goto(search_url, timeout=30000)
                        page.wait_for_selector("article", timeout=10000)
                    except Exception as e:
                        log_msg(f"Failed to load page {page_num}: {e}")
                        break
                    
                    html = page.content()
                    soup = BeautifulSoup(html, "html.parser")
                    
                    ads_on_page = 0
                    products = []
                    
                    for ad in soup.select("article"):
                        try:
                            # Link
                            link_el = ad.select_one(".ellipsis")
                            link = "https://www.kleinanzeigen.de" + link_el["href"] if link_el and "href" in link_el.attrs else ""
                            
                            # Title
                            title_el = ad.select_one("h2")
                            title = title_el.get_text(strip=True).replace(",", "") if title_el else ""
                            
                            # Price
                            price_el = ad.select_one("p.aditem-main--middle--price-shipping--price")
                            price = price_el.get_text(strip=True) if price_el else ""
                            price = price.split(' ')[0] if price else ""
                            
                            products.append({
                                "link": link,
                                "brand": brand,
                                "title": title,
                                "price": price,
                                "image_urls": []
                            })
                        except Exception as e:
                            log_msg(f"Error parsing ad: {e}")
                            continue
                    
                    # Scrape details for each product
                    for product in products:
                        link = product.get('link')
                        if link:
                            try:
                                page.goto(link, timeout=30000)
                                
                                # Images
                                img_urls = []
                                try:
                                    page.wait_for_selector("#viewad-image", timeout=10000)
                                    img_elements = page.query_selector_all("#viewad-image")
                                    
                                    for img_el in img_elements:
                                        src = img_el.get_attribute("src")
                                        if src and src not in img_urls:
                                            img_urls.append(src)
                                except Exception as e:
                                    log_msg(f"Error getting images: {e}")
                                
                                product["image_urls"] = img_urls
                                
                                # Description
                                description_text = ""
                                try:
                                    page.wait_for_selector("#viewad-description-text", timeout=10000)
                                    description_el = page.query_selector("#viewad-description-text")
                                    description_text = description_el.inner_text().strip().replace(",", " ") if description_el else ""
                                except Exception as e:
                                    log_msg(f"Error getting description: {e}")
                                
                                product["description"] = description_text
                                ads_on_page += 1
                                all_results.append(product)
                            except Exception as e:
                                log_msg(f"Error scraping product detail: {e}")
                                continue
                    
                    # Break if no ads found
                    if ads_on_page == 0:
                        log_msg(f"No ads found on page {page_num}, finishing brand {brand}")
                        break
                    
                    page_num += 1
                    time.sleep(1)  # Be polite
            
            finally:
                page.close()
        
        browser.close()
    
    log_msg(f"Scraping complete. Total results: {len(all_results)}")
    
    return {
        'results': all_results,
        'total_count': len(all_results),
        'timestamp': datetime.now().isoformat()
    }
