import os
import json
from flask import Flask, render_template, request, jsonify, Response
from dotenv import load_dotenv

# Import custom modules
from crawler import discover_public_links, scrape_pages_with_limit
from ai import run_ai_audit

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max request size

@app.route("/")
def index():
    """Serve the main Deep Audit frontend interface."""
    return render_template("index.html")

@app.route("/api/audit", methods=["GET"])
def run_audit():
    """
    Main real-time audit endpoint using Server-Sent Events (SSE).
    1. Validates input URL structure and accessibility.
    2. Streams progress updates matching execution steps.
    3. Discovers public pages via hybrid crawler (Sitemap -> lxml BFS Depth 3).
    4. Scrapes content with limits.
    5. Runs AI analysis on aggregated content using the custom Neeura.ai guidelines.
    6. Yields complete structured audit report to frontend.
    """
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    # Normalize URL
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
        
    print(f"\n🔍 Starting Real-Time Deep Audit for: {url}")

    def generate_audit_stream():
        try:
            # Step 1: Submit URL completed on input submission
            
            # Step 2: Discover Pages
            yield f"data: {json.dumps({'step': 'discover', 'message': 'Searching for sitemaps and discovering public pages...'})}\n\n"
            public_urls = discover_public_links(url, max_discovery=20)
            
            if not public_urls:
                yield f"data: {json.dumps({'error': 'No public pages discovered', 'suggestion': 'The site may block crawlers or have no indexable content.'})}\n\n"
                return
                
            # Step 3: Scrape Content
            yield f"data: {json.dumps({'step': 'scrape', 'message': f'Discovered {len(public_urls)} pages. Fetching and scraping page content...'})}\n\n"
            scraped_data_list = scrape_pages_with_limit(public_urls)
                    
            if not scraped_data_list:
                yield f"data: {json.dumps({'error': 'Failed to extract content from any page', 'suggestion': 'The site may rely heavily on JavaScript or block scraping.'})}\n\n"
                return
                
            combined_text = "\n".join(scraped_data_list)
            
            # Step 4: AI Analysis
            yield f"data: {json.dumps({'step': 'analyze', 'message': f'Scraped {len(combined_text)} characters. Running Neeura AI structured audit...'})}\n\n"
            audit_report = run_ai_audit(url, combined_text)
            
            # Step 5: Report Ready / Complete
            yield f"data: {json.dumps({'step': 'complete', 'message': 'Audit compiled successfully!', 'data': audit_report})}\n\n"
            print("✅ Real-Time Audit complete!")
            
        except ValueError as val_err:
            print(f"⚠️ Validation warning during SSE audit: {val_err}")
            yield f"data: {json.dumps({'error': str(val_err), 'suggestion': 'Please double check spelling, verify the target host status, or check if automated crawlers are being blocked.'})}\n\n"
            
        except Exception as e:
            print(f"❌ Unexpected error during SSE audit stream: {e}")
            yield f"data: {json.dumps({'error': f'Server error: {str(e)}', 'suggestion': 'Check server logs for internal trace information.'})}\n\n"

    return Response(generate_audit_stream(), mimetype="text/event-stream")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"🚀 Starting Deep Audit server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=True)