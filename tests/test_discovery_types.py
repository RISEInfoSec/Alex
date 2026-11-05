import json
from unittest.mock import patch
import pandas as pd
from alex.discovery_types import paper_route_hold
from alex.pipelines import quality_gate, rescore


def test_declared_type_is_not_inferred_from_title_or_treated_as_format_verification():
    assert paper_route_hold({'discovery_resource_type':'dataset'})
    assert paper_route_hold({'discovery_resource_type':'publication','discovery_resource_subtype':'report'})
    assert paper_route_hold({'discovery_resource_type':'repository'})
    assert paper_route_hold({'discovery_resource_type':'journal-article'}) is None
    assert paper_route_hold({'discovery_resource_type':'publication','discovery_resource_subtype':'article'}) is None
    assert paper_route_hold({'title':'A new dataset for cyber investigations'}) is None
    assert paper_route_hold({'discovery_resource_type':float('nan')}) is None


def test_high_scoring_dataset_stays_in_review_and_cannot_escape_through_rescore(tmp_path):
    data=tmp_path/'data';config=tmp_path/'config';data.mkdir();config.mkdir()
    (config/'quality_weights.json').write_text(json.dumps(dict(venue=.35,citations=.40,relevance=.25,institution_bonus=10,
        auto_include_threshold=60,review_threshold=20,preprint_auto_include_threshold=35,preprint_review_threshold=20)))
    (config/'venue_whitelist.json').write_text(json.dumps({'high_trust':['IEEE']}))
    (config/'query_registry.json').write_text(json.dumps({'queries':['cybercrime'],'core_keywords':['cybercrime']}))
    base=dict(authors='Test Author',affiliations='Test University',year=2026,venue='IEEE',doi='',citation_count=500,
              abstract='Cybercrime methods and reproducible experimental evidence.',source_url='https://example.org/test')
    rows=[dict(base,title='Cybercrime dataset',discovery_resource_type='dataset'),
          dict(base,title='Cybercrime paper about datasets',discovery_resource_type='journal-article')]
    pd.DataFrame(rows).to_csv(data/'discovery_candidates.csv',index=False)
    with patch('alex.utils.io.ROOT',tmp_path):
        quality_gate.run()
        review=pd.read_csv(data/'review_queue.csv')
        assert review['title'].tolist()==['Cybercrime dataset']
        pool=pd.read_csv(data/'accepted_candidates.csv')
        assert len(pool)==2 and pool['abstract'].notna().all()
        pool.to_csv(data/'accepted_harvested.csv',index=False)
        rescore.run()
    accepted=pd.read_csv(data/'accepted_harvested.csv')
    assert accepted['title'].tolist()==['Cybercrime paper about datasets']
    metrics=pd.read_csv(data/'rescore_metrics.csv')
    assert len(metrics)==2 and 'dataset' in metrics.loc[metrics.title=='Cybercrime dataset','document_type_hold'].iloc[0]
    assert pd.read_csv(data/'discovery_candidates.csv')['abstract'].notna().all()
