"""Source-tier routing based on official publication URLs, never a score boost."""
from functools import lru_cache
from urllib.parse import urlsplit
from alex.utils.io import load_json, root_file
from alex.utils.text import clean

@lru_cache(maxsize=1)
def source_tiers():
    data = load_json(root_file('config', 'source_tiers.json'))
    if data.get('version') != 1:
        raise ValueError('Unknown source tier registry version')
    return data['tiers']


def source_designation(row):
    registry=source_tiers()
    urls=[]
    for field in ('source_url','apwg_paper_url','publisher_landing_url'):
        try:
            u=urlsplit(clean(row.get(field)))
            if u.scheme != 'https' or not u.hostname or u.username or u.password: continue
            urls.append((u.hostname.lower().rstrip('.'),u.path.lower()))
        except ValueError:
            continue
    # Explicit SOUPS provenance takes precedence over overlapping host names.
    for tier in ('established_broad_scope','trusted_curated'):
        for source in registry[tier]['sources']:
            for host,path in urls:
                if any(host==h or host.endswith('.'+h) for h in source['hosts']) and (not source.get('path_contains') or any(p in path for p in source['path_contains'])):
                    return {'tier':tier,'source':source['name'],'priority':registry[tier]['priority']}
    return {'tier':'general_discovery','source':'','priority':registry['general_discovery']['priority']}
