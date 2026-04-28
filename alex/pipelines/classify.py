from __future__ import annotations
import json
import logging
import os

import pandas as pd
import requests

from alex.utils.io import load_df, load_json, save_df, root_file, validate_columns
from alex.utils.text import clean, normalize_title, unique_keep

logger = logging.getLogger(__name__)

# Note: uses requests.post directly (not HttpClient) because LLM calls should NOT be cached
# and the OpenAI API requires POST, not GET.
OPENAI_URL = "https://api.openai.com/v1/responses"

# Fixed enum: Category buckets. Picked from labels the model itself produced
# when classify worked (Apr 25 corpus) plus gaps for research areas that
# weren't getting their own bucket. Keep this list closed — every change
# affects how downstream consumers (the site, search, filters) bucket papers.
# When "Other" exceeds ~20% of a run, that's a signal to add a category, not
# silently drift on the model's whim.
CATEGORIES = [
    "OSINT Methodology",
    "Social Media & SOCMINT",
    "Dark Web & Underground",
    "Cyber Threat Intelligence",
    "Digital Forensics & Evidence",
    "Malware & Exploits",
    "Vulnerability Research",
    "Disinformation & Influence",
    "Cybercrime & Fraud",
    "Network & Infrastructure Security",
    "IoT & CPS Security",
    "Privacy & Surveillance",
    "AI/ML for Security",
    "Foundations & Surveys",
    "Other",
]

INVESTIGATION_TYPES = [
    "Network Investigation",
    "Social Media Analysis",
    "Dark Web Analysis",
    "Malware Analysis",
    "Attribution",
    "Phishing Analysis",
    "Forensic Investigation",
    "Threat Hunting",
    "Vulnerability Assessment",
    "Incident Response",
    "Other",
]

OSINT_SOURCE_TYPES = [
    "Social Media",
    "Public Records",
    "Dark Web",
    "DNS/WHOIS",
    "Satellite Imagery",
    "Government Data",
    "News Media",
    "Forums & Communities",
    "Code Repositories",
    "Corporate Records",
    "Court Records",
    "Academic Literature",
    "Leaked Data",
    "Other",
]

# OpenAI structured-output schema. With strict=True every property must be
# in `required` and `additionalProperties: false` is mandatory. The enums
# guarantee Category/Investigation_Type/source-types come back from the
# fixed lists above — no more model-invented near-duplicates.
CLASSIFICATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["Category", "Investigation_Type", "OSINT_Source_Types", "Keywords", "Tags"],
    "properties": {
        "Category": {"type": "string", "enum": CATEGORIES},
        "Investigation_Type": {"type": "string", "enum": INVESTIGATION_TYPES},
        "OSINT_Source_Types": {
            "type": "array",
            "items": {"type": "string", "enum": OSINT_SOURCE_TYPES},
        },
        "Keywords": {"type": "array", "items": {"type": "string"}},
        "Tags": {"type": "array", "items": {"type": "string"}},
    },
}

PROMPT = (
    "You classify OSINT and cyber-investigation papers. Read the paper's "
    "title, abstract, venue, and authors, then return a JSON object that "
    "matches the supplied schema. Pick the single best Category and "
    "Investigation_Type from the enums; use 'Other' only when no listed "
    "value reasonably fits. OSINT_Source_Types must be an array of values "
    "from the source-type enum (use [] when no specific source applies). "
    "Keywords and Tags are free-form short strings."
)

FALLBACK = {
    "Category": "Other",
    "Investigation_Type": "Other",
    "OSINT_Source_Types": [],
    "Keywords": [],
    "Tags": [],
}

# Account-level OpenAI failures that will not recover on retry. We raise
# instead of falling back so the run aborts before stamping every paper as
# Category=Other (the silent-corruption mode that produced 1,499 bogus
# classifications on 2026-04-25 when the account ran out of credits).
FATAL_ERROR_CODES = {
    "insufficient_quota",
    "billing_hard_limit_reached",
    "account_deactivated",
    "invalid_api_key",
}


class OpenAIQuotaError(RuntimeError):
    """Raised on account-level OpenAI failures so classify aborts loudly."""


# Per-run cumulative token usage. Reset by run() and reported at end so
# any pipeline activity touching OpenAI surfaces its token spend.
_TOKEN_USAGE: dict = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

# Default seminal threshold used when quality_weights.json is absent (tests
# that don't write the scoring config) or when the key is missing. Matches
# the longstanding hardcoded value.
_DEFAULT_SEMINAL_THRESHOLD = 500


def _seminal_threshold() -> float:
    """Read the seminal-citation threshold from quality_weights.json.

    Until 2026-04-28 this value was hardcoded `500` in classify.py, which
    quietly ignored the same key in `config/quality_weights.json`. Reading
    it here keeps the config as the single source of truth for thresholds.
    """
    path = root_file("config", "quality_weights.json")
    if not path.exists():
        return _DEFAULT_SEMINAL_THRESHOLD
    try:
        weights = load_json(path)
    except (ValueError, OSError):
        return _DEFAULT_SEMINAL_THRESHOLD
    return float(weights.get("seminal_citation_threshold", _DEFAULT_SEMINAL_THRESHOLD))


def _safe_citation_count(row) -> float:
    try:
        return float(row.get("citation_count") or 0)
    except (ValueError, TypeError):
        return 0.0


def _record_usage(usage: dict) -> None:
    if not usage:
        return
    _TOKEN_USAGE["calls"] += 1
    _TOKEN_USAGE["input_tokens"]  += int(usage.get("input_tokens",  0) or 0)
    _TOKEN_USAGE["output_tokens"] += int(usage.get("output_tokens", 0) or 0)
    _TOKEN_USAGE["total_tokens"]  += int(usage.get("total_tokens",  0) or 0)


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
        # Structured outputs: forces the model to return JSON conforming
        # to CLASSIFICATION_SCHEMA. With strict=True the model can't drift
        # on Category/Investigation_Type/source-types — values come from
        # the fixed enums or the request fails server-side.
        "text": {
            "format": {
                "type": "json_schema",
                "name": "PaperClassification",
                "schema": CLASSIFICATION_SCHEMA,
                "strict": True,
            },
        },
    }
    title = row.get("title", "")
    try:
        r = requests.post(OPENAI_URL, headers=headers, json=body, timeout=60)
    except requests.exceptions.RequestException as exc:
        logger.warning("OpenAI network error for %r: %s", title, exc)
        return dict(FALLBACK)

    if not r.ok:
        # Check for fatal account-level errors before falling back. The error
        # code lives in the response body; r.raise_for_status() throws away
        # that detail, so parse it ourselves.
        code = ""
        try:
            code = (r.json().get("error") or {}).get("code", "") or ""
        except ValueError:
            pass
        if code in FATAL_ERROR_CODES or r.status_code in (401, 403):
            raise OpenAIQuotaError(
                f"OpenAI {r.status_code} (code={code or 'unknown'}) — aborting run. "
                f"Body: {r.text[:500]}"
            )
        logger.warning("OpenAI %s for %r: %s", r.status_code, title, r.text[:300])
        return dict(FALLBACK)

    try:
        data = r.json()
    except ValueError as exc:
        logger.warning("OpenAI returned non-JSON for %r: %s", title, exc)
        return dict(FALLBACK)

    _record_usage(data.get("usage") or {})

    text = _extract_response_text(data)
    if not text:
        logger.warning("Empty response text from OpenAI for %r", title)
        return dict(FALLBACK)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("OpenAI response text not JSON for %r: %s", title, exc)
        return dict(FALLBACK)


def _extract_response_text(data: dict) -> str:
    """Pull the model's text from the OpenAI Responses API.

    The top-level `output_text` convenience field was reliable through
    Apr 25 then started returning empty in our request shape (observed
    Apr 27: 100% empty across 519 calls). The structured
    `output[i].content[j].text` path is canonical and is populated when
    the model generates text. We prefer the convenience field when it
    has content and walk the structured array as fallback. The structured
    output may include multiple text segments (e.g. with reasoning blocks),
    so we concatenate them in order.
    """
    text = data.get("output_text") or ""
    if text:
        return text
    parts: list[str] = []
    for item in data.get("output") or []:
        for content in item.get("content") or []:
            seg = content.get("text") or ""
            if seg:
                parts.append(seg)
    return "".join(parts)


def _dedup_key(row) -> str:
    """Dedup key for a paper row: normalised DOI if present, else normalised title."""
    doi = clean(row.get("doi", "")).lower()
    if doi:
        return f"doi:{doi}"
    return f"title:{normalize_title(clean(row.get('title', '')))}"


def _load_rescore_window_run_id() -> str:
    path = root_file("data", ".rescore_window.json")
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Ignoring malformed rescore window token: %s", path)
        return ""
    return clean(data.get("run_id", ""))


def _rows_match_run_id(df: pd.DataFrame, run_id: str, context: str) -> bool:
    if df.empty:
        return True
    if "rescore_run_id" not in df.columns:
        logger.warning("Ignoring rescore pruning: %s missing rescore_run_id", context)
        return False
    values = {clean(v) for v in df["rescore_run_id"].tolist() if clean(v)}
    if values != {run_id}:
        logger.warning("Ignoring rescore pruning: %s run_id mismatch (%s)", context, sorted(values))
        return False
    return True


def run() -> None:
    _TOKEN_USAGE.update({"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
    output_path = root_file("data", "accepted_classified.csv")
    window_path = root_file("data", ".rescore_window.json")
    df = load_df(root_file("data", "accepted_harvested.csv"))
    rescored = load_df(root_file("data", "rescore_metrics.csv"))
    window_run_id = _load_rescore_window_run_id()
    if df.empty and rescored.empty:
        print("No harvested accepted candidates to classify.")
        # Additive model: don't overwrite the existing published corpus on
        # empty input. Only create an empty placeholder if no corpus exists
        # yet (so downstream workflows can still `git add` cleanly).
        if not output_path.exists():
            save_df(output_path, pd.DataFrame())
        if window_path.exists():
            window_path.unlink()
        return

    if not df.empty:
        validate_columns(df, ["title", "abstract", "venue", "authors", "citation_count"], "accepted_harvested.csv")

    rows = []
    if not df.empty:
        seminal_threshold = _seminal_threshold()
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
            # Quality_Tier is no longer asked of the LLM (it always
            # returned "Standard"). publish.py derives the tier deterministically
            # from total_quality_score so the field stays available to consumers.
            out["Seminal_Flag"] = "TRUE" if _safe_citation_count(row) >= seminal_threshold else "FALSE"
            rows.append(out)

    new_df = pd.DataFrame(rows)

    # Additive merge: preserve every paper ever classified. Fresh classifier
    # output wins on conflict (newer metadata, latest tags). When rescore
    # metrics are available, treat that current window as authoritative:
    # rows reconsidered this run are removed from the existing corpus, then
    # only the surviving accepted rows are added back.
    existing = load_df(output_path)
    rescored_keys = set()
    if window_run_id and _rows_match_run_id(rescored, window_run_id, "rescore_metrics.csv") \
       and _rows_match_run_id(df, window_run_id, "accepted_harvested.csv"):
        rescored_keys = {_dedup_key(row) for _, row in rescored.iterrows()}
    new_keys = {_dedup_key(row) for _, row in new_df.iterrows()}
    replacement_keys = rescored_keys or new_keys

    if existing.empty:
        merged: pd.DataFrame = new_df
    elif not replacement_keys:
        merged = existing
    else:
        existing_keep = existing[~existing.apply(_dedup_key, axis=1).isin(replacement_keys)]
        merged = pd.concat([existing_keep, new_df], ignore_index=True)

    save_df(output_path, merged)
    if window_path.exists():
        window_path.unlink()
    print(f"Classified {len(rows)} new papers; corpus now {len(merged)} (was {len(existing)})")
    u = _TOKEN_USAGE
    print(
        f"OpenAI usage: {u['calls']} calls, "
        f"{u['input_tokens']} input + {u['output_tokens']} output = "
        f"{u['total_tokens']} total tokens"
    )
