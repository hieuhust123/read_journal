# fetchers/aaai_fetcher.py

import requests
from bs4 import BeautifulSoup

def fetch_aaai_papers():
    """Fetch AAAI papers from the AAAI Digital Library."""
    url = "https://aaai.org/Library/AAAI/aaai-library.php"
    try:
        response = requests.get(url, headers = {"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        papers = []
        # Select links ending in .pdf in the main content area
        for link in soup.select("a[href$='.pdf'], a[href$='.PDF']"):
            title = link.text.strip() or "No title"
            pdf_url = link.get('href')
            if pdf_url and not pdf_url.startswith('http'):
                pdf_url = 'https://aaai.org' + pdf_url
            papers.append({"title": title, "pdf_url": pdf_url, "citations": 0})
        return papers
    except requests.RequestException as e:
        print(f"Error fetching AAAI papers: {e}")
        return []
