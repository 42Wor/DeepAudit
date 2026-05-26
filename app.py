import os
import json
import time
from flask import Flask, render_template, request, jsonify, Response
from dotenv import load_dotenv

# Import custom crawler and AI audit modules
from crawler import discover_public_links, scrape_pages_with_limit
from ai import run_ai_audit
from cache_manager import audit_cache, active_tracker

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
    1. Distinguishes between stream initiations and standard fetch checks.
    2. Dynamically falls back to local memory if Redis is offline.
    3. Handles non-blocking lock checks and cached output routing.
    4. Streams real-time updates of crawler metrics and AI analysis results.
    """
    url = request.args.get("url", "").strip()
    bypass_cache = request.args.get("nocache", "false").lower() == "true"

    if not url:
        return jsonify({"error": "URL parameter is required"}), 400

    # Normalize URL structure
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Distinguish between EventSource (SSE) streams and standard fetch() requests
    is_sse_request = "text/event-stream" in request.headers.get("Accept", "")

    # Handle standard fetch checks (e.g., status inquiries or error reading fallbacks)
    if not is_sse_request:
        is_locked = False
        if hasattr(active_tracker, "local_active_set"):
            is_locked = url.strip().lower() in active_tracker.local_active_set
        elif hasattr(active_tracker, "client"):
            try:
                is_locked = bool(active_tracker.client.exists(f"lock:audit:{url.strip().lower()}"))
            except Exception:
                pass
        
        if is_locked:
            return jsonify({
                "error": "An active audit is currently running for this website."
            }), 429
            
        cached_report = audit_cache.get(url)
        if cached_report:
            return jsonify(cached_report)
        return jsonify({"status": "idle"})

    # --- BELOW CODE EXECUTES FOR LIVE SSE CONNECTIONS ONLY ---
    if not active_tracker.acquire(url):
        return jsonify({
            "error": "An active audit is already running for this website. Please wait for it to finish."
        }), 429

    def generate_audit_stream():
        try:
            # Check cached reports if cache bypass was not requested
            if not bypass_cache:
                cached_report = audit_cache.get(url)
                if cached_report:
                    # Visual Terminal Logger for Cache Hit
                    print("\n" + "="*70)
                    print("⚡ [CACHE HIT] Serving Cached Audit Report")
                    print(f"   URL:     {url}")
                    print("   Source:  Distributed Redis Cache (or local fallback)")
                    print("   Cost:    0 Web Requests / 0 Gemini Tokens (100% Free)")
                    print("="*70 + "\n")

                    # Fast handshake for cached results (no artificial delays)
                    yield f"data: {json.dumps({'step': 'start', 'message': '🚀 Connected to cache stream...', 'progress': 10})}\n\n"
                    time.sleep(0.05)
                    
                    if "audit_summary" in cached_report:
                        cached_report["audit_summary"]["from_cache"] = True

                    yield f"data: {json.dumps({'step': 'complete', 'message': '🎉 Loaded cached report.', 'progress': 100, 'data': cached_report})}\n\n"
                    return

            # Visual Terminal Logger for Cache Bypass/Miss
            if bypass_cache:
                print("\n" + "="*70)
                print("🔄 [CACHE BYPASS] Force-Refreshing Website Audit")
                print(f"   URL:     {url}")
                print("   Reason:  Bypassing existing Redis cache (nocache=true)")
                print("   Action:  Executing fresh crawl and calling Gemini API.")
                print("="*70 + "\n")
            else:
                print("\n" + "="*70)
                print("🌀 [CACHE MISS] Running Full Audit & AI Analysis")
                print(f"   URL:     {url}")
                print("   Reason:  No valid cache record found (or cache expired)")
                print("   Action:  Initiating crawler, parser, and Gemini API pipeline.")
                print("="*70 + "\n")

            # ---- Step 0: Welcome & validation ----
            yield f"data: {json.dumps({'step': 'start', 'message': '🚀 Deep Audit initialized', 'progress': 0})}\n\n"
            time.sleep(0.1)

            # ---- Step 1: Discover pages (25%) ----
            yield f"data: {json.dumps({'step': 'discover', 'message': '🔎 25% – Scanning for sitemaps & public links...', 'progress': 25})}\n\n"
            public_urls = discover_public_links(url, max_discovery=20)

            if not public_urls:
                yield f"data: {json.dumps({'error': 'No public pages discovered', 'suggestion': 'The site may block crawlers or has no indexable routes.', 'progress': 25})}\n\n"
                return

            page_count = len(public_urls)
            yield f"data: {json.dumps({'step': 'discover', 'message': f'📄 25% – Found {page_count} public pages!', 'progress': 25, 'pagesFound': page_count})}\n\n"
            time.sleep(0.1)

            # ---- Step 2: Scrape content (50%) ----
            yield f"data: {json.dumps({'step': 'scrape', 'message': f'📥 50% – Fetching and scraping {page_count} pages...', 'progress': 50})}\n\n"
            scraped_data_list = scrape_pages_with_limit(public_urls)

            if not scraped_data_list:
                yield f"data: {json.dumps({'error': 'Failed to extract content from any page', 'suggestion': 'The site may rely heavily on JavaScript or blocks scraping.', 'progress': 50})}\n\n"
                return

            combined_text = "\n".join(scraped_data_list)
            char_count = len(combined_text)
            yield f"data: {json.dumps({'step': 'scrape', 'message': f'✨ 50% – Scraped {char_count:,} characters from {len(scraped_data_list)} pages.', 'progress': 50, 'characters': char_count})}\n\n"
            time.sleep(0.1)

            # ---- Step 3: AI analysis (75%) ----
            yield f"data: {json.dumps({'step': 'analyze', 'message': '🧠 75% – Running Neeura AI structured audit (this may take a moment)...', 'progress': 75})}\n\n"
            audit_report = run_ai_audit(url, combined_text)

            # ---- Step 4: Final report (100%) ----
            summary = {
                "audited_url": url,
                "pages_analyzed": len(scraped_data_list),
                "total_characters": char_count,
                "report_version": "Deep Audit v2.0",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
                "from_cache": False
            }
            
            # Format and cache completed data
            if isinstance(audit_report, dict):
                audit_report["audit_summary"] = summary
                audit_cache.set(url, audit_report)
            else:
                audit_report = {"raw_report": audit_report, "audit_summary": summary}
                audit_cache.set(url, audit_report)

            yield f"data: {json.dumps({'step': 'complete', 'message': '🎉 100% – Audit complete! Ready to view your report.', 'progress': 100, 'data': audit_report})}\n\n"
            
            print("\n" + "="*70)
            print("✅ Audit complete and saved to Cache.")
            print("="*70 + "\n")

        except ValueError as val_err:
            print(f"⚠️ Validation warning during SSE audit: {val_err}")
            yield f"data: {json.dumps({'error': str(val_err), 'suggestion': 'Please double check spelling or verify target host status.', 'progress': 0})}\n\n"

        except Exception as e:
            print(f"❌ Unexpected error during SSE audit stream: {e}")
            yield f"data: {json.dumps({'error': f'Server error: {str(e)}', 'suggestion': 'Check server logs for internal trace information.', 'progress': 0})}\n\n"

        finally:
            # Guarantee release of active execution lock under all scenarios [1]
            active_tracker.release(url)

    return Response(generate_audit_stream(), mimetype="text/event-stream")


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"🚀 Starting Deep Audit server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=True)