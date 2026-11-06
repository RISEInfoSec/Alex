"""Preserve existing content-bound releases and explicit human corpus keeps."""
import json
import re

from alex.metadata_holds import canonical_doi
from alex.resource_types import TYPES
from alex.utils.text import clean, normalize_title


def identities(row):
    doi = canonical_doi(clean(row.get('doi')))
    title = normalize_title(clean(row.get('title')))
    return {v for v in ('doi:' + doi if doi else '', 'title:' + title if title else '') if v}


def keep_identities(root):
    path = root / 'config/editorial_relevance_feedback.json'
    if not path.exists():
        return set()
    result = set()
    for example in json.loads(path.read_text())['audit_examples']:
        if example.get('human_decision') == 'keep':
            if not re.fullmatch('[0-9a-f]{64}', example.get('content_sha256', '')):
                raise ValueError('Human keep lacks bound content evidence')
            result.update(identities(example))
    return result


def approved_paper(row, keeps):
    if clean(row.get('document_type')) in TYPES:
        return False  # The separate reviewed-resource guard validates these.
    if clean(row.get('review_candidate_id')):
        if not re.fullmatch('[0-9a-f]{64}', clean(row.get('review_content_sha256'))):
            raise ValueError('Reviewed paper lacks content binding')
        return True
    if clean(row.get('inclusion_path')).startswith(
            ('Explicitly approved APWG release', 'Explicit human quality approval; APWG batch ')):
        return True
    return bool(identities(row) & keeps)


def filter_approved_inputs(frame, existing, keeps):
    protected = set().union(*(identities(row) for _, row in existing.iterrows()
                              if approved_paper(row, keeps)))
    if frame.empty or not protected:
        return frame
    return frame.loc[~frame.apply(lambda row: bool(identities(row) & protected), axis=1)].copy()
