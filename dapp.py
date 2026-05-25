import os
import time
import json
from flask import Flask, render_template, request, jsonify, Response

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/audit", methods=["GET"])
def run_audit():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
        
    def generate_dummy_stream():
        yield f"data: {json.dumps({'step': 'discover', 'message': 'Searching for public sitemaps and crawling domain routes...'})}\n\n"
        time.sleep(1.2)
        
        yield f"data: {json.dumps({'step': 'scrape', 'message': 'Discovered 6 pages. Scraping text content and filtering code blocks...'})}\n\n"
        time.sleep(1.2)
        
        yield f"data: {json.dumps({'step': 'analyze', 'message': 'Sending payload to Gemini for structured audit and analysis...'})}\n\n"
        time.sleep(1.2)
        
        dummy_data = {
            "detected_industry": "professional_services",
            "automation_score": 45,
            "hours_wasted_monthly": "35-50",
            "money_lost_monthly": "$1,200-$2,000",
            "business_summary": "This site represents a growing B2B professional services firm operating globally. While they maintain active landing pages, client acquisition and operations are managed via slow, manual follow-ups.",
            "issues": [
                {
                    "type": "Lead Generation",
                    "severity": "critical",
                    "description": "Lead intake forms are static and completely unintegrated with a CRM. Manual entry processes waste up to 18 hours per month, with approximately a 25% drop-off in candidate follow-up times."
                },
                {
                    "type": "Communication",
                    "severity": "high",
                    "description": "Lack of live chat support or interactive triage means off-hours inquiries are completely dropped, costing around 12 hours/month of potential engagement."
                },
                {
                    "type": "Operations",
                    "severity": "medium",
                    "description": "No self-serve booking interface. Manual coordination of calendar availability via back-and-forth emails wastes 8 hours/month."
                }
            ],
            "automation_opportunities": [
                {
                    "opportunity": "CRM Sync & Lead Qualification Pipeline",
                    "tools": "n8n, OpenAI Assistant API, HubSpot",
                    "time_saved": "15-20 hours/month",
                    "implementation_time": "2 weeks",
                    "impact": "Automatically processes incoming leads, runs AI qualification scoring, and pushes structured records directly into HubSpot with custom alerts."
                },
                {
                    "opportunity": "24/7 AI-Driven Triage and Booking Agent",
                    "tools": "Custom AI Chatbot, Cal.com API, n8n",
                    "time_saved": "10-15 hours/month",
                    "implementation_time": "2-3 weeks",
                    "impact": "Resolves basic visitor questions instantly and books qualified prospect conversations directly into sales calendars without human delay."
                }
            ]
        }
        
        yield f"data: {json.dumps({'step': 'complete', 'message': 'Audit compiled successfully!', 'data': dummy_data})}\n\n"

    return Response(generate_dummy_stream(), mimetype="text/event-stream")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)