"""
LLM judge layer.

Takes the rule-based issues (spelling + semantic) and uses Groq (Llama 3.3), grounded
with RAG-retrieved knowledge-base context, to:
  1. Filter out spelling false-positives (brand names, model numbers, tech terms)
  2. Add a plain-English explanation + concrete fix suggestion to semantic issues

Falls back silently (returns rule-based issues unchanged) if no
GROQ_API_KEY is set, so the script always works even without LLM access.
"""

from __future__ import annotations

import json
import os
import re
from typing import List, Optional
from groq import Groq

# Model Name for Groq
MODEL_NAME = "llama-3.3-70b-versatile"


def _get_client() -> Optional[Groq]:
    """Initialize Groq client if API key exists."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None
    return Groq(api_key=api_key)


def _short_error(e: Exception) -> str:
    """Extract a simple short error message."""
    msg = str(e)
    match = re.search(r"'message':\s*'([^']+)'", msg)
    if match:
        msg = match.group(1)
    return msg[:200]


def _call_groq_json(client: Groq, system: str, user: str) -> Optional[dict | list]:
    """Call Groq Llama model and parse a JSON response."""
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            model=MODEL_NAME,
            temperature=0,
            response_format={"type": "json_object"},  # Forces JSON output
        )
        text = (response.choices[0].message.content or "").strip()
        
        # Clean markdown code blocks if Llama wraps JSON in ```json
        if "```" in text:
            text = re.sub(r"```json\s*", "", text)
            text = re.sub(r"```\s*", "", text)

        return json.loads(text.strip())
    except Exception as e:
        raise RuntimeError(_short_error(e)) from e


# --------------------------------------------------------------------------
# 1. Spelling false-positive filter
# --------------------------------------------------------------------------

def judge_spelling_issues(issues: List, kb) -> List:
    """
    Filters out false-positive typos (brands, technical terms) using Groq.
    """
    client = _get_client()
    if client is None or not issues:
        return issues  # Fallback to rule-based

    kb_context = kb.retrieve("spelling brand names technical terms typo", top_k=3)
    context_text = "\n\n".join(f"[{c.source}] {c.text}" for c in kb_context)

    flagged_words = [
        {"location": i.location, "word": i.original, "suggestion": i.suggestion}
        for i in issues
    ]

    system = (
        "You are a precise proofreading assistant for ecommerce product pages. "
        "Decide whether flagged words are real spelling mistakes or acceptable brand/product/technical terms. "
        "Respond strictly with valid JSON inside an object containing a 'results' key array."
    )
    
    user = f"""Guidelines (from internal knowledge base):
{context_text}

Flagged words:
{json.dumps(flagged_words, indent=2)}

Respond in this exact JSON format:
{{
  "results": [
    {{"word": "example", "is_real_mistake": true, "corrected_suggestion": "correct_word"}}
  ]
}}

Rules:
- is_real_mistake=false for brand names, model names, technical terms, units.
- is_real_mistake=true only for genuine misspellings.
- corrected_suggestion: correction string if true, else null.
"""

    try:
        data = _call_groq_json(client, system, user)
        if isinstance(data, dict) and "results" in data:
            result = data["results"]
        elif isinstance(data, list):
            result = data
        else:
            result = None
    except Exception as e:
        print(f"[llm_judge] LLM call failed, falling back to rule-based spelling results: {e}")
        return issues

    if not result:
        return issues

    verdicts = {v["word"]: v for v in result if "word" in v}

    filtered = []
    for issue in issues:
        verdict = verdicts.get(issue.original)
        if verdict is None:
            filtered.append(issue)
            continue
        if verdict.get("is_real_mistake"):
            if verdict.get("corrected_suggestion"):
                issue.suggestion = verdict["corrected_suggestion"]
            issue.message += " (confirmed by LLM)"
            filtered.append(issue)
            
    return filtered


# --------------------------------------------------------------------------
# 2. Semantic issue enrichment
# --------------------------------------------------------------------------

def enrich_semantic_issues(issues: List, kb) -> List:
    """
    Adds explanation and fix suggestions for semantic issues using Groq.
    """
    client = _get_client()
    if client is None or not issues:
        return issues

    for issue in issues:
        kb_context = kb.retrieve(issue.message, top_k=2)
        context_text = "\n\n".join(f"[{c.source}] {c.text}" for c in kb_context)
        if not context_text:
            continue

        system = (
            "You are an ecommerce accessibility/SEO auditor. "
            "Write a short explanation and concrete fix. Respond ONLY in JSON format."
        )
        user = f"""Guideline context:
{context_text}

Detected issue: {issue.location}: {issue.message}

Respond with JSON object:
{{"explanation": "one sentence explanation", "fix": "one sentence concrete fix"}}"""

        try:
            result = _call_groq_json(client, system, user)
        except Exception as e:
            print(f"[llm_judge] LLM call failed, falling back to rule-based semantic results for remaining issues: {e}")
            break

        if result and isinstance(result, dict) and "fix" in result:
            issue.message = f"{issue.message} | {result.get('explanation', '')}"
            issue.suggestion = result.get("fix")

    return issues