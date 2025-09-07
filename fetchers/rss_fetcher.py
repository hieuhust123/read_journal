import feedparser

def fetch_rss_entries(feed_url):
    """
    Fetch entries from an RSS feed.
    Returns a list of dicts with relevant metadata.
    """
    feed = feedparser.parse(feed_url)
    entries = []
    for entry in feed.entries:
        entry_info = {
            "title": entry.title,
            "link": entry.link,
            "published": entry.get("published", ""),
            "summary": entry.get("summary", "")
        }
        entries.append(entry_info)
    return entries

if __name__ == "__main__":
    # Example: ArXiv's RSS feed for Computer Science - AI
    url = "http://export.arxiv.org/rss/cs.AI"
    entries = fetch_rss_entries(url)
    for e in entries[:5]:
        print(e["title"], e["published"], e["link"])
