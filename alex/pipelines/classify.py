from __future__ import annotations
import os, json
import pandas as pd
import requests
from alex.utils.io import load_df, save_df, root_file
from alex.utils.text import clean, unique_keep

OPENAI_URL = "https://api.openai.com/v1/responses"

PROMPT = '''
Classify this OSINT / cyber investigation paper into:
- Category
- Investigation_Type
- OSINT_Source_Types
- Keywords
- Tags
Return JSON only.
'''

def call_openai(row: dict) -> dict:
    api_key = os.getenv("OPENAI_API_KEY", "")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    if not api_key:
        return {
            "Category": "Other",
            "Investigation_Type": "Other",
            "OSINT_Source_Types": [],
            "Keywords": [],
            "Tags": []
        }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": PROMPT}]},
            {"role": "user", "content": [{"type": "input_text", "text": json.dumps(row, ensure_ascii=False)}]},
        ]
    }
    r = requests.post(OPENAI_URL, headers=headers, json=body, timeout=60)
    r.raise_for_status()
    data = r.json()
    text = data.get("output_text", "")
    return json.loads(text) if text else {
        "Category": "Other", "Investigation_Type": "Other", "OSINT_Source_Types": [], "Keywords": [], "Tags": []
    }

def run() -> None:
    df = load_df(root_file("data", "accepted_harvested.csv"))
    if df.empty:
        print("No harvested accepted candidates to classify.")
        return
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
        out["Seminal_Flag"] = "TRUE" if float(row.get("citation_count") or 0) >= 500 else "FALSE"
        rows.append(out)
    save_df(root_file("data", "accepted_classified.csv"), pd.DataFrame(rows))
    print(f"Classified {len(rows)} papers")
