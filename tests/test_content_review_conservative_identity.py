import json
from pathlib import Path
import random
import subprocess

from alex.editorial_exclusions import record_keys

ROOT=Path(__file__).resolve().parents[1]


def compare(pairs):
    code="""const {profile,possiblyMatches}=require('./tools/content_review/conservative_identity.cjs');
let s='';process.stdin.on('data',x=>s+=x).on('end',()=>{const p=JSON.parse(s);process.stdout.write(JSON.stringify(p.map(([a,b])=>possiblyMatches(profile(a),b))));});"""
    result=subprocess.run(['node','-e',code],cwd=ROOT,input=json.dumps(pairs,ensure_ascii=False),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


def test_possible_overlap_covers_python_identity_matches_without_inventing_decisions():
    pairs=[
      ({'title':'Strasse'},{'title':'Straße'}),
      ({'title':'Key'},{'title':'Key'}),
      ({'title':'A'},{'title':'&#65;'}),
      ({'title':'Foo Bar'},{'title':'Foo&nbsp;Bar'}),
      ({'title':'i'},{'title':'İ'}),
      ({'title':'unrelated','doi':'10.1000/X'},{'title':'another','doi':'https://doi.org/10.1000/x'}),
      ({'title':'unrelated','source_url':'https://EXAMPLE.org/a/b?x=1'},
       {'title':'another','link':'http://example.org/a/b?x=1&utm_source=test'}),
      ({'title':'A long independent title','doi':'10.1000/new','source_url':'https://a.example/paper'},
       {'title':'Different document','doi':'10.2000/old','source_url':'https://b.example/other'}),
    ]
    result=compare(pairs)
    for (candidate,other),possible in zip(pairs,result):
        if record_keys(candidate)&record_keys(other):assert possible
    assert result[-1] is False


def test_adversarial_unicode_entity_and_punctuation_matches_are_never_missed():
    rng=random.Random(4096);pairs=[]
    for _ in range(300):
        parts=[''.join(rng.choice('abcdef012345') for _ in range(rng.randrange(1,7))) for _ in range(3)]
        title=' '.join(parts);other=rng.choice([' &nbsp; ',' &#32; ',' - ',': ']).join(parts)
        pairs.append(({'title':title},{'title':other}))
    pairs.extend([({'title':'ss'},{'title':'ß'}),({'title':'ff'},{'title':'ﬀ'}),
                  ({'title':'k'},{'title':'K'}),({'title':'i'},{'title':'İ'}),
                  ({'title':'example','source_url':'https://example.com/a'},
                   {'title':'different','source_url':'http://EXAMPLE.COM/a/'}),
                  ({'title':'example','doi':'10.123/a'},{'title':'different','doi':'DOI: 10.123/A'})])
    possible=compare(pairs)
    matched=0
    for (candidate,other),result in zip(pairs,possible):
        if record_keys(candidate)&record_keys(other):
            matched+=1;assert result,(candidate,other)
    assert matched>200


def test_ascii_candidates_cover_many_unicode_normalization_cases():
    rng=random.Random(7211);pairs=[]
    for _ in range(6000):
        codepoint=rng.randrange(1,0x110000)
        if 0xd800<=codepoint<=0xdfff:continue
        source=rng.choice(['A','E','I','K','S'])+chr(codepoint)+rng.choice(['B','M','Z'])
        keys=record_keys({'title':source})
        title=next((k[6:] for k in keys if k.startswith('title:')),None)
        if title and title.isascii() and '&' not in title:pairs.append(({'title':title},{'title':source}))
    assert len(pairs)>1000
    possible=compare(pairs)
    for (candidate,other),result in zip(pairs,possible):
        assert record_keys(candidate)&record_keys(other)
        assert result,(candidate,other)


def test_unicode_candidates_conservatively_cover_matching_python_keys():
    rng=random.Random(9162);pairs=[]
    variants=[('Straße','STRASSE'),('ﬀ','ff'),('K','k'),('café','CAFÉ'),
              ('A &amp; B','A & B'),('one\u00a0two','one two'),('中','中')]
    for _ in range(1800):
        left,right=rng.choice(variants)
        prefix=''.join(rng.choice('abCD12') for _ in range(rng.randrange(1,8)))
        suffix=''.join(rng.choice('xyZ34') for _ in range(rng.randrange(1,8)))
        a={'title':prefix+' '+left+' '+suffix};b={'title':prefix+' '+right+' '+suffix}
        pairs.extend(((a,b),(b,a)))
    pairs.extend([({'title':'Café analysis'},{'title':'Zebra report'}),
                  ({'title':'研究'},{'title':'An unrelated title'})])
    possible=compare(pairs);matched=0
    for (candidate,other),result in zip(pairs,possible):
        if record_keys(candidate)&record_keys(other):matched+=1;assert result,(candidate,other)
    assert matched>3000
    assert possible[-2] is False
    assert possible[-1] is True  # A wholly uncertain title remains held.


def test_unicode_candidates_match_normalized_python_forms():
    rng=random.Random(9241);pairs=[]
    for _ in range(6000):
        cp=rng.randrange(1,0x110000)
        if 0xd800<=cp<=0xdfff:continue
        raw='A'+chr(cp)+'B'
        title=next((k[6:] for k in record_keys({'title':raw}) if k.startswith('title:')),None)
        if title:
            pairs.extend((({'title':raw},{'title':title}),({'title':title},{'title':raw})))
    possible=compare(pairs)
    for (candidate,other),result in zip(pairs,possible):
        assert record_keys(candidate)&record_keys(other)
        assert result,(candidate,other)
