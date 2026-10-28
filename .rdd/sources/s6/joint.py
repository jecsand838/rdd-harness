"""Build the disposable native/WASM/package carrier with exact candidate contracts."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,tempfile,time
sys.dont_write_bytecode=True
from provision import ROOT,build_environment
runtime=ROOT/'.rdd/runtime/s6';runtime.mkdir(parents=True,exist_ok=True)
work=Path(tempfile.mkdtemp(prefix='joint-',dir=runtime));source=Path(__file__).with_name('carrier');shutil.copytree(source,work/'carrier');carrier=work/'carrier'
shutil.copytree(ROOT/'gen/rust',carrier/'candidate-contracts')
env,paths,clis=build_environment();env['CARGO_TARGET_DIR']=str(runtime/'joint-target')
logs=work/'logs';logs.mkdir()
shutil.copyfile(__file__,work/'runner.py')
inputs=[{'path':str(p.relative_to(carrier)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in carrier.rglob('*') if p.is_file()]
(work/'inputs.json').write_text(json.dumps(inputs,indent=2)+'\n')
(work/'environment.json').write_text(json.dumps({k:env[k] for k in ['CARGO_HOME','CARGO_TARGET_DIR','RUSTUP_HOME','RUSTC','PATH','DYLD_FALLBACK_LIBRARY_PATH']},indent=2)+'\n')
def run(name,argv,cwd=carrier,timeout=600):
 record={'argv':argv,'cwd':str(cwd),'started_epoch':time.time(),'status':'running'};command=logs/(name+'.json');command.write_text(json.dumps(record,indent=2)+'\n')
 try:
  with (logs/(name+'.stdout')).open('wb') as out,(logs/(name+'.stderr')).open('wb') as err:
   r=subprocess.run(argv,cwd=cwd,env=env,stdout=out,stderr=err,timeout=timeout)
  record.update(returncode=r.returncode,status='finished',finished_epoch=time.time());command.write_text(json.dumps(record,indent=2)+'\n')
  r.stdout=(logs/(name+'.stdout')).read_bytes();r.stderr=(logs/(name+'.stderr')).read_bytes();assert r.returncode==0,(name,r.stderr.decode(errors='replace')[-6000:]);return r
 except BaseException as error:
  record.update(status='failed',error=repr(error),finished_epoch=time.time());command.write_text(json.dumps(record,indent=2)+'\n');raise
preserved=work/'artifacts';preserved.mkdir()
prior=work/'prior-cache-artifacts';prior.mkdir()
for name,path in [('native-debug',runtime/'joint-target/debug/qualification-carrier'),('bundle',runtime/'joint-target/release/bundle')]:
 if path.is_dir():shutil.copytree(path,prior/name)
 elif path.is_file():shutil.copy2(path,prior/name)
run('ui',[clis['trunk'],'build','--release','--locked'],carrier/'ui')
shutil.copytree(carrier/'ui/dist',preserved/'ui')
run('native',[paths['cargo'],'build','--locked','-p','qualification-carrier'])
shutil.copy2(runtime/'joint-target/debug/qualification-carrier',preserved/'native-debug')
run('native-storage',[str(runtime/'joint-target/debug/qualification-carrier'),'--storage-probe',str(work/'disposable.db')])
assert run('reopen',[str(runtime/'joint-target/debug/qualification-carrier'),'--read-probe',str(work/'disposable.db')]).stdout.strip()==b'native-baseline'
run('package',[paths['cargo'],'tauri','build','--bundles','app,dmg','--ci','--','--locked'],carrier,900)
artifacts=[]
for base in [runtime/'joint-target/debug/qualification-carrier',runtime/'joint-target/release/bundle',carrier/'ui/dist']:
 for p in ([base] if base.is_file() else base.rglob('*')):
  if p.is_file():artifacts.append({'path':str(p),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
# Preserve binary/package bytes before a subsequent build reuses the target cache.
shutil.copytree(runtime/'joint-target/release/bundle',preserved/'bundle')
changed_inputs=[row['path'] for row in inputs if not (carrier/row['path']).is_file() or hashlib.sha256((carrier/row['path']).read_bytes()).hexdigest()!=row['sha256']]
(work/'input-audit.json').write_text(json.dumps({'changed_frozen_inputs':changed_inputs},indent=2)+'\n');assert not changed_inputs,changed_inputs
record={'status':'pass','work':str(work),'artifacts':artifacts,'candidate_generated_inventory':json.loads((ROOT/'gen/rust/.rdd-generated.json').read_text())['generated_files'] if 'generated_files' in json.loads((ROOT/'gen/rust/.rdd-generated.json').read_text()) else hashlib.sha256((ROOT/'gen/rust/.rdd-generated.json').read_bytes()).hexdigest(),'cache':'warmed shared S6 target/Cargo home; previously fresh qualified compiler installation reverified','scope':'qualified compiler plus exact candidate types jointly compiled and round-tripped with retained non-Todo native/WASM carrier; storage/reopen and package creation executed; canonical Invoke over actual IPC is executed by the packaged UI and must be observed by C-READY-HOST; actual product adapters and product scenarios remain separate'}
(work/'result.json').write_text(json.dumps(record,indent=2)+'\n');(runtime/'joint-result.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))
