//! Disposable Darwin filesystem qualification. No Todo/application behavior.
use std::ffi::CString;
use std::fs::{self, File, OpenOptions};
use std::io::{self, BufRead, BufReader, Read, Write};
use std::os::fd::AsRawFd;
use std::os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt, symlink};
use std::os::unix::process::ExitStatusExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

// SDK 27.0 sys/stdio.h and sys/fcntl.h; qualified only for aarch64-apple-darwin.
const RENAME_EXCL: u32 = 0x0000_0004;
const F_FULLFSYNC: i32 = 51;
unsafe extern "C" {
    fn renameatx_np(fromfd: i32, from: *const i8, tofd: i32, to: *const i8, flags: u32) -> i32;
    fn fcntl(fd: i32, command: i32, ...) -> i32;
}

fn payload(label: &str, size: usize) -> Vec<u8> {
    format!("{{\"fixture\":\"{label}\",\"padding\":\"{}\"}}\n", "x".repeat(size)).into_bytes()
}

fn fresh_file(path: &Path, bytes: &[u8]) -> io::Result<()> {
    let mut file = OpenOptions::new().create_new(true).write(true).mode(0o600).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    // SAFETY: live owned file descriptor and documented no-argument Darwin command.
    if unsafe { fcntl(file.as_raw_fd(), F_FULLFSYNC) } != 0 {
        return Err(io::Error::last_os_error());
    }
    assert_eq!(fs::read(path)?, bytes);
    assert_eq!(fs::metadata(path)?.permissions().mode() & 0o777, 0o600);
    Ok(())
}

fn publish(directory: &File, source: &str, destination: &str, flags: u32) -> io::Result<()> {
    let source = CString::new(source).unwrap();
    let destination = CString::new(destination).unwrap();
    // SAFETY: valid directory FD and stable NUL-terminated relative leaf names.
    let result = unsafe {
        renameatx_np(directory.as_raw_fd(), source.as_ptr(), directory.as_raw_fd(), destination.as_ptr(), flags)
    };
    if result == 0 { Ok(()) } else { Err(io::Error::last_os_error()) }
}

fn checkpoint(label: &str) -> io::Result<()> {
    println!("checkpoint:{label}");
    io::stdout().flush()?;
    let mut byte = [0_u8];
    // Parent holds stdin open, then kills this worker at the observed checkpoint.
    io::stdin().read_exact(&mut byte)?;
    Err(io::Error::other("child checkpoint unexpectedly resumed"))
}

fn child(directory: &Path, cut: &str) -> io::Result<()> {
    let parent = File::open(directory)?;
    fresh_file(&directory.join("candidate.tmp"), &payload("new", 131_075))?;
    fresh_file(&directory.join("publication.journal"), b"fixture-publication-pending\n")?;
    parent.sync_all()?;
    if cut == "before-publication" { return checkpoint(cut); }
    publish(&parent, "candidate.tmp", "backup.json", 0)?;
    parent.sync_all()?;
    checkpoint(cut)
}

fn observe_crash(directory: &Path, cut: &str) -> io::Result<()> {
    fs::create_dir(directory)?;
    fresh_file(&directory.join("backup.json"), &payload("old", 65_537))?;
    let mut worker = Command::new(std::env::current_exe()?)
        .arg("--child").arg(directory).arg(cut)
        .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::inherit()).spawn()?;
    let mut checkpoint_line = String::new();
    let observed = BufReader::new(worker.stdout.take().unwrap()).read_line(&mut checkpoint_line)?;
    assert!(observed > 0, "child exited before controlled checkpoint");
    assert_eq!(checkpoint_line.trim(), format!("checkpoint:{cut}"));
    worker.kill()?;
    let status = worker.wait()?;
    assert_eq!(status.signal(), Some(9));
    // Journal deliberately has no acknowledged result. Reconcile by actual bytes.
    assert_eq!(fs::read(directory.join("publication.journal"))?, b"fixture-publication-pending\n");
    let actual = fs::read(directory.join("backup.json"))?;
    let before = cut == "before-publication";
    let expected = if before { payload("old", 65_537) } else { payload("new", 131_075) };
    assert_eq!(actual, expected, "partial or wrong publication result");
    assert_eq!(directory.join("candidate.tmp").exists(), before);
    println!("PASS cut={cut} signal=SIGKILL journal=pending reconciled={} exact_bytes={}",
        if before { "old" } else { "new" }, actual.len());
    Ok(())
}

fn run(directory: &Path) -> io::Result<()> {
    fs::create_dir(directory)?;
    let parent = File::open(directory)?;
    let old = payload("old", 65_537);
    let new = payload("new", 131_075);
    fresh_file(&directory.join("backup.json"), &old)?;
    fresh_file(&directory.join("candidate.tmp"), &new)?;
    let error = publish(&parent, "candidate.tmp", "backup.json", RENAME_EXCL).unwrap_err();
    assert_eq!(error.kind(), io::ErrorKind::AlreadyExists);
    assert_eq!(fs::read(directory.join("backup.json"))?, old);
    assert_eq!(fs::read(directory.join("candidate.tmp"))?, new);
    println!("PASS no-clobber existing-destination=unchanged candidate=unchanged error=EEXIST");

    publish(&parent, "candidate.tmp", "backup.json", 0)?;
    parent.sync_all()?;
    assert_eq!(fs::read(directory.join("backup.json"))?, new);
    assert!(!directory.join("candidate.tmp").exists());
    println!("PASS confirmed-replacement exact-new-bytes file-sync=ok fullfsync=ok directory-sync=ok");

    fresh_file(&directory.join("new.tmp"), &new)?;
    publish(&parent, "new.tmp", "new-backup.json", RENAME_EXCL)?;
    parent.sync_all()?;
    assert_eq!(fs::read(directory.join("new-backup.json"))?, new);
    println!("PASS no-clobber absent-destination=complete-new-file");

    let managed = directory.join("managed.fixture");
    fresh_file(&managed, b"managed-data-fixture\n")?;
    let hard_alias = directory.join("hard-alias.fixture");
    fs::hard_link(&managed, &hard_alias)?;
    let symlink_alias = directory.join("symlink-alias.fixture");
    symlink(&managed, &symlink_alias)?;
    let identity = |path: &Path| -> io::Result<(u64, u64)> {
        let metadata = fs::metadata(path)?;
        Ok((metadata.dev(), metadata.ino()))
    };
    assert_eq!(identity(&managed)?, identity(&hard_alias)?);
    assert_eq!(identity(&managed)?, identity(&symlink_alias)?);
    assert_eq!(fs::canonicalize(&managed)?, fs::canonicalize(&symlink_alias)?);
    assert_eq!(fs::read(&managed)?, b"managed-data-fixture\n");
    println!("PASS alias-detection hardlink=device-inode symlink=canonical-path-and-device-inode");

    for repeat in 0..3 {
        for cut in ["before-publication", "after-publication-before-ack"] {
            observe_crash(&directory.join(format!("cut-{repeat}-{cut}")), cut)?;
        }
    }
    println!("PASS filesystem-qualification cases=10 crash-cases=6 production-acceptance=false");
    Ok(())
}

fn main() -> io::Result<()> {
    assert_eq!(std::env::consts::OS, "macos");
    let args: Vec<String> = std::env::args().collect();
    if args.get(1).map(String::as_str) == Some("--child") {
        return child(Path::new(&args[2]), &args[3]);
    }
    let directory = PathBuf::from(args.get(1).expect("usage: filesystem-probe FRESH_DIRECTORY"));
    run(&directory)
}
