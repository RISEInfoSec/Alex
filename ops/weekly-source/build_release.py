"""Build a reproducible code-only Python executable from verified public review sources."""
from pathlib import Path
import hashlib,json,tarfile,zipfile

HERE=Path(__file__).resolve().parent
BASE=Path('/workspace/work/preservation/codex_soups-corpus-review')
OUT=HERE/'alex-weekly-source.pyz'
def oid(data):return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
def main():
    with tarfile.open(HERE.parent/'alex-review-recovery.tar.gz') as archive:
        r=json.load(archive.extractfile('refs/codex/soups-corpus-review'))
    inputs={}
    for row in r['entries']:
        path=row['path']
        if row['type']=='blob' and path.endswith('.py') and path.startswith(('alex/','tools/content_review/')):
            data=(BASE/path).read_bytes();assert oid(data)==row['sha']
            inputs[path]=data
    for path in (HERE/'tools/content_review').glob('*.py'):inputs['tools/content_review/'+path.name]=path.read_bytes()
    for path in list(inputs):
        for parent in Path(path).parents:
            if parent!=Path('.'):
                inputs.setdefault(str(parent/'__init__.py'),b'')
    inputs['setup_checkout.py']=(HERE/'setup_checkout.py').read_bytes()
    inputs['__main__.py']=(HERE/'run_clock.py').read_bytes()
    with zipfile.ZipFile(OUT,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as out:
        for path,value in sorted(inputs.items()):
            info=zipfile.ZipInfo(path,date_time=(2026,11,24,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o600<<16;out.writestr(info,value,compresslevel=9)
    data=OUT.read_bytes()
    meta={'file':OUT.name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'git_blob':oid(data),
          'base_source':r['head'],'code_dependencies':{k:hashlib.sha256(v).hexdigest() for k,v in sorted(inputs.items())}}
    (HERE/'release.json').write_text(json.dumps(meta,indent=2)+'\n')
    print({k:v for k,v in meta.items() if k!='code_dependencies'},'modules',len(inputs))
if __name__=='__main__':main()
