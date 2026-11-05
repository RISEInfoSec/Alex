"""Derive current queue counts from every registered collection's actual rows."""
from tools.content_review.lifecycle import current_pass, GATES


def summarize(manifests):
    sources = {}
    for collection, manifest in manifests.items():
        rows = manifest.get('records', []) + manifest.get('preflight_records', [])
        identities = [r.get('candidate_id') or
                      ('apwg-' + str(r['review_number']) if collection == 'apwg' and r.get('review_number') is not None else None)
                      for r in rows]
        if None in identities or len(set(identities)) != len(rows):
            raise ValueError('Duplicate queue identity: ' + collection)
        pending = [r for r in rows if r.get('decision', r.get('editorial_decision', 'pending'))
                   in ('pending', 'unreviewed', None) and r.get('publication_status') != 'published_live_verified']
        if collection == 'corpus-audit':
            # Keep/removal review never contributes to new-content intake.
            pending = []
        automatic = [r for r in pending if r.get('automatic_handoff_pending') and r.get('automatic_handoff_status') != 'consumed_published']
        manual = [r for r in pending if r not in automatic]
        complete = [r for r in manual if all(current_pass(r, g) for g in GATES)]
        ready = [r for r in complete if r.get('review_ready') and r.get('editorial_queue_eligible')
                 and r.get('recommendation_content_sha256') == r.get('content_sha256')]
        sources[collection] = {'records': len(rows), 'pending': len(pending), 'ready': len(ready),
            'ready_batches': len({r.get('review_batch', r.get('batch')) for r in ready}),
            'preflight_incomplete': len(manual) - len(complete),
            'awaiting_recommendation_or_admission': len(complete) - len(ready),
            'automatic_publication_pending': len(automatic)}
    return {'sources': sources, 'ready_total': sum(s['ready'] for s in sources.values()),
            'preflight_pending': sum(s['preflight_incomplete'] for s in sources.values())}
