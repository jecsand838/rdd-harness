"""One bounded native session; wrapper, app and secondary logs are disjoint."""
from pathlib import Path
import hashlib,json,os,subprocess,sys,time
import argparse,plistlib,re
parser=argparse.ArgumentParser()
parser.add_argument('--root',required=True);parser.add_argument('--app',required=True);parser.add_argument('--identity',required=True)
parser.add_argument('kind',choices=['dialog','instance']);parser.add_argument('label');parser.add_argument('mode',nargs='?');parser.add_argument('--timeout',type=int,default=120)
a=parser.parse_args();assert re.fullmatch(r'[A-Za-z0-9_-]+',a.label) and 1<=a.timeout<=180
P=Path(a.root).resolve();kind,label=a.kind,a.label;app=Path(a.app).resolve();ident=json.loads(Path(a.identity).read_text())
plist=plistlib.loads((app/'Contents/Info.plist').read_bytes());exe=app/'Contents/MacOS'/plist['CFBundleExecutable'];expected=ident['executable_sha256']
assert str(exe)==ident['executable'] and plist['CFBundleIdentifier']==ident['bundle_identifier']
assert hashlib.sha256(exe.read_bytes()).hexdigest()==expected
(P/'runtime').mkdir(exist_ok=True);(P/'logs').mkdir(exist_ok=True)
root=P/'runtime'/label;root.mkdir()
for name,value in [('selected.json',b'{"synthetic":"old"}\n'),('managed.db',b'managed synthetic immutable'),('adjacent.json',b'unrelated')]:
 (root/name).write_bytes(value)
before={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in root.iterdir() if f.is_file()}
env={k:v for k,v in os.environ.items() if k in ('HOME','USER','LOGNAME','LANG','TMPDIR')};env['PATH']='/usr/bin:/bin:/usr/sbin:/sbin'
argv=[str(exe),'--dialog' if kind=='dialog' else '--instance-gui',str(root)]
if kind=='dialog':assert a.mode is not None;argv.append(a.mode)
prefix=P/'logs'/(label+'-app')
started=time.time();deadline=started+a.timeout;secondary=None
with prefix.with_suffix('.stdout').open('wb') as stdout,prefix.with_suffix('.stderr').open('wb') as stderr:
 child=subprocess.Popen(argv,env=env,stdout=stdout,stderr=stderr)
 record=dict(argv=argv,environment=env,pid=child.pid,started_epoch=started,deadline_epoch=deadline,app=str(app),binary_sha256=expected,before=before,child_stdout=str(prefix.with_suffix('.stdout')),child_stderr=str(prefix.with_suffix('.stderr')))
 (P/'runtime'/f'{label}-session.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record),flush=True)
 timed_out=False
 try:
  while child.poll() is None and time.time()<deadline:
   if kind=='instance' and secondary is None and (root/'trigger-secondary').exists():
    secondary_argv=[str(exe),'--instance-headless',str(root),'0'];t=time.time()
    secondary=subprocess.run(secondary_argv,env=env,capture_output=True,timeout=5)
    q=P/'logs'/(label+'-secondary');q.with_suffix('.stdout').write_bytes(secondary.stdout);q.with_suffix('.stderr').write_bytes(secondary.stderr)
    q.with_suffix('.command.json').write_text(json.dumps(dict(argv=secondary_argv,environment=env,started_epoch=t,finished_epoch=time.time(),returncode=secondary.returncode),indent=2)+'\n')
    record['secondary_returncode']=secondary.returncode
   time.sleep(.1)
  if child.poll() is None:
   timed_out=True;child.terminate()
   try:child.wait(timeout=3)
   except subprocess.TimeoutExpired:child.kill();child.wait(timeout=3)
 finally:
  if child.poll() is None:child.kill();child.wait(timeout=3)
record.update(finished_epoch=time.time(),returncode=child.returncode,timed_out=timed_out,after={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in root.iterdir() if f.is_file()})
for name in ('stdout','stderr'):
 f=prefix.with_suffix('.'+name);record[name]={'path':str(f),'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()}
prefix.with_suffix('.command.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({'pid':child.pid,'returncode':child.returncode,'timed_out':timed_out}),flush=True)
raise SystemExit(124 if timed_out else child.returncode)
