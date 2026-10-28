use prost::Message;
use rdd_contracts::qualification::v1::{echo_response,EchoRequest,EchoResponse,Failure,ProbeService};
use std::{future::Future,pin::Pin,sync::{Arc,atomic::{AtomicBool,Ordering}},task::Poll};
use turso::{Builder,Connection};
use turso::transaction::TransactionBehavior;
type AnyError=Box<dyn std::error::Error+Send+Sync>;
struct Probe {path:String}

type Dispatch=Arc<dyn Fn(todo_contracts::todo::native_api::v1::InvokeRequest)->Pin<Box<dyn Future<Output=todo_contracts::todo::native_api::v1::InvokeResponse>+Send>>+Send+Sync>;
#[derive(Clone)] struct CandidateEntry{dispatch:Dispatch}
impl todo_contracts::todo::native_api::v1::NativeApiService for CandidateEntry{
 fn invoke(&self,request:todo_contracts::todo::native_api::v1::InvokeRequest)->impl Future<Output=todo_contracts::todo::native_api::v1::InvokeResponse>+Send{(self.dispatch)(request)}
}
#[derive(Clone)] struct WorkspaceProbe;
impl todo_contracts::todo::workspace::v1::WorkspaceService for WorkspaceProbe{
 async fn open(&self,request:todo_contracts::todo::workspace::v1::OpenRequest)->todo_contracts::todo::workspace::v1::OpenResponse{let _=&request;todo_contracts::todo::workspace::v1::OpenResponse{outcome:Some(todo_contracts::todo::workspace::v1::open_response::Outcome::Failure(todo_contracts::todo::workspace::v1::Failure{code:4,safe_message:"qualification-only".into(),..Default::default()}))}}
 async fn update_draft(&self,request:todo_contracts::todo::workspace::v1::UpdateDraftRequest)->todo_contracts::todo::workspace::v1::UpdateDraftResponse{let _=&request;todo_contracts::todo::workspace::v1::UpdateDraftResponse{outcome:Some(todo_contracts::todo::workspace::v1::update_draft_response::Outcome::Failure(todo_contracts::todo::workspace::v1::Failure{code:4,safe_message:"qualification-only".into(),..Default::default()}))}}
 async fn navigate(&self,request:todo_contracts::todo::workspace::v1::NavigateRequest)->todo_contracts::todo::workspace::v1::NavigateResponse{let _=&request;todo_contracts::todo::workspace::v1::NavigateResponse{outcome:Some(todo_contracts::todo::workspace::v1::navigate_response::Outcome::Failure(todo_contracts::todo::workspace::v1::Failure{code:4,safe_message:"qualification-only".into(),..Default::default()}))}}
 async fn decide_intent(&self,request:todo_contracts::todo::workspace::v1::DecideIntentRequest)->todo_contracts::todo::workspace::v1::DecideIntentResponse{let _=&request;todo_contracts::todo::workspace::v1::DecideIntentResponse{outcome:Some(todo_contracts::todo::workspace::v1::decide_intent_response::Outcome::Failure(todo_contracts::todo::workspace::v1::Failure{code:4,safe_message:"qualification-only".into(),..Default::default()}))}}
 async fn submit(&self,request:todo_contracts::todo::workspace::v1::SubmitRequest)->todo_contracts::todo::workspace::v1::SubmitResponse{let _=&request;todo_contracts::todo::workspace::v1::SubmitResponse{outcome:Some(todo_contracts::todo::workspace::v1::submit_response::Outcome::Failure(todo_contracts::todo::workspace::v1::Failure{code:4,safe_message:"qualification-only".into(),..Default::default()}))}}
 async fn read_state(&self,request:todo_contracts::todo::workspace::v1::ReadStateRequest)->todo_contracts::todo::workspace::v1::ReadStateResponse{let _=&request;todo_contracts::todo::workspace::v1::ReadStateResponse{outcome:Some(todo_contracts::todo::workspace::v1::read_state_response::Outcome::Failure(todo_contracts::todo::workspace::v1::Failure{code:4,safe_message:"qualification-only".into(),..Default::default()}))}}
 async fn evaluate_view(&self,request:todo_contracts::todo::workspace::v1::EvaluateViewRequest)->todo_contracts::todo::workspace::v1::EvaluateViewResponse{let _=&request;todo_contracts::todo::workspace::v1::EvaluateViewResponse{outcome:Some(todo_contracts::todo::workspace::v1::evaluate_view_response::Outcome::Failure(todo_contracts::todo::workspace::v1::Failure{code:4,safe_message:"qualification-only".into(),..Default::default()}))}}
 async fn transfer(&self,request:todo_contracts::todo::workspace::v1::TransferRequest)->todo_contracts::todo::workspace::v1::TransferResponse{let _=&request;todo_contracts::todo::workspace::v1::TransferResponse{outcome:Some(todo_contracts::todo::workspace::v1::transfer_response::Outcome::Failure(todo_contracts::todo::workspace::v1::Failure{code:4,safe_message:"qualification-only".into(),..Default::default()}))}}
 async fn read_help(&self,request:todo_contracts::todo::workspace::v1::ReadHelpRequest)->todo_contracts::todo::workspace::v1::ReadHelpResponse{let _=&request;todo_contracts::todo::workspace::v1::ReadHelpResponse{outcome:Some(if request.session=="qualification-session"{todo_contracts::todo::workspace::v1::read_help_response::Outcome::Success(todo_contracts::todo::workspace::v1::Help{application_version:"0.1.0".into(),plain_text:"CANONICAL INVOKE READY".into()})}else{todo_contracts::todo::workspace::v1::read_help_response::Outcome::Failure(todo_contracts::todo::workspace::v1::Failure{code:4,safe_message:"qualification-only".into(),..Default::default()})})}}
}
#[derive(Clone)] struct DiagnosticsProbe;
impl todo_contracts::todo::diagnostics::v1::DiagnosticsService for DiagnosticsProbe{
 async fn emit(&self,_request:todo_contracts::todo::diagnostics::v1::EmitRequest)->todo_contracts::todo::diagnostics::v1::EmitResponse{Default::default()}
}
fn wire<D,W>(identity:&'static str,builder:tauri::Builder<tauri::Wry>,diagnostics:D,workspace:W)->Result<tauri::Builder<tauri::Wry>,todo_contracts::todo::native_api::v1::Failure>
where D:todo_contracts::todo::diagnostics::v1::DiagnosticsService+Clone+'static,W:todo_contracts::todo::workspace::v1::WorkspaceService+Clone+'static{
 use todo_contracts::todo::native_api::v1 as api;
 if identity.is_empty(){return Err(api::Failure{code:api::ErrorCode::Unavailable.into(),correlation_id:"qualification-init".into()})}
 let entry=CandidateEntry{dispatch:Arc::new(move |request|{let workspace=workspace.clone();let diagnostics=diagnostics.clone();Box::pin(async move{
  let _retained_diagnostics=diagnostics;
  let operation=match request.action{
   Some(api::invoke_request::Action::Open(r))=>api::reply::Operation::Open(workspace.open(r).await),
   Some(api::invoke_request::Action::UpdateDraft(r))=>api::reply::Operation::UpdateDraft(workspace.update_draft(r).await),
   Some(api::invoke_request::Action::Navigate(r))=>api::reply::Operation::Navigate(workspace.navigate(r).await),
   Some(api::invoke_request::Action::DecideIntent(r))=>api::reply::Operation::DecideIntent(workspace.decide_intent(r).await),
   Some(api::invoke_request::Action::Submit(r))=>api::reply::Operation::Submit(workspace.submit(r).await),
   Some(api::invoke_request::Action::ReadState(r))=>api::reply::Operation::ReadState(workspace.read_state(r).await),
   Some(api::invoke_request::Action::EvaluateView(r))=>api::reply::Operation::EvaluateView(workspace.evaluate_view(r).await),
   Some(api::invoke_request::Action::Transfer(r))=>api::reply::Operation::Transfer(workspace.transfer(r).await),
   Some(api::invoke_request::Action::ReadHelp(r))=>api::reply::Operation::ReadHelp(workspace.read_help(r).await),
   None=>return api::InvokeResponse{outcome:Some(api::invoke_response::Outcome::Failure(api::Failure{code:api::ErrorCode::Malformed.into(),correlation_id:"qualification-shape".into()}))}
  };
  api::InvokeResponse{outcome:Some(api::invoke_response::Outcome::Success(api::Reply{operation:Some(operation)}))}
 })})};
 Ok(builder.manage(entry).invoke_handler(tauri::generate_handler![probe_api,forbidden_probe,todo_invoke]))
}
#[tauri::command]
async fn todo_invoke(request:Vec<u8>,state:tauri::State<'_,CandidateEntry>)->Result<Vec<u8>,String>{
 use todo_contracts::todo::native_api::v1::{InvokeRequest,NativeApiService};
 let request=InvokeRequest::decode(request.as_slice()).map_err(|_|"entry_decode".to_string())?;
 Ok(state.invoke(request).await.encode_to_vec())
}

async fn read(conn:&Connection)->Result<String,AnyError>{
 let mut rows=conn.query("SELECT value FROM probe WHERE id=1",()).await?;
 Ok(match rows.next().await?{Some(row)=>row.get::<String>(0)?,None=>"empty".into()})
}
async fn open(path:&str)->Result<(turso::Database,Connection),AnyError>{
 if let Some(parent)=std::path::Path::new(path).parent(){std::fs::create_dir_all(parent)?;}
 let db=Builder::new_local(path).build().await?;let conn=db.connect()?;
 conn.execute("CREATE TABLE IF NOT EXISTS probe(id INTEGER PRIMARY KEY,value TEXT NOT NULL)",()).await?;
 Ok((db,conn))
}
impl ProbeService for Probe {
 async fn echo(&self,request:EchoRequest)->EchoResponse{
  let result:Result<String,AnyError>=async {
   let (_db,mut conn)=open(&self.path).await?;
   if !request.value.is_empty(){
    let tx=conn.transaction_with_behavior(TransactionBehavior::Immediate).await?;
    tx.execute("DELETE FROM probe",()).await?;
    tx.execute("INSERT INTO probe VALUES(1,?1)",(request.value,)).await?;
    tx.commit().await?;
   }
   read(&conn).await
  }.await;
  EchoResponse{outcome:Some(match result{Ok(v)=>echo_response::Outcome::Value(v),Err(_)=>echo_response::Outcome::Failure(Failure{code:"storage_failure".into()})})}
 }
}
#[tauri::command]
async fn probe_api(request:Vec<u8>,state:tauri::State<'_,Probe>)->Result<Vec<u8>,String>{
 if request.len()>1024{return Err("entry_size".into());}
 let request=EchoRequest::decode(request.as_slice()).map_err(|_|"entry_decode".to_string())?;
 Ok(state.echo(request).await.encode_to_vec())
}
#[tauri::command]
fn forbidden_probe()->String{"must_be_denied".into()}
async fn storage_suite(path:&str)->Result<(),AnyError>{
 let provider=Probe{path:path.into()};
 let response=provider.echo(EchoRequest{value:"native-baseline".into()}).await;
 assert!(matches!(response.outcome,Some(echo_response::Outcome::Value(ref s)) if s=="native-baseline"));
 let (_db,mut conn)=open(path).await?;
 assert_eq!(read(&conn).await?,"native-baseline");
 let mut pragmas=Vec::new();
 for pragma in ["PRAGMA journal_mode","PRAGMA synchronous"]{
  let mut rows=conn.query(pragma,()).await?;
  let result=if let Some(row)=rows.next().await?{format!("{:?}",row.get_value(0)?)}else{"no_row".into()};pragmas.push((pragma,result));
 }
 {let tx=conn.transaction_with_behavior(TransactionBehavior::Immediate).await?;tx.execute("UPDATE probe SET value='rollback'",()).await?;tx.rollback().await?;}
 assert_eq!(read(&conn).await?,"native-baseline");
 {let tx=conn.transaction().await?;tx.execute("UPDATE probe SET value='drop'",()).await?;drop(tx);}
 assert_eq!(read(&conn).await?,"native-baseline");
 {let tx=conn.transaction().await?;assert!(tx.execute("INSERT INTO missing_table VALUES(1)",()).await.is_err());tx.rollback().await?;}
 assert_eq!(read(&conn).await?,"native-baseline");
 let checkpoint=Arc::new(AtomicBool::new(false));
 {let checkpoint=checkpoint.clone();let mut pending=Box::pin(async {
   let tx=conn.transaction().await?;tx.execute("UPDATE probe SET value='cancelled'",()).await?;checkpoint.store(true,Ordering::SeqCst);std::future::pending::<()>().await;tx.commit().await?;Ok::<(),AnyError>(())
  });
  std::future::poll_fn(|cx|match Pin::new(&mut pending).poll(cx){Poll::Pending if checkpoint.load(Ordering::SeqCst)=>Poll::Ready(()),Poll::Pending=>Poll::Pending,Poll::Ready(_)=>panic!("suspended transaction completed")}).await;
  drop(pending);
 }
 assert!(checkpoint.load(Ordering::SeqCst));assert_eq!(read(&conn).await?,"native-baseline");
 assert!(EchoRequest::decode(&[255u8][..]).is_err());
 let normalizer=icu_normalizer::ComposingNormalizer::new_nfc();assert_eq!(normalizer.normalize("e\u{301}"),"é");
 let mapper=icu_casemap::CaseMapper::new();assert_eq!(mapper.fold_string("Straße"),"strasse");
 println!("{{\"storage\":\"pass\",\"reopen\":true,\"explicit_rollback\":true,\"drop_next_access\":true,\"cancel_after_write\":true,\"error_then_rollback\":true,\"malformed_decode\":true,\"unicode_smoke\":true,\"pragma_observations\":{:?}}}",pragmas);
 Ok(())
}
fn data_path()->String{
 std::env::var("RDD_QUALIFICATION_DATA").unwrap_or_else(|_|{
  let base=std::env::var("HOME").expect("home");format!("{base}/Library/Application Support/com.rdd.qualification.r20261028/probe.db")
 })
}
fn main(){
 let candidate=todo_contracts::todo::native_api::v1::InvokeRequest{action:Some(todo_contracts::todo::native_api::v1::invoke_request::Action::ReadHelp(Default::default()))};
 assert_eq!(todo_contracts::todo::native_api::v1::InvokeRequest::decode(candidate.encode_to_vec().as_slice()).unwrap(),candidate);

 let args:Vec<String>=std::env::args().collect();
 if args.get(1).map(String::as_str)==Some("--storage-probe") {tauri::async_runtime::block_on(storage_suite(args.get(2).expect("database path"))).expect("storage suite");return;}
 if args.get(1).map(String::as_str)==Some("--read-probe") {let value=tauri::async_runtime::block_on(async {let (_db,conn)=open(args.get(2).expect("database path")).await?;read(&conn).await}).expect("read probe");println!("{value}");return;}
 if args.get(1).map(String::as_str)==Some("--kill-before-commit") {tauri::async_runtime::block_on(async {let (_db,mut conn)=open(args.get(2).expect("database path")).await.unwrap();let tx=conn.transaction().await.unwrap();tx.execute("UPDATE probe SET value='uncommitted-kill'",()).await.unwrap();println!("CHECKPOINT uncommitted-write");std::process::abort();});return;}
 wire("com.rdd.qualification.r20261028",tauri::Builder::default().manage(Probe{path:data_path()}),DiagnosticsProbe,WorkspaceProbe).expect("typed registration").run(tauri::generate_context!()).expect("qualification desktop runtime");
}
