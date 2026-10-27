"""Reuse verified abstract metadata without querying a scholarly provider."""
from functools import lru_cache
from alex.utils.io import load_json, root_file
from alex.utils.text import clean, normalize_title
from alex.pipelines.apwg_editorial_review import abstract_digest


@lru_cache(maxsize=1)
def checkpoint() -> dict:
    return load_json(root_file('config', 'apwg_abstract_checkpoint.json'))


def restore(row: dict) -> tuple[dict, bool]:
    if (clean(row.get('abstract')) or
            clean(row.get('in_existing_alex_corpus')).lower() == 'true' or
            row.get('duplicate_review_status') in {'exact_doi_or_title_match', 'hold_possible_variant'}):
        return row, False
    doi = clean(row.get('doi')).lower().removeprefix('https://doi.org/')
    for entry in checkpoint()['entries']:
        if (doi != clean(entry.get('doi')).lower() or
                normalize_title(row.get('title', '')) != normalize_title(entry['title']) or
                clean(row.get('year')) != str(entry['year'])):
            continue
        if not doi and clean(row.get('apwg_paper_url')) != entry.get('apwg_paper_url'):
            continue
        text = clean(entry['abstract'])
        if abstract_digest(text) != entry['abstract_sha256']:
            raise ValueError('Verified abstract checkpoint digest mismatch')
        return {**row, 'abstract': text, 'abstract_source': entry['abstract_source']}, True
    return row, False


def restore_citations(row: dict) -> tuple[dict, bool]:
    """Preserve dated OpenAlex counts instead of silently switching providers.

    Match identity, never choose the larger count, retain the Crossref
    observation separately, and never overwrite a new OpenAlex observation.
    """
    if (clean(row.get('in_existing_alex_corpus')).lower() == 'true' or
            row.get('duplicate_review_status') in {'exact_doi_or_title_match', 'hold_possible_variant'}):
        return row, False
    current_source = clean(row.get('citation_count_source'))
    if clean(row.get('citation_count')) and current_source != 'Crossref is-referenced-by-count':
        return row, False
    doi = clean(row.get('doi')).lower().removeprefix('https://doi.org/')
    for entry in checkpoint()['entries']:
        if (not doi or doi != clean(entry.get('doi')).lower() or
                normalize_title(row.get('title', '')) != normalize_title(entry['title']) or
                clean(row.get('year')) != str(entry['year'])):
            continue
        if (entry.get('citation_count_source') != 'OpenAlex cited_by_count' or
                clean(entry.get('citation_count')) == ''):
            return row, False
        count = str(entry['citation_count'])
        if not count.isdigit():
            raise ValueError('Invalid checkpoint citation count')
        return {**row, 'citation_count': count,
                'citation_count_source': entry['citation_count_source'],
                'citation_snapshot_created_at': checkpoint()['snapshot_created_at'],
                'citation_snapshot_run': str(checkpoint()['source_run']),
                'citation_snapshot_artifact': str(checkpoint()['source_artifact']),
                'alternate_citation_count': clean(row.get('citation_count')),
                'alternate_citation_count_source': current_source}, True
    return row, False
