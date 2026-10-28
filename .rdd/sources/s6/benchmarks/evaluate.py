"""Independent S4 sample evaluator; no application query/clock implementation."""
import json,math,sys
EXPECTED={'C-P1':{'launch_ms':(30,2000)},'C-P2':{**{n+'_ms':(100,200) for n in ('create','edit','complete','reopen','delete')},**{n+'_ms':(100,250) for n in ('search','status_filter','date_filter','ordering')}},'C-P3':{'export_ms':(30,5000),'restore_ms':(30,5000)}}
def unique(pairs):
 d={}
 for k,v in pairs:
  if k in d:raise ValueError('duplicate JSON key')
  d[k]=v
 return d
def evaluate(check,data):
 assert type(data['errors']) is int and data['errors']==0
 env=data['environment'];assert env['host_profile']=='todo-macos26-arm64-reference'
 assert type(env['free_bytes']) is int and env['free_bytes']>=15*1024**3
 assert env['window_points']=={'width':1280,'height':720}
 assert env['ssd_backing_attested'] is True and env['ac_power_attested'] is True and env['normal_mode_attested'] is True
 assert env['concurrent_build_or_benchmark'] is False and env['instrumented'] is False
 assert all(isinstance(env[k],str) and env[k].strip() for k in ['attested_by','attested_at','os_build','webview_version','cpu','source_digest','package_sha256','evaluator_sha256'])
 assert type(env['ram_bytes']) is int and env['ram_bytes']>=32*1024**3
 assert set(data['samples'])==set(EXPECTED[check]) and set(data['units'])==set(EXPECTED[check])
 result={}
 for name,(n,limit) in EXPECTED[check].items():
  values=data['samples'][name];assert len(values)==n and data['units'][name]=='ms'
  assert all(type(x) in (int,float) and math.isfinite(x) and x>=0 for x in values)
  ordered=sorted(values);p95=ordered[math.ceil(.95*n)-1];assert p95<=limit,(name,p95,limit)
  result[name]={'count':n,'p50':ordered[math.ceil(.5*n)-1],'p95':p95,'max':max(values)}
 return result
if __name__=='__main__':
 if len(sys.argv)!=3:raise SystemExit('CHECK_ID RAW_JSON')
 data=json.load(open(sys.argv[2]),object_pairs_hook=unique,parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)))
 print(json.dumps(evaluate(sys.argv[1],data)))
