"""Exact clean-source export/resume/check/raw-receipt import on this native host."""
from pathlib import Path
import hashlib,json,shutil,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[3];runtime=ROOT/'.rdd/runtime/s6/transfer';runtime.mkdir(parents=True,exist_ok=True)
checkpoint=runtime/'checkpoint.json'
assert checkpoint.is_file(),'Before invoking the check, run ./rdd export-run .rdd/runtime/s6/transfer/checkpoint.json outside another controller command.'
work=Path(tempfile.mkdtemp(prefix='replay-',dir=runtime));logs=work/'logs';logs.mkdir()
def run(label,args,cwd=ROOT,timeout=120):
 r=subprocess.run(args,cwd=cwd,capture_output=True,text=True,timeout=timeout);(logs/(label+'.stdout')).write_text(r.stdout);(logs/(label+'.stderr')).write_text(r.stderr);assert r.returncode==0,(label,r.stderr,r.stdout);return r.stdout
head=run('head',['git','rev-parse','HEAD']).strip();payload=json.loads(checkpoint.read_text());assert payload['source_commit']==head
host=ROOT/'.rdd/runtime/host.json';assert host.is_file()
clones=[]
for label in ('producer','receiver'):
 clone=work/label;run(label+'-clone',['git','clone','--no-hardlinks','--local','--no-checkout',str(ROOT),str(clone)]);run(label+'-checkout',['git','checkout','-B',payload['state']['base_branch'],head],clone)
 run(label+'-resume',['./rdd','resume','--from',str(checkpoint)],clone)
 (clone/'.rdd/runtime').mkdir(parents=True,exist_ok=True);shutil.copyfile(host,clone/'.rdd/runtime/host.json');clones.append(clone)
producer,receiver=clones
receipt=json.loads(run('fixture-check',['./rdd','check','C-QUAL-FIXTURES'],producer,180));assert receipt['outcome']=='pass' and receipt['source_commit']==head
source_log=producer/receipt['log_path'];assert hashlib.sha256(source_log.read_bytes()).hexdigest()==receipt['log_digest']
target_log=receiver/receipt['log_path'];target_log.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source_log,target_log)
receipt_file=work/'receipt.json';receipt_file.write_text(json.dumps(receipt,indent=2)+'\n')
imported=json.loads(run('receipt-import',['./rdd','check','import',str(receipt_file),'--local-host'],receiver));assert imported['status']=='imported' and imported['evidence']==receipt['id']
assert run('source-head-after',['git','rev-parse','HEAD']).strip()==head
print(json.dumps({'resources':{'R-TRANSFER':{'environment':'macos-reference','version':'same-host-exact-source','observation':'Actual clean-source clones resumed the matching checkpoint; producer fixture check passed and its exact raw log/receipt imported through --local-host into receiver. '+str(work)}},'checkpoint_sha256':hashlib.sha256(checkpoint.read_bytes()).hexdigest(),'receipt':receipt['id'],'scope':'same-host clean-source transfer and native controller receipt mechanism, not remote attestation'}))
