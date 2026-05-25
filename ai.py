import os
import json
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

# ===========================================================================
# Core AI Audit Function (Single, self-contained entry point)
# ===========================================================================

def run_ai_audit(url: str, combined_text: str) -> dict:
    """
    Runs the website analysis using the Gemini API (google-genai SDK).
    
    To change AI providers in the future (e.g. to OpenAI or Anthropic), 
    this is the ONLY function in your entire application you will need to edit.
    """
    # Truncate content to fit securely inside LLM context window limits
    max_chars = 40000  
    if len(combined_text) > max_chars:
        combined_text = combined_text[:max_chars] + "\n[Content truncated due to length limits]"
    
    prompt = f"""
You are an expert web auditor and AI automation consultant. Analyze the scraped content from {url} and provide a comprehensive, highly professional audit.

SCRAPED CONTENT:
{combined_text}

Provide a structured analysis covering:
1. What the business does (2-3 sentences)
2. Key features, services, or products detected
3. Issues found (SEO, accessibility, UX, content quality, or operational bottlenecks)
4. AI automation opportunities that could improve this business

Focus on practical, actionable insights. Be specific, realistic, and avoid generic recommendations.
"""
    
    try:
        # Initialize the modern Gemini Client using the environment variable API key
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        
        print(f"   [AI] Initialized Gemini Client successfully.")
        print(f"   [AI] Sending content to Gemini (gemini-3.5-flash) for structured audit...")
        print(f"   [AI] Total payload size: {len(combined_text)} characters.")
        
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                response_mime_type="application/json",
                response_schema=audit_report_schema,
            )
        )
        
        print(f"   [AI] Received raw response from Gemini API. Parsing response text...")
        
        # Parse and return the structured JSON response
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