def keyword_filter(papers, keywords):
    """
    Return only papers whose title or abstract contains any of the provided keywords.
    """
    filtered = []
    keywords_lower = [k.lower() for k in keywords]
    for paper in papers:
        text_to_search = (paper.get("title", "") + " " + paper.get("abstract", "")).lower()
        if any(kw in text_to_search for kw in keywords_lower):
            filtered.append(paper)
    return filtered
