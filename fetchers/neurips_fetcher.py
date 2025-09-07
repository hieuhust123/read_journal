import requests
from bs4 import BeautifulSoup

def fetch_neurips_papers():
    url = "https://proceedings.neurips.cc/paper_files/paper/2024"
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        papers = []
        for link in soup.select("a"):
            title = link.text.strip()
            pdf_url = url + link.get("href", "")
            papers.append({"title": title, "pdf_url": pdf_url, "citations": 0})
        return papers
    except requests.RequestException as e:
        print(f"Error fetching NeurIPS papers: {e}")
        return []
