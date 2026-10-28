//! Disposable synthetic mechanisms only. No Todo data model or product implementation.
use std::{collections::HashMap,fs::{self,File,OpenOptions},io::{self,Read,Write},os::{fd::AsRawFd,unix::{ffi::OsStrExt,fs::{MetadataExt,OpenOptionsExt,PermissionsExt},net::{UnixListener,UnixStream}}},path::{Path,PathBuf},time::{Duration,Instant}};
use sha2::{Digest,Sha256};
use serde_json::{json,Value};
use objc2::{MainThreadMarker,MainThreadOnly,rc::Retained,sel};
use objc2_app_kit::*;
use objc2_foundation::{NSString,NSURL,NSRect,NSPoint,NSSize,NSTimer};
use block2::RcBlock;
type Result<T> = std::result::Result<T,Box<dyn std::error::Error>>;
const OLD:&[u8]=b"{\"synthetic\":\"old\"}\n";
const NEW:&[u8]=b"{\"synthetic\":\"new-complete\",\"payload\":\"non-Todo\"}\n";
fn emit(v:Value){println!("{v}");io::stdout().flush().unwrap();}
fn sha(bytes:&[u8])->String{format!("{:x}",Sha256::digest(bytes))}
fn fail<T>(s:&str)->Result<T>{Err(io::Error::other(s).into())}
fn random_handle()->String{let mut b=[0u8;16];unsafe{libc::arc4random_buf(b.as_mut_ptr().cast(),b.len());}b.iter().map(|x|format!("{x:02x}")).collect()}
fn canonical_selected(p:&Path)->Result<PathBuf>{if p.exists(){Ok(p.canonicalize()?)}else{Ok(p.parent().ok_or("parent")?.canonicalize()?.join(p.file_name().ok_or("filename")?))}}
fn identity(p:&Path)->Result<Option<Value>>{if !p.exists(){return Ok(None)}let m=p.metadata()?;if !m.is_file(){return fail("not_regular_file")}Ok(Some(json!({"dev":m.dev(),"ino":m.ino(),"sha256":sha(&fs::read(p)?)})))}
#[derive(Clone)]struct Grant{path:PathBuf,expected:Option<Value>,write:bool}
struct Grants{items:HashMap<String,Grant>,protected:Vec<PathBuf>,root:PathBuf}
impl Grants{
 fn new(root:PathBuf,protected:Vec<PathBuf>)->Self{Self{items:HashMap::new(),protected,root}}
 fn select(&mut self,path:&Path,write:bool)->Result<String>{let path=canonical_selected(path)?;if !path.starts_with(&self.root){return fail("outside_owned_probe_root")}let id=identity(&path)?;for p in &self.protected{if canonical_selected(p)?==path || (id.is_some() && identity(p)?==id){return fail("protected")}}
  // Compare device/inode as well as bytes, so any managed-file hardlink rejects.
  if let Some(ref selected)=id{for p in &self.protected{if let Some(managed)=identity(p)?{if selected["dev"]==managed["dev"]&&selected["ino"]==managed["ino"]{return fail("protected_identity")}}}}
  let handle=random_handle();self.items.insert(handle.clone(),Grant{path,expected:id,write});Ok(handle)
 }
 fn get(&self,h:&str)->Result<&Grant>{self.items.get(h).ok_or_else(||io::Error::other("invalid_handle").into())}
 fn read(&self,h:&str)->Result<Vec<u8>>{let g=self.get(h)?;if g.write{return fail("wrong_mode")}if identity(&g.path)?!=g.expected{return fail("changed_selection")}Ok(fs::read(&g.path)?)}
 fn cancel(&mut self,h:&str){self.items.remove(h);}
}
fn checkpoint(stage:&str,pause:&str){emit(json!({"checkpoint":stage,"pid":std::process::id()}));if pause==stage{loop{std::thread::sleep(Duration::from_millis(50));}}}
fn supported(parent:&File)->Result<Value>{let mut s:libc::statfs=unsafe{std::mem::zeroed()};if unsafe{libc::fstatfs(parent.as_raw_fd(),&mut s)}!=0{return Err(io::Error::last_os_error().into())}let name=unsafe{std::ffi::CStr::from_ptr(s.f_fstypename.as_ptr())}.to_string_lossy().into_owned();let local=s.f_flags & libc::MNT_LOCAL as u32!=0;let readonly=s.f_flags & libc::MNT_RDONLY as u32!=0;if name!="apfs"||!local||readonly{return fail("unsupported_storage")}Ok(json!({"fstype":name,"local":local,"readonly":readonly,"fsid":format!("{:?}",s.f_fsid)}))}
fn publication(g:&Grant,root:&Path,confirmed:bool,pause:&str)->Result<Value>{
 if !g.write{return fail("wrong_mode")}
 if g.expected.is_some()&&!confirmed{return fail("replacement_not_confirmed")}
 if identity(&g.path)?!=g.expected{return fail("destination_changed")}
 let parent=OpenOptions::new().read(true).custom_flags(libc::O_DIRECTORY|libc::O_CLOEXEC|libc::O_NOFOLLOW).open(g.path.parent().ok_or("parent")?)?;
 let storage=supported(&parent)?;
 if pause=="unsupported-fixture"{return fail("injected_unsupported_before_modification")}
 let handle=random_handle();let temp_name=format!(".rdd-qual-{handle}.tmp");let temp=g.path.parent().unwrap().join(&temp_name);let journal=root.join("publication-intent.json");
 let intent=json!({"destination":g.path,"temp":temp,"old":g.expected,"new_sha256":sha(NEW),"new_bytes":NEW.len(),"scope":"synthetic process-failure only"});
 let mut jf=OpenOptions::new().write(true).create_new(true).mode(0o600).open(&journal)?;jf.write_all(intent.to_string().as_bytes())?;jf.sync_all()?;
 checkpoint("intent",pause);
 let ctemp=std::ffi::CString::new(temp_name)?;
 let fd=unsafe{libc::openat(parent.as_raw_fd(),ctemp.as_ptr(),libc::O_WRONLY|libc::O_CREAT|libc::O_EXCL|libc::O_CLOEXEC|libc::O_NOFOLLOW,0o600)};if fd<0{return Err(io::Error::last_os_error().into())}
 use std::os::fd::FromRawFd;let mut file=unsafe{File::from_raw_fd(fd)};
 file.write_all(&NEW[..NEW.len()/2])?;checkpoint("partial",pause);file.write_all(&NEW[NEW.len()/2..])?;
 if pause=="digest-mismatch"{return fail("injected_complete_digest_mismatch")}
 file.sync_all()?;if sha(&fs::read(&temp)?)!=sha(NEW){return fail("digest_mismatch")}
 checkpoint("ready",pause);
 if identity(&g.path)?!=g.expected{return fail("destination_changed_before_publication")}
 let cname=std::ffi::CString::new(g.path.file_name().unwrap().as_bytes())?;
 let flags=if confirmed{0}else{libc::RENAME_EXCL};
 let rc=unsafe{libc::renameatx_np(parent.as_raw_fd(),ctemp.as_ptr(),parent.as_raw_fd(),cname.as_ptr(),flags)};
 if rc!=0{return Err(io::Error::last_os_error().into())}
 checkpoint("published",pause);
 let dir_sync=unsafe{libc::fsync(parent.as_raw_fd())};let dir_errno=if dir_sync==0{None}else{Some(io::Error::last_os_error().raw_os_error())};
 if identity(&g.path)?.as_ref().map(|v|&v["sha256"])!=Some(&json!(sha(NEW))){return fail("postpublication_unknown")}
 Ok(json!({"published":true,"storage":storage,"sha256":sha(NEW),"directory_fsync":dir_sync,"directory_fsync_errno":dir_errno,"destination":g.path}))
}
fn resolve(root:&Path)->Result<Value>{let intent:Value=serde_json::from_slice(&fs::read(root.join("publication-intent.json"))?)?;let dest=canonical_selected(&PathBuf::from(intent["destination"].as_str().ok_or("destination")?))?;if !dest.starts_with(root){return fail("recovery_outside_owned_probe_root")}let actual=identity(&dest)?;let state=if actual.as_ref().map(|v|&v["sha256"])==Some(&intent["new_sha256"]){"new_complete"}else if actual==intent["old"].as_object().map(|_|intent["old"].clone()){if actual.is_none(){"old_absent"}else{"old_complete"}}else{"unresolved"};
 let temp=PathBuf::from(intent["temp"].as_str().ok_or("temp")?);if fs::symlink_metadata(&temp).map(|m|m.file_type().is_symlink()).unwrap_or(false){return fail("recovery_temporary_symlink")}let safe=temp.parent()==dest.parent()&&temp.file_name().and_then(|s|s.to_str()).map(|s|s.starts_with(".rdd-qual-")&&s.ends_with(".tmp")).unwrap_or(false);if !safe{return fail("invalid_owned_temporary")}
 if state=="unresolved"{return fail("unknown_destination_preserved")}
 let temp_before=temp.exists();if temp_before{fs::remove_file(&temp)?;}let journal=root.join("publication-intent.json");let history=root.join(format!("publication-resolved-{}.json",random_handle()));fs::rename(&journal,&history)?;
 Ok(json!({"reconciled":state,"actual":actual,"owned_temp_removed":temp_before,"destination_preserved":true}))
}
fn file_suite(root:&Path)->Result<()>{fs::create_dir_all(root)?;let managed=root.join("managed.db");fs::write(&managed,b"protected-synthetic")?;let adjacent=root.join("adjacent.txt");fs::write(&adjacent,b"unrelated")?;let selected=root.join("selected.json");fs::write(&selected,OLD)?;let mut grants=Grants::new(root.to_path_buf(),vec![managed.clone()]);let before=fs::read(&managed)?;
 for (name,p) in [("direct",managed.clone()),("symlink",root.join("alias.db")),("hardlink",root.join("hard.db"))]{if name=="symlink"{std::os::unix::fs::symlink(&managed,&p)?}if name=="hardlink"{fs::hard_link(&managed,&p)?}assert!(grants.select(&p,true).is_err());emit(json!({"case":format!("protected_{name}"),"passed":true}));}
 let h=grants.select(&selected,false)?;assert_eq!(grants.read(&h)?,OLD);assert!(grants.read(adjacent.to_str().unwrap()).is_err());assert!(grants.read("foreign-handle").is_err());grants.cancel(&h);assert!(grants.read(&h).is_err());emit(json!({"case":"selected_read_adjacent_foreign_cancelled","passed":true}));
 let h=grants.select(&selected,true)?;let g=grants.get(&h)?.clone();assert!(grants.read(&h).is_err());assert!(publication(&g,root,false,"").is_err());assert_eq!(fs::read(&selected)?,OLD);assert!(publication(&g,root,true,"unsupported-fixture").is_err());assert_eq!(fs::read(&selected)?,OLD);assert!(!root.join("publication-intent.json").exists());
 fs::write(&selected,b"changed")?;assert!(publication(&g,root,true,"").is_err());assert_eq!(fs::read(&selected)?,b"changed");assert_eq!(fs::read(&managed)?,before);assert_eq!(fs::read(&adjacent)?,b"unrelated");emit(json!({"case":"mode_consent_changed_unsupported_preservation","passed":true}));
 // Actual Darwin no-replace primitive rejects a newly occupied destination.
 let temp=root.join("noreplace.tmp");fs::write(&temp,NEW)?;let a=std::ffi::CString::new(temp.as_os_str().as_bytes())?;let b=std::ffi::CString::new(selected.as_os_str().as_bytes())?;let rc=unsafe{libc::renameatx_np(libc::AT_FDCWD,a.as_ptr(),libc::AT_FDCWD,b.as_ptr(),libc::RENAME_EXCL)};assert_eq!(rc,-1);assert_eq!(io::Error::last_os_error().raw_os_error(),Some(libc::EEXIST));assert_eq!(fs::read(&selected)?,b"changed");emit(json!({"case":"actual_no_replace_eexist","passed":true}));Ok(())}
fn scope_suite(root:&Path)->Result<()>{
 let roles=["database","recovery","migration","diagnostics"];let mut protected=Vec::new();
 for role in roles{let path=root.join(format!("{role}.managed"));fs::write(&path,format!("synthetic-{role}"))?;protected.push(path);}
 let mut grants=Grants::new(root.to_path_buf(),protected.clone());
 for (index,path) in protected.iter().enumerate(){
  for mode in [false,true]{assert!(grants.select(path,mode).is_err());}
  let symlink=root.join(format!("role-{index}-symlink"));std::os::unix::fs::symlink(path,&symlink)?;assert!(grants.select(&symlink,true).is_err());
  let hardlink=root.join(format!("role-{index}-hardlink"));fs::hard_link(path,&hardlink)?;assert!(grants.select(&hardlink,true).is_err());
  emit(json!({"case":"managed_role_aliases","role":roles[index],"passed":true}));
 }
 let outside=root.parent().ok_or("parent")?.join("outside-scope-control.json");fs::write(&outside,OLD)?;
 for mode in [false,true]{assert!(grants.select(&outside,mode).is_err());}
 let escape=root.join("outward-symlink.json");std::os::unix::fs::symlink(&outside,&escape)?;
 for mode in [false,true]{assert!(grants.select(&escape,mode).is_err());}
 assert_eq!(fs::read(&outside)?,OLD);emit(json!({"case":"owned_boundary_read_write_and_outward_symlink","passed":true,"outside_unchanged":true}));Ok(())
}
struct Instance{_lock:File,listener:UnixListener}
fn admission(root:&Path)->Result<Option<Instance>>{fs::create_dir_all(root)?;fs::set_permissions(root,fs::Permissions::from_mode(0o700))?;std::env::set_current_dir(root)?;let lock=OpenOptions::new().create(true).read(true).write(true).mode(0o600).custom_flags(libc::O_CLOEXEC|libc::O_NOFOLLOW).open("instance.lock")?;
 if unsafe{libc::flock(lock.as_raw_fd(),libc::LOCK_EX|libc::LOCK_NB)}!=0{let err=io::Error::last_os_error();if err.raw_os_error()!=Some(libc::EWOULDBLOCK){return Err(err.into())}let deadline=Instant::now()+Duration::from_secs(2);loop{match UnixStream::connect("instance.sock"){Ok(mut s)=>{s.write_all(b"ACTIVATE\n")?;emit(json!({"role":"secondary","pid":std::process::id(),"database_opened":false,"activation_sent":true}));return Ok(None)},Err(e) if Instant::now()<deadline=>{let _=e;std::thread::sleep(Duration::from_millis(10));},Err(e)=>return Err(e.into())}}}
 if Path::new("instance.sock").exists(){fs::remove_file("instance.sock")?;}let listener=UnixListener::bind("instance.sock")?;fs::set_permissions("instance.sock",fs::Permissions::from_mode(0o600))?;listener.set_nonblocking(true)?;
 // Synthetic surrogate for opening storage: must occur only after lock/socket admission.
 let mut mark=OpenOptions::new().append(true).create(true).mode(0o600).open("database-open-ledger")?;writeln!(mark,"{}",std::process::id())?;mark.sync_all()?;emit(json!({"role":"primary","pid":std::process::id(),"database_opened":true,"admission_precedes_database":true}));Ok(Some(Instance{_lock:lock,listener}))}
fn activation(i:&Instance)->Result<bool>{match i.listener.accept(){Ok((mut stream,_))=>{stream.set_nonblocking(true)?;let deadline=Instant::now()+Duration::from_millis(500);let mut message=Vec::new();loop{let mut chunk=[0u8;16];match stream.read(&mut chunk){Ok(0)=>return fail("activation_incomplete"),Ok(n)=>{message.extend_from_slice(&chunk[..n]);if !b"ACTIVATE\n".starts_with(&message){return fail("invalid_activation_message")}if message==b"ACTIVATE\n"{return Ok(true)}},Err(e) if e.kind()==io::ErrorKind::WouldBlock=>{},Err(e)=>return Err(io::Error::other(format!("activation_read: {e}")).into())}if Instant::now()>=deadline{return fail("activation_frame_timeout")}std::thread::sleep(Duration::from_millis(5));}},Err(e) if e.kind()==io::ErrorKind::WouldBlock=>Ok(false),Err(e)=>Err(io::Error::other(format!("activation_accept: {e}")).into())}}
fn application(mtm:MainThreadMarker)->Retained<NSApplication>{let app=NSApplication::sharedApplication(mtm);app.setActivationPolicy(NSApplicationActivationPolicy::Regular);let menu=NSMenu::new(mtm);let top=NSMenuItem::new(mtm);let submenu=NSMenu::new(mtm);unsafe{submenu.addItemWithTitle_action_keyEquivalent(&NSString::from_str("Quit RDD Native Mechanisms"),Some(sel!(terminate:)),&NSString::from_str("q"));}top.setSubmenu(Some(&submenu));menu.addItem(&top);app.setMainMenu(Some(&menu));app}
fn window(mtm:MainThreadMarker)->(Retained<NSWindow>,Retained<NSTextField>){let window=unsafe{NSWindow::initWithContentRect_styleMask_backing_defer(NSWindow::alloc(mtm),NSRect::new(NSPoint::new(80.,100.),NSSize::new(640.,240.)),NSWindowStyleMask::Titled|NSWindowStyleMask::Closable|NSWindowStyleMask::Miniaturizable,NSBackingStoreType::Buffered,false)};window.setTitle(&NSString::from_str("RDD Native Mechanisms"));let field=NSTextField::initWithFrame(NSTextField::alloc(mtm),NSRect::new(NSPoint::new(25.,110.),NSSize::new(570.,40.)));field.setStringValue(&NSString::from_str("synthetic-draft-retained"));field.setEditable(true);window.contentView().unwrap().addSubview(&field);window.makeKeyAndOrderFront(None);(window,field)}
fn gui_instance(root:&Path)->Result<()>{let Some(i)=admission(root)?else{return Ok(())};let mtm=MainThreadMarker::new().ok_or("main_thread")?;let app=application(mtm);let (window,field)=window(mtm);let app2=app.clone();let w=window.clone();let f=field.clone();let block=RcBlock::new(move|_:std::ptr::NonNull<NSTimer>|{if activation(&i).unwrap(){w.makeKeyAndOrderFront(None);#[allow(deprecated)]app2.activateIgnoringOtherApps(true);emit(json!({"event":"activated","draft":f.stringValue().to_string(),"window_visible":w.isVisible(),"pid":std::process::id()}));}});let _timer=unsafe{NSTimer::scheduledTimerWithTimeInterval_repeats_block(0.05,true,&block)};#[allow(deprecated)]app.activateIgnoringOtherApps(true);emit(json!({"event":"gui_ready","draft":field.stringValue().to_string()}));app.run();Ok(())}
fn dialog(root:&Path,mode:&str)->Result<()>{let mtm=MainThreadMarker::new().ok_or("main_thread")?;let app=application(mtm);let (window,_field)=window(mtm);let panel:Retained<NSSavePanel>=if mode.starts_with("open"){let p=NSOpenPanel::openPanel(mtm);p.setCanChooseFiles(true);p.setCanChooseDirectories(false);p.setAllowsMultipleSelection(false);p.into_super()}else{NSSavePanel::savePanel(mtm)};panel.setTitle(Some(&NSString::from_str(&format!("Qualification {mode}"))));panel.setDirectoryURL(Some(&NSURL::fileURLWithPath_isDirectory(&NSString::from_str(root.to_str().unwrap()),true)));panel.setNameFieldStringValue(&NSString::from_str("selected.json"));panel.setCanCreateDirectories(false);panel.setMessage(Some(&NSString::from_str("Synthetic unencrypted qualification data; owned fixtures only.")));let a=app.clone();let p=panel.clone();let r=root.to_path_buf();let mode=mode.to_string();let block=RcBlock::new(move|response:NSModalResponse|{p.orderOut(None);let output:Result<Value>=(||{if response!=NSModalResponseOK{return Ok(json!({"dialog":mode,"response":response,"cancelled":true,"grant_issued":false}))}let url=p.URL().ok_or("selection_url")?;if !url.isFileURL(){return fail("non_file_url")}let path=PathBuf::from(unsafe{std::ffi::CStr::from_ptr(url.fileSystemRepresentation().as_ptr())}.to_str()?);let mut grants=Grants::new(r.clone(),vec![r.join("managed.db")]);let h=grants.select(&path,!mode.starts_with("open"))?;let g=grants.get(&h)?.clone();if mode.starts_with("open"){let bytes=grants.read(&h)?;Ok(json!({"dialog":mode,"response":response,"selected":path,"selected_sha256":sha(&bytes),"grant_issued":true,"adjacent_denied":grants.read("adjacent.json").is_err()}))}else{let result=publication(&g,&r,true,"")?;Ok(json!({"dialog":mode,"response":response,"grant_issued":true,"publication":result}))}})();match output{Ok(v)=>emit(v),Err(e)=>emit(json!({"dialog_error":e.to_string()}))};unsafe{a.terminate(None);}});#[allow(deprecated)]app.activateIgnoringOtherApps(true);panel.beginSheetModalForWindow_completionHandler(&window,&block);emit(json!({"event":"dialog_ready","pid":std::process::id()}));app.run();Ok(())}
fn main()->Result<()>{let args:Vec<String>=std::env::args().collect();let mode=args.get(1).ok_or("mode")?;let root=PathBuf::from(args.get(2).ok_or("owned_root")?).canonicalize()?;match mode.as_str(){
 "--file-suite"=>file_suite(&root)?,
 "--scope-suite"=>scope_suite(&root)?,
 "--publish"=>{let mut grants=Grants::new(root.clone(),vec![root.join("managed.db")]);let h=grants.select(&root.join("selected.json"),true)?;emit(publication(grants.get(&h)?,&root,true,args.get(3).map(String::as_str).unwrap_or(""))?);},
 "--resolve"=>emit(resolve(&root)?),
 "--instance-headless"=>{if let Some(i)=admission(&root)?{let until=Instant::now()+Duration::from_millis(args.get(3).ok_or("lifetime_ms")?.parse()?);while Instant::now()<until{if activation(&i)?{emit(json!({"event":"activated_headless"}));}std::thread::sleep(Duration::from_millis(10));}}},
 "--instance-gui"=>gui_instance(&root)?,
 "--dialog"=>dialog(&root,args.get(3).ok_or("dialog_mode")?)?,
 _=>return fail("unknown_mode")};Ok(())}
