import os
from flask import Flask, render_template, request, jsonify
import httpx

from crawler import discover_public_links, scrape_page
from ai import run_ai_audit

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/audit", methods=["POST"])
def run_audit():
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    
    if not url:
        return jsonify({"error": "A URL parameter is required."}), 400
        
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # 1. Page Discovery
    public_urls = discover_public_links(url, max_discovery=8)
    if not public_urls:
        return jsonify({"error": "Failed to discover any public URLs on this site."}), 400

    # 2. Extract Data from discovered URLs
    scraped_data_list = []
    with httpx.Client(follow_redirects=True, timeout=10.0) as http_client:
        for p_url in public_urls:
            text = scrape_page(p_url, http_client)
            if text:
                scraped_data_list.append(f"PAGE: {p_url}\nTEXT: {text}\n---")
                
    combined_scraped_text = "\n".join(scraped_data_list)

    # 3. LLM Audit Generation
    try:
        audit_report = run_ai_audit(url, combined_scraped_text)
        audit_report["scanned_pages"] = public_urls
        return jsonify(audit_report)
    except Exception as e:
        return jsonify({"error": f"LLM analysis failed: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)