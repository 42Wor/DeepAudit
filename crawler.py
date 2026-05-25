import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse, urlunparse
from typing import List
import httpx
from lxml import html

# ---------------------------------------------------------------------------
# Configuration & Safety Filters (Skips Auth but Allows Public Pages)
# ---------------------------------------------------------------------------

EXCLUSION_KEYWORDS = [
    "login", "signin", "signup", "register", "auth", "admin", "dashboard",
    "cart", "checkout", "my-account", "account", "settings",
    "wp-admin", "logout", "reset-password", "billing", "payment", 
    "subscribe", "unsubscribe", "verify", "confirmation", "password-reset", 
    "forgot-password", "api", "graphql", "rest", "webhook", "callback", "oauth"
]

EXCLUDED_EXTENSIONS = (
    '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.bmp',
    '.ico', '.zip', '.tar', '.gz', '.rar', '.7z', '.mp4', '.mp3',
    '.avi', '.mov', '.wmv', '.flv', '.css', '.js', '.json', '.xml',
    '.csv', '.xls', '.xlsx', '.doc', '.docx', '.ppt', '.pptx', '.txt',
    '.ttf', '.woff', '.woff2', '.eot'
)

USER_AGENT = 'Mozilla/5.0 (compatible; DeepAuditBot/1.0; +https://neeura.ai/bot)'

# ---------------------------------------------------------------------------
# URL Validation & Normalization
# ---------------------------------------------------------------------------

def normalize_url(url: str) -> str:
    """Normalize URL by removing fragments and standardizing format consistently."""
    parsed = list(urlparse(url))
    parsed[5] = ''  # Remove fragment (#heading)
    path = parsed[2].rstrip('/')
    if not path:
        path = '/'
    parsed[2] = path
    parsed[0] = parsed[0].lower() # Scheme (http/https)
    parsed[1] = parsed[1].lower() # Netloc (domain)
    return urlunparse(parsed).rstrip('/')

def is_public_url(url: str, base_domain: str) -> bool:
    """
    Check if URL is public, belongs to the same domain,
    and is safe from infinite loops (system/query/assets).
    """
    try:
        parsed = urlparse(url)
        
        # Keep crawling restricted to current domain
        if parsed.netloc != base_domain:
            return False
            
        if parsed.scheme not in ('http', 'https'):
            return False
            
        if parsed.path.lower().endswith(EXCLUDED_EXTENSIONS):
            return False
            
        # Filter typical system, loop-prone, or auth URLs (keeps profile/policy/faq)
        normalized_url = url.lower()
        for keyword in EXCLUSION_KEYWORDS:
            if keyword in normalized_url:
                return False
                
        # Limit total parameters to block infinite query loops (?sort=1&page=2...)
        if len(parsed.query.split('&')) > 5:
            return False
            
        return True
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Dynamic Sitemap Discovery (Robots.txt & Standard Paths)
# ---------------------------------------------------------------------------

def discover_sitemap_urls(base_url: str, client: httpx.Client) -> List[str]:
    """Find sitemap URLs dynamically via robots.txt and common standard locations."""
    sitemaps = []
    
    # 1. Attempt to parse robots.txt for "Sitemap:" declarations
    robots_url = urljoin(base_url, '/robots.txt')
    try:
        resp = client.get(robots_url, timeout=5.0)
        if resp.status_code == 200:
            matches = re.findall(r'^[Ss]itemap:\s*(https?://\S+)', resp.text, re.MULTILINE)
            for match in matches:
                normalized = normalize_url(match.strip())
                if normalized not in sitemaps:
                    sitemaps.append(normalized)
    except Exception as e:
        print(f"   [Sitemap] Robots.txt check skipped: {e}")

    # 2. Add common standard fallbacks
    common_paths = [
        '/sitemap.xml',
        '/sitemap_index.xml',
        '/sitemap.txt',
        '/wp-sitemap.xml'
    ]
    for path in common_paths:
        full_url = urljoin(base_url, path)
        if full_url not in sitemaps:
            sitemaps.append(full_url)
            
    return sitemaps

# ---------------------------------------------------------------------------
# Sitemap Parser (XML, Sitemap Index, & Plain Text)
# ---------------------------------------------------------------------------

def parse_sitemap(sitemap_url: str, client: httpx.Client, base_domain: str, max_links: int) -> List[str]:
    """Recursively parse XML Sitemaps, Sitemap Indexes, or plain Text sitemaps."""
    urls = []
    try:
        resp = client.get(sitemap_url, timeout=5.0)
        if resp.status_code != 200:
            return []
            
        content_type = resp.headers.get('content-type', '').lower()
        
        # 1. Plain Text Sitemaps (.txt or text/plain format)
        if sitemap_url.endswith('.txt') or 'text/plain' in content_type:
            for line in resp.text.splitlines():
                clean_url = normalize_url(line.strip())
                if is_public_url(clean_url, base_domain):
                    urls.append(clean_url)
                    if len(urls) >= max_links:
                        return urls
            return urls

        # 2. XML Sitemap & Sitemap Index Parsing
        try:
            root = ET.fromstring(resp.content)
            ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            
            # Check if it's a Sitemap Index pointing to nested sitemaps
            sitemaps_locs = root.findall('.//sm:sitemap/sm:loc', ns)
            if not sitemaps_locs:
                sitemaps_locs = root.findall('.//sitemap/loc') # Fallback if no namespace
                
            if sitemaps_locs:
                print(f"   [Sitemap Index] Navigating sitemap index hierarchy...")
                # Recurse first 3 sub-sitemaps to prevent deep infinite loop lookups
                for sub_sitemap in sitemaps_locs[:3]:
                    sub_url = sub_sitemap.text.strip()
                    urls.extend(parse_sitemap(sub_url, client, base_domain, max_links - len(urls)))
                    if len(urls) >= max_links:
                        break
                return urls
            
            # Parse typical urlset sitemap
            url_locs = root.findall('.//sm:url/sm:loc', ns)
            if not url_locs:
                url_locs = root.findall('.//url/loc')
                
            for loc in url_locs:
                if loc.text:
                    clean_url = normalize_url(loc.text.strip())
                    if is_public_url(clean_url, base_domain):
                        urls.append(clean_url)
                        if len(urls) >= max_links:
                            break
                            
        except ET.ParseError:
            # Simple RegEx fallback extraction if XML structure is partially broken
            found_urls = re.findall(r'https?://[^\s<>"]+', resp.text)
            for found_url in found_urls:
                clean_url = normalize_url(found_url)
                if is_public_url(clean_url, base_domain):
                    urls.append(clean_url)
                    if len(urls) >= max_links:
                        break
                        
    except Exception as e:
        print(f"   [Sitemap] Error reading {sitemap_url}: {e}")
        
    return list(dict.fromkeys(urls))

# ---------------------------------------------------------------------------
# Fallback BFS Crawler (Strictly depth-limited & interactive elements scanner)
# ---------------------------------------------------------------------------

def fallback_bfs_crawl(start_url: str, base_domain: str, max_links: int) -> List[str]:
    """BFS crawling using lxml (No BS4). Scans standard links, button onclicks, and custom attributes."""
    visited = set()
    normalized_start = normalize_url(start_url)
    queue = [(normalized_start, 0)]  # Queue stores tuples of (Normalized URL, depth)
    discovered_urls = []
    
    # Maximum click distance from home page set to 3 to access nested views
    MAX_DEPTH = 3 
    
    with httpx.Client(timeout=8.0, follow_redirects=True, headers={'User-Agent': USER_AGENT}) as client:
        while queue and len(discovered_urls) < max_links:
            current_url, depth = queue.pop(0)
            
            if current_url in visited:
                continue
                
            visited.add(current_url)
            
            try:
                # Polite delay
                time.sleep(0.5)
                
                response = client.get(current_url)
                # Skip 404 or other errors
                if response.status_code != 200 or 'text/html' not in response.headers.get('content-type', ''):
                    continue
                
                discovered_urls.append(current_url)
                
                # Enforce depth safety limit
                if depth >= MAX_DEPTH:
                    continue
                
                # Parse HTML with lxml
                tree = html.fromstring(response.content)
                tree.make_links_absolute(current_url)
                
                # Group for keeping track of links found on this page
                candidate_links = []
                
                # 1. Standard Anchor Tags
                for link in tree.xpath('//a/@href'):
                    candidate_links.append(link)
                    
                # 2. Button Interactive Elements (data-href or data-url configurations)
                for btn_link in tree.xpath('//button/@data-href | //button/@data-url | //*[contains(@class, "btn")]/@data-href'):
                    candidate_links.append(urljoin(current_url, btn_link))
                    
                # 3. Onclick Redirection Parser (Extracts paths/links from scripts)
                for onclick in tree.xpath('//*[@onclick]/@onclick'):
                    matches = re.findall(r"['\"](/[^'\"]+)['\"]|['\"](https?://[^'\"]+)['\"]", onclick)
                    for match in matches:
                        found_path = match[0] if match[0] else match[1]
                        candidate_links.append(urljoin(current_url, found_path))
                
                # Standardize, filter, and queue discovered links
                for link in candidate_links:
                    clean_link = normalize_url(link)
                    if (is_public_url(clean_link, base_domain) and 
                        clean_link not in visited and 
                        clean_link not in [q[0] for q in queue]):
                        queue.append((clean_link, depth + 1))
                        
            except Exception as e:
                print(f"   [Crawler] Exception crawling {current_url}: {e}")
                continue
                
    return discovered_urls

# ---------------------------------------------------------------------------
# Core Interface Function (Verification Included)
# ---------------------------------------------------------------------------

def discover_public_links(start_url: str, max_discovery: int = 6) -> List[str]:
    """Hybrid approach: Crawls sitemaps first, falls back to BFS. Verifies 200 OK status on all results."""
    base_domain = urlparse(start_url).netloc
    normalized_start = normalize_url(start_url)
    
    with httpx.Client(timeout=5.0, headers={'User-Agent': USER_AGENT}) as client:
        print("   [Crawler] Searching for public URLs via Sitemap sources...")
        sitemap_candidates = discover_sitemap_urls(normalized_start, client)
        
        discovered_urls = []
        for sitemap_url in sitemap_candidates:
            urls = parse_sitemap(sitemap_url, client, base_domain, max_discovery)
            discovered_urls.extend(urls)
            if len(discovered_urls) >= max_discovery:
                break
                
        if not discovered_urls:
            print("   [Crawler] No Sitemap found. Activating loop-safe fallback crawler...")
            discovered_urls = fallback_bfs_crawl(normalized_start, base_domain, max_discovery)
            
        # Deduplicate while preserving order
        unique_urls = list(dict.fromkeys(discovered_urls))
        
        # Strict Verification: Filter out non-200 / 404 pages
        verified_urls = []
        print("   [Crawler] Verifying page statuses (dropping dead/404 links)...")
        for url in unique_urls:
            try:
                resp = client.get(url, timeout=5.0)
                if resp.status_code == 200:
                    verified_urls.append(url)
                    if len(verified_urls) >= max_discovery:
                        break
            except Exception:
                continue
                
        return verified_urls

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
            
            tree = html.fromstring(response.content)
            
            # Clean unwanted structural trees
            tags_to_remove = ['script', 'style', 'nav', 'footer', 'header', 'aside', 'noscript', 'svg']
            for tag in tags_to_remove:
                for element in tree.xpath(f'//{tag}'):
                    element.drop_tree()
            
            # Extract content text
            text = tree.text_content()
            
            # Clean up whitespace
            text = re.sub(r'\s+', ' ', text).strip()
            
            return text[:3000]
            
    except Exception as e:
        print(f"   [Scraper] Error scraping {url}: {e}")
        return ""