import os
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

# Import our custom modules
from crawler import discover_public_links, scrape_page
from ai import run_ai_audit

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max request size

@app.route("/")
def index():
    """Serve the main Deep Audit frontend interface."""
    return render_template("index.html")

@app.route("/api/audit", methods=["POST"])
def run_audit():
    """
    Main audit endpoint.
    1. Validates input URL
    2. Discovers public pages via hybrid crawler (Sitemap -> lxml BFS)
    3. Scrapes content from discovered pages
    4. Runs AI analysis on aggregated content (Currently Placeholder)
    5. Returns structured audit report to frontend
    """
    try:
        # 1. Parse and validate request
        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body must be JSON"}), 400
        
        url = data.get("url", "").strip()
        if not url:
            return jsonify({"error": "URL parameter is required"}), 400
        
        # Normalize URL
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
            
        print(f"\n🔍 Starting Deep Audit for: {url}")
        
        # 2. Discover public pages
        print("📋 Discovering public pages...")
        public_urls = discover_public_links(url, max_discovery=6)
        
        if not public_urls:
            return jsonify({
                "error": "No public pages discovered",
                "suggestion": "The site may block crawlers or have no indexable content"
            }), 400
            
        print(f"   Found {len(public_urls)} public pages")
        
        # 3. Scrape content from discovered pages
        print("📄 Scraping page content...")
        scraped_data_list = []
        
        for i, page_url in enumerate(public_urls, 1):
            print(f"   [{i}/{len(public_urls)}] Scraping: {page_url}")
            text = scrape_page(page_url)
            if text:
                scraped_data_list.append(f"PAGE: {page_url}\nCONTENT: {text}\n---")
                
        if not scraped_data_list:
            return jsonify({
                "error": "Failed to extract content from any page",
                "suggestion": "The site may rely heavily on JavaScript or block scraping"
            }), 400
            
        combined_text = "\n".join(scraped_data_list)
        print(f"   Extracted {len(combined_text)} characters total")
        
        # 4. Run AI analysis (Currently returns exact placeholder data)
        print("🤖 Running AI analysis...")
        audit_report = run_ai_audit(url, combined_text)
        
        # 5. Add scanned pages to the final response and return
        audit_report["scanned_pages"] = public_urls
        
        print("✅ Audit complete!")
        return jsonify(audit_report)
        
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return jsonify({
            "error": f"Server error: {str(e)}",
            "suggestion": "Check server logs for details"
        }), 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"🚀 Starting Deep Audit server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=True)