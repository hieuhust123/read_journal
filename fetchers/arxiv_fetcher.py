import arxiv
def fetch_arxiv_papers(query="machine learning", max_results=5):
    """
    Fetch the latest arXiv papers given a query string.
    Sort by submission date (descending).
    Returns a list of dicts with relevant metadata.
    """
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending
    )

    papers = []
    for result in search.results():
        paper_info = {
            "title": result.title,
            "authors": [author.name for author in result.authors],
            "abstract": result.summary,
            "published": result.published,
            "updated": result.updated,
            "pdf_url": result.pdf_url,
            "entry_id": result.entry_id  # arXiv identifier
        }
        papers.append(paper_info)

    return papers
