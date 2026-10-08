use leptos::prelude::*;
use wasm_bindgen::prelude::*;
use wasm_bindgen_futures::{JsFuture, spawn_local};
use prost::Message;
use rdd_contracts::todo::v1::{QueryRequest, QueryResponse, Query, query_response};

#[wasm_bindgen]
unsafe extern "C" {
    #[wasm_bindgen(js_namespace = ["window", "__TAURI__", "core"], js_name = invoke)]
    fn invoke(command: &str, args: &JsValue) -> js_sys::Promise;
}

#[wasm_bindgen(start)]
pub fn start() {
    let (state, set_state) = signal("pending".to_string());
    leptos::mount::mount_to_body(move || view! { <main><h1>"Dependency qualification"</h1><p id="outcome" role="status">{move || state.get()}</p></main> });
    spawn_local(async move {
        let denied = JsFuture::from(invoke("forbidden_probe", &js_sys::Object::new().into())).await;
        if denied.is_ok() {
            let args = js_sys::Object::new();
            js_sys::Reflect::set(&args, &"outcome".into(), &"FAIL forbidden command allowed".into()).unwrap();
            let _ = JsFuture::from(invoke("finish_probe", &args.into())).await;
            return;
        }
        let request = QueryRequest { query: Some(Query { search: "packaged Rust WASM invoke".into(), ..Default::default() }), ..Default::default() };
        let args = js_sys::Object::new();
        let bytes = js_sys::Array::new();
        for byte in request.encode_to_vec() { bytes.push(&JsValue::from(byte)); }
        js_sys::Reflect::set(&args, &"payload".into(), &bytes.into()).unwrap();
        let result = JsFuture::from(invoke("probe", &args.into())).await;
        match result {
            Ok(value) => {
                let bytes: Vec<u8> = js_sys::Array::from(&value).iter().map(|v| v.as_f64().unwrap() as u8).collect();
                let response = QueryResponse::decode(bytes.as_slice()).unwrap();
                let text = match response.result {
                    Some(query_response::Result::Value(value)) if value.matching_count == 1 && value.generation == 1 => "PASS packaged Rust WASM invoke + generated QueryRequest/QueryResponse + Turso commit".to_string(),
                    _ => "FAIL protobuf response".to_string(),
                };
                set_state.set(text.clone());
                let args = js_sys::Object::new();
                js_sys::Reflect::set(&args, &"outcome".into(), &text.into()).unwrap();
                let _ = JsFuture::from(invoke("finish_probe", &args.into())).await;
            }
            Err(error) => {
                let args = js_sys::Object::new();
                js_sys::Reflect::set(&args, &"outcome".into(), &format!("FAIL: {error:?}").into()).unwrap();
                let _ = JsFuture::from(invoke("finish_probe", &args.into())).await;
            }
        }
    });
}
