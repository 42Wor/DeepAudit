import time
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse, urlunparse
import httpx
from lxml import html

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

EXCLUDED_EXTENSIONS = (
    '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp',
    '.css', '.js', '.json', '.xml', '.csv', '.zip', '.mp4'
)

USER_AGENT = 'Mozilla/5.0 (compatible; DeepAuditBot/1.0)'

# ---------------------------------------------------------------------------
# URL Utilities
# ---------------------------------------------------------------------------

def normalize_url(url: str) -> str:
    """Normalize URL by removing fragments and standardizing format."""
    parsed = list(urlparse(url))
    parsed[5] = ''  # Remove fragment (#)
    return urlunparse(parsed).rstrip('/')

def is_valid_public_url(url: str, base_domain: str) -> bool:
    """Check if URL belongs to the same domain and is a valid web page."""
    try:
        parsed = urlparse(url)
        if parsed.netloc != base_domain:
            return False
        if parsed.scheme not in ('http', 'https'):
            return False
        if parsed.path.lower().endswith(EXCLUDED_EXTENSIONS):
            return False
        return True
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Hybrid Crawler Methods
# ---------------------------------------------------------------------------

def get_sitemap_links(base_url: str, base_domain: str, max_links: int) -> list:
    """Attempt to fetch and parse sitemap.xml for URLs."""
    sitemap_url = urljoin(base_url, '/sitemap.xml')
    urls = []
    
    try:
        with httpx.Client(timeout=5.0, headers={'User-Agent': USER_AGENT}) as client:
            response = client.get(sitemap_url)
            
            if response.status_code == 200:
                # Parse XML
                root = ET.fromstring(response.content)
                
                # Handle standard sitemap namespaces
                namespaces = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
                
                # Find all <loc> tags
                locs = root.findall('.//sm:loc', namespaces)
                if not locs:
                    # Fallback if namespace is missing
                    locs = root.findall('.//loc')
                
                for loc in locs:
                    if loc.text:
                        clean_url = normalize_url(loc.text.strip())
                        if is_valid_public_url(clean_url, base_domain):
                            urls.append(clean_url)
                            if len(urls) >= max_links:
                                break
                                
    except Exception as e:
        print(f"   [Sitemap] Failed or not found: {e}")
        
    return urls

def fallback_bfs_crawl(start_url: str, base_domain: str, max_links: int) -> list:
    """Fallback crawler using lxml (No BeautifulSoup) to find links."""
    visited = set()
    queue = [start_url]
    discovered_urls = []
    
    with httpx.Client(timeout=8.0, follow_redirects=True, headers={'User-Agent': USER_AGENT}) as client:
        while queue and len(discovered_urls) < max_links:
            current_url = queue.pop(0)
            
            if current_url in visited:
                continue
                
            visited.add(current_url)
            
            try:
                response = client.get(current_url)
                if response.status_code != 200 or 'text/html' not in response.headers.get('content-type', ''):
                    continue
                
                discovered_urls.append(current_url)
                
                # Parse HTML using lxml instead of BeautifulSoup
                tree = html.fromstring(response.content)
                tree.make_links_absolute(current_url)
                
                # Extract all href attributes using XPath
                for link in tree.xpath('//a/@href'):
                    clean_link = normalize_url(link)
                    if is_valid_public_url(clean_link, base_domain) and clean_link not in visited:
                        queue.append(clean_link)
                        
            except Exception as e:
                print(f"   [Crawler] Error fetching {current_url}: {e}")
                continue
                
    return discovered_urls

def discover_public_links(start_url: str, max_discovery: int = 6) -> list:
    """
    Hybrid approach: 
    1. Try Sitemap.xml
    2. If no links found, fallback to lxml BFS crawler
    """
    base_domain = urlparse(start_url).netloc
    
    print("   [Crawler] Attempting to read sitemap.xml...")
    urls = get_sitemap_links(start_url, base_domain, max_discovery)
    
    if urls:
        print(f"   [Crawler] Success! Found {len(urls)} links via Sitemap.")
        return urls
        
    print("   [Crawler] Sitemap failed or empty. Falling back to lxml BFS crawler...")
    urls = fallback_bfs_crawl(start_url, base_domain, max_discovery)
    
    return urls

# ---------------------------------------------------------------------------
# Page Scraper (Using lxml)
# ---------------------------------------------------------------------------

def scrape_page(url: str) -> str:
    """Download page and extract clean text content using lxml."""
    try:
        with httpx.Client(timeout=8.0, follow_redirects=True, headers={'User-Agent': USER_AGENT}) as client:
            response = client.get(url)
            if response.status_code != 200:
                return ""
            
            # Parse HTML with lxml
            tree = html.fromstring(response.content)
            
            # Remove non-content elements using XPath
            tags_to_remove = ['script', 'style', 'nav', 'footer', 'header', 'aside', 'noscript', 'svg']
            for tag in tags_to_remove:
                for element in tree.xpath(f'//{tag}'):
                    element.drop_tree()
            
            # Extract raw text
            text = tree.text_content()
            
            # Clean up whitespace (remove extra newlines and spaces)
            text = re.sub(r'\s+', ' ', text).strip()
            
            # Limit content length to preserve memory/tokens
            return text[:3000]
            
    except Exception as e:
        print(f"   [Scraper] Error scraping {url}: {e}")
        return ""