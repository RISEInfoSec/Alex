"""Strict public pipeline-state schema for non-decision relevance evidence."""
from __future__ import annotations
import csv
import json
import re
from pathlib import Path
from alex.utils.text import clean

# These describe the publication, source, and calculated scoring evidence.
# Do not add reviewer/actor/decision fields: this file can live on the public
# pipeline-state branch. Human review decisions belong to the private ledger.
RECORD_FIELDS = (
    'title','authors','year','doi','abstract','source_url','venue','publisher',
    'collection','collection_source','collection_url','discovery_source',
    'apwg_source_url','apwg_paper_url','apwg_year','publication_year_source',
    'author_source','abstract_source','venue_evidence_url','venue_source',
    'publisher_landing_url','source_checkpoint_artifacts','affiliations',
    'citation_count','citation_count_source','discovery_resource_type',
    'discovery_resource_subtype','document_type','publication_date',
    'publication_date_source','publication_date_status','publication_date_basis',
)
SCORE_FIELDS = ('venue_score','citation_score','institution_score','institution_bonus',
                'title_anchor_bonus','relevance_score','total_quality_score','document_type_hold')
EVIDENCE_FIELDS = RECORD_FIELDS + SCORE_FIELDS
OUTPUT_FIELDS = EVIDENCE_FIELDS + ('source_relevance_review_id','source_tier',
    'source_tier_name','source_review_priority','scoring_policy_sha256',
    'review_reason','recommended_action')


def checkpoint_artifacts(value):
    """Only retain explicit config-relative artifact SHA-256 references."""
    if not clean(value):return ''
    try:
        data=json.loads(value) if isinstance(value,str) else value
    except (TypeError,ValueError) as exc:
        raise ValueError('invalid_source_checkpoint_artifacts') from exc
    if not isinstance(data,dict) or len(data)>100:
        raise ValueError('invalid_source_checkpoint_artifacts')
    for path,digest in data.items():
        if (not isinstance(path,str) or not re.fullmatch(r'config/[A-Za-z0-9_./-]+\.json',path)
                or '..' in Path(path).parts or not isinstance(digest,str)
                or not re.fullmatch(r'[a-f0-9]{64}',digest)):
            raise ValueError('invalid_source_checkpoint_artifacts')
    return json.dumps(data,sort_keys=True,ensure_ascii=False,separators=(',',':'))


def evidence_fields(row):
    result={field:clean(row.get(field)) for field in EVIDENCE_FIELDS}
    result['source_checkpoint_artifacts']=checkpoint_artifacts(row.get('source_checkpoint_artifacts'))
    return result


def validate_queue(path):
    """Fail before public-state write if existing headers contain private data."""
    path=Path(path)
    if not path.exists():return
    with path.open(encoding='utf-8',newline='') as stream:
        csv.field_size_limit(100000000)
        reader=csv.DictReader(stream);headers=reader.fieldnames
        if not headers:raise ValueError('source_relevance_queue_missing_header')
        if len(set(headers))!=len(headers) or not set(headers).issubset(OUTPUT_FIELDS) or 'source_relevance_review_id' not in headers:
            raise ValueError('source_relevance_queue_unexpected_columns')
        for row in reader:
            if None in row:raise ValueError('source_relevance_queue_malformed_row')
            checkpoint_artifacts(row.get('source_checkpoint_artifacts'))
