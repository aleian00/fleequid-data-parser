import time
import json
import pandas as pd
import ollama
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import os

# --- Configuration ---
# Ensure this model is pulled in your local Ollama instance (e.g., ollama pull llama3.1)
OLLAMA_MODEL = "llama3.1" 
CSV_FILE = "output/auction_data.csv"
URL = "https://fleequid.com/en/auctions/dp/mercedes-benz-citaro-o-530-le-euro5-220kw-13057mt-6a817410-c004-454e-aead-9b3394478067"

def get_target_schema():
    """Reads the CSV to get the list of column names for structured extraction."""
    if not os.path.exists(CSV_FILE):
        # Gracefully handle missing CSV by creating a minimal one if necessary
        print(f"⚠️ {CSV_FILE} not found. Creating empty file.")
        # Assuming these two columns are always required
        pd.DataFrame(columns=["Reference", "Name"]).to_csv(CSV_FILE, index=False)
    
    df = pd.read_csv(CSV_FILE)
    return df.columns.tolist()

def scrape_dynamic_content(url):
    """
    Browses the page, expands ALL sections using the specific 'i-lucide:plus' class, 
    and annotates strikethrough text for the LLM.
    """
    with sync_playwright() as p:
        print(f"🕵️  Agent launching browser for: {url}")
        # Setting headless=True is faster and recommended for scraping
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url)
        page.wait_for_load_state("networkidle")

        # 1. EXPAND ALL SECTIONS (Clicking ALL plus icons repeatedly)
        # Target the specific 'plus' icon provided by the user.
        plus_selector = 'span[class*="i-lucide:plus"]'
        
        print("🖱️  Expanding all collapsed sections...")
        max_loops = 20 # Safety limit
        
        for _ in range(max_loops):
            # Re-evaluate the locator to find all current plus icons
            pluses = page.locator(plus_selector)
            count = pluses.count()
            
            if count == 0:
                print("   All sections appear expanded.")
                break
                
            try:
                # We click the first element found. When clicked, it changes to 'minus' 
                # and is automatically removed from the list for the next iteration.
                # This ensures every plus icon gets clicked sequentially.
                pluses.first.click(force=True, timeout=2000) 
                time.sleep(0.5) # Wait for animation/DOM update
            except Exception as e:
                print(f"   ⚠️ Could not click an expander, stopping expansion loop: {e}")
                break

        # 2. ANNOTATE FALSE VALUES (Strikethrough)
        # Injects JS to check the computed style for "line-through" and appends a tag.
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
        return html, page

def parse_static_data(soup):
    """Parses 'Reference' and 'Name' statically as requested."""
    data = {}
    
    # 1. Static Name (Often the H1 element)
    h1 = soup.find('h1')
    if h1:
        data[' Name'] = h1.get_text(strip=True) # Note the leading space from your CSV
        
    # 2. Static Reference (Guessing the last part of the URL based on the structure)
    url_parts = URL.split('-')
    if url_parts:
        # Assuming the Reference is the unique UUID at the end of the path
        data['Reference'] = url_parts[-1] 
        
    return data

def analyze_with_llm(html_content, columns):
    """Uses Ollama to map the cleaned HTML text to the specific CSV columns."""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Remove clutter to save tokens (scripts, styles, navigation, footer)
    for tag in soup(["script", "style", "svg", "footer", "nav", "header"]):
        tag.decompose()
    
    text_content = soup.get_text(separator='\n')
    
    # Clean and limit text content for the LLM
    lines = [line.strip() for line in text_content.splitlines() if line.strip()]
    clean_text = "\n".join(lines)
    clean_text = clean_text[:15000] # Safe limit for Llama3 context
    
    print("🧠  Agent analyzing text with Ollama...")
    
    # Pass the required column list to the LLM to enforce the schema
    prompt = f"""
    You are a data extraction agent. 
    
    TASK:
    Extract vehicle specifications from the text below and map them to the provided JSON keys.
    
    RULES:
    1. OUTPUT JSON ONLY. Do not use markdown (e.g., ```json) or any intro text.
    2. USE ONLY THESE KEYS (fill as many as found, maintaining the original spacing): 
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
    
    return response['message']['content']

def save_result(json_str, static_data):
    try:
        # Clean markdown wrappers if present
        json_str = json_str.replace("```json", "").replace("```", "").strip()
        
        # Robust JSON parsing (in case the LLM is slightly messy)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            print("⚠️  JSON Decode Error. Attempting to extract JSON substring.")
            start = json_str.find('{')
            end = json_str.rfind('}') + 1
            if start != -1 and end != -1:
                data = json.loads(json_str[start:end])
            else:
                raise
        
        # Merge static data into the LLM-extracted data
        data.update(static_data)
        
        # Align with CSV schema
        schema_cols = pd.read_csv(CSV_FILE).columns.tolist()
        
        # Create DataFrame from the new data
        df_new = pd.DataFrame([data])
        
        # Ensure only the columns from the CSV schema are used
        # We fill missing columns with NaN (which appears as blank in CSV)
        df_final = pd.DataFrame(columns=schema_cols)
        df_final = pd.concat([df_final, df_new], ignore_index=True)
        df_final = df_final[schema_cols]
        
        # Append to CSV without headers (since it's an existing file)
        df_final.to_csv(CSV_FILE, mode='a', header=False, index=False)
        print(f"✅ Success! Data appended to {CSV_FILE}")
        
    except Exception as e:
        print(f"❌  Error saving: {e}")
        print("DEBUG - Raw LLM Output:\n", json_str)

def get_static_data(page):
    reference = page.eval_on_selector(
                "span.select-all", 
                "element => element.textContent"
            )
    name = page.eval_on_selector(
                "h1.text-highlighted", 
                "element => element.textContent.trim()"
            )
    return name, reference

# --- Main Execution ---
if __name__ == "__main__":
    # Ensure Ollama is running (ollama serve) before executing
    
    # 1. Get the required column schema
    columns = get_target_schema()
    
    # 2. Scrape the dynamically loaded HTML
    html, page = scrape_dynamic_content(URL)
    soup = BeautifulSoup(html, 'html.parser')

    # 3. Parse static fields
    # Reference and Name
    name, refence = get_static_data(page)    
    
    # 4. LLM Parse for all other fields
    llm_json = analyze_with_llm(html, columns)
    
    # 5. Save the combined result to the CSV
    save_result(llm_json, static_info)