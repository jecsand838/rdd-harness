use prost::Message;
use rdd_contracts::todo::v1::*;

#[tauri::command]
async fn probe(payload: Vec<u8>) -> Result<Vec<u8>, String> {
    let request = QueryRequest::decode(payload.as_slice()).map_err(|e| e.to_string())?;
    Ok(ProbeProvider.query(request).await?.encode_to_vec())
}

struct ProbeProvider;
impl ApplicationService for ProbeProvider {
    type Error = String;
    async fn query(&self, request: QueryRequest) -> Result<QueryResponse, String> {
    let result = async {
        let path = std::env::var("RDD_PROBE_DB").map_err(|e| e.to_string())?;
        let search = request.query.ok_or("missing query")?.search;
        let db = turso::Builder::new_local(&path).build().await.map_err(|e| e.to_string())?;
        let mut conn = db.connect().map_err(|e| e.to_string())?;
        conn.execute("PRAGMA synchronous=FULL", ()).await.map_err(|e| e.to_string())?;
        conn.execute("PRAGMA fullfsync=ON", ()).await.map_err(|e| e.to_string())?;
        conn.execute("CREATE TABLE IF NOT EXISTS probe (id INTEGER PRIMARY KEY, value TEXT NOT NULL)", ()).await.map_err(|e| e.to_string())?;
        let tx = conn.transaction().await.map_err(|e| e.to_string())?;
        tx.execute("INSERT OR REPLACE INTO probe VALUES (?1,?2)", (1, search.as_str())).await.map_err(|e| e.to_string())?;
        tx.commit().await.map_err(|e| e.to_string())?;
        let mut rows = conn.query("SELECT value FROM probe WHERE id=?1", [1]).await.map_err(|e| e.to_string())?;
        let value: String = rows.next().await.map_err(|e| e.to_string())?.ok_or("missing row")?.get(0).map_err(|e| e.to_string())?;
        if value != search { return Err("stored probe value mismatch".into()); }
        Ok::<_,String>(QueryResponse { result: Some(query_response::Result::Value(QueryResult { matching_count: 1, collection_count: 1, generation: 1, ..Default::default() })) })
    }.await;
    result
    }
    async fn get_task(&self, _: GetTaskRequest) -> Result<GetTaskResponse, String> { Err("outside qualification scope".into()) }
    async fn mutate(&self, _: MutateRequest) -> Result<MutateResponse, String> { Err("outside qualification scope".into()) }
    async fn reconcile(&self, _: ReconcileRequest) -> Result<ReconcileResponse, String> { Err("outside qualification scope".into()) }
    async fn confirm_delete(&self, _: ConfirmDeleteRequest) -> Result<ConfirmDeleteResponse, String> { Err("outside qualification scope".into()) }
    async fn export(&self, _: ExportRequest) -> Result<ExportResponse, String> { Err("outside qualification scope".into()) }
    async fn prepare_restore(&self, _: PrepareRestoreRequest) -> Result<PrepareRestoreResponse, String> { Err("outside qualification scope".into()) }
    async fn restore(&self, _: RestoreRequest) -> Result<RestoreResponse, String> { Err("outside qualification scope".into()) }
    async fn discard_restore(&self, _: DiscardRestoreRequest) -> Result<DiscardRestoreResponse, String> { Err("outside qualification scope".into()) }
    async fn lifecycle(&self, _: LifecycleRequest) -> Result<LifecycleResponse, String> { Err("outside qualification scope".into()) }
}

#[tauri::command]
fn finish_probe(app: tauri::AppHandle, outcome: String) -> Result<(), String> {
    let activation = (|| {
        let window = app.get_webview_window("main").ok_or("missing native window".to_string())?;
        window.show().map_err(|e| e.to_string())?;
        window.set_focus().map_err(|e| e.to_string())?;
        Ok::<_, String>(())
    })();
    let outcome = match activation {
        Ok(()) => outcome,
        Err(error) => format!("FAIL native window activation: {error}"),
    };
    let report = std::env::var("RDD_PROBE_REPORT").map_err(|e| e.to_string())?;
    std::fs::write(report, &outcome).map_err(|e| e.to_string())?;
    println!("{outcome}");
    let exit = if outcome.starts_with("PASS ") { 0 } else { 1 };
    let hold = std::env::var("RDD_PROBE_HOLD_SECONDS").ok().and_then(|n| n.parse::<u64>().ok()).unwrap_or(0);
    tauri::async_runtime::spawn(async move {
        tokio::time::sleep(std::time::Duration::from_secs(hold)).await;
        app.exit(exit);
    });
    Ok(())
}

#[tauri::command]
fn forbidden_probe() -> String { "BROKEN_DENIAL".into() }

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![probe, finish_probe, forbidden_probe])
        .run(tauri::generate_context!())
        .expect("dependency probe runtime");
}
use tauri::Manager;
