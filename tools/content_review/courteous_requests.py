"""Process-shared per-origin serialization for bounded local source requests."""
import fcntl,hashlib,time,urllib.parse,tempfile
from pathlib import Path
def install():
 import requests
 original=requests.Session.send
 if getattr(original,'_courteous',False):return
 def send(self,request,**kwargs):
  origin=urllib.parse.urlsplit(request.url).netloc.lower()
  directory=Path(tempfile.gettempdir())/'alex-content-review-request-locks';directory.mkdir(exist_ok=True)
  path=directory/(hashlib.sha256(origin.encode()).hexdigest()+'.lock')
  with path.open('a+') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX);lock.seek(0)
   try:previous=float(lock.read().strip() or 0)
   except ValueError:previous=0
   time.sleep(max(0,2-(time.time()-previous)))
   try:return original(self,request,**kwargs)
   finally:
    lock.seek(0);lock.truncate();lock.write(str(time.time()));lock.flush()
 send._courteous=True
 requests.Session.send=send
