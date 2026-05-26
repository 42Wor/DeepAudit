import os
import json
import threading
from typing import Dict, Any, List
from google import genai
from google.genai import types

# ===========================================================================
# Native Schema Definition (Streamlined - No Unused Fields)
# ===========================================================================

audit_report_schema = {
    "type": "OBJECT",
    "properties": {
        "detected_industry": {
            "type": "STRING",
            "description": "The detected industry of this business: freight, healthcare, restaurant, retail, education, real_estate, salon, professional_services, manufacturing, or general."
        },
        "automation_score": {
            "type": "INTEGER",
            "description": "Automation readiness score from 5 to 100. Lower means more automation needed."
        },
        "hours_wasted_monthly": {
            "type": "STRING",
            "description": "Estimated range of hours wasted on manual tasks per month, e.g. 40-60"
        },
        "money_lost_monthly": {
            "type": "STRING",
            "description": "Estimated money lost per month due to manual processes, e.g. PKR 80,000-120,000 or $500-800"
        },
        "business_summary": {
            "type": "STRING",
            "description": "Strictly 2-3 sentences explaining what this business does, their approximate size, and their primary market."
        },
        "issues": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "type": {
                        "type": "STRING",
                        "description": "Category: SEO, Communication, Automation, Operations, Website Health, or Lead Generation."
                    },
                    "severity": {
                        "type": "STRING",
                        "description": "The severity level: critical, high, or medium"
                    },
                    "description": {
                        "type": "STRING",
                        "description": "Detailed explanation of the specific problem found, estimated hours wasted, concrete financial loss, and business impact."
                    }
                },
                "required": ["type", "severity", "description"]
            },
            "description": "List of problems found, ordered by severity."
        },
        "automation_opportunities": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "opportunity": {
                        "type": "STRING",
                        "description": "Specific solution name Neeura.ai will build."
                    },
                    "tools": {
                        "type": "STRING",
                        "description": "Specific tools used: n8n, WhatsApp API, AI chatbot, custom dashboard, etc."
                    },
                    "time_saved": {
                        "type": "STRING",
                        "description": "Hours saved per month, e.g. 15-20 hours/month"
                    },
                    "implementation_time": {
                        "type": "STRING",
                        "description": "How long to build, e.g. 1-2 weeks"
                    },
                    "impact": {
                        "type": "STRING",
                        "description": "Detailed business explanation of how Neeura.ai implements it and the direct ROI."
                    }
                },
                "required": ["opportunity", "tools", "time_saved", "implementation_time", "impact"]
            },
            "description": "Specific high-impact automation opportunities Neeura.ai can build, ordered by impact."
        }
    },
    "required": [
        "detected_industry", "automation_score", "hours_wasted_monthly", 
        "money_lost_monthly", "business_summary", 
        "issues", "automation_opportunities"
    ]
}

# Thread-local storage to cache Client instances safely per execution thread
_thread_local = threading.local()

def _get_gemini_client() -> genai.Client:
    if not hasattr(_thread_local, "client"):
        _thread_local.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return _thread_local.client

# ===========================================================================
# Core AI Audit Function
# ===========================================================================

def run_ai_audit(url: str, combined_text: str) -> dict:
    """
    Runs the website analysis using the Gemini API.
    """
    max_chars = 32000  
    if len(combined_text) > max_chars:
        combined_text = combined_text[:max_chars] + "\n[Content truncated due to length limits]"
    
    prompt = (
        f"Analyze this website: {url}\n\n"
        f"Here is the scraped content from their website. Detect their industry. Find every operational gap. "
        f"Score their automation readiness. Calculate time and money they are losing. "
        f"Then pitch specific Neeura.ai solutions with realistic timelines and ROI.\n\n"
        f"Be brutally specific. No generic advice. Every finding must reference something you actually found or did NOT find in their website content.\n\n"
        f"SCRAPED CONTENT:\n{combined_text}"
    )
    
    try:
        client = _get_gemini_client()
        
        # Calculate approximate query metrics
        estimated_tokens = len(combined_text) // 4
        
        # Structured visual logger in console
        print("\n" + "-" * 60)
        print("🧠 [AI] Initiating Gemini Structured Query")
        print(f"   Model:            gemini-3.1-flash-lite")
        print(f"   Payload Chars:    {len(combined_text):,} characters")
        print(f"   Est. Prompt Size: ~{estimated_tokens:,} tokens")
        print("   Temperature:      0.25")
        print("-" * 60)
        
        config_args = {
            "temperature": 0.25, 
            "response_mime_type": "application/json",
            "response_schema": audit_report_schema,
            "system_instruction": (
                "You are an expert AI automation consultant working for 'Neeura.ai', a premier, PSEB-certified AI automation agency based in Pakistan. "
                "Your goal is to perform a brutally honest, highly professional audit of a potential client's website to expose operational inefficiencies, manual bottlenecks, and tech gaps, demonstrating exactly how custom automation solves these issues.\n\n"
                "Strict Rules:\n"
                "1. FIRST, detect the industry of the business from the scraped content (freight/logistics, healthcare/clinic, restaurant/food, retail/ecommerce, education, real estate, salon/beauty, professional services, manufacturing, or general). Use industry-specific terms and target their distinct operational pain points throughout the report.\n"
                "2. Keep the 'business_summary' to 2-3 sentences. Identify what the business does, their approximate size, and their primary target market based on their content.\n"
                "3. For each 'issue', provide a brutally honest, face-to-face analysis of a technical or operational failure. State the issue category, its severity (critical, high, or medium), and a highly detailed description including an estimate of hours wasted monthly, concrete financial loss, and business-crippling impacts (like slow response times, drop-offs, and lost clients). Do not hallucinate elements that are not there.\n"
                "4. For 'automation_opportunities', provide specific custom builds that Neeura.ai can engineer for them (e.g., booking automation pipelines, customer qualification bots). Detail exactly how Neeura.ai builds it (using platforms like n8n, WhatsApp API, AI chatbots, custom dashboards), the realistic hours saved monthly, development timeline, and business ROI.\n"
                "5. Score the company on 'automation_score' from 5 to 100. Start at 100 and deduct points: -15 for each missing critical feature, -10 for high, -5 for medium (minimum score is 5).\n"
                "6. For estimated totals ('hours_wasted_monthly' and 'money_lost_monthly'), provide realistic monthly ranges based on their scale. Use Pakistani Rupees (PKR) for Pakistani targets/businesses, and US Dollars (USD) for international businesses.\n"
                "7. Maintain a direct, authoritative, no-nonsense face-to-face consultative tone. Avoid corporate fluff."
            )
        }
        
        # Check for thinking config support
        try:
            if hasattr(types, "ThinkingConfig"):
                config_args["thinking_config"] = types.ThinkingConfig(
                    thinking_level="low"
                )
        except Exception:
            pass

        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(**config_args)
        )
        
        result_json = json.loads(response.text)
        
        print("🧠 [AI] Gemini response received and parsed successfully.")
        print("-" * 60 + "\n")
        
        return result_json
        
    except Exception as e:
        print(f"   [AI Error] Gemini analysis failed: {e}")
        
        # Fallback dictionary matching backend expectations on failure
        return {
            "detected_industry": "general",
            "automation_score": 50,
            "hours_wasted_monthly": "20-40",
            "money_lost_monthly": "$500-1000",
            "business_summary": f"Unable to analyze {url} dynamically. The site may require JavaScript rendering or the active AI service is currently unavailable.",
            "issues": [{
                "type": "Website Health",
                "severity": "high",
                "description": f"AI analysis failed to complete: {str(e)}. Please check API credentials and network quotas."
            }],
            "automation_opportunities": [{
                "opportunity": "Schedule a Manual Consultation with Neeura.ai",
                "tools": "Custom Consultation",
                "time_saved": "10-15 hours/month",
                "implementation_time": "1 week",
                "impact": "The automated analysis cycle was interrupted. Please contact Neeura.ai directly so our experts can manually review your website and build a custom automation strategy for you."
            }]
        }