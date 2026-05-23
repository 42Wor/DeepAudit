import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse
import httpx
from bs4 import BeautifulSoup

EXCLUSION_KEYWORDS = [
    "login", "signin", "signup", "register", "auth", "admin", "dashboard",
    "cart", "checkout", "my-account", "account", "settings", "profile",
    "privacy-policy", "terms-of-service", "terms-and-conditions", "wp-admin",
    "logout", "reset-password"
]

EXCLUDED_EXTENSIONS = (
    '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.zip', 
    '.tar', '.gz', '.mp4', '.mp3', '.css', '.js', '.json', '.xml'
)

def is_public_url(url: str, base_domain: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc != base_domain:
        return False
    if parsed.path.lower().endswith(EXCLUDED_EXTENSIONS):
        return False
    normalized_url = url.lower()
    for keyword in EXCLUSION_KEYWORDS:
        if keyword in normalized_url:
            return False
    return True

def get_links_from_sitemap(base_url: str, http_client: httpx.Client) -> list:
    """Helper to read public links directly from sitemap.xml if it exists."""
    parsed_base = urlparse(base_url)
    sitemap_url = f"{parsed_base.scheme}://{parsed_base.netloc}/sitemap.xml"
    try:
        response = http_client.get(sitemap_url, timeout=5.0)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            urls = []
            for elem in root.iter():
                if elem.tag.endswith('loc'):
                    url = elem.text.strip()
                    if is_public_url(url, parsed_base.netloc):
                        urls.append(url)
            return urls
    except Exception as e:
        print(f"Sitemap check skipped: {e}")
    return []

def discover_public_links(start_url: str, max_discovery: int = 10) -> list:
    """Finds up to `max_discovery` public links, falling back to a recursive crawl."""
    domain = urlparse(start_url).netloc
    
    with httpx.Client(follow_redirects=True, timeout=10.0) as http_client:
        discovered = get_links_from_sitemap(start_url, http_client)
        if discovered:
            return discovered[:max_discovery]
        
        to_visit = [start_url]
        visited = set()
        
        while to_visit and len(visited) < max_discovery:
            current_url = to_visit.pop(0)
            if current_url in visited:
                continue
            try:
                response = http_client.get(current_url)
                if response.status_code != 200:
                    continue
                
                visited.add(current_url)
                soup = BeautifulSoup(response.text, 'html.parser')
                
                for link in soup.find_all('a', href=True):
                    full_url = urljoin(start_url, link['href'])
                    if is_public_url(full_url, domain) and full_url not in visited and full_url not in to_visit:
                        to_visit.append(full_url)
            except Exception:
                continue
        return list(visited)

def scrape_page(url: str, http_client: httpx.Client) -> str:
    """Downloads page and extracts clean, non-markup text."""
    try:
        response = http_client.get(url, timeout=8.0)
        if response.status_code != 200:
            return ""
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for elem in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            elem.extract()
            
        cleaned_text = re.sub(r'\s+', ' ', soup.get_text()).strip()
        return cleaned_text[:2500]  # Cap character limit to preserve context window
    except Exception:
        return ""