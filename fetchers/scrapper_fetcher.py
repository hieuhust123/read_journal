import requests
from bs4 import BeautifulSoup

def scrape_conference_site(url):
    """
    Scrapes a conference's website (placeholder example).
    Returns a list of dicts with paper metadata.
    """
    response = requests.get(url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')

    # This part depends on the actual site structure:
    # e.g., <div class="paper"><a href="paper.pdf">Title</a></div>
    papers = []
    for paper_div in soup.select("div.paper"):
        title_element = paper_div.find("a")
        if not title_element:
            continue
        title = title_element.text.strip()
        pdf_url = title_element.get("href", "")
        papers.append({"title": title, "pdf_url": pdf_url})

    return papers
