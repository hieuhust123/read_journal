import requests
from bs4 import BeautifulSoup

def fetch_iclr_papers():
    url = "https://openreview.net/group?id=ICLR.cc/2025/Conference#tab-accept-oral"
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        papers = []
        for link in soup.select("a"):
            title = link.text.strip()
            pdf_url = link.get("href", "")
            papers.append({"title": title, "pdf_url": pdf_url, "citations": 0})
        return papers
    except requests.RequestException as e:
        print(f"Error fetching ICLR papers: {e}")
        return []
