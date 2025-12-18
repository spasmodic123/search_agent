from langchain_core.tools import tool
from ddgs import DDGS
import trafilatura
import time
import random

@tool
def search_web(query: str) -> str:
    """Run a web search for the given query."""
    print(f"DEBUG: Searching for '{query}'")
    try:
        with DDGS() as ddgs:
            results = [r for r in ddgs.text(query, max_results=5)]
            return str(results)
    except Exception as e:
        return f"Error performing search: {e}"

@tool
def visit_page(url: str) -> str:
    """
    Visits a webpage and extracts its text content using Trafilatura.
    Useful for reading news articles, blog posts, or documentation.
    """
    print(f"DEBUG: Visiting {url}")
    
    # Common User-Agents to bypass basic anti-bot checks
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    ]
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Rotate User-Agent
            headers = {"User-Agent": random.choice(user_agents)}
            
            # Use requests to download the page
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status() # Check for HTTP errors (404, 403, etc.)
            
            # Use Trafilatura to extract text from the HTML string
            text = trafilatura.extract(response.text, include_comments=False, include_tables=True)
            
            if not text:
                return "ERROR: NO main content found on this page (extraction failed)"
            
            return str(text[:10000])

        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = random.uniform(1, 3)
                print(f"DEBUG: Visit failed ({e}), retrying in {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue
            return f"ERROR: Failed to visit page after {max_retries} retries: {e}"