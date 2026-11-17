"""Compute required checks from retained source bytes and existing ALEX policy."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import importlib.metadata
import json
from pathlib import Path
import re

from bs4 import BeautifulSoup
from pypdf import PdfReader

from alex.discovery_types import paper_route_hold
from alex.editorial_exclusions import load_keys, record_keys
from alex.metadata_holds import canonical_doi, load_holds
from alex.pipelines.apwg_quality_review import assess
from alex.utils.scoring import safe_int_year
from alex.utils.text import clean, normalize_title
from stage1.engine import canonical, digest, REQUIRED_CHECKS


class CheckRunner:
    def __init__(self, root):
        self.root = Path(root).resolve()
        names = ('quality_weights.json', 'query_registry.json', 'venue_whitelist.json',
                 'corpus_exclusions.json', 'corpus_metadata_holds.json',
                 'editorial_relevance_feedback.json')
        self.config = {n: json.loads((self.root / 'config' / n).read_text()) for n in names}
        self.policy = (self.config['quality_weights.json'], self.config['query_registry.json'],
                       self.config['venue_whitelist.json']['high_trust'])
        self.excluded = load_keys(self.root / 'config/corpus_exclusions.json')
        self.metadata_holds = {h['doi'] for h in load_holds(self.root / 'config/corpus_metadata_holds.json')}
        # Keep/remove labels are retained context; neither is an approval for
        # a new candidate or permission to override an exclusion.
        self.feedback = self.config['editorial_relevance_feedback.json']
        source_files = ('alex/pipelines/apwg_quality_review.py', 'alex/utils/scoring.py',
                        'alex/discovery_types.py', 'alex/editorial_exclusions.py',
                        'alex/metadata_holds.py', 'stage1/engine.py',
                        'stage2/checks.py', 'stage2/adapters.py', 'stage2/effects.py',
                        'stage2/store.py', 'stage2/preview.py', 'stage2/run.py',
                        'alex/pipelines/apwg_import.py', 'alex/publication_dates.py',
                        'alex/utils/text.py', 'alex/utils/paginate.py')
        source_files += tuple(str(p.relative_to(self.root)) for p in sorted((self.root / 'alex/connectors').glob('*.py')))
        self.year = datetime.now(timezone.utc).year
        self.policy_hash = digest({'config': self.config, 'year': self.year,
                                   'packages': {n: importlib.metadata.version(n) for n in ('pypdf', 'beautifulsoup4', 'pandas')},
                                   'implementation': {n: hashlib.sha256((self.root / n).read_bytes()).hexdigest()
                                                      for n in source_files}})

    def evaluate(self, record, document):
        content_hash = digest(record)
        results = {}
        evidence = {'candidate_content_hash': content_hash, 'policy_hash': self.policy_hash,
                    'mode': 'retained_source_evaluation', 'live_access_verified': False}

        def put(name, result, reason, **details):
            results[name] = {'result': result, 'evidence': canonical(dict(evidence, reason=reason, **details))}

        year = safe_int_year(record.get('year'))
        required = all(clean(record.get(k)) for k in ('title', 'authors', 'source_url'))
        valid_year = year is not None and 1000 <= year <= self.year
        doi = canonical_doi(record.get('doi', ''))
        valid_doi = not doi or bool(re.fullmatch(r'10\.\d{4,9}/\S+', doi))
        put('metadata', 'pass' if required and valid_year and valid_doi else 'hold',
            'required_bibliographic_fields' if required and valid_year and valid_doi else 'incomplete_or_invalid_metadata')

        raw, text, access_reason = None, '', 'missing_document_receipt'
        if document:
            try:
                raw = bytes.fromhex(document['body_hex'])
                if len(raw) > 8 * 1024 * 1024:
                    raise ValueError('document_too_large')
                if hashlib.sha256(raw).hexdigest() != document['body_sha256']:
                    raise ValueError('document_hash_mismatch')
                if document['candidate_content_hash'] != content_hash or document['url'] != record['source_url']:
                    raise ValueError('document_identity_mismatch')
                if document['status'] != 200 or document.get('access') != 'public':
                    access_reason = 'restricted_or_unsuccessful_retained_response'
                    raw = None
                else:
                    access_reason = 'retained_public_response_bytes'
            except (ValueError, TypeError, KeyError):
                raw = None
                access_reason = 'invalid_document_receipt'
        put('access', 'pass' if raw else 'hold', access_reason,
            body_sha256=document.get('body_sha256') if document else None)

        format_reason = paper_route_hold(record)
        if doi in self.metadata_holds:
            format_reason = 'existing_technical_metadata_hold'
        if raw is not None and not format_reason:
            try:
                mime = document['content_type'].split(';')[0].strip().lower()
                if mime == 'application/pdf' and raw.startswith(b'%PDF-'):
                    pdf = PdfReader(io.BytesIO(raw), strict=True)
                    if pdf.is_encrypted or not 0 < len(pdf.pages) <= 100:
                        raise ValueError('unsupported_pdf')
                    text = '\n'.join(page.extract_text() or '' for page in pdf.pages)
                elif mime == 'text/html':
                    page = BeautifulSoup(raw, 'html.parser')
                    for tag in page(['script', 'style', 'nav', 'footer']):
                        tag.decompose()
                    article = page.find('article')
                    if article is None:
                        raise ValueError('not_article_content')
                    text = article.get_text(' ', strip=True)
                else:
                    raise ValueError('unsupported_document_format')
                if (len(text.split()) < 40 or normalize_title(record['title']) not in normalize_title(text)
                        or not clean(record.get('abstract'))
                        or normalize_title(record['abstract']) not in normalize_title(text)):
                    raise ValueError('document_content_identity_or_length')
                if any(term in text.casefold() for term in ('sign in to access', 'access denied', 'captcha required')):
                    raise ValueError('restricted_document_body')
                format_reason = 'parsed_supported_article_bytes'
            except Exception:
                # Parser errors may contain private document fragments.
                format_reason = 'unparseable_or_mismatched_document'
                text = ''
        elif not format_reason:
            format_reason = 'document_not_available_for_format_check'
        put('format', 'pass' if text else 'hold', format_reason,
            extracted_text_sha256=hashlib.sha256(text.encode()).hexdigest() if text else None)

        # No caller-provided score or check flags are consulted. This invokes
        # the existing production review scorer with unchanged configuration.
        quality = assess(record, self.policy)
        excluded = bool(record_keys(record) & self.excluded)
        relevance_ok = (quality['quality_core_term_gate'] == 'pass' and
                        quality['quality_relevance_gate'] == 'pass' and not excluded)
        put('relevance', 'pass' if relevance_ok else 'hold',
            'existing_editorial_exclusion' if excluded else 'existing_core_and_relevance_gates',
            score=quality['quality_relevance_score'], feedback_registry_sha256=digest(self.feedback))
        quality_ok = (quality['quality_review_status'] == 'provisional_auto_threshold' and
                      not excluded and doi not in self.metadata_holds and not paper_route_hold(record))
        put('quality', 'pass' if quality_ok else 'hold', quality['quality_review_status'], assessment=quality)
        assert set(results) == set(REQUIRED_CHECKS)
        return {content_hash: results}
