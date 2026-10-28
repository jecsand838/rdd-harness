"""Actual framed activation, canonical scope and interrupted retry controls."""
from pathlib import Path
import hashlib,json,os,selectors,signal,socket,subprocess,time
import argparse,plistlib,re
parser=argparse.ArgumentParser()
parser.add_argument('--root',required=True);parser.add_argument('--app',required=True);parser.add_argument('--identity',required=True)
a=parser.parse_args();P=Path(a.root).resolve();APP=Path(a.app).resolve();identity=json.loads(Path(a.identity).read_text());plist=plistlib.loads((APP/'Contents/Info.plist').read_bytes());EXE=APP/'Contents/MacOS'/plist['CFBundleExecutable']
assert str(EXE)==identity['executable'] and hashlib.sha256(EXE.read_bytes()).hexdigest()==identity['executable_sha256']
assert plist['CFBundleIdentifier']==identity['bundle_identifier']
(P/'logs').mkdir(parents=True,exist_ok=True);(P/'runtime').mkdir(parents=True,exist_ok=True)
ENV={k:v for k,v in os.environ.items() if k in ('HOME','USER','LOGNAME','LANG','TMPDIR')};ENV['PATH']='/usr/bin:/bin:/usr/sbin:/sbin'
records=[]
OLD=b'{"synthetic":"old"}\n';NEW=b'{"synthetic":"new-complete","payload":"non-Todo"}\n'
def retain(label,argv,start,rc,out,err,expected):
 prefix=P/'logs'/label;prefix.with_suffix('.stdout').write_bytes(out);prefix.with_suffix('.stderr').write_bytes(err)
 r=dict(argv=argv,environment=ENV,started_epoch=start,finished_epoch=time.time(),returncode=rc,expected_returncode=expected)
 prefix.with_suffix('.command.json').write_text(json.dumps(r,indent=2)+'\n');records.append(r);assert rc==expected,(label,rc,err)
def run(label,*args,expected=0):
 argv=[str(EXE),*map(str,args)];start=time.time();r=subprocess.run(argv,env=ENV,capture_output=True,timeout=5);retain(label,argv,start,r.returncode,r.stdout,r.stderr,expected);return r.stdout
def main():
 root=P/'runtime/supplemental';root.mkdir()
 scope=root/'scope';scope.mkdir();run('20-scope','--scope-suite',scope)
 for exists in [True,False]:
  for stage in ['intent','partial','ready','published']:
   name=f'21-{exists}-{stage}';case=root/name;case.mkdir();(case/'managed.db').write_bytes(b'managed')
   if exists:(case/'selected.json').write_bytes(OLD)
   argv=[str(EXE),'--publish',str(case),stage];start=time.time();child=subprocess.Popen(argv,env=ENV,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
   stdout=b'';selector=selectors.DefaultSelector();selector.register(child.stdout,selectors.EVENT_READ);deadline=time.monotonic()+5
   try:
    found=False
    while time.monotonic()<deadline:
     if selector.select(.1):
      line=child.stdout.readline();stdout+=line
      if not line:break
      if json.loads(line).get('checkpoint')==stage:found=True;child.kill();break
    assert found,'meaningful checkpoint unavailable'
    out,err=child.communicate(timeout=2);retain(name,argv,start,child.returncode,stdout+out,err,-signal.SIGKILL)
   finally:
    selector.close()
    if child.poll() is None:child.kill();child.wait(timeout=2)
   before=(case/'selected.json').read_bytes() if (case/'selected.json').exists() else None
   run(name+'-unresolved-retry','--publish',case,expected=1)
   assert ((case/'selected.json').read_bytes() if (case/'selected.json').exists() else None)==before
   run(name+'-resolve','--resolve',case)
   assert not (case/'publication-intent.json').exists()
   run(name+'-safe-retry','--publish',case)
   assert (case/'selected.json').read_bytes()==NEW
   run(name+'-retry-resolve','--resolve',case)
   assert not (case/'publication-intent.json').exists()
 # Persisted recovery metadata cannot introduce authority outside its owned root.
 corrupt=root/'corrupt-recovery';corrupt.mkdir();outside=root/'outside-scope-control.json';before=outside.read_bytes()
 (corrupt/'publication-intent.json').write_text(json.dumps(dict(destination=str(outside),temp=str(outside.parent/'.rdd-qual-forged.tmp'),old=None,new_sha256='unmatched')))
 run('21-corrupt-recovery-outside','--resolve',corrupt,expected=1);assert outside.read_bytes()==before
 symlink_case=root/'symlink-recovery';symlink_case.mkdir();destination=symlink_case/'selected.json';destination.write_bytes(OLD);temp=symlink_case/'.rdd-qual-forged.tmp';temp.symlink_to(outside)
 st=destination.stat();old=dict(dev=st.st_dev,ino=st.st_ino,sha256=hashlib.sha256(OLD).hexdigest())
 (symlink_case/'publication-intent.json').write_text(json.dumps(dict(destination=str(destination),temp=str(temp),old=old,new_sha256=hashlib.sha256(NEW).hexdigest())))
 run('21-corrupt-recovery-temp-symlink','--resolve',symlink_case,expected=1);assert outside.read_bytes()==before and destination.read_bytes()==OLD
 fragment=root/'fragmented';fragment.mkdir();argv=[str(EXE),'--instance-headless',str(fragment),'1500'];start=time.time();child=subprocess.Popen(argv,env=ENV,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 first=child.stdout.readline();assert json.loads(first)['role']=='primary'
 # Relative AF_UNIX name avoids Darwin's sockaddr_un path-length ceiling.
 previous=Path.cwd()
 try:
  os.chdir(fragment)
  with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
   client.connect('instance.sock');client.sendall(b'ACT');time.sleep(.05);client.sendall(b'IVATE\n')
 finally:os.chdir(previous)
 out,err=child.communicate(timeout=3);retain('22-fragmented-activation',argv,start,child.returncode,first+out,err,0)
 assert sum(json.loads(line).get('event')=='activated_headless' for line in out.splitlines())==1
 assert len((fragment/'database-open-ledger').read_text().splitlines())==1
 result=dict(status='passed',scope='non-Todo native mechanisms only',commands=len(records),expected_nonzero=sum(r['expected_returncode']!=0 for r in records),records=records)
 (P/'supplemental-results.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:result[k] for k in ['status','commands','expected_nonzero']}))
if __name__=='__main__':main()
