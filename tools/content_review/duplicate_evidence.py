"""Local duplicate/exclusion evidence with explicit same-work upstream aliases."""
import re
from html import unescape
from alex.editorial_exclusions import record_keys

def arxiv_id(row):
    ids=set()
    for key in ('source_url','doi'):
        value=str(row.get(key,''))
        match=re.search(r'(?:arxiv\.org/(?:abs|pdf)/|10\.48550/arxiv\.)(\d{4}\.\d{4,5})(?:v\d+)?',value,re.I)
        if match:ids.add(match.group(1))
    return next(iter(ids)) if len(ids)==1 else None

def upstream_alias(row,other):
    """Only identifier AND exact normalized title/byline establish this alias."""
    norm=lambda v:re.sub(r'\W+',' ',unescape(str(v)).casefold()).strip()
    aid=arxiv_id(row)
    return bool(aid and aid==arxiv_id(other) and norm(row.get('title'))==norm(other.get('title'))
                and norm(row.get('authors')) and norm(row.get('authors'))==norm(other.get('authors')))

def audit(row,collections,upstream,exclusion_keys):
    keys=record_keys(row);matches=[];aliases=[]
    for name,items in collections.items():
        for other in items:
            if row['candidate_id'] in (other.get('candidate_id'),other.get('discovery_identity')):continue
            overlap=keys&record_keys(other)
            if overlap:matches.append({'origin':name,'candidate_id':other.get('candidate_id'),'keys':sorted(overlap)})
    for other in upstream:
        overlap=keys&record_keys(other)
        if not overlap:continue
        if str(other.get('candidate_id'))==str(row.get('upstream_candidate_id')):continue
        if upstream_alias(row,other):aliases.append({'upstream_candidate_id':other.get('candidate_id'),'arxiv_id':arxiv_id(other),'reason':'Same arXiv identifier, normalized title and complete author byline; distinct discovery identity retained.'})
        else:matches.append({'origin':'weekly_upstream','candidate_id':other.get('candidate_id'),'keys':sorted(overlap)})
    excluded=sorted(keys&exclusion_keys)
    return {'status':'held' if matches or excluded else 'passed','matches':matches,'upstream_aliases':aliases,'exclusions':excluded}
