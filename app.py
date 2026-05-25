import os
import json
import time
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
    2. Streams cool, progress‑aware updates matching execution steps.
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
            # ---- Step 0: Welcome & validation ----
            yield f"data: {json.dumps({'step': 'start', 'message': '🚀 Deep Audit initialized', 'progress': 0})}\n\n"
            time.sleep(0.2)  # small pause for dramatic effect

            # ---- Step 1: Discover pages (25%) ----
            yield f"data: {json.dumps({'step': 'discover', 'message': '🔎 25% – Scanning for sitemaps & public links...', 'progress': 25})}\n\n"
            public_urls = discover_public_links(url, max_discovery=20)

            if not public_urls:
                yield f"data: {json.dumps({'error': 'No public pages discovered', 'suggestion': 'The site may block crawlers or have no indexable content.', 'progress': 25})}\n\n"
                return

            page_count = len(public_urls)
            yield f"data: {json.dumps({'step': 'discover', 'message': f'📄 25% – Found {page_count} public pages!', 'progress': 25, 'pagesFound': page_count})}\n\n"
            time.sleep(0.2)

            # ---- Step 2: Scrape content (50%) ----
            yield f"data: {json.dumps({'step': 'scrape', 'message': f'📥 50% – Fetching and scraping {page_count} pages...', 'progress': 50})}\n\n"
            scraped_data_list = scrape_pages_with_limit(public_urls)

            if not scraped_data_list:
                yield f"data: {json.dumps({'error': 'Failed to extract content from any page', 'suggestion': 'The site may rely heavily on JavaScript or block scraping.', 'progress': 50})}\n\n"
                return

            combined_text = "\n".join(scraped_data_list)
            char_count = len(combined_text)
            yield f"data: {json.dumps({'step': 'scrape', 'message': f'✨ 50% – Scraped {char_count:,} characters from {len(scraped_data_list)} pages.', 'progress': 50, 'characters': char_count})}\n\n"
            time.sleep(0.2)

            # ---- Step 3: AI analysis (75%) ----
            yield f"data: {json.dumps({'step': 'analyze', 'message': '🧠 75% – Running Neeura AI structured audit (this may take a moment)...', 'progress': 75})}\n\n"
            audit_report = run_ai_audit(url, combined_text)

            # ---- Step 4: Final report (100%) ----
            # Create a "cool" summary to inject into the report (optional)
            summary = {
                "audited_url": url,
                "pages_analyzed": len(scraped_data_list),
                "total_characters": char_count,
                "report_version": "Deep Audit v2.0",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
            }
            # Merge summary into audit report if it's a dict, otherwise attach as extra field
            if isinstance(audit_report, dict):
                audit_report["audit_summary"] = summary
            else:
                # If AI returns a string, wrap it
                audit_report = {"raw_report": audit_report, "audit_summary": summary}

            yield f"data: {json.dumps({'step': 'complete', 'message': '🎉 100% – Audit complete! Ready to view your report.', 'progress': 100, 'data': audit_report})}\n\n"
            print("✅ Real-Time Audit complete!")

        except ValueError as val_err:
            print(f"⚠️ Validation warning during SSE audit: {val_err}")
            yield f"data: {json.dumps({'error': str(val_err), 'suggestion': 'Please double check spelling, verify the target host status, or check if automated crawlers are being blocked.', 'progress': 0})}\n\n"

        except Exception as e:
            print(f"❌ Unexpected error during SSE audit stream: {e}")
            yield f"data: {json.dumps({'error': f'Server error: {str(e)}', 'suggestion': 'Check server logs for internal trace information.', 'progress': 0})}\n\n"

    return Response(generate_audit_stream(), mimetype="text/event-stream")


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"🚀 Starting Deep Audit server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=True)