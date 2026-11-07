import json
from pathlib import Path
import subprocess

import pytest

from tools.content_review.apwg_adapter import normalize

ROOT = Path(__file__).resolve().parents[1]


def invoke(manifest):
    code = """const {normalize}=require('./tools/content_review/site_apwg_adapter.cjs');let s='';
process.stdin.on('data',x=>s+=x).on('end',()=>{try{process.stdout.write(JSON.stringify(normalize(JSON.parse(s))));}
catch(e){process.stderr.write(e.message);process.exitCode=1;}});"""
    return subprocess.run(['node', '-e', code], cwd=ROOT, input=json.dumps(manifest, ensure_ascii=True), text=True, capture_output=True)


def test_site_apwg_identities_match_python_filtered_view():
    rows = [{'review_number':i, 'title':f'Paper {i} é', 'year':'2026', 'author':'Author',
             'apwg_paper_url':f'https://example.test/{i}', 'abstract':'Source abstract',
             'recommendation':'include' if i % 2 else 'unknown'} for i in range(1, 44)]
    rows.insert(3, {'review_number':90, 'editorial_decision':'approved_quality_hold'})
    rows.insert(4, {'review_number':91, 'editorial_decision':'rejected'})
    rows[12]['review_batch'] = 7
    rows[13]['year'] = 2025
    manifest = {'records':rows}
    result = invoke(manifest)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == normalize(manifest)


@pytest.mark.parametrize('rows', [
    [{'review_number':1, 'title':'A', 'year':2026}, {'review_number':1, 'title':'B', 'year':2026}],
    [{'review_number':1, 'title':'A', 'year':'unknown'}],
    [{'review_number':1, 'title':'A', 'year':2026, 'authors':['not a string']}],
    [{'review_number':1, 'title':'\ud800', 'year':2026}],
    [{'review_number':True, 'title':'A', 'year':2026}],
])
def test_site_apwg_adapter_rejects_ambiguous_or_unencodable_rows(rows):
    assert invoke({'records':rows}).returncode != 0
