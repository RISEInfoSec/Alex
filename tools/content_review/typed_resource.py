"""Validate non-paper staging without granting paper classification or admission."""
import copy,re
TYPES={'best_practice_guide','technical_report','investigative_journalism','presentation_slides','presentation_recording','presentation_transcript','poster_or_extended_abstract'}

def validate_staging(row):
    stage=row.get('typed_resource_staging',{})
    if stage.get('actual_type') not in TYPES or row.get('verified_document_type')!=stage['actual_type']:raise ValueError('Verified actual resource type required')
    if stage.get('content_sha256')!=row.get('content_sha256'):raise ValueError('Stale typed evidence')
    if stage.get('publication_ready') is not False or row.get('review_ready'):raise ValueError('Staging cannot grant public admission')
    for key in ('source_sha256','text_sha256'):
        if not re.fullmatch('[0-9a-f]{64}',str(stage.get(key,''))):raise ValueError('Source/text evidence digest required')
    for key in ('source_receipt','author','publication_date'):
        if not stage.get(key):raise ValueError('Verified metadata missing: '+key)
    if stage['actual_type']=='best_practice_guide' and not stage.get('publication_version'):raise ValueError('Guide version required')
    # Original publication and revision dates remain separate. No citation-like
    # surrogate, invented abstract, numeric deduction or paper exporter is used.
    return copy.deepcopy(stage)
