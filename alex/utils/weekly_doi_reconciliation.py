"""Content-bound exceptions for isolated weekly enrichment recovery."""
import hashlib
import json
from pathlib import Path


def for_series(series: dict | None, directory: Path) -> dict | None:
    if not series or series.get('publication_authorized') is not False:
        return None
    path = directory / 'config' / 'weekly_doi_reconciliations.json'
    if not path.is_file():
        return None
    policies = json.loads(path.read_text(encoding='utf-8'))
    matches = [p for p in policies if p['series'] == series['series']
               and p['window_end'] == series['window']['until_date']]
    if len(matches) > 1:
        raise ValueError('Ambiguous weekly DOI reconciliation')
    return matches[0] if matches else None


def selected_dois(dois: list[str], policy: dict) -> list[str]:
    normalized = sorted({d.lower().strip().removeprefix('https://doi.org/') for d in dois})
    if hashlib.sha256('\n'.join(normalized).encode()).hexdigest() != policy['workset_sha256']:
        raise ValueError('Weekly DOI reconciliation workset changed')
    unresolved = set(policy['unresolved'])
    authorized = set(policy['authorized_new_dois'])
    if not unresolved or not unresolved <= set(normalized) or not authorized <= set(normalized) or authorized & unresolved:
        raise ValueError('Invalid weekly DOI disposition or authorization')
    return [d for d in normalized if d not in unresolved]
