import re
import time
import random
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse, urlunparse
from typing import List
import httpx
from lxml import html
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------------------------------------------------------
# Configuration & Safety Filters
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
MAX_WORKERS = 5  # Number of parallel HTTP requests
POLITE_DELAY = 0.1  # Small delay per request (in seconds)

# Pre-compiled regular expression for faster filter parsing
EXCLUSION_RE = re.compile('|'.join(re.escape(k) for k in EXCLUSION_KEYWORDS), re.IGNORECASE)

# Single, thread-safe high-performance HTTP client with built-in connection pooling
_SHARED_CLIENT = httpx.Client(
    headers={'User-Agent': USER_AGENT},
    timeout=5.0,
    limits=httpx.Limits(
        max_keepalive_connections=50,  # Keep open pooled connections
        max_connections=100,          # High limit for concurrent requests
        keepalive_expiry=30.0
    ),
    follow_redirects=True
)

# ---------------------------------------------------------------------------
# URL Validation & Normalization
# ---------------------------------------------------------------------------

def normalize_url(url: str) -> str:
    parsed = list(urlparse(url))
    parsed[5] = ''  # Remove fragment
    path = parsed[2]
    if not path or path == '/':
        path = '/'
    parsed[2] = path
    parsed[0] = parsed[0].lower()
    parsed[1] = parsed[1].lower()
    return urlunparse(parsed)

def is_public_url(url: str, base_domain: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.netloc != base_domain:
            return False
        if parsed.scheme not in ('http', 'https'):
            return False
        if parsed.path.lower().endswith(EXCLUDED_EXTENSIONS):
            return False
        # Fast regex match is much quicker than loop iterations
        if EXCLUSION_RE.search(url):
            return False
        if len(parsed.query.split('&')) > 5:
            return False
        return True
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Dynamic Sitemap Discovery (Parallel)
# ---------------------------------------------------------------------------

def discover_sitemap_urls(base_url: str, client: httpx.Client = _SHARED_CLIENT) -> List[str]:
    """Find sitemap URLs via robots.txt and common paths in parallel."""
    robots_url = urljoin(base_url, '/robots.txt')
    common_paths = [
        '/sitemap.xml', '/sitemap_index.xml',
        '/sitemap.txt', '/wp-sitemap.xml'
    ]

    def fetch_robots():
        try:
            resp = client.get(robots_url, timeout=4.0)
            if resp.status_code == 200:
                matches = re.findall(r'^[Ss]itemap:\s*(https?://\S+)', resp.text, re.MULTILINE)
                return [normalize_url(m.strip()) for m in matches]
        except Exception as e:
            print(f"   [Sitemap] Robots.txt check skipped: {e}")
        return []

    def check_common_path(path):
        full_url = urljoin(base_url, path)
        try:
            # Using HEAD prevents pulling unnecessary payload
            resp = client.head(full_url, timeout=3.0)
            if resp.status_code == 200:
                return full_url
        except Exception:
            pass
        return None

    sitemaps = fetch_robots()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(check_common_path, path) for path in common_paths]
        for future in as_completed(futures):
            result = future.result()
            if result and result not in sitemaps:
                sitemaps.append(result)

    return sitemaps

# ---------------------------------------------------------------------------
# Sitemap Parser (Recursive with parallel sub‑sitemap fetching)
# ---------------------------------------------------------------------------

def parse_sitemap(sitemap_url: str, base_domain: str, max_links: int, client: httpx.Client = _SHARED_CLIENT) -> List[str]:
    urls = []
    try:
        resp = client.get(sitemap_url, timeout=5.0)
        if resp.status_code != 200:
            return []

        content_type = resp.headers.get('content-type', '').lower()

        # Plain text sitemap
        if sitemap_url.endswith('.txt') or 'text/plain' in content_type:
            for line in resp.text.splitlines():
                clean = normalize_url(line.strip())
                if is_public_url(clean, base_domain):
                    urls.append(clean)
                    if len(urls) >= max_links:
                        return urls
            return urls

        # XML parsing
        try:
            root = ET.fromstring(resp.content)
            ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}

            # Check for sitemap index
            sitemaps_locs = root.findall('.//sm:sitemap/sm:loc', ns)
            if not sitemaps_locs:
                sitemaps_locs = root.findall('.//sitemap/loc')

            if sitemaps_locs:
                print(f"   [Sitemap Index] Navigating sitemap index hierarchy...")
                # Fetch first 3 sub‑sitemaps in parallel
                sub_urls = [loc.text.strip() for loc in sitemaps_locs[:3]]
                with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, 3)) as executor:
                    futures = {executor.submit(parse_sitemap, sub_url, base_domain, max_links - len(urls), client): sub_url
                               for sub_url in sub_urls}
                    for future in as_completed(futures):
                        urls.extend(future.result())
                        if len(urls) >= max_links:
                            break
                return list(dict.fromkeys(urls))

            # Normal URL set
            url_locs = root.findall('.//sm:url/sm:loc', ns)
            if not url_locs:
                url_locs = root.findall('.//url/loc')

            for loc in url_locs:
                if loc.text:
                    clean = normalize_url(loc.text.strip())
                    if is_public_url(clean, base_domain):
                        urls.append(clean)
                        if len(urls) >= max_links:
                            break
        except ET.ParseError:
            # Fallback regex extraction
            found = re.findall(r'https?://[^\s<>"]+', resp.text)
            for f_url in found:
                clean = normalize_url(f_url)
                if is_public_url(clean, base_domain):
                    urls.append(clean)
                    if len(urls) >= max_links:
                        break
    except Exception as e:
        print(f"   [Sitemap] Error reading {sitemap_url}: {e}")

    return list(dict.fromkeys(urls))

# ---------------------------------------------------------------------------
# Parallel BFS Crawler (Depth 3, each depth level parallel)
# ---------------------------------------------------------------------------

def fallback_bfs_crawl(start_url: str, base_domain: str, max_links: int, client: httpx.Client = _SHARED_CLIENT) -> List[str]:
    visited = set()
    normalized_start = normalize_url(start_url)
    queue = [(normalized_start, 0)]
    discovered = []
    MAX_DEPTH = 3

    def fetch_page(url, depth):
        """Fetch and parse a single page, returning discovered links."""
        if POLITE_DELAY > 0:
            time.sleep(POLITE_DELAY)  # Small courtesy delay
        try:
            response = client.get(url, timeout=5.0)
            if response.status_code != 200 or 'text/html' not in response.headers.get('content-type', ''):
                return url, None, depth

            tree = html.fromstring(response.content)
            tree.make_links_absolute(url)

            standard_links = tree.xpath('//a/@href')
            interactive_links = []

            for btn_link in tree.xpath('//button/@data-href | //button/@data-url | //*[contains(@class, "btn")]/@data-href'):
                interactive_links.append(urljoin(url, btn_link))

            for onclick in tree.xpath('//*[@onclick]/@onclick'):
                matches = re.findall(r"['\"](/[^'\"]+)['\"]|['\"](https?://[^'\"]+)['\"]", onclick)
                for match in matches:
                    found_path = match[0] if match[0] else match[1]
                    interactive_links.append(urljoin(url, found_path))

            raw_js_matches = re.findall(r"(?:navigateTo|navigate|push|location\.href|location)\s*\(\s*['\"](/[^'\"]+)['\"]", response.text)
            for r_match in raw_js_matches:
                interactive_links.append(urljoin(url, r_match))

            all_links = standard_links + interactive_links
            valid_links = []
            for link in all_links:
                clean = normalize_url(link)
                if is_public_url(clean, base_domain):
                    valid_links.append(clean)

            print(f"   [Crawl] {url} -> {len(valid_links)} new links")
            return url, valid_links, depth

        except Exception as e:
            print(f"   [Crawler] Exception on {url}: {e}")
            return url, None, depth

    # BFS with parallel same‑depth fetching
    while queue and len(discovered) < max_links:
        # Group all URLs of the current depth (lowest depth in queue)
        current_depth = queue[0][1]
        batch = []
        while queue and queue[0][1] == current_depth:
            batch.append(queue.pop(0))

        if not batch:
            continue

        # Fetch all pages in this batch in parallel
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(batch))) as executor:
            futures = {executor.submit(fetch_page, url, depth): (url, depth) for url, depth in batch}
            for future in as_completed(futures):
                url, links, depth = future.result()
                if url not in visited:
                    visited.add(url)
                    discovered.append(url)
                    if len(discovered) >= max_links:
                        break
                    if links and depth < MAX_DEPTH:
                        for link in links:
                            if link not in visited and not any(q[0] == link for q in queue):
                                queue.append((link, depth + 1))

                if len(discovered) >= max_links:
                    break

    return discovered[:max_links]

# ---------------------------------------------------------------------------
# Core Discovery (Hybrid: Sitemap → BFS, parallel verification)
# ---------------------------------------------------------------------------

def discover_public_links(start_url: str, max_discovery: int = 6, client: httpx.Client = _SHARED_CLIENT) -> List[str]:
    base_domain = urlparse(start_url).netloc
    normalized_start = normalize_url(start_url)

    print("   [Crawler] Searching for public URLs via Sitemap sources...")
    sitemap_candidates = discover_sitemap_urls(normalized_start, client)

    discovered = []
    for sitemap_url in sitemap_candidates:
        urls = parse_sitemap(sitemap_url, base_domain, max_discovery, client)
        discovered.extend(urls)
        if len(discovered) >= max_discovery:
            break

    if not discovered:
        print("   [Crawler] No Sitemap found. Activating loop-safe fallback crawler...")
        discovered = fallback_bfs_crawl(normalized_start, base_domain, max_discovery, client)

    unique_urls = list(dict.fromkeys(discovered))

    # Verify all URLs are alive (200) in parallel using the pooled client
    print("   [Crawler] Verifying page statuses (parallel)...")
    verified = []

    def check_url(url):
        try:
            # Try lightweight HEAD requests first (drastically reduces bandwidth/time)
            resp = client.head(url, timeout=3.0)
            if resp.status_code == 200:
                return (url, True)
            # Revert to standard GET only if the server explicitly blocks HEAD requests
            if resp.status_code in (405, 403, 400):
                resp = client.get(url, timeout=3.0)
                return (url, resp.status_code == 200)
        except Exception:
            pass
        return (url, False)

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(unique_urls))) as executor:
        futures = {executor.submit(check_url, u): u for u in unique_urls}
        for future in as_completed(futures):
            url, ok = future.result()
            if ok:
                verified.append(url)
                if len(verified) >= max_discovery:
                    break

    return verified

# ---------------------------------------------------------------------------
# Fast Page Scraper (used in parallel)
# ---------------------------------------------------------------------------

def scrape_page(url: str, client: httpx.Client = _SHARED_CLIENT) -> str:
    try:
        response = client.get(url, timeout=5.0)
        if response.status_code != 200:
            return ""

        tree = html.fromstring(response.content)
        # Dropping nested elements with a single unified xpath minimizes internal tree traversals
        for element in tree.xpath('//script | //style | //nav | //footer | //header | //aside | //noscript | //svg'):
            element.drop_tree()

        text = tree.text_content()
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:3000]
    except Exception as e:
        print(f"   [Scraper] Error scraping {url}: {e}")
        return ""

# ---------------------------------------------------------------------------
# Parallel Scraping with Token Limit
# ---------------------------------------------------------------------------

def scrape_pages_with_limit(urls: List[str], client: httpx.Client = _SHARED_CLIENT) -> List[str]:
    token_limit = random.randint(50000, 80000)
    print(f"   [Limit] Dynamic token limit initialized: {token_limit} tokens.")

    # Scrape all pages in parallel using the pooled connection pool
    scraped = []
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(urls))) as executor:
        futures = {executor.submit(scrape_page, url, client): url for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            text = future.result()
            scraped.append((url, text))

    # Sort back to original input order
    scraped.sort(key=lambda x: urls.index(x[0]))

    cumulative_tokens = 0
    result = []
    for idx, (page_url, text) in enumerate(scraped, 1):
        print(f"   [{idx}/{len(urls)}] Scraping: {page_url}")
        if not text:
            print(f"      [Scrape Error] Empty content or failed fetch for {page_url}")
            continue

        page_tokens = len(text) // 4
        print(f"      [Tokens] Scraped: {len(text)} chars (~{page_tokens} tokens)")

        if cumulative_tokens + page_tokens > token_limit:
            remaining = token_limit - cumulative_tokens
            if remaining > 100:
                truncated = text[:remaining * 4] + "\n[Content truncated due to Deep Audit token limits]"
                result.append(f"PAGE: {page_url}\nCONTENT: {truncated}\n---")
                print(f"      [Limit] Content truncated to fit. Added {remaining} tokens.")
            print(f"   [Limit] Strict token limit reached ({token_limit} tokens). Stopping.")
            break
        else:
            result.append(f"PAGE: {page_url}\nCONTENT: {text}\n---")
            cumulative_tokens += page_tokens
            print(f"      [Cumulative] Total tokens so far: {cumulative_tokens}/{token_limit}")

    print(f"   [Limit] Final total estimated tokens consumed: {cumulative_tokens}/{token_limit}")
    return result