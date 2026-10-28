"""Pinned clean Rust/Buf installation and actual compiler smoke; source inputs are frozen."""
from pathlib import Path
import sys,os,json,urllib.request,urllib.error,urllib.parse,hashlib,datetime,subprocess,shutil,tarfile,time,tempfile
ROOT=Path(__file__).resolve().parents[3]
def install(P):
    for sub in ('metadata','archives','tools','logs'):(P/sub).mkdir(parents=True,exist_ok=True)
    ARCHIVES=P/'archives';TOOLS=P/'tools';RUSTUP=P/'rustup-home';CARGO=P/'cargo-home';LOG=P/'logs';records=[]
    def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
    def download(name,url,expected,maximum=300_000_000):
     parsed=urllib.parse.urlsplit(url)
     if parsed.scheme!='https' or parsed.hostname not in ['static.rust-lang.org','github.com']:raise ValueError('undeclared acquisition origin')
     target=ARCHIVES/name;started=time.time();rec={'name':name,'url':url,'started_utc':stamp(),'expected_sha256':expected};h=hashlib.sha256();count=0;failure=None
     try:
      with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'rdd-s6-qualified-provision/1.0'}),timeout=45) as response,target.open('xb') as out:
       final=urllib.parse.urlsplit(response.url)
       if final.scheme!='https':raise ValueError('non-HTTPS acquisition redirect')
       rec.update(status=response.status,final_url=urllib.parse.urlunsplit((final.scheme,final.netloc,final.path,'','')),redacted_public_redirect_query_keys=sorted(urllib.parse.parse_qs(final.query)),response_headers=dict(response.headers))
       while True:
        block=response.read(1024*1024)
        if not block:break
        count+=len(block)
        if count>maximum:raise ValueError('archive bounded size exceeded')
        h.update(block);out.write(block)
     except Exception as error:
      failure=error;rec['error']=repr(error)
      if isinstance(error,urllib.error.HTTPError):
       raw=error.read(65536);raw_path=LOG/(name+'.http-error.raw');raw_path.write_bytes(raw);rec.update(status=error.code,error_headers=dict(error.headers),error_body_path=str(raw_path),error_body_sha256=hashlib.sha256(raw).hexdigest())
     rec.update(bytes=count,sha256=h.hexdigest(),finished_utc=stamp(),elapsed_seconds=time.time()-started,path=str(target),checksum_match=failure is None and h.hexdigest()==expected)
     (P/'metadata'/(name+'.download.json')).write_text(json.dumps(rec,indent=2)+'\n')
     if failure:raise failure
     if not rec['checksum_match']:raise ValueError('official checksum mismatch: '+name)
     records.append(rec);return target
    def global_settings_hashes():
     home=Path(os.environ['HOME']);names=['.cargo/env','.rustup/settings.toml','.zprofile','.zshrc','.profile','.bash_profile','.bashrc'];result=[]
     for name in names:
      path=home/name;row={'path':str(path),'exists':path.exists()}
      if path.is_file():row.update(bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
      result.append(row)
     return result
    before_global=global_settings_hashes();(P/'metadata/global-settings-before.json').write_text(json.dumps(before_global,indent=2)+'\n')
    pins=json.loads(Path(__file__).with_name('tools.json').read_text());plan=pins['acquisition_plan'];component_data=pins['rust_components'];buf=pins['buf_assets']
    # Retain exact official archives before installation. The installer separately
    # downloads the same checksum-addressed components into its initially empty home.
    installer=download('rustup-init-1.29.2-aarch64-apple-darwin',plan['rustup_init_url'],plan['rustup_init_sha256'],30_000_000);installer.chmod(0o755)
    for component in component_data['components']:
     component['archive_path']=str(download(Path(component['url']).name,component['url'],component['sha256']))
    checksum_asset=next(x for x in buf['assets'] if x['name']=='sha256.txt');checks=download('buf-1.73.0-sha256.txt',checksum_asset['url'],checksum_asset['digest'].split(':',1)[1],100_000).read_text();buf_asset=next(x for x in buf['assets'] if x['name']=='buf-Darwin-arm64');advertised=buf_asset['digest'].split(':',1)[1];official=next(line.split()[0] for line in checks.splitlines() if line.split()[-1].lstrip('*')=='buf-Darwin-arm64');assert advertised==official
    buf_archive=download('buf-1.73.0-Darwin-arm64',buf_asset['url'],official,100_000_000);bufdir=TOOLS/'buf/bin';bufdir.mkdir(parents=True);bufexe=bufdir/'buf';shutil.copy2(buf_archive,bufexe);bufexe.chmod(0o755)
    for home in [RUSTUP,CARGO]:
     home.mkdir(exist_ok=False);assert not list(home.iterdir())
    (P/'metadata/empty-homes.json').write_text(json.dumps({'observed_utc':stamp(),'RUSTUP_HOME':str(RUSTUP),'CARGO_HOME':str(CARGO),'both_empty':True},indent=2)+'\n')
    env={k:os.environ[k] for k in ['HOME','USER','LOGNAME','TMPDIR','LANG'] if k in os.environ};env.update({'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','RUSTUP_HOME':str(RUSTUP),'CARGO_HOME':str(CARGO),'RUSTUP_DIST_SERVER':'https://static.rust-lang.org','RUSTUP_UPDATE_ROOT':'https://static.rust-lang.org/rustup','RUSTUP_VERSION':plan['rustup_version']})
    def run(label,args,timeout=300):
     started=time.time();r=subprocess.run(args,env=env,cwd=P,capture_output=True,timeout=timeout);rec={'argv':args,'cwd':str(P),'environment':env,'started_utc':datetime.datetime.fromtimestamp(started,datetime.timezone.utc).isoformat(),'finished_utc':stamp(),'elapsed_seconds':time.time()-started,'returncode':r.returncode,'stdout_sha256':hashlib.sha256(r.stdout).hexdigest(),'stderr_sha256':hashlib.sha256(r.stderr).hexdigest()};(LOG/(label+'.stdout')).write_bytes(r.stdout);(LOG/(label+'.stderr')).write_bytes(r.stderr);(LOG/(label+'.command.json')).write_text(json.dumps(rec,indent=2)+'\n');assert r.returncode==0,(label,r.returncode,r.stdout.decode(),r.stderr.decode());return r
    run('01-installer-version',[str(installer),'--version'],15);run('02-installer-help',[str(installer),'--help'],15)
    args=[str(installer),'-y','--no-modify-path','--profile','minimal','--default-toolchain','1.99.0','--component','rustfmt','--component','clippy','--target','wasm32-unknown-unknown'];run('03-fresh-install',args,900)
    proxy=CARGO/'bin/rustup';toolchain=RUSTUP/'toolchains/1.99.0-aarch64-apple-darwin';assert toolchain.is_dir();env['PATH']=str(CARGO/'bin')+os.pathsep+str(bufdir)+os.pathsep+'/usr/bin:/bin:/usr/sbin:/sbin';env['RUSTUP_AUTO_INSTALL']='0'
    verification_output={}
    for label,args in [('04-rustup-version',[str(proxy),'--version']),('05-rustc-version',[str(toolchain/'bin/rustc'),'-Vv']),('06-cargo-version',[str(toolchain/'bin/cargo'),'-Vv']),('07-rustfmt-version',[str(toolchain/'bin/rustfmt'),'--version']),('08-clippy-version',[str(toolchain/'bin/cargo-clippy'),'--version']),('09-installed-targets',[str(proxy),'target','list','--installed','--toolchain','1.99.0']),('10-installed-components',[str(proxy),'component','list','--installed','--toolchain','1.99.0']),('11-buf-version',[str(bufexe),'--version']),('12-new-rustc-path',[str(proxy),'which','--toolchain','1.99.0','rustc'])]:verification_output[label]=run(label,args,30).stdout.decode()
    assert 'rustup 1.29.2' in verification_output['04-rustup-version']
    assert 'release: 1.99.0' in verification_output['05-rustc-version']
    assert 'cargo 1.99.0' in verification_output['06-cargo-version']
    assert verification_output['11-buf-version'].strip()=='1.73.0'
    assert set(verification_output['09-installed-targets'].splitlines())=={'aarch64-apple-darwin','wasm32-unknown-unknown'}
    expected_components={'cargo-aarch64-apple-darwin','clippy-aarch64-apple-darwin','rust-std-aarch64-apple-darwin','rust-std-wasm32-unknown-unknown','rustc-aarch64-apple-darwin','rustfmt-aarch64-apple-darwin'}
    assert set(verification_output['10-installed-components'].splitlines())==expected_components
    assert Path(verification_output['12-new-rustc-path'].strip()).resolve()==(toolchain/'bin/rustc').resolve()
    # Compare every installed regular member listed by the selected component tar
    # against the contemporaneously retained official archive bytes, without extract.
    comparisons=[]
    for component in component_data['components']:
     matched=0;missing=[];different=[];members=[]
     with tarfile.open(component['archive_path'],mode='r:xz') as archive:
      top=archive.getmembers()[0].name.split('/')[0]
      for member in archive.getmembers():
       if not member.isfile():continue
       if Path(member.name).is_absolute() or '..' in Path(member.name).parts:raise ValueError('unsafe archive member')
       rel=Path(member.name).relative_to(top);parts=rel.parts
       if len(parts)<2 or parts[0] in ['install.sh','components','rust-installer-version','version','git-commit-hash','LICENSE-APACHE','LICENSE-MIT','COPYRIGHT','README.md']:continue
       if parts[1]=='manifest.in':continue
       installed=toolchain/Path(*parts[1:])
       if not installed.is_file() or not installed.resolve().is_relative_to(toolchain.resolve()):missing.append(str(Path(*parts[1:])));continue
       expected=hashlib.sha256(archive.extractfile(member).read()).hexdigest();actual=hashlib.sha256(installed.read_bytes()).hexdigest()
       if expected!=actual:different.append(str(Path(*parts[1:])))
       else:matched+=1
       members.append({'installed_relative_path':str(Path(*parts[1:])),'bytes':member.size,'sha256':expected,'match':expected==actual})
     comparisons.append({'package':component['package'],'target':component['target'],'archive':component['archive_path'],'matching_regular_files':matched,'missing':missing,'different':different,'members':members})
    (P/'metadata/installed-archive-comparison.json').write_text(json.dumps(comparisons,indent=2)+'\n')
    assert all(r['matching_regular_files']>0 and not r['missing'] and not r['different'] for r in comparisons),[(r['package'],r['missing'][:5],r['different'][:5]) for r in comparisons]
    after_global=global_settings_hashes();(P/'metadata/global-settings-after.json').write_text(json.dumps(after_global,indent=2)+'\n');assert before_global==after_global,'global shell/Rustup settings changed during provisioning'
    paths={'RUSTUP_HOME':str(RUSTUP),'install_CARGO_HOME':str(CARGO),'rustup':str(proxy),'rustc':str(toolchain/'bin/rustc'),'cargo':str(toolchain/'bin/cargo'),'rustfmt':str(toolchain/'bin/rustfmt'),'cargo_fmt':str(toolchain/'bin/cargo-fmt'),'clippy_driver':str(toolchain/'bin/clippy-driver'),'cargo_clippy':str(toolchain/'bin/cargo-clippy'),'buf':str(bufexe),'toolchain_root':str(toolchain)}
    identities=[]
    for name,path in paths.items():
     f=Path(path)
     if f.is_file():identities.append({'name':name,'path':path,'resolved_path':str(f.resolve()),'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()})
    result={'status':'pass','completed_utc':stamp(),'scope':'fresh official pinned Rust/components/WASM and Buf installation only; existing macOS26.6.2/SDK27CLT provided baseline; no carrier, canonical contract, fresh OS or SDK qualification','native_or_wasm_compilation_executed':False,'observed_global_shell_and_rustup_settings_unchanged':before_global==after_global,'paths':paths,'identities':identities,'official_downloads':records,'installed_component_file_matches':[{'package':r['package'],'target':r['target'],'matching_files':r['matching_regular_files']} for r in comparisons],'next_build_environment':{'RUSTUP_HOME':str(RUSTUP),'RUSTUP_AUTO_INSTALL':'0','PATH_prefix':[str(toolchain/'bin'),str(CARGO/'bin'),str(bufdir)],'CARGO_HOME':'use separate architect-owned empty build Cargo home; install Cargo home contains only freshly installed proxies/config'}};(P/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'status':'pass','paths':paths,'component_matches':result['installed_component_file_matches']},indent=2))

def probe():
    runtime=ROOT/'.rdd/runtime/s6';runtime.mkdir(parents=True,exist_ok=True)
    result_path=runtime/'toolchain.json'
    if not result_path.exists():
        destination=runtime/'provision'
        subprocess.run([sys.executable,__file__,'--install',str(destination)],check=True,capture_output=True,timeout=1000)
        shutil.copyfile(destination/'result.json',result_path)
    result=json.loads(result_path.read_text());pins=json.loads(Path(__file__).with_name('tools.json').read_text());paths=result['paths']
    for record in pins['expected_identities']:
        assert hashlib.sha256(Path(paths[record['name']]).read_bytes()).hexdigest()==record['sha256'],record['name']
    work=Path(tempfile.mkdtemp(prefix='tool-smoke-',dir=runtime));code=work/'smoke.rs';code.write_text('fn main(){assert_eq!(2+2,4);println!("compiler smoke passed");}\n')
    compiler_env=os.environ.copy();compiler_env['DYLD_FALLBACK_LIBRARY_PATH']=str(Path(paths['toolchain_root'])/'lib')
    native=work/'native';subprocess.run([paths['rustc'],str(code),'-o',str(native)],check=True,capture_output=True,timeout=60,env=compiler_env)
    subprocess.run([str(native)],check=True,capture_output=True,timeout=10)
    subprocess.run([paths['rustc'],str(code),'--target','wasm32-unknown-unknown','-o',str(work/'smoke.wasm')],check=True,capture_output=True,timeout=60,env=compiler_env)
    subprocess.run([paths['buf'],'build','--as-file-descriptor-set','--output',str(work/'contracts.binpb')],cwd=ROOT,check=True,capture_output=True,timeout=30)
    observations={}
    for rid,version,key in [('R-RUST','1.99.0','rustc'),('R-CARGO','1.99.0','cargo'),('R-BUF','1.73.0','buf')]:
        observed=subprocess.run([paths[key],'--version'],check=True,capture_output=True,text=True,timeout=15);assert version in observed.stdout
        observations[rid]={'environment':'macos-reference','version':version,'observation':'Pinned archive identity rechecked; native/WASM compiler and actual descriptor smoke passed; '+paths[key]}
    assert sys.version_info[:3]==(3,14,7)
    observations['R-PYTHON']={'environment':'macos-reference','version':'3.14.7','observation':'Provided Python executed acquisition, hashing and assertion runner: '+sys.version}
    clis=acquire_clis(runtime/'clis')
    for name,rid,version in [('trunk','R-TRUNK','0.22.1'),('cargo-tauri','R-TAURI','2.12.4'),('wasm-bindgen','R-WASM-BINDGEN','0.2.129')]:
        run=subprocess.run([clis[name],'--version'],check=True,capture_output=True,text=True,timeout=15);assert version in run.stdout
        observations[rid]={'environment':'macos-reference','version':version,'observation':'Official archive and executable identities verified; actual executable invocation passed; joint mechanisms checked separately: '+run.stdout.strip()}
    print(json.dumps({'resources':observations,'scope':'fresh pinned compiler/Buf smoke and retained CLI identity; joint package proof is separate'}))
def acquire_clis(destination):
    import zipfile
    destination.mkdir(parents=True,exist_ok=True)
    pins=json.loads(Path(__file__).with_name('tools.json').read_text())
    assets=json.loads(Path(__file__).with_name('tool-acquisition.json').read_text())['official_prebuilt_tools'];found={}
    for asset in assets:
        name='trunk' if asset['name'].startswith('trunk') else 'cargo-tauri' if asset['name'].startswith('cargo-tauri') else 'wasm-bindgen'
        archive=destination/asset['name'];target=destination/name
        if not archive.exists():
            with urllib.request.urlopen(asset['url'],timeout=45) as response,archive.open('xb') as out:
                shutil.copyfileobj(response,out)
        assert hashlib.sha256(archive.read_bytes()).hexdigest()==asset['digest'].split(':')[1]
        expected=pins['existing_cli_identities'][name]
        if not target.exists():
            if archive.suffix=='.zip':
                with zipfile.ZipFile(archive) as z:
                    members=[m for m in z.namelist() if Path(m).name==name];assert len(members)==1;data=z.read(members[0])
            else:
                with tarfile.open(archive) as t:
                    members=[m for m in t.getmembers() if m.isfile() and Path(m.name).name==name];assert len(members)==1;data=t.extractfile(members[0]).read()
            target.write_bytes(data);target.chmod(0o755)
        assert hashlib.sha256(target.read_bytes()).hexdigest()==expected['sha256'];found[name]=str(target)
    return found

def build_environment():
    runtime=ROOT/'.rdd/runtime/s6';result=json.loads((runtime/'toolchain.json').read_text());paths=result['paths'];env=os.environ.copy()
    pins=json.loads(Path(__file__).with_name('tools.json').read_text())
    for record in pins['expected_identities']:
        assert hashlib.sha256(Path(paths[record['name']]).read_bytes()).hexdigest()==record['sha256'],record['name']
    for key in ['RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS','RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','RUSTDOCFLAGS','CARGO_ENCODED_RUSTDOCFLAGS']:
        env.pop(key,None)
    env.update(RUSTUP_HOME=paths['RUSTUP_HOME'],RUSTUP_AUTO_INSTALL='0',RUSTC=paths['rustc'],CARGO_HOME=str(runtime/'build-cargo-home'),CARGO_BUILD_JOBS='1',CARGO_INCREMENTAL='0',CARGO_PROFILE_DEV_DEBUG='0',CARGO_PROFILE_RELEASE_DEBUG='0',PYTHONDONTWRITEBYTECODE='1')
    clis=acquire_clis(runtime/'clis');env['DYLD_FALLBACK_LIBRARY_PATH']=str(Path(paths['toolchain_root'])/'lib');env['PATH']=os.pathsep.join([str(Path(paths['rustc']).parent),str(Path(paths['rustup']).parent),str(Path(paths['buf']).parent),str(runtime/'clis')])+os.pathsep+env['PATH']
    return env,paths,clis

if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--install':install(Path(sys.argv[2]).resolve())
    elif len(sys.argv)>2 and sys.argv[1]=='--exec':
        env,paths,_=build_environment();runtime=ROOT/'.rdd/runtime/s6';out=Path(tempfile.mkdtemp(prefix='qualified-launch-',dir=runtime))
        (out/'environment.json').write_text(json.dumps({'argv':sys.argv[2:],'paths':paths,'environment':{k:env[k] for k in ['PATH','RUSTC','RUSTUP_HOME','CARGO_HOME','DYLD_FALLBACK_LIBRARY_PATH']},'scope':'outer controller launch; frozen check argv never recursively mutates this checkout'},indent=2)+'\n')
        raise SystemExit(subprocess.call(sys.argv[2:],env=env,cwd=ROOT))
    elif len(sys.argv)==1:probe()
    else:raise SystemExit('usage: provision.py [--install OWNED_ROOT | --exec COMMAND ...]')
