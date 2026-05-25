import os
import json
import threading
from typing import Dict, Any, List
from google import genai
from google.genai import types

# ===========================================================================
# Native Schema Definition (Plain Dict – avoids SDK serialization pitfalls)
# ===========================================================================

audit_report_schema = {
    "type": "OBJECT",
    "properties": {
        "business_summary": {
            "type": "STRING",
            "description": "Strictly a 1-2 sentence summary of what this business/website does based on the scraped content."
        },
        "detected_features": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "List of key features, services, or products currently identified on the site."
        },
        "issues": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "type": {
                        "type": "STRING",
                        "description": "The category of the issue, e.g., SEO, Accessibility, UX, Content, or Operations."
                    },
                    "description": {
                        "type": "STRING",
                        "description": "A highly detailed, in-depth explanation of the detected issue, bottleneck, or technical gap, and exactly how it negatively impacts their business operations."
                    }
                },
                "required": ["type", "description"]
            },
            "description": "List of detailed problems, bottlenecks, or technical gaps found on the site."
        },
        "automation_opportunities": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "opportunity": {
                        "type": "STRING",
                        "description": "Name or title of the specific automation solution Neeura.ai can build for them."
                    },
                    "impact": {
                        "type": "STRING",
                        "description": "A detailed business plan explaining exactly how Neeura.ai will implement this automation, the specific tools/AI used, and the massive impact it will have on their efficiency, scale, or revenue."
                    }
                },
                "required": ["opportunity", "impact"]
            },
            "description": "Specific, high-impact AI automation strategies and services that Neeura.ai can provide to this business."
        }
    },
    "required": ["business_summary", "detected_features", "issues", "automation_opportunities"]
}

# Thread-local storage to cache Client instances safely per execution thread
_thread_local = threading.local()

def _get_gemini_client() -> genai.Client:
    """
    Retrieves or initializes a thread-safe cached Gemini client.
    Reuses connection pools across multiple audit requests to minimize latency.
    """
    if not hasattr(_thread_local, "client"):
        # Explicitly passing API key from environment variable
        _thread_local.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return _thread_local.client

# ===========================================================================
# Core AI Audit Function (Single, self-contained entry point)
# ===========================================================================

def run_ai_audit(url: str, combined_text: str) -> dict:
    """
    Runs the website analysis using the Gemini API (google-genai SDK).
    """
    # 32k characters (approx 8k tokens) is the optimal limit for quick turnaround times
    max_chars = 32000  
    if len(combined_text) > max_chars:
        combined_text = combined_text[:max_chars] + "\n[Content truncated due to length limits]"
    
    # Prompt tailored to pitch Neeura.ai's services
    prompt = f"Analyze the following scraped website content from {url}. Generate a highly detailed, structured audit report and an AI automation business plan pitching what Neeura.ai can do for them:\n\nSCRAPED CONTENT:\n{combined_text}"
    
    try:
        # Retrieve client from cache (saves network initialization overhead)
        client = _get_gemini_client()
        
        print(f"   [AI] Cached Gemini Client retrieved.")
        print(f"   [AI] Sending content to Gemini (gemini-3.5-flash) for structured audit...")
        print(f"   [AI] Total payload size: {len(combined_text)} characters.")
        
        # Build optimized config with updated System Instructions
        config_args = {
            "temperature": 0.3, # Slightly increased to allow for more creative/detailed business plans
            "response_mime_type": "application/json",
            "response_schema": audit_report_schema,
            "system_instruction": (
                "You are an expert AI automation consultant working for 'Neeura.ai', a premier AI automation agency. "
                "Your goal is to analyze a potential client's website and generate a highly detailed, actionable business plan and automation strategy. "
                "1. Keep the 'business_summary' strictly to 1 or 2 sentences. "
                "2. For 'issues', provide deep, highly detailed explanations of their operational bottlenecks and technical gaps. "
                "3. For 'automation_opportunities', pitch specific, high-impact solutions that Neeura.ai can build and implement for them. Explain exactly what Neeura.ai will do to solve their problems and scale their business."
            )
        }
        
        # Enable low-latency fast response config if supported by model/SDK version
        try:
            if hasattr(types, "ThinkingConfig") and hasattr(types, "ThinkingLevel"):
                config_args["thinking_config"] = types.ThinkingConfig(
                    thinking_level=types.ThinkingLevel.LOW
                )
        except Exception:
            pass

        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(**config_args)
        )
        
        print(f"   [AI] Received raw response from Gemini API. Parsing response text...")
        
        result_json = json.loads(response.text)
        print(f"   [AI] Successfully parsed response JSON. Main keys: {list(result_json.keys())}")
        return result_json
        
    except Exception as e:
        print(f"   [AI Error] Gemini analysis failed: {e}")
        
        # Safe fallback schema matching frontend expectations on API failure
        return {
            "business_summary": f"Unable to analyze {url} dynamically. The site may require JavaScript rendering or the active AI service is currently unavailable.",
            "detected_features": ["Analysis error: Features could not be loaded."],
            "issues": [{
                "type": "System Error",
                "description": f"AI analysis failed to complete: {str(e)}. Please check API credentials and network quotas."
            }],
            "automation_opportunities": [{
                "opportunity": "Schedule a Manual Consultation with Neeura.ai",
                "impact": "The automated analysis cycle was interrupted. Please contact Neeura.ai directly so our experts can manually review your website and build a custom automation strategy for you."
            }]
        }