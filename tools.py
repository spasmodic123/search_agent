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
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            download = trafilatura.fetch_url(url)
            
            if download is None:
                # If fetch failed, retry mechanism
                if attempt < max_retries - 1:
                    wait_time = random.uniform(1, 3)
                    print(f"DEBUG: Fetch returned None, retrying in {wait_time:.1f}s...")
                    time.sleep(wait_time)
                    continue
                return "ERROR: COULD NOT FETCH PAGE (Trafilatura returned None)"
            
            text = trafilatura.extract(download, include_comments=False, include_tables=True)
            
            if not text:
                return "ERROR: NO main content found on this page"
            
            return str(text[:10000])

        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = random.uniform(1, 3)
                print(f"DEBUG: Visit failed ({e}), retrying in {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue
            return f"ERROR: Failed to visit page after {max_retries} retries: {e}"