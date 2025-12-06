import pandas as pd
from playwright.sync_api import sync_playwright
import time
from collections import defaultdict

# Configuration
START_URL = "https://fleequid.com/en/auctions/bus?state%5B%5D=Running"

def extract_auction_data(auction_link):
    # Placeholder for auction data extraction logic
    print(f"Extracting data from {auction_link}...")
    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True) 
            
        # 2. specific context with a real User Agent
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        try:

            page.goto(auction_link)
            page.wait_for_load_state('networkidle')

            print(f"Page Title: {page.title()}")
        
            auction_reference = get_reference(page)

            #auction_whole_description = structure_data(get_whole_description(page))

            print(f"Auction Reference: {auction_reference}")
          #  auction_description = get_description(page)
            auction_engine_data = html_get_engine_data(page)
            #auction_axles_tires_data = get_axlesandtires_data(page)
                        
            # structured_description = structure_data(auction_description)
            # structured_engine_data = structure_data(auction_engine_data)


        except Exception as e:
            print(f"Error accessing page: {e}")
            return None
        finally:
            browser.close()


    return {"link": auction_link, "data": "Sample Data"}

def get_reference(page):
    reference = page.eval_on_selector(
                "span.select-all", 
                "element => element.textContent"
            )
    print(f"Reference: {reference}")
    return reference

def get_whole_description_js(page):
    # Return the visible text for the first `div.w-full` block.
    # Using `innerText` preserves visible formatting and excludes hidden markers.
    whole_description = page.eval_on_selector_all(
        "div.w-full", 
        r"""
        (divs) => {
            // Iterate through every 'w-full' container found
            return divs.map(div => {
                // Select all <p> tags. 
                // Note: We do not need to select 'span' separately because 
                // p.textContent includes the text inside the spans.
                const nodes = Array.from(div.querySelectorAll('p'));
                
                return nodes.map(node => {
                    // textContent gets raw text (including hidden ones)
                    // replace removes excessive whitespace/newlines
                    return node.textContent.replace(/\s+/g, ' ').trim();
                }).filter(text => text.length > 0); // Filter out empty strings
            }).flat(); // Combine all sections into one list
        }
        """
    )
    print(f"Whole Description: {whole_description}")
    return whole_description

def get_description(page):
    description = page.eval_on_selector(
        "div[role='region'][aria-labelledby*='accordion-trigger']",
        "element => Array.from(element.querySelectorAll('p')).map(p => p.textContent.trim())"
    )
    print(f"Description: {description}")
    return description

def html_get_engine_data(page):
    html = page.content()
    engine_section = html.split("reka-collapsible-content-v-0-5-0-4",1)[1].split("Axles and Tires",1)[0]
    #write to file for inspection
    with open("engine_section.html", "w", encoding="utf-8") as f:
        f.write(html)
   # print (f"Engine Section HTML: {engine_section}")


def get_engine_data(page):
    engine_data = page.eval_on_selector_(
        "div[role='region'][aria-labelledby*='reka-accordion-trigger']",
        "element => Array.from(element.querySelectorAll('p')).map(p => p.textContent.trim())"
    )
    print(f"Engine Data: {engine_data}")
    return engine_data

def get_axlesandtires_data(page):
    axles_tires_data = page.eval_on_selector(
        "div[aria-labelledby='reka-accordion-trigger-v-0-5-0-7']",
        "element => Array.from(element.querySelectorAll('p')).map(p => p.textContent.trim())"
    )
    print(f"Axles and Tires Data: {axles_tires_data}")
    return axles_tires_data

def structure_data(unstructured_data):
    # Initialize with list values
    data_dict = defaultdict(list)
    for entry in unstructured_data:
        parts = entry.split('\xa0')
        if len(parts) >= 2:
            data_dict[parts[0].strip()].append(parts[1].strip())
    return data_dict

def get_auction_links(url):
    print(f"Opening browser for {url}...")
    
    with sync_playwright() as p:
        # 1. Launch with headless=False to bypass basic bot detection
        browser = p.chromium.launch(headless=True) 
        
        # 2. specific context with a real User Agent
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        page = context.new_page()
        
        try:
            page.goto(url)
            
            # 3. Wait for the specific content to load, not just a time.sleep
            # This waits until the network is quiet (page fully loaded)
            page.wait_for_load_state('networkidle') 
            # Print page title to verify we are actually in
            print(f"Page Title: {page.title()}")
            # Optional: Wait specifically for the product grid if networkidle isn't enough
            # page.wait_for_selector('.product-card', timeout=10000)
            
            if page:
                #print("Success! Content length:", len(page))
                links = get_links(page)
                print("Extracted Links:")
                for link in links:
                    print(link)
            else:
                print("Failed to retrieve content.")
            return links
            
        except Exception as e:
            print(f"Error accessing page: {e}")
            return None
        finally:
            browser.close()

def get_links(page_content):
    print("Extracting auction links...")
    links = page_content.eval_on_selector_all(
            "a[href*='/auctions/dp/']", 
            "elements => elements.map(e => e.href)"
        )
        
        # Deduplicate links and filter out non-detail pages
    unique_links = list(set([l for l in links if len(l.split('/')) > 6]))
    print(f"Found {len(unique_links)} potential auctions.")
    return unique_links

def main():
    print("Starting extraction...")
   # auction_links = get_auction_links(START_URL)
    extract_auction_data("https://fleequid.com/en/auctions/dp/mercedes-benz-citaro-o-530-le-euro5-220kw-13057mt-28062b19-c136-4de9-8393-015ebd5ef7c8")
   

if __name__ == "__main__":
    main()