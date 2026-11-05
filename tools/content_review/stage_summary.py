"""Derive display counts from retained stage evidence without changing gates."""
from collections import Counter

GATES = ('format', 'access', 'metadata', 'duplicates', 'quality', 'schema')

def derive(records):
    groups = {}
    for row in records:
        collection = row.get('collection')
        if not collection:
            raise ValueError('Stage record has no collection')
        counts = groups.setdefault(collection, {gate: Counter() for gate in GATES})
        checks = row.get('checks') or {}
        for gate in GATES:
            check = checks.get(gate)
            status = check.get('status') if isinstance(check, dict) else None
            counts[gate][status if status is not None else 'not_checked'] += 1
    return {c: {g: dict(sorted(counts.items())) for g, counts in gates.items()}
            for c, gates in sorted(groups.items())}

def validate_summary(data):
    if data.get('summary') != derive(data['records']):
        raise ValueError('Stage summary differs from actual retained records; regenerate with stage_summary.derive')
