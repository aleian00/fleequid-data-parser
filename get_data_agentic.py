import time
import json
import pandas as pd
import ollama
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import os
import logging

# --- Configuration ---
OLLAMA_MODEL = "llama3.1" 
CSV_FILE = "output/auction_data.csv"
URL = "https://fleequid.com/en/auctions/dp/mercedes-benz-citaro-o-530-le-euro5-220kw-13057mt-6a817410-c004-454e-aead-9b3394770857"

# --- Logging Setup ---
os.makedirs("log", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("log/agent.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def get_target_schema():
    """Reads the CSV to get the list of column names for structured extraction."""
    os.makedirs(os.path.dirname(CSV_FILE), exist_ok=True)
    
    if not os.path.exists(CSV_FILE):
        logger.warning(f"{CSV_FILE} not found. Creating empty file.")
        pd.DataFrame(columns=["Reference", "Name"]).to_csv(CSV_FILE, index=False)
    
    df = pd.read_csv(CSV_FILE)
    logger.info(f"Schema loaded: {df.columns.tolist()}")
    return df.columns.tolist()

def get_static_data(page):
    """Helper function to extract static data using Playwright selectors."""
    try:
        reference = page.eval_on_selector(
                    "span.select-all", 
                    "element => element.textContent"
                )
        
        name = page.eval_on_selector(
                    "h1.text-highlighted", 
                    "element => element.textContent.trim()"
                )
        logger.info(f"Static data extracted: Reference={reference}, Name={name}")
        return {"Reference": reference, "Name": name}
    except Exception as e:
        logger.error(f"Error extracting static data: {e}")
        return {"Reference": None, "Name": None}

def scrape_dynamic_content(url):
    """Browses the page, expands ALL sections, and extracts data."""
    try:
        with sync_playwright() as p:
            logger.info(f"Launching browser for: {url}")
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url)
            page.wait_for_load_state("networkidle")

            plus_selector = 'span[class*="i-lucide:plus"]'
            logger.info("Expanding all collapsed sections...")
            max_loops = 20
            
            for _ in range(max_loops):
                pluses = page.locator(plus_selector)
                count = pluses.count()
                
                if count == 0:
                    logger.info("All sections expanded.")
                    break
                    
                try:
                    pluses.first.click(force=True, timeout=2000) 
                    time.sleep(0.5) 
                except Exception as e:
                    logger.warning(f"Could not click expander: {e}")
                    break

            static_info = get_static_data(page) 

            page.evaluate("""() => {
                const allElements = document.querySelectorAll('*');
                allElements.forEach(el => {
                    const style = window.getComputedStyle(el);
                    if (style.textDecorationLine.includes('line-through') || style.textDecoration.includes('line-through')) {
                        el.innerText = el.innerText + " [VALUE: FALSE]"; 
                    }
                });
            }""")

            html = page.content()
            browser.close()
            logger.info("Content scraped successfully.")
            return html, static_info 
    except Exception as e:
        logger.error(f"Error scraping dynamic content: {e}")
        raise

def analyze_with_llm(html_content, columns):
    """Uses Ollama to map the cleaned HTML text to the specific CSV columns."""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        for tag in soup(["script", "style", "svg", "footer", "nav", "header", "button"]):
            tag.decompose()
        
        text_content = soup.get_text(separator='\n')
        lines = [line.strip() for line in text_content.splitlines() if line.strip()]
        clean_text = "\n".join(lines)
        clean_text = clean_text[:15000]
        
        logger.info("Analyzing text with Ollama...")
        
        prompt = f"""
        You are a data extraction agent. 
        
        TASK:
        Extract vehicle specifications from the text below and map them to the provided JSON keys.
        
        RULES:
        1. OUTPUT JSON ONLY. Do not use markdown (e.g., ```json) or any intro text.
        2. USE ONLY THESE KEYS (fill as many as found, maintaining the original structure): 
           {json.dumps(columns)}
        
        3. FALSE VALUES: 
           - If a line has "[VALUE: FALSE]", map it to "False" or "No".
           - If a checkbox feature is listed without the tag, map it to "True" or "Yes".
           
        TEXT DATA:
        ---
        {clean_text}
        ---
        """

        response = ollama.chat(model=OLLAMA_MODEL, messages=[
            {'role': 'user', 'content': prompt},
        ])
        
        logger.info("LLM analysis completed.")
        return response['message']['content']
    except Exception as e:
        logger.error(f"Error in LLM analysis: {e}")
        raise

def save_result(json_str, static_data):
    try:
        json_str = json_str.replace("```json", "").replace("```", "").strip()
        
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("JSON decode error. Attempting to extract JSON substring.")
            start = json_str.find('{')
            end = json_str.rfind('}') + 1
            if start != -1 and end != -1:
                data = json.loads(json_str[start:end])
            else:
                raise
        
        data.update(static_data)
        schema_cols = pd.read_csv(CSV_FILE).columns.tolist()
        
        df_new = pd.DataFrame([data])
        df_final = pd.DataFrame(columns=schema_cols)
        df_final = pd.concat([df_final, df_new], ignore_index=True)
        df_final = df_final[schema_cols]
        
        df_final.to_csv(CSV_FILE, mode='a', header=False, index=False)
        logger.info(f"Data appended to {CSV_FILE}")
        
    except Exception as e:
        logger.error(f"Error saving result: {e}\nRaw LLM Output:\n{json_str}")

# --- Main Execution ---
if __name__ == "__main__":
    logger.info("Agent starting...")
    
    columns = get_target_schema()
    html, static_info = scrape_dynamic_content(URL) 
    llm_json = analyze_with_llm(html, columns)
    save_result(llm_json, static_info)
    
    logger.info("Agent completed.")
