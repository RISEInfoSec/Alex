"""Retain declared source types without mistaking them for verified paper format."""
from alex.utils.text import clean

NON_PAPER_TYPES = {
    'dataset', 'data-set', 'software', 'code', 'repository', 'presentation',
    'poster', 'image', 'video', 'audio', 'lesson', 'physicalobject',
    'book', 'book-chapter', 'book-section', 'report', 'technical-report',
    'dissertation', 'thesis', 'peer-review', 'editorial', 'letter',
    'monograph', 'edited-book', 'reference-book', 'reference-entry', 'book-part',
    'book-series', 'book-set', 'journal', 'journal-volume', 'journal-issue',
    'proceedings', 'component', 'standard', 'report-series', 'event', 'paratext',
}


def paper_route_hold(row):
    declared = clean(row.get('discovery_resource_type')).casefold()
    subtype = clean(row.get('discovery_resource_subtype')).casefold()
    kind = subtype if declared == 'publication' and subtype else declared
    if kind in NON_PAPER_TYPES:
        return 'Declared source type requires separate format review: ' + kind
    for field in ('harvest_crossref_type', 'harvest_openalex_type'):
        kind = clean(row.get(field)).casefold()
        if kind in NON_PAPER_TYPES:
            return 'Harvest source type requires separate format review: ' + kind
    return None
