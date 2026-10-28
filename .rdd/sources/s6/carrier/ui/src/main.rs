use leptos::prelude::*;
use prost::Message;
use rdd_contracts::qualification::v1::{EchoRequest,EchoResponse,echo_response};
use wasm_bindgen::prelude::*;
#[wasm_bindgen]
extern "C" {
 #[wasm_bindgen(catch,js_namespace = ["window", "__TAURI__", "core"], js_name = invoke)]
 async fn invoke_checked(command: &str, args: JsValue) -> Result<JsValue, JsValue>;
}
async fn call(command:&str, bytes:Vec<u8>)->Result<String,String>{
 let args=js_sys::Object::new();let values=js_sys::Array::new();
 for b in bytes {values.push(&JsValue::from_f64(b as f64));}
 js_sys::Reflect::set(&args,&JsValue::from_str("request"),&values).map_err(|_|"argument mapping".to_string())?;
 let raw=invoke_checked(command,args.into()).await.map_err(|e|format!("rejected: {:?}",e))?;
 let array=js_sys::Array::from(&raw);let bytes:Vec<u8>=array.iter().map(|x|x.as_f64().unwrap_or(0.0) as u8).collect();
 let response=EchoResponse::decode(bytes.as_slice()).map_err(|e|e.to_string())?;
 match response.outcome {Some(echo_response::Outcome::Value(v))=>Ok(v),Some(echo_response::Outcome::Failure(f))=>Err(f.code),None=>Err("missing outcome".into())}
}

async fn canonical_call()->Result<String,String>{
 use todo_contracts::todo::native_api::v1 as api;
 let mut request=api::InvokeRequest{action:Some(api::invoke_request::Action::ReadHelp(Default::default()))};
 if let Some(api::invoke_request::Action::ReadHelp(ref mut value))=request.action{value.session="qualification-session".into();}
 let args=js_sys::Object::new();let values=js_sys::Array::new();for b in request.encode_to_vec(){values.push(&JsValue::from_f64(b as f64));}
 js_sys::Reflect::set(&args,&JsValue::from_str("request"),&values).map_err(|_|"argument mapping".to_string())?;
 let raw=invoke_checked("todo_invoke",args.into()).await.map_err(|_|"canonical invoke rejected".to_string())?;
 let bytes:Vec<u8>=js_sys::Array::from(&raw).iter().map(|x|x.as_f64().unwrap_or(0.0) as u8).collect();
 let response=api::InvokeResponse::decode(bytes.as_slice()).map_err(|_|"canonical response decode".to_string())?;
 match response.outcome{
  Some(api::invoke_response::Outcome::Success(reply))=>match reply.operation{
   Some(api::reply::Operation::ReadHelp(response))=>match response.outcome{
    Some(todo_contracts::todo::workspace::v1::read_help_response::Outcome::Success(help))=>Ok(help.plain_text),_=>Err("canonical help failure".into())},_=>Err("canonical wrong operation".into())},_=>Err("canonical entry failure".into())
 }
}

fn main(){
 let candidate=todo_contracts::todo::native_api::v1::InvokeRequest{action:Some(todo_contracts::todo::native_api::v1::invoke_request::Action::ReadHelp(Default::default()))};
 assert_eq!(todo_contracts::todo::native_api::v1::InvokeRequest::decode(candidate.encode_to_vec().as_slice()).unwrap(),candidate);

 leptos::mount::mount_to_body(||{
 let (canonical,set_canonical)=signal("CANONICAL INVOKE PENDING".to_string());
 wasm_bindgen_futures::spawn_local(async move{set_canonical.set(canonical_call().await.unwrap_or_else(|e|e));});
 let (result,set_result)=signal("Loading persisted probe value...".to_string());
 wasm_bindgen_futures::spawn_local(async move {set_result.set(match call("probe_api",EchoRequest{value:String::new()}.encode_to_vec()).await{Ok(v)=>format!("READY last={v}"),Err(e)=>e});});
 view!{<main><h1>"RDD Qualification Carrier"</h1><p>"Disposable mechanism probe; no Todo behavior."</p>
 <p id="canonical" role="status">{move || canonical.get()}</p>
 <button id="persist" on:click=move |_| {set_result.set("PENDING".into());wasm_bindgen_futures::spawn_local(async move {set_result.set(match call("probe_api",EchoRequest{value:"probe-20261028-R5".into()}.encode_to_vec()).await{Ok(v)=>format!("COMMITTED {v}"),Err(e)=>e});});}>"Persist generated API probe"</button>
 <button id="malformed" on:click=move |_| {wasm_bindgen_futures::spawn_local(async move {set_result.set(match call("probe_api",vec![255]).await {Ok(v)=>format!("UNEXPECTED {v}"),Err(e)=>format!("MALFORMED {e}")});});}>"Reject malformed request"</button>
 <button id="denied" on:click=move |_| {wasm_bindgen_futures::spawn_local(async move {set_result.set(match call("forbidden_probe",vec![]).await {Ok(v)=>format!("UNEXPECTED {v}"),Err(e)=>format!("DENIED {e}")});});}>"Reject undeclared permission"</button>
 <p id="result" role="status" aria-live="polite">{move || result.get()}</p></main>}
 });
}
