import csv
import io
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def parse(data,chunk):
    code="""const {CsvRows}=require('./tools/content_review/stream_csv.cjs');
let s='';process.stdin.on('data',x=>s+=x).on('end',()=>{const v=JSON.parse(s),b=Buffer.from(v.base64,'base64'),rows=[];
try{const p=new CsvRows(r=>rows.push(r));for(let i=0;i<b.length;i+=v.chunk)p.update(b.subarray(i,i+v.chunk));
process.stdout.write(JSON.stringify({summary:p.finish(),rows}));}catch(e){process.stderr.write(e.message);process.exitCode=1;}});"""
    import base64
    return subprocess.run(['node','-e',code],cwd=ROOT,input=json.dumps({'base64':base64.b64encode(data).decode(),'chunk':chunk}),text=True,capture_output=True)


def test_streamed_csv_matches_python_for_utf8_quotes_and_crlf_across_boundaries():
    text='candidate_id,title,doi,source_url,link,extra\r\n1,"A, title",,"https://example.test/a","","x"\r\n2,"line one\r\nline ""two"" é",10.2/x,,https://example.test/b,\r\n3,plain,,,,\r\n'
    data=b'\xef\xbb\xbf'+text.encode()
    expected=[{k:r[k] for k in ('candidate_id','title','doi','source_url','link')} for r in csv.DictReader(io.StringIO(text,newline=''))]
    for size in [1,2,3,7,64,257]:
        result=parse(data,size);assert result.returncode==0,result.stderr
        value=json.loads(result.stdout);assert value['summary']['rows']==3 and value['rows']==expected


def test_streamed_csv_rejects_duplicate_headers_extra_cells_and_unterminated_quotes():
    for data in [b'candidate_id,title,title\n1,a,b\n',b'candidate_id,title\n1,a,extra\n',b'candidate_id,title\n1,"unfinished']:
        assert parse(data,3).returncode!=0
