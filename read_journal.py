import time
import schedule
import requests

from fetchers.arxiv_fetcher import fetch_arxiv_papers
from fetchers.rss_fetcher import fetch_rss_entries
from fetchers.keyword_filter import keyword_filter
from fetchers.neurips_fetcher import fetch_neurips_papers
from fetchers.iclr_fetcher import fetch_iclr_papers
from fetchers.icml_fetcher import fetch_icml_papers
from fetchers.aaai_fetcher import fetch_aaai_papers

KEYWORDS = ["reinforcement learning", "transformer", 
            "deep learning", "neural network", "AI", 
            "artificial intelligence", "machine learning", 
            "computer vision", "natural language processing"]

#KEYWORDS = ["backpropagation", "backward pass", "chain rule" ]



def normalize_rss(rss_raw):
         # Normalize RSS format
    rss_papers = []
    for entry in rss_raw:
        rss_papers.append({
            "title": entry["title"],
            "abstract": entry.get("summary", ""),
            "published": entry.get("published", ""),
            "pdf_url": entry.get("link", "")
        })
    return rss_papers 

def job():
    try:
        #Fetch papers from arXiv
        arxiv_papers = fetch_arxiv_papers(query="artificial intelligence", max_results=5)

        # # Fetch papers from RSS feed
        # rss_raw = fetch_rss_entries("http://export.arxiv.org/rss/cs.AI")
        # rss_papers = normalize_rss(rss_raw)
        # Convert to a consistent format (title, abstract, etc.) – if needed

        # Fetch papers from NeurIPS
        neurips_papers = fetch_neurips_papers()

        # Fetch papers from ICLR
        iclr_papers = fetch_iclr_papers()
        icml_papers = fetch_icml_papers()
        aaai_papers = fetch_aaai_papers()        
        # Combine and filter papers
        combined =  icml_papers  + iclr_papers + aaai_papers + neurips_papers

        # Filter by keywords
        unique_papers = {paper['title']: paper for paper in combined}.values()
        filtered = keyword_filter(combined, KEYWORDS)

        print(f"Total unique papers: {len(unique_papers)} | Filtered: {len(filtered)}")
        # Group papers by source
        sources = {
            #'ArXiv': arxiv_papers,
            #'RSS': rss_papers,
            'NeurIPS': neurips_papers,
            'ICLR': iclr_papers,
            'ICML': icml_papers,
            'AAAI': aaai_papers
        }

        for name, papers in sources.items():
            group = keyword_filter(papers, KEYWORDS)
            if not group:
                continue
            # Sort by citation count (default to 0 if missing)
            group_sorted = sorted(group, key=lambda p: p.get('citations', 0))
            print(f"\n{name} ({len(group_sorted)} papers):")
            for paper in group_sorted:
                print(f"- Title: {paper['title']}\n  Link: {paper['pdf_url']}")
                if 'citations' in paper:
                    print(f"  Citations: {paper['citations']}")
                else:
                    print(f"  Citations: 0")
                if paper.get('published'):
                    print(f"  Published: {paper['published']}")
                if paper.get('abstract'):
                    # Print a preview of the abstract (up to 200 chars)
                    abs_text = paper['abstract']
                    preview = abs_text[:200] + ('...' if len(abs_text) > 200 else '')
                    print(f"  Abstract: {preview}")
                print()  # Blank line between entries
    except Exception as e:
        print(f"Error in job execution: {e}")


if __name__ == "__main__":
    job()
