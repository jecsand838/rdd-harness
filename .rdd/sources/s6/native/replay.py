"""Rebuild immutable native v3 and replay CLI mechanisms with explicit identity."""
from pathlib import Path
import hashlib,json,os,plistlib,shutil,subprocess,sys,tempfile,time
sys.dont_write_bytecode=True;sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from provision import ROOT,build_environment
HERE=Path(__file__).parent;runtime=ROOT/'.rdd/runtime/s6';runtime.mkdir(parents=True,exist_ok=True)
work=Path(tempfile.mkdtemp(prefix='native-',dir=runtime));native=work/'native';native.mkdir();(native/'src').mkdir();logs=work/'logs';logs.mkdir()
inputs=[]
for name in ['Cargo.toml','Cargo.lock','src/main.rs','Info.plist']:
 p=HERE/name;out=native/name;shutil.copy2(p,out);inputs.append({'path':'native/'+name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
for name in ['replay.py','probe_suite.py','supplemental.py','gui_watch.py','pins.json','archives.json']:
 shutil.copy2(HERE/name,work/name);inputs.append({'path':name,'sha256':hashlib.sha256((HERE/name).read_bytes()).hexdigest()})
(work/'inputs.json').write_text(json.dumps(inputs,indent=2)+'\n')
env,paths,_=build_environment();env['CARGO_TARGET_DIR']=str(runtime/'joint-target')
(work/'environment.json').write_text(json.dumps({k:env[k] for k in ['CARGO_HOME','CARGO_TARGET_DIR','RUSTUP_HOME','RUSTC','PATH','DYLD_FALLBACK_LIBRARY_PATH']},indent=2)+'\n')
def run(label,argv,timeout=120):
 record={'argv':argv,'cwd':str(work),'started_epoch':time.time()};receipt=logs/(label+'.json');receipt.write_text(json.dumps(record,indent=2)+'\n')
 try:
  with (logs/(label+'.stdout')).open('wb') as out,(logs/(label+'.stderr')).open('wb') as err:r=subprocess.run(argv,cwd=work,env=env,stdout=out,stderr=err,timeout=timeout)
  record.update(returncode=r.returncode,finished_epoch=time.time());receipt.write_text(json.dumps(record,indent=2)+'\n');assert r.returncode==0,(label,(logs/(label+'.stderr')).read_text()[-5000:])
 except BaseException as error:record.update(error=repr(error));receipt.write_text(json.dumps(record,indent=2)+'\n');raise
binary=runtime/'joint-target/debug/rdd-native-mechanisms'
if binary.exists():shutil.copy2(binary,work/'previous-cache-native')
run('build',[paths['cargo'],'build','--locked','--manifest-path',str(native/'Cargo.toml')],300)
app=work/'RDD Native Mechanisms v3.app';macos=app/'Contents/MacOS';macos.mkdir(parents=True);shutil.copy2(native/'Info.plist',app/'Contents/Info.plist');shutil.copy2(binary,macos/'rdd-native-mechanisms')
run('sign',['/usr/bin/codesign','--force','--sign','-',str(app)]);run('verify-signature',['/usr/bin/codesign','--verify','--deep','--strict',str(app)])
plist=plistlib.loads((app/'Contents/Info.plist').read_bytes());executable=macos/'rdd-native-mechanisms';identity={'executable':str(executable),'executable_sha256':hashlib.sha256(executable.read_bytes()).hexdigest(),'bundle_identifier':plist['CFBundleIdentifier'],'source_sha256':hashlib.sha256((native/'src/main.rs').read_bytes()).hexdigest(),'manifest_sha256':hashlib.sha256((native/'Cargo.toml').read_bytes()).hexdigest(),'lock_sha256':hashlib.sha256((native/'Cargo.lock').read_bytes()).hexdigest(),'build_cache':'warmed shared S6 cache; preserved S5 cache untouched'}
identity_path=work/'identity.json';identity_path.write_text(json.dumps(identity,indent=2)+'\n')
archives=json.loads((HERE/'archives.json').read_text())['packages'];verified=[]
for row in archives:
 matches=list((Path(env['CARGO_HOME'])/'registry/cache').glob('*/'+row['name']+'-'+row['version']+'.crate'));assert len(matches)==1,row['name'];assert hashlib.sha256(matches[0].read_bytes()).hexdigest()==row['sha256'];verified.append(row['name']+'@'+row['version'])
for label,script in [('mechanisms','probe_suite.py'),('supplemental','supplemental.py')]:run(label,[sys.executable,str(work/script),'--root',str(work),'--app',str(app),'--identity',str(identity_path)],180)
changed=[row['path'] for row in inputs if hashlib.sha256((work/row['path']).read_bytes()).hexdigest()!=row['sha256']];(work/'input-audit.json').write_text(json.dumps({'changed_inputs':changed},indent=2)+'\n');assert not changed
historical=json.loads((HERE.parent/'manifest.json').read_text())['native_qualification'];assert identity['source_sha256']==historical['source_sha256']
report={'status':'pass','work':str(work),'identity':identity,'verified_archive_count':len(verified),'mechanisms':json.loads((work/'mechanism-v3-results.json').read_text()),'supplemental':json.loads((work/'supplemental-results.json').read_text()),'same_historical_binary':identity['executable_sha256']==historical['historical_binary_sha256'],'scope':'reproduced locked native CLI mechanisms and exact source comparison with accepted S5 GUI inputs; no repeated GUI observation or product scenario is claimed'}
(work/'result.json').write_text(json.dumps(report,indent=2)+'\n');(runtime/'native-result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k not in ['mechanisms','supplemental']}))
