import os
import json
from openai import OpenAI

# Initialize the OpenAI Client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def run_ai_audit(url: str, combined_scraped_text: str) -> dict:
    """Takes aggregated scraped text and prompts the OpenAI model for structured audit insights."""
    system_prompt = (
        "You are an expert digital agency auditor. Analyze the following scraped textual data representing "
        "multiple public pages of a website. Provide a highly constructive audit in JSON format.\n"
        "Expected JSON format structure:\n"
        "{\n"
        '  "business_summary": "Explanation of what the business does.",\n'
        '  "detected_features": ["Feature A", "Feature B"],\n'
        '  "issues": [\n'
        '     {"type": "E.g., Bad UX", "description": "Constructive explanation."}\n'
        '  ],\n'
        '  "automation_opportunities": [\n'
        '     {"opportunity": "E.g., WhatsApp Lead Qualifier", "impact": "Why this helps save overhead."}\n'
        '  ]\n'
        "}"
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Target Domain: {url}\n\nScraped Public Pages Content:\n{combined_scraped_text}"}
        ],
        temperature=0.2
    )
    
    return json.loads(response.choices[0].message.content)