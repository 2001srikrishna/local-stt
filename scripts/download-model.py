#!/usr/bin/env python3
"""Download only named official Whisper weights; verify Hugging Face LFS SHA256."""
import argparse,hashlib,json,os,tempfile,urllib.request
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('model',choices=['base.en','large-v3-turbo']);args=p.parse_args()
name='ggml-'+args.model+'.bin';directory=Path.home()/'whisper.cpp/models';directory.mkdir(parents=True,exist_ok=True);target=directory/name
if target.exists():print('Preserving existing model:',target);raise SystemExit(0)
def request(url):return urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'local-stt-setup/1'}),timeout=60)
with request('https://huggingface.co/api/models/ggerganov/whisper.cpp/tree/main') as r:items=json.load(r)
entry=next(x for x in items if x['path']==name);expected=entry['lfs']['oid'];expected_size=entry['size']
if len(expected)!=64:raise SystemExit('No supported upstream SHA256 available')
fd,path=tempfile.mkstemp(prefix='.'+name+'-',dir=directory);temporary=Path(path)
try:
 digest=hashlib.sha256();size=0
 with os.fdopen(fd,'wb') as out,request('https://huggingface.co/ggerganov/whisper.cpp/resolve/main/'+name) as source:
  while block:=source.read(1024*1024):out.write(block);digest.update(block);size+=len(block)
 if size!=expected_size or digest.hexdigest()!=expected:raise SystemExit('Model checksum/size mismatch')
 temporary.chmod(0o644);os.replace(temporary,target);print('Verified model:',target)
finally:temporary.unlink(missing_ok=True)
