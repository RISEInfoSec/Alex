from copy import deepcopy
import json
import pytest
from alex.pipelines import apwg_editorial_review as editorial
from alex.pipelines import apwg_import_recommendation as recommendation
from alex.pipelines.apwg_quality_review import assess
from alex.pipelines.apwg_release import mechanical_checks
from alex.pipelines import apwg_abstract_checkpoint as checkpoint
from alex.utils.io import root_file

@pytest.mark.parametrize('source', ['FIRST', 'M3AAWG', 'SANS', 'Virus Bulletin', 'APWG'])
def test_optional_doi_does_not_change_scores_or_review_and_release(source, monkeypatch):
    abstract = ('Cybersecurity cybercrime phishing investigation of online fraud and threat intelligence. '
                'The research studies evidence, open source intelligence, malware and security methods. ' * 3)
    base = {'title':'Cybersecurity phishing investigation', 'authors':'A. Researcher',
            'year':'2025', 'venue':source, 'publisher':source, 'abstract':abstract,
            'abstract_source':'Official publication', 'apwg_paper_url':'https://example.invalid/publication',
            'citation_count':'15', 'editorial_selection_status':'approved',
            'editorial_classification_status':'approved', 'proposed_category':'Cybercrime & Fraud',
            'proposed_investigation_type':'Phishing Analysis', 'quality_review_status':'human_quality_review'}
    approved = {'doi':'10.9999/example', 'apwg_paper_url':base['apwg_paper_url'],
                'title':base['title'], 'year':2025, 'category':base['proposed_category'],
                'investigation_type':base['proposed_investigation_type'], 'selection_approved':True,
                'classification_approved':True, 'reviewed_abstract_sha256':editorial.abstract_digest(abstract),
                'approved_abstract_sha256':editorial.abstract_digest(abstract)}
    monkeypatch.setattr(editorial, 'decisions', lambda: {approved['doi']: approved})
    with_doi={**base, 'doi':approved['doi']}; without_doi={**base, 'doi':''}
    assert assess(with_doi) == assess(without_doi)
    assert editorial.decision_for(with_doi)[1] == editorial.decision_for(without_doi)[1] == 'approved'
    assert recommendation.recommendation(with_doi) == recommendation.recommendation(without_doi)
    mechanical_checks(with_doi); mechanical_checks(without_doi)
    for patch in ({'abstract': abstract+'changed'}, {'year':'2024'}, {'apwg_paper_url':'https://example.invalid/other'}):
        assert editorial.decision_for({**without_doi, **patch})[1] != 'approved'
    assert recommendation.recommendation({**without_doi, 'quality_review_status':'hold_core_term_gate'})[0] == 'hold_core_term_gate'
    assert recommendation.recommendation({**without_doi, 'duplicate_review_status':'hold_possible_variant'})[0] == 'hold_duplicate_review'


def test_unrelated_hold_and_rejection_are_not_overridden_by_missing_doi(monkeypatch):
    row={'doi':'', 'title':'Example', 'year':'2024', 'apwg_paper_url':'https://example.invalid/item'}
    for field,status in [('editorial_hold','held'), ('editorial_rejected','rejected')]:
        entry={**row, field:True, 'reason':'Existing editorial decision'}
        monkeypatch.setattr(editorial,'decisions',lambda:{'url:'+row['apwg_paper_url']:entry})
        assert editorial.decision_for(row)[1] == status


def test_verified_abstract_and_citations_are_reused_by_url_without_a_doi(monkeypatch):
    abstract='Verified original abstract'
    entry={'doi':'10.9999/example', 'title':'Example', 'year':'2024',
           'apwg_paper_url':'https://example.invalid/paper', 'abstract':abstract,
           'abstract_source':'Verified original', 'abstract_sha256':editorial.abstract_digest(abstract),
           'citation_count':'42', 'citation_count_source':'OpenAlex cited_by_count'}
    monkeypatch.setattr(checkpoint,'checkpoint',lambda:{'entries':[entry],
        'snapshot_created_at':'2026-01-01', 'source_run':1, 'source_artifact':2})
    row={**entry,'doi':'','abstract':'','citation_count':'','citation_count_source':''}
    assert checkpoint.restore(row)[0]['abstract']==abstract
    assert checkpoint.restore_citations(row)[0]['citation_count']=='42'
    for change in ({'year':'2023'}, {'apwg_paper_url':'https://example.invalid/other'},
                   {'doi':'10.9999/different'}):
        assert not checkpoint.restore({**row,**change})[1]
        assert not checkpoint.restore_citations({**row,**change})[1]


def test_existing_apwg_165_keeps_approval_and_independent_quality_hold():
    pending=json.loads(root_file('config','apwg_pending_review.json').read_text())['records'][0]
    assert pending['review_number']==165 and not pending['doi']
    title=pending['title']
    abstract=next(e for e in json.loads(root_file('config','apwg_abstract_checkpoint.json').read_text())['entries'] if e['title']==title)
    verified=next(e for e in json.loads(root_file('config','apwg_verified_corrections.json').read_text())['entries'] if e['title']==title)
    row={**pending, **verified, 'year':str(verified['year']), 'apwg_paper_url':pending['apwg_paper_url'],
         'abstract':abstract['abstract'], 'abstract_source':abstract['abstract_source'],
         'editorial_selection_status':'approved', 'editorial_classification_status':'approved',
         'proposed_category':pending['approved_category'],
         'proposed_investigation_type':pending['approved_investigation_type']}
    assert editorial.decision_for(row)[1]=='approved'
    mechanical_checks(row)
    quality=assess(row)
    assert quality['quality_core_term_gate']=='fail'
    assert recommendation.recommendation({**row,**quality})[0]=='hold_core_term_gate'
