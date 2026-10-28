"""Disposable typed wiring and permissions qualification; not product adapter adoption."""
from pathlib import Path
import hashlib,json,os,re,shutil,subprocess,sys,tempfile
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from provision import build_environment
from tools.rdd.artifacts import module_contracts_validate,domain_solution_validate,unique
spec=json.loads((ROOT/'.rdd/spec.json').read_text());modules=unique(spec['modules'],'module');elements=unique(spec['solution_elements'],'element')
domain_solution_validate(ROOT,spec,modules,elements)
module_contracts_validate(ROOT,spec,modules,elements,unique(spec['checks'],'check'),spec['documents']+spec['decisions'])
index=json.loads((ROOT/spec['contract_index_path']).read_text())['contract_index'];services={r['symbol'].split('.')[1]:r for r in index['services']}
(ROOT/'.rdd/runtime/s6').mkdir(parents=True,exist_ok=True)
work=Path(tempfile.mkdtemp(prefix='construction-',dir=ROOT/'.rdd/runtime/s6'));(work/'src').mkdir()
(work/'Cargo.toml').write_text('[package]\nname="rdd-construction-proof"\nversion="0.0.0"\nedition="2021"\n[workspace]\n[dependencies]\nrdd-contracts={path='+json.dumps(str(ROOT/'gen/rust'))+'}\n')
shutil.copyfile(ROOT/'gen/rust/Cargo.lock',work/'Cargo.lock')
lines=['use std::sync::{Arc,atomic::{AtomicUsize,Ordering}};','static LIVE:AtomicUsize=AtomicUsize::new(0); static CALLS:AtomicUsize=AtomicUsize::new(0);','struct Token; impl Drop for Token{fn drop(&mut self){LIVE.fetch_sub(1,Ordering::SeqCst);}}','fn ready<F:core::future::Future>(f:F)->F::Output{struct Wake;impl std::task::Wake for Wake{fn wake(self:Arc<Self>){}} let w=std::task::Waker::from(Arc::new(Wake));let mut c=std::task::Context::from_waker(&w);let mut f=std::pin::pin!(f);match f.as_mut().poll(&mut c){std::task::Poll::Ready(v)=>v,_=>panic!("disposable provider unexpectedly pending")}}']
order=[]
while len(order)<len(services):
 for mid in services:
  if mid not in order and all(d in order for d in modules[mid]['depends_on']):order.append(mid)
for mid in order:
 service=services[mid];trait=service['rust_trait'];ctor='make_probe_entry' if mid=='native_api' else 'construct';deps=modules[mid]['depends_on'];names=[f'D{i}' for i in range(len(deps))]
 bounds=', '.join(n+':'+services[d]['rust_trait']+'+Clone' for n,d in zip(names,deps));generic='<'+bounds+'>' if names else '';args='<'+', '.join(names)+'>' if names else '';tup='('+','.join(names)+(',' if names else '')+')';params=''.join(', d'+str(i)+':'+n for i,n in enumerate(names));vals='('+','.join('d'+str(i) for i in range(len(names)))+(',' if names else '')+')'
 failure=f'rdd_contracts::todo::{mid}::v1::Failure'
 lines += [f'mod {mid} {{',f'pub use {trait};',f'#[derive(Clone)] struct PrivateProvider{generic} {{_deps:{tup},_token:super::Arc<super::Token>}}',f'impl{generic} {trait} for PrivateProvider{args} {{']
 for op in service['operations']:lines += [f"fn {op['rust_method']}(&self,_request:{op['rust_input']})->impl core::future::Future<Output={op['rust_output']}>+Send {{async {{super::CALLS.fetch_add(1,super::Ordering::SeqCst);Default::default()}}}}"]
 lines += ['}',f'pub(super) fn {ctor}{generic}(identity:&\'static str{params})->Result<impl {trait}+Clone,{failure}> {{if identity.is_empty(){{return Err(Default::default())}};super::LIVE.fetch_add(1,super::Ordering::SeqCst);Ok(PrivateProvider{{_deps:{vals},_token:super::Arc::new(super::Token)}})}}','}']
# These are actual Rust source consumers. The qualification checker resolves their
# explicit trait calls to descriptor identities and fails unauthorized methods.
consumers={};expectedcalls=0
for mid,m in modules.items():
 providers=sorted({s.split('.')[1] for s in m['consumed_operations']});params=', '.join('p_'+p+':&impl '+services[p]['rust_trait'] for p in providers);body=[]
 for symbol in m['consumed_operations']:
  provider=symbol.split('.')[1];op=next(o for o in services[provider]['operations'] if o['symbol']==symbol);body.append(f"let _ = ready({services[provider]['rust_trait']}::{op['rust_method']}(p_{provider},Default::default()));");expectedcalls+=1
 if mid=='ui':
  native=(ROOT/'gen/rust/src/generated/todo.native_api.v1.rs').read_text();variants=re.findall(r'^        (\w+)\(super::super::super::workspace::v1::\w+Request\)',native,re.M)
  assert len(variants)==9,(variants,'all workspace request variants must be constructible by inference')
  body += ['let _requests:Vec<rdd_contracts::todo::native_api::v1::InvokeRequest>=vec!['+', '.join('rdd_contracts::todo::native_api::v1::InvokeRequest{action:Some(rdd_contracts::todo::native_api::v1::invoke_request::Action::'+v+'(Default::default()))}' for v in variants)+'];']
 consumers[mid]='fn consumer_'+mid+'('+params+'){'+''.join(body)+'}'
def permission_check(mid,source):
 seen=[]
 for trait,method in re.findall(r'(rdd_contracts::todo::\w+::v1::\w+Service)::(\w+)\(',source):
  matches=[o['symbol'] for s in services.values() if s['rust_trait']==trait for o in s['operations'] if o['rust_method']==method]
  assert len(matches)==1,'unknown descriptor call';assert matches[0] in modules[mid]['consumed_operations'],('forbidden call',mid,matches[0]);seen+=matches
 return seen
for mid,source in consumers.items():assert set(permission_check(mid,source))==set(modules[mid]['consumed_operations'])
negative=consumers['query'].replace('}', 'let _ = ready(rdd_contracts::todo::collection::v1::CollectionService::create(p_collection,Default::default()));}',1)
try:permission_check('query',negative)
except AssertionError as e:(work/'forbidden-call.txt').write_text(negative+'\n'+repr(e))
else:raise AssertionError('unauthorized real consumer source accepted')
lines+=list(consumers.values());lines+=['fn main(){let identity="com.rdd.qualification";']
for mid in order:
 ctor='make_probe_entry' if mid=='native_api' else 'construct';params=''.join(', p_'+d+'.clone()' for d in modules[mid]['depends_on']);lines += [f'assert!({mid}::{ctor}(""{params}).is_err());',f'let p_{mid}={mid}::{ctor}(identity{params}).unwrap();']
# The registered entry is invoked through its generated interface, not downcast.
lines+=['fn register<T:rdd_contracts::todo::native_api::v1::NativeApiService>(entry:T)->T{entry}','let registered=register(p_native_api.clone());','let _=ready(rdd_contracts::todo::native_api::v1::NativeApiService::invoke(&registered,Default::default()));','drop(registered);']
for mid,m in modules.items():lines+=['consumer_'+mid+'('+', '.join('&p_'+p for p in sorted({s.split('.')[1] for s in m['consumed_operations']}))+');']
lines += [f'assert_eq!(CALLS.load(Ordering::SeqCst),{expectedcalls+1});',f'assert_eq!(LIVE.load(Ordering::SeqCst),{len(services)});']
for mid in reversed(order):lines+=['drop(p_'+mid+');']
lines+=['assert_eq!(LIVE.load(Ordering::SeqCst),0);','}'];source='\n'.join(lines)+'\n';(work/'src/main.rs').write_text(source)
env,qualified_paths,_=build_environment();env['CARGO_TARGET_DIR']=str(ROOT/'.rdd/runtime/cargo-target');env['CARGO_INCREMENTAL']='0';env['CARGO_PROFILE_DEV_DEBUG']='0'
def run(label,argv,ok=True):
 r=subprocess.run(argv,capture_output=True,text=True,timeout=180,env=env);(work/(label+'.stdout')).write_text(r.stdout);(work/(label+'.stderr')).write_text(r.stderr)
 assert (r.returncode==0)==ok,(label,r.stderr);return r
(work/'qualified-environment.json').write_text(json.dumps({'paths':qualified_paths,'cargo_home':env['CARGO_HOME'],'path':env['PATH']},indent=2)+'\n')
cargo=[qualified_paths['cargo']];manifest=['--manifest-path',str(work/'Cargo.toml')]
run('lock',cargo+['generate-lockfile','--offline']+manifest)
run('positive-native',cargo+['run','--quiet','--locked']+manifest)
run('positive-wasm',cargo+['check','--locked','--target','wasm32-unknown-unknown']+manifest)
# An actual export bypass consumer must fail compilation against opaque returns.
private=source.replace('let registered=register(', 'let _ = p_collection._deps; let registered=register(',1);(work/'src/main.rs').write_text(private);r=run('private-export-negative',cargo+['check','--locked']+manifest,False);assert 'no field' in r.stderr or 'private' in r.stderr
# An incompatible provider cannot be substituted at the real constructor boundary.
wrong=source.replace('collection::construct(identity, p_storage.clone())','collection::construct(identity, p_diagnostics.clone())',1);assert wrong!=source;(work/'src/main.rs').write_text(wrong);r=run('wrong-provider-negative',cargo+['check','--locked']+manifest,False);assert 'StorageService' in r.stderr
(work/'src/main.rs').write_text(source)
print(json.dumps({'providers':len(services),'actual_generated_calls':expectedcalls+1,'registration_reachability':'pass','initialization_failure_and_drop':'pass','native_and_wasm_consumers':'pass','ui_all_action_variants':9,'forbidden_consumer_source_rejection':'pass','private_export_compiler_rejection':'pass','wrong_dependency_compiler_rejection':'pass','source_sha256':hashlib.sha256(source.encode()).hexdigest(),'evidence':str(work),'scope':'eight construction analogues and one private native-entry factory, typed providers and explicit-call permission checker; actual native_api Builder wiring is C-QUAL-JOINT. Real adapters, indirect-call bypass analysis and behavioral semantics remain product checks'}))
