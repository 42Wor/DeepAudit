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
            "description": "2-3 sentence summary of what this business/website does based on content"
        },
        "detected_features": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "List of key features, services, or products identified on the site"
        },
        "issues": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "type": {
                        "type": "STRING",
                        "description": "The category of the issue, e.g., SEO, Accessibility, UX, Content, or Operations"
                    },
                    "description": {
                        "type": "STRING",
                        "description": "A concise description of the detected issue and its operational impact"
                    }
                },
                "required": ["type", "description"]
            },
            "description": "List of problems, bottlenecks, or technical gaps found on the site"
        },
        "automation_opportunities": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "opportunity": {
                        "type": "STRING",
                        "description": "Name or title of the automation opportunity"
                    },
                    "impact": {
                        "type": "STRING",
                        "description": "Detailed impact on business efficiency, scale, or user experience"
                    }
                },
                "required": ["opportunity", "impact"]
            },
            "description": "AI automation opportunities that could improve this business operations"
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
    
    # Prompt contains only target data to facilitate cleaner generation
    prompt = f"Analyze the following scraped website content from {url} and generate the structured audit report:\n\nSCRAPED CONTENT:\n{combined_text}"
    
    try:
        # Retrieve client from cache (saves network initialization overhead)
        client = _get_gemini_client()
        
        print(f"   [AI] Cached Gemini Client retrieved.")
        print(f"   [AI] Sending content to Gemini (gemini-3.5-flash) for structured audit...")
        print(f"   [AI] Total payload size: {len(combined_text)} characters.")
        
        # Build optimized config
        config_args = {
            "temperature": 0.2, # Lower temperature for stable, faster outputs
            "response_mime_type": "application/json",
            "response_schema": audit_report_schema,
            "system_instruction": "You are an expert web auditor and AI automation consultant. Analyze the scraped content of the website and provide a structured, practical audit with realistic and actionable recommendations."
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
                "opportunity": "Manual Audit Required",
                "impact": "The automated analysis cycle was interrupted. Please review the website's paths manually."
            }]
        }