"""Run one owned experiment with aggregate disk, process and lease bounds."""
import argparse, fcntl, hashlib, json, os, pathlib, shutil, signal, subprocess, time

def usage(paths):
    return sum(int(subprocess.check_output(['du','-sk',str(p)],text=True,timeout=10).split()[0])*1024 for p in paths if pathlib.Path(p).exists())

def processes():
    rows={}
    for line in subprocess.check_output(['ps','-axo','pid=,ppid=,pgid=,lstart='],text=True,timeout=5).splitlines():
        parts=line.split(None,3)
        if len(parts)==4: rows[int(parts[0])]=(int(parts[1]),int(parts[2]),parts[3])
    return rows

def main():
    p=argparse.ArgumentParser();p.add_argument('--state',required=True);p.add_argument('--label',required=True);p.add_argument('--timeout',type=int,required=True);p.add_argument('--canonical',action='store_true');p.add_argument('command',nargs=argparse.REMAINDER);a=p.parse_args()
    state=json.loads(pathlib.Path(a.state).read_text());out=pathlib.Path(a.state).parent/'logs';out.mkdir(exist_ok=True)
    command=a.command[1:] if a.command[:1]==['--'] else a.command
    if not command or a.timeout<=0: raise SystemExit('positive timeout and command required')
    lock=open(state['lock'],'a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    started=time.time()
    if started+a.timeout>state['deadline']: raise SystemExit('command plus shutdown reserve exceeds current lease')
    initial=usage(state['roots']);canonical=state['roots'][1]
    if initial-state['baseline_bytes']>=state['growth_limit_bytes'] or usage([canonical])>=state['canonical_growth_limit_bytes'] or shutil.disk_usage(out).free<state['minimum_free_bytes']: raise SystemExit('resource headroom unavailable')
    record={'argv':command,'started_epoch':started,'deadline':min(state['deadline'],started+a.timeout),'samples':[],'owned_processes':{}}
    owned={};reason=None
    child=None;groups=set();caught=None;signal_errors=[]
    def terminate(signum,frame):
        raise InterruptedError('guard received signal '+str(signum))
    for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP): signal.signal(sig,terminate)
    def capture():
        rows=processes();desc={child.pid} if child else set();changed=True
        desc|={pid for pid,row in rows.items() if row[1] in groups}
        while changed:
            added={pid for pid,row in rows.items() if row[0] in desc};changed=bool(added-desc);desc|=added
        owned.update({pid:rows[pid] for pid in desc if pid in rows})
        groups.update(row[1] for pid,row in owned.items() if pid in rows and rows[pid][2]==row[2])
        return rows
    try:
        with (out/(a.label+'.stdout')).open('wb') as stdout,(out/(a.label+'.stderr')).open('wb') as stderr:
            child=subprocess.Popen(command,stdout=stdout,stderr=stderr,start_new_session=True)
            groups.add(child.pid)
            while True:
                capture()
                sample={'epoch':time.time(),'free_bytes':shutil.disk_usage(out).free,'owned_bytes':usage(state['roots']),'canonical_bytes':usage([canonical])};record['samples'].append(sample)
                if sample['epoch']>=record['deadline']:reason='deadline'
                if sample['free_bytes']<state['minimum_free_bytes']:reason='free-space reserve'
                if sample['owned_bytes']-state['baseline_bytes']>=state['growth_limit_bytes']:reason='aggregate growth cap'
                if sample['canonical_bytes']>=state['canonical_growth_limit_bytes']:reason='cumulative canonical growth cap'
                (out/(a.label+'.monitor.json')).write_text(json.dumps(record,indent=2)+'\n')
                if reason or child.poll() is not None:break
                time.sleep(2)
    except BaseException as error:
        caught=repr(error);reason='guard exception: '+caught
    finally:
        for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):signal.signal(sig,signal.SIG_IGN)
        for sig,seconds in ((signal.SIGTERM,12),(signal.SIGKILL,8)):
            if child is not None:child.poll()
            try:capture()
            except BaseException:pass
            for group in set(groups):
                if group==os.getpgrp():continue
                try:os.killpg(group,sig)
                except ProcessLookupError:pass
                except OSError as error:signal_errors.append({'group':group,'signal':sig,'error':repr(error)})
            until=time.time()+seconds
            while time.time()<until:
                if child is not None:child.poll()
                try:
                    rows=capture()
                    if not any(row[1] in groups for row in rows.values()):break
                except BaseException:break
                time.sleep(.1)
        if child is not None:
            try:rc=child.wait(timeout=5)
            except BaseException:rc=125
        else:rc=125
    try:
        rows=processes();remaining=[pid for pid,row in rows.items() if row[1] in groups]
    except BaseException as error:
        remaining=['unverified'];reason='final process inspection failed: '+repr(error)
    record.update(returncode=rc,stop_reason=reason,finished_epoch=time.time(),owned_processes=owned,remaining=remaining,signal_errors=signal_errors)
    for ext in ('stdout','stderr'):
        path=out/(a.label+'.'+ext);record[ext]={'path':str(path),'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    (out/(a.label+'.json')).write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({'label':a.label,'returncode':rc,'stop_reason':reason,'remaining':remaining,'record':str(out/(a.label+'.json'))}))
    raise SystemExit(125 if reason or remaining else rc)

if __name__=='__main__':main()
