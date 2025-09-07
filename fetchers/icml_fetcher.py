import requests
from bs4 import BeautifulSoup

def fetch_icml_papers():
    """Fetch accepted ICLR papers from the OpenReview ICLR page."""
    url = "https://proceedings.mlr.press/v262/"
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        papers = []
        # Look for PDF links in the ICLR accepted papers listing
        for link in soup.select("a[href*='pdf']"):
            title = link.text.strip() or "No title"
            pdf_url = link.get('href')
            if pdf_url and not pdf_url.startswith('http'):
                pdf_url = 'https://openreview.net' + pdf_url
            papers.append({"title": title, "pdf_url": pdf_url, "citations": 0})
        return papers
    except requests.RequestException as e:
        print(f"Error fetching ICLR papers: {e}")
        return []