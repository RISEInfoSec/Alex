from __future__ import annotations
import json
import logging
import os

import pandas as pd
import requests

from alex.utils.io import load_df, save_df, root_file, validate_columns
from alex.utils.text import clean, unique_keep

logger = logging.getLogger(__name__)

# Note: uses requests.post directly (not HttpClient) because LLM calls should NOT be cached
# and the OpenAI API requires POST, not GET.
OPENAI_URL = "https://api.openai.com/v1/responses"

PROMPT = """
Classify this OSINT / cyber investigation paper into:
- Category (e.g., Digital Forensics, Threat Intelligence, OSINT Methodology, Network Security, Privacy & Surveillance, Cybercrime, Other)
- Investigation_Type (e.g., Network Investigation, Social Media Analysis, Dark Web Analysis, Malware Analysis, Attribution, Other)
- OSINT_Source_Types (list, e.g., Social Media, Public Records, Dark Web, DNS/WHOIS, Satellite Imagery, Government Data)
- Keywords (list of key terms)
- Tags (list of miscellaneous labels)
- Quality_Tier (one of: Seminal, High, Standard, Exploratory)
Return JSON only.
"""

FALLBACK = {
    "Category": "Other",
    "Investigation_Type": "Other",
    "OSINT_Source_Types": [],
    "Keywords": [],
    "Tags": [],
    "Quality_Tier": "Standard",
}


def _safe_citation_count(row) -> float:
    try:
        return float(row.get("citation_count") or 0)
    except (ValueError, TypeError):
        return 0.0


def call_openai(row: dict) -> dict:
    api_key = os.getenv("OPENAI_API_KEY", "")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    if not api_key:
        return dict(FALLBACK)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": PROMPT}]},
            {"role": "user", "content": [{"type": "input_text", "text": json.dumps(row, ensure_ascii=False)}]},
        ],
    }
    try:
        r = requests.post(OPENAI_URL, headers=headers, json=body, timeout=60)
        r.raise_for_status()
        data = r.json()
        text = data.get("output_text", "")
        if text:
            return json.loads(text)
        logger.warning("Empty output_text from OpenAI for: %s", row.get("title", ""))
        return dict(FALLBACK)
    except requests.exceptions.RequestException as exc:
        logger.warning("OpenAI request failed for '%s': %s", row.get("title", ""), exc)
        return dict(FALLBACK)
    except json.JSONDecodeError as exc:
        logger.warning("OpenAI returned invalid JSON for '%s': %s", row.get("title", ""), exc)
        return dict(FALLBACK)


def run() -> None:
    df = load_df(root_file("data", "accepted_harvested.csv"))
    if df.empty:
        print("No harvested accepted candidates to classify.")
        return
    validate_columns(df, ["title", "abstract", "venue", "authors", "citation_count"], "accepted_harvested.csv")
    rows = []
    for _, row in df.iterrows():
        payload = {
            "title": clean(row.get("title")),
            "abstract": clean(row.get("abstract")),
            "venue": clean(row.get("venue")),
            "authors": clean(row.get("authors")),
        }
        tags = call_openai(payload)
        out = dict(row)
        out["Category"] = tags.get("Category", "Other")
        out["Investigation_Type"] = tags.get("Investigation_Type", "Other")
        out["OSINT_Source_Types"] = "; ".join(unique_keep(tags.get("OSINT_Source_Types", [])))
        out["Keywords"] = "; ".join(unique_keep(tags.get("Keywords", [])))
        out["Tags"] = "; ".join(unique_keep(tags.get("Tags", [])))
        out["Quality_Tier"] = tags.get("Quality_Tier", "Standard")
        out["Seminal_Flag"] = "TRUE" if _safe_citation_count(row) >= 500 else "FALSE"
        rows.append(out)
    save_df(root_file("data", "accepted_classified.csv"), pd.DataFrame(rows))
    print(f"Classified {len(rows)} papers")
