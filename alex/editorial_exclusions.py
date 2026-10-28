"""Content-review exclusions: identity-bound human decisions, never source bans."""
from __future__ import annotations
import json
import re
import unicodedata
from html import unescape
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit
from alex.utils.text import clean


def record_keys(row):
    keys=set()
    doi=clean(row.get('doi')).casefold()
    doi=re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)','',doi).strip()
    if doi:keys.add('doi:'+doi)
    title=re.sub(r'[\W_]+',' ',unicodedata.normalize('NFKC',unescape(clean(row.get('title')))).casefold()).strip()
    if title:
        keys.add('title:'+title)
        try:year=str(int(float(clean(row.get('year')))))
        except (ValueError,OverflowError):year=''
        if year:keys.add('title-year:'+title+'|'+year)
    for field in ('source_url','link'):
        value=clean(row.get(field))
        if not value:continue
        url=urlsplit(value)
        if url.scheme.lower() not in ('http','https') or not url.netloc:continue
        query=urlencode(sorted((k,v) for k,v in parse_qsl(url.query) if not k.lower().startswith('utm_') and k.lower() not in ('fbclid','gclid')))
        keys.add('url:'+url.netloc.casefold()+url.path.rstrip('/')+('?' + query if query else ''))
    return keys


def exclusion_keys(row):
    keys=record_keys(row)
    if any(k.startswith('title-year:') for k in keys):keys={k for k in keys if not k.startswith('title:')}
    return keys


def load_keys(path:Path):
    if not path.exists():return set()
    data=json.loads(path.read_text())
    if data.get('schema_version')!=1 or not isinstance(data.get('records'),list):
        raise ValueError('Invalid editorial exclusion registry')
    keys=set()
    for row in data['records']:
        if row.get('decision')!='rejected' or not row.get('submission_id') or not row.get('reviewed_content_sha256'):
            raise ValueError('Exclusion lacks a content-bound human decision')
        identity=exclusion_keys(row)
        if not identity:raise ValueError('Exclusion has no bibliographic identity')
        keys.update(identity)
    return keys


def filter_frame(frame,path:Path):
    keys=load_keys(path)
    if not keys or frame.empty:return frame
    return frame.loc[~frame.apply(lambda row: bool(record_keys(row)&keys),axis=1)].copy()
