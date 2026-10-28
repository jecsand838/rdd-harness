"""Measured native facilities and separately authorized exact observer evidence."""
from pathlib import Path
import csv,hashlib,json,os,platform,shutil,signal,socket,subprocess,sys,tempfile,time
ROOT=Path(__file__).resolve().parents[3];runtime=ROOT/'.rdd/runtime/s6';runtime.mkdir(parents=True,exist_ok=True)
work=Path(tempfile.mkdtemp(prefix='host-',dir=runtime));records=[]
def interrupted(signum,frame):raise InterruptedError('host probe interrupted: '+str(signum))
for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):signal.signal(sig,interrupted)
def run(label,args,timeout=15,ok=True):
 r=subprocess.run(args,capture_output=True,timeout=timeout);(work/(label+'.stdout')).write_bytes(r.stdout);(work/(label+'.stderr')).write_bytes(r.stderr);records.append({'label':label,'argv':args,'returncode':r.returncode});assert (r.returncode==0)==ok,(label,r.stderr.decode(errors='replace'));return r
osversion=run('os',['/usr/bin/sw_vers','-productVersion']).stdout.decode().strip();build=run('os-build',['/usr/bin/sw_vers','-buildVersion']).stdout.decode().strip();memory=int(run('ram',['/usr/sbin/sysctl','-n','hw.memsize']).stdout);model=run('model',['/usr/sbin/sysctl','-n','hw.model']).stdout.decode().strip();sdk=run('sdk',['/usr/bin/xcrun','--sdk','macosx','--show-sdk-version']).stdout.decode().strip()
assert platform.machine()=='arm64' and osversion=='26.6.2' and build=='25G83' and memory==32*1024**3 and model=='VirtualMac2,1' and sdk=='27.0'
# The alternate principal reads the provided public host file, then is denied
# a synthetic private file in the current account tree. This qualifies the
# account-denial mechanism, not any product file layout or mode independently.
control=work/'account';control.mkdir();(control/'private').write_text('private sensitivity control\n');(control/'private').chmod(0o600)
run('account-id',['sudo','-n','-u','nobody','--','/usr/bin/id'])
assert run('account-public',['sudo','-n','-u','nobody','--','/bin/cat','/etc/hosts']).stdout
run('account-private',['sudo','-n','-u','nobody','--','/bin/cat',str(control/'private')],ok=False)
# One owned loopback client establishes actual process-attribution sensitivity.
server=socket.socket();server.settimeout(8);server.bind(('127.0.0.1',0));server.listen(1);port=server.getsockname()[1];client=None;capture=None;conn=None
try:
 capfile=work/'control.pcap';capout=(work/'capture.stdout').open('wb');caperr=(work/'capture.stderr').open('wb')
 capture=subprocess.Popen(['sudo','-n','/usr/sbin/tcpdump','-i','pktap,lo0','-k','NP','-n','-s','128','-c','12','-U','-w',str(capfile),'tcp','port',str(port)],stdout=capout,stderr=caperr)
 time.sleep(.3)
 client=subprocess.Popen([sys.executable,'-c','import socket,time,sys;s=socket.create_connection(("127.0.0.1",int(sys.argv[1])));s.sendall(b"RDD-NET-CONTROL");time.sleep(4);s.close()',str(port)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 conn,_=server.accept();assert conn.recv(128)==b'RDD-NET-CONTROL'
 net=run('nettop',['/usr/bin/nettop','-n','-x','-p',str(client.pid),'-L','2','-s','1','-J','bytes_in,bytes_out'],8).stdout.decode();rows=list(csv.reader(net.splitlines()));assert any(len(row)>=3 and row[0].endswith('.'+str(client.pid)) and row[2].isdigit() and int(row[2])>=15 for row in rows)
 client.communicate(timeout=6);assert client.returncode==0;capture.wait(timeout=6);assert capture.returncode==0
 capout.close();caperr.close();render=run('pcap',['/usr/sbin/tcpdump','-k','NP','-nn','-r',str(capfile)]).stdout.decode();assert any((':'+str(client.pid)+')') in line and 'length 15' in line for line in render.splitlines())
finally:
 if conn:conn.close()
 server.close()
 if client and client.poll() is None:client.terminate();client.wait(timeout=5)
 if capture and capture.poll() is None:
  # Signal only the still-unreaped process created above; never a discovered PID.
  subprocess.run(['sudo','-n','/bin/kill','-INT',str(capture.pid)],capture_output=True,timeout=5);capture.wait(timeout=5)
# The denied-network process must prove an actual attempt was rejected.
code='import socket,sys\ntry: socket.create_connection(("127.0.0.1",9),timeout=2)\nexcept PermissionError: print("DENIED");sys.exit(0)\nsys.exit(3)'
assert run('network-denied',['/usr/bin/sandbox-exec','-p','(version 1) (allow default) (deny network*)',sys.executable,'-c',code]).stdout.strip()==b'DENIED'
# Parent supplies an exact separately reviewed binding and actual UI observation.
authorized=json.loads((runtime/'observer-authorized.json').read_text())
def checked_path(key):
 item=authorized[key];p=Path(item['path']);assert hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256'],key;return p
observer=checked_path('observer');target=checked_path('target');binding_path=checked_path('binding');binding=json.loads(binding_path.read_text());action=json.loads(checked_path('action').read_text())
assert str(observer)==binding['observer_executable'] and authorized['observer']['sha256']==binding['observer_sha256']
assert hashlib.sha256((binding_path.parent/'observer.swift').read_bytes()).hexdigest()==binding['source_sha256']
assert str(target)==binding['target_executable'] and authorized['target']['sha256']==binding['target_sha256']
trust=json.loads(run('observer-current-trust',[str(observer)]).stdout);assert trust['trusted'] is True and trust['ui_actions_requested'] is False and trust['observer_bundle_identifier']==binding['observer_bundle_identifier']
assert action['trusted'] is True and action['target_path']==str(target) and action['target_sha256']==binding['target_sha256'] and action['observer_bundle_identifier']==binding['observer_bundle_identifier']
assert action['actual_window_size_points']=={'width':1280,'height':720} and action['stable_geometry_samples']>=3 and action['press_status']==0
assert action['precondition_observed_absent_ns']<=action['action_start_ns']<action['first_observed_visible_ns']
assert any('COMMITTED probe-20261028-R5' in value for value in action['final_text'])
assert 'CANONICAL INVOKE READY' in action['initial_text'] and 'CANONICAL INVOKE READY' in action['final_text']
# The fresh bound package is one of the actual newly built candidate packages.
joint=json.loads((runtime/'joint-result.json').read_text());assert any(row['sha256']==binding['target_sha256'] for row in joint['artifacts'])
report={'os':osversion,'build':build,'machine':platform.machine(),'model':model,'ram_bytes':memory,'sdk':sdk,'free_bytes':shutil.disk_usage(ROOT).free,'benchmark_conditions_qualified':False,'records':records,'account_control_directory':str(control),'observer_binding':binding,'scope':'actual facilities and exact-package synthetic AX mechanism; physical SSD/AC/normal mode remain human attestation; full rendered/input-ready product oracle, process-tree no-egress acceptance, accessibility and benchmark readiness are separate'}
(work/'result.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'resources':{'R-HOST':{'environment':'macos-reference','version':'macos26.6.2-arm64-32GiB-SDK27','observation':json.dumps(report)},'R-OBSERVER':{'environment':'macos-reference','version':'v6-guarded-identity','observation':'Actual current trust, explicit new binding, stable 1280x720 frame and new marker evidence verified: '+str(work)}},'scope':report['scope']}))
