from langchain_core.tools import tool
from ddgs import DDGS

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

# @tool
# def visit_page(url: str) -> str:
#     """Visit a web page and extract its text content."""
#     import requests
#     from bs4 import BeautifulSoup

#     print(f"DEBUG: Visiting {url}")
#     try:
#         headers = {
#             "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
#         }
#         response = requests.get(url, headers=headers, timeout=10)
#         response.raise_for_status()
        
#         # Use BeautifulSoup to extract text
#         soup = BeautifulSoup(response.content, 'html.parser')
        
#         # Extract text from p, h1, h2, h3, li,
#         # We focus on p tags but include headers for context
#         texts = []
#         for element in soup.find_all(['h1', 'h2', 'h3', 'p', 'li']):
#             text = element.get_text(strip=True)
#             if len(text) > 5: # Filter out very short snippets
#                 texts.append(text)
        
#         content = "\n".join(texts)
        
#         # Limit content length to avoid overflowing context
#         return content[:10000]
        
#     except Exception as e:
#         return f"Error visiting page: {e}"


@tool
def visit_page(url: str) -> str:
    """Visit a web page and extract its text content."""
    import trafilatura

    print(f"DEBUG: Visiting {url}")
    try:
        download = trafilatura.fetch_url(url)

        if download is None:
            return "ERROR: COULD NOT FETCH PAGE"
        
        text = trafilatura.extract(download, include_comments=False, include_tables=True)

        if not text:
            return "ERROR: NO main content found on this page"
        
        return str(text[:10000])

    except Exception as e:
        return f"Error visiting page: {e}"


'''
逻辑：使用 DuckDuckGo 进行搜索。
关键点：@tool 装饰器非常重要。它会将 Python 函数转换成 OpenAI/LLM 能理解的 JSON Schema（包含函数名、描述、参数类型）。LLM 并不直接运行代码，而是生成一个“请帮我运行这个函数”的指令，这个 schema 就是沟通的桥梁。
'''