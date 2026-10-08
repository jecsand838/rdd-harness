use caseless::Caseless;
use std::{error::Error, io::Write, path::Path, time::Duration};
use turso::{Builder, Connection, transaction::TransactionBehavior};
use unicode_normalization::UnicodeNormalization;
mod commit_gate;

#[derive(Debug, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct SyntheticBackup { value: String }

async fn count(conn: &Connection) -> Result<i64, Box<dyn Error>> {
    let mut rows = conn.query("SELECT count(*) FROM probe", ()).await?;
    Ok(rows.next().await?.ok_or("missing count")?.get(0)?)
}

async fn scalar(conn: &Connection, sql: &str) -> Result<i64, Box<dyn Error>> {
    let mut rows = conn.query(sql, ()).await?;
    Ok(rows.next().await?.ok_or("missing pragma")?.get(0)?)
}

fn key(text: &str) -> String { text.chars().nfc().default_case_fold().collect() }

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<String> = std::env::args().collect();
    let mode = args.get(1).map(String::as_str).unwrap_or("normal");
    let path = args.get(2).ok_or("supply database path")?;
    let gate = std::sync::Arc::new(commit_gate::CommitGateIO::new()?);
    let builder = Builder::new_local(path);
    let db = if mode == "during_commit_wal_sync" { builder.with_io_impl(gate.clone()).build().await? } else { builder.build().await? };
    let mut conn = db.connect()?;
    conn.execute("PRAGMA synchronous=FULL", ()).await?;
    conn.execute("PRAGMA fullfsync=ON", ()).await?;
    assert_eq!(scalar(&conn, "PRAGMA synchronous").await?, 2);
    assert_eq!(scalar(&conn, "PRAGMA fullfsync").await?, 1);
    conn.execute("CREATE TABLE IF NOT EXISTS probe (id INTEGER PRIMARY KEY, value TEXT NOT NULL)", ()).await?;
    if mode == "check" {
        println!("count={}", count(&conn).await?);
        return Ok(());
    }
    if mode == "before_commit" || mode == "after_ack" || mode == "during_commit_wal_sync" {
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate).await?;
        tx.execute("INSERT INTO probe VALUES (?1, ?2)", (1, "synthetic acknowledged value")).await?;
        if mode == "after_ack" { tx.commit().await?; }
        else if mode == "during_commit_wal_sync" {
            gate.armed.store(true, std::sync::atomic::Ordering::SeqCst);
            tx.commit().await?;
            panic!("commit gate was not reached");
        }
        println!("checkpoint={mode}");
        std::io::stdout().flush()?;
        loop { tokio::time::sleep(Duration::from_secs(1)).await; }
    }
    conn.execute("DELETE FROM probe", ()).await?;
    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate).await?;
    tx.execute("INSERT INTO probe VALUES (?1, ?2)", (1, "committed Ω")).await?;
    tx.commit().await?;
    assert_eq!(count(&conn).await?, 1);
    let tx = conn.transaction().await?;
    tx.execute("INSERT INTO probe VALUES (?1, ?2)", (2, "explicit rollback")).await?;
    tx.rollback().await?;
    assert_eq!(count(&conn).await?, 1);
    {
        let tx = conn.transaction().await?;
        tx.execute("INSERT INTO probe VALUES (?1, ?2)", (3, "drop rollback")).await?;
    }
    assert_eq!(count(&conn).await?, 1);
    let tx = conn.transaction().await?;
    tx.execute("INSERT INTO probe VALUES (?1, ?2)", (4, "failed later statement")).await?;
    assert!(tx.execute("INSERT INTO probe VALUES (?1, ?2)", (1, "duplicate key")).await.is_err());
    tx.rollback().await?;
    assert_eq!(count(&conn).await?, 1);
    drop(conn); drop(db);
    let reopened = Builder::new_local(path).build().await?;
    let conn = reopened.connect()?;
    assert_eq!(count(&conn).await?, 1);
    let mut rows = conn.query("SELECT value FROM probe WHERE id=?1", [1]).await?;
    let value: String = rows.next().await?.ok_or("missing committed row")?.get(0)?;
    assert_eq!(value, "committed Ω");
    assert_eq!(unicode_normalization::UNICODE_VERSION, (16,0,0));
    assert_eq!(caseless::UNICODE_VERSION, (16,0,0));
    assert_eq!(key("Straße"), key("STRASSE"));
    assert_eq!(key("café"), key("cafe\u{301}"));
    assert_ne!(key("café"), key("cafe"));
    assert!(key("Σςσ").contains(&key("σσσ")));
    assert_eq!(key("İ"), "i\u{307}");
    assert!(!key("anything").contains(&key("%_.*")));
    assert!(chrono::NaiveDate::from_ymd_opt(1, 1, 1).is_some());
    assert!(chrono::NaiveDate::from_ymd_opt(9999, 12, 31).is_some());
    assert!(chrono::NaiveDate::from_ymd_opt(2025, 2, 29).is_none());
    let _ = chrono::Utc::now().timestamp_nanos_opt().ok_or("timestamp overflow")?;
    let _ = chrono::Local::now().date_naive();
    let mut random = [0u8; 16]; getrandom::fill(&mut random)?;
    let identity: String = random.iter().map(|b| format!("{b:02x}")).collect();
    assert_eq!(identity.len(), 32);
    use sha2::Digest;
    let digest = sha2::Sha256::digest(b"abc");
    let digest_hex: String = digest.iter().map(|b| format!("{b:02x}")).collect();
    assert_eq!(digest_hex, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    let synthetic = SyntheticBackup { value: "synthetic Ω".into() };
    let bytes = serde_json::to_vec(&synthetic)?;
    assert_eq!(serde_json::from_slice::<SyntheticBackup>(&bytes)?, synthetic);
    assert!(serde_json::from_str::<SyntheticBackup>("{\"value\":\"one\",\"value\":\"two\"}").is_err());
    assert!(serde_json::from_str::<SyntheticBackup>("{\"value\":\"one\",\"unexpected\":0}").is_err());
    let _native_atomic_api = libc::renameatx_np;
    assert_ne!(libc::RENAME_EXCL, 0);
    let parent = Path::new(path).parent().ok_or("missing parent")?;
    let old = parent.join("backup.json");
    let tmp = parent.join("backup.tmp");
    std::fs::write(&old, b"old-complete")?;
    let mut file = std::fs::OpenOptions::new().create_new(true).write(true).open(&tmp)?;
    file.write_all(b"new-complete")?; file.sync_all()?; drop(file);
    std::fs::rename(&tmp, &old)?;
    std::fs::File::open(parent)?.sync_all()?;
    assert_eq!(std::fs::read(&old)?, b"new-complete");
    println!("PASS transaction commit/reopen, explicit rollback, drop rollback, constraint-error rollback");
    println!("PASS synchronous=2 fullfsync=1, Unicode16 NFC+default-fold fixtures, local replacement+directory sync");
    println!("PASS pinned calendar/random/SHA256/strict-JSON APIs; native renameatx_np binding available");
    Ok(())
}
