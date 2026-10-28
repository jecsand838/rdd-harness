"""Actual small non-Todo filesystem/instance probes; preserve every subprocess."""
from pathlib import Path
import hashlib,json,os,selectors,signal,subprocess,time
import argparse,plistlib,re
parser=argparse.ArgumentParser()
parser.add_argument('--root',required=True);parser.add_argument('--app',required=True);parser.add_argument('--identity',required=True)
a=parser.parse_args();P=Path(a.root).resolve();APP=Path(a.app).resolve();identity=json.loads(Path(a.identity).read_text());plist=plistlib.loads((APP/'Contents/Info.plist').read_bytes());EXE=APP/'Contents/MacOS'/plist['CFBundleExecutable']
assert str(EXE)==identity['executable'] and hashlib.sha256(EXE.read_bytes()).hexdigest()==identity['executable_sha256']
assert plist['CFBundleIdentifier']==identity['bundle_identifier']
(P/'logs').mkdir(parents=True,exist_ok=True);(P/'runtime').mkdir(parents=True,exist_ok=True)
ENV={k:v for k,v in os.environ.items() if k in ('HOME','USER','LOGNAME','LANG','TMPDIR')}
ENV['PATH']='/usr/bin:/bin:/usr/sbin:/sbin'
OLD=b'{"synthetic":"old"}\n'
NEW=b'{"synthetic":"new-complete","payload":"non-Todo"}\n'
records=[]
def capture(label,args,expected=0):
    argv=[str(EXE),*map(str,args)];start=time.time()
    r=subprocess.run(argv,env=ENV,capture_output=True,timeout=10)
    return retain(label,argv,start,r.returncode,r.stdout,r.stderr,expected)
def retain(label,argv,start,rc,stdout,stderr,expected):
    label='v3-'+label
    prefix=P/'logs'/label
    prefix.with_suffix('.stdout').write_bytes(stdout)
    prefix.with_suffix('.stderr').write_bytes(stderr)
    record=dict(label=label,argv=argv,environment=ENV,started_epoch=start,
                finished_epoch=time.time(),returncode=rc,expected_returncode=expected,
                expected_nonzero=expected!=0,stdout_sha256=hashlib.sha256(stdout).hexdigest(),
                stderr_sha256=hashlib.sha256(stderr).hexdigest())
    prefix.with_suffix('.command.json').write_text(json.dumps(record,indent=2)+'\n')
    records.append(record)
    assert rc==expected,(label,rc,expected,stderr.decode(errors='replace'))
    return stdout
def fixture(name,exists=True):
    root=P/'runtime/cli-v3'/name;root.mkdir(parents=True)
    (root/'managed.db').write_bytes(b'managed synthetic immutable')
    if exists:(root/'selected.json').write_bytes(OLD)
    return root
def killed(name,stage,exists):
    root=fixture(name,exists);argv=[str(EXE),'--publish',str(root),stage]
    start=time.time();child=subprocess.Popen(argv,env=ENV,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    data=b'';sel=selectors.DefaultSelector();sel.register(child.stdout,selectors.EVENT_READ)
    until=time.monotonic()+8
    try:
        while time.monotonic()<until:
            ready=sel.select(.1)
            if ready:
                line=child.stdout.readline();data+=line
                if not line:break
                event=json.loads(line)
                if event.get('checkpoint')==stage:
                    child.kill();break
        else:raise AssertionError('checkpoint timeout')
        rest,err=child.communicate(timeout=3)
    finally:
        if child.poll() is None:child.kill();child.wait(timeout=3)
        sel.close()
    retain(name,argv,start,child.returncode,data+rest,err,-signal.SIGKILL)
    output=capture(name+'-resolve',['--resolve',root])
    resolved=json.loads(output)
    expected='new_complete' if stage=='published' else ('old_complete' if exists else 'old_absent')
    assert resolved['reconciled']==expected
    target=root/'selected.json'
    assert (target.read_bytes() if target.exists() else None)==(NEW if stage=='published' else OLD if exists else None)
    assert not list(root.glob('.rdd-qual-*.tmp'))
    assert (root/'managed.db').read_bytes()==b'managed synthetic immutable'
def instances(name,simultaneous):
    root=P/'runtime/cli-v3'/name;root.mkdir(parents=True)
    processes=[];starts=[];outputs=[]
    argv=[str(EXE),'--instance-headless',str(root),'1800']
    for i in range(2):
        starts.append(time.time());child=subprocess.Popen(argv,env=ENV,stdout=subprocess.PIPE,stderr=subprocess.PIPE);processes.append(child)
        if i==0 and not simultaneous:
            line=child.stdout.readline();outputs.append(line);assert json.loads(line)['role']=='primary'
        else:outputs.append(b'')
    try:
        all_events=[]
        for i,child in enumerate(processes):
            out,err=child.communicate(timeout=5);out=outputs[i]+out
            retain(f'{name}-{i}',argv,starts[i],child.returncode,out,err,0)
            all_events.extend(json.loads(line) for line in out.splitlines())
    finally:
        for child in processes:
            if child.poll() is None:child.kill();child.wait(timeout=3)
    assert sum(e.get('role')=='primary' for e in all_events)==1
    assert sum(e.get('role')=='secondary' for e in all_events)==1
    assert sum(e.get('event')=='activated_headless' for e in all_events)==1
    assert len((root/'database-open-ledger').read_text().splitlines())==1
    return all_events
def main():
    suite=P/'runtime/cli-v3/file-suite';suite.mkdir(parents=True)
    capture('10-file-suite',['--file-suite',suite])
    for exists in (True,False):
        for stage in ('intent','partial','ready','published'):
            killed(f'11-kill-{stage}-{exists}',stage,exists)
    for exists in (True,False):
        root=fixture(f'12-success-{exists}',exists)
        out=capture(f'12-success-{exists}',['--publish',root]);assert json.loads(out.splitlines()[-1])['published']
        assert (root/'selected.json').read_bytes()==NEW
        capture(f'12-success-{exists}-resolve',['--resolve',root])
        capture(f'12-success-{exists}-retry',['--publish',root])
        capture(f'12-success-{exists}-retry-resolve',['--resolve',root])
    root=fixture('13-digest-mismatch')
    capture('13-digest-mismatch',['--publish',root,'digest-mismatch'],1)
    capture('13-digest-mismatch-resolve',['--resolve',root]);assert (root/'selected.json').read_bytes()==OLD
    root=fixture('14-readonly')
    root.chmod(0o500)
    try:capture('14-readonly',['--publish',root],1)
    finally:root.chmod(0o700)
    assert (root/'selected.json').read_bytes()==OLD
    schedules={name:instances(name,sim) for name,sim in [('15-sequential',False),('16-simultaneous',True)]}
    result=dict(status='passed',scope='synthetic native mechanisms; no Todo acceptance',
                commands=len(records),expected_nonzero=sum(r['expected_nonzero'] for r in records),
                schedules=schedules,records=records)
    (P/'mechanism-v3-results.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('status','scope','commands','expected_nonzero')}))
if __name__=='__main__':main()
