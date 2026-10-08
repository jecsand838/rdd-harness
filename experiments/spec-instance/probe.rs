//! Generic account-private file lease/activation primitives, not Todo implementation.
use std::fs::{self, OpenOptions};
use std::io::{self, BufRead, BufReader, Read, Write};
use std::os::fd::AsRawFd;
use std::os::unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt, PermissionsExt};
use std::os::unix::process::ExitStatusExt;
use std::path::Path;
use std::process::{Child, ChildStdout, Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

// SDK 27.0 sys/fcntl.h, Darwin only.
const LOCK_EX: i32 = 2;
const LOCK_NB: i32 = 4;
unsafe extern "C" { fn flock(fd: i32, operation: i32) -> i32; }

fn line(message: &str) -> io::Result<()> {
    println!("{message}");
    io::stdout().flush()
}

fn create_private(path: &Path, bytes: &[u8]) -> io::Result<()> {
    let mut file = OpenOptions::new().write(true).create_new(true).mode(0o600).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()
}

fn child(root: &Path, nonce: &str) -> io::Result<()> {
    line("ready")?;
    io::stdin().read_exact(&mut [0_u8])?;
    let lease = OpenOptions::new().read(true).write(true).create(true).truncate(false)
        .mode(0o600).open(root.join("instance.lease"))?;
    // SAFETY: owned live descriptor; documented Darwin nonblocking exclusive operation.
    if unsafe { flock(lease.as_raw_fd(), LOCK_EX | LOCK_NB) } == 0 {
        // A marker for the point where the real application may initialize its database.
        create_private(&root.join(format!("owner-{nonce}")), b"lease-held-before-owner-marker\n")?;
        line("owner")?;
        let deadline = Instant::now() + Duration::from_secs(20);
        while Instant::now() < deadline {
            for entry in fs::read_dir(root)? {
                let path = entry?.path();
                let name = path.file_name().unwrap().to_string_lossy();
                if !name.starts_with("request-") || name.ends_with(".tmp") { continue; }
                let request_nonce = fs::read_to_string(&path)?;
                let ack = root.join(format!("ack-{request_nonce}"));
                if ack.exists() { continue; }
                // A simulated synchronous activation callback, not a GUI-focus claim.
                create_private(&root.join(format!("callback-{request_nonce}")), b"callback-finished\n")?;
                let temp = root.join(format!("ack-{request_nonce}.tmp"));
                create_private(&temp, request_nonce.as_bytes())?;
                fs::rename(temp, ack)?;
            }
            thread::sleep(Duration::from_millis(50));
        }
        // Keep the lock's owning descriptor alive throughout primary service.
        drop(lease);
        Err(io::Error::other("owner was not terminated by parent at the expected checkpoint"))
    } else {
        let error = io::Error::last_os_error();
        if error.kind() != io::ErrorKind::WouldBlock { return Err(error); }
        line("secondary")?;
        let temp = root.join(format!("request-{nonce}.tmp"));
        create_private(&temp, nonce.as_bytes())?;
        fs::rename(temp, root.join(format!("request-{nonce}")))?;
        let deadline = Instant::now() + Duration::from_secs(5);
        while Instant::now() < deadline {
            let ack = root.join(format!("ack-{nonce}"));
            if let Ok(value) = fs::read_to_string(ack) {
                assert_eq!(value, nonce, "acknowledgment nonce mismatch");
                assert_eq!(fs::read(root.join(format!("callback-{nonce}")))?, b"callback-finished\n");
                assert!(!root.join(format!("owner-{nonce}")).exists(), "secondary crossed owner boundary");
                return line(&format!("ack:{nonce}"));
            }
            thread::sleep(Duration::from_millis(10));
        }
        Err(io::Error::other("no activation acknowledgment; secondary must not open database"))
    }
}

struct Worker { process: Child, reader: BufReader<ChildStdout>, nonce: String }

impl Worker {
    fn spawn(root: &Path, nonce: &str) -> io::Result<Self> {
        let mut process = Command::new(std::env::current_exe()?).arg("--child").arg(root).arg(nonce)
            .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::inherit()).spawn()?;
        let reader = BufReader::new(process.stdout.take().unwrap());
        let mut worker = Self { process, reader, nonce: nonce.to_owned() };
        assert_eq!(worker.read_line()?, "ready");
        Ok(worker)
    }
    fn release(&mut self) -> io::Result<()> { self.process.stdin.as_mut().unwrap().write_all(b"g") }
    fn read_line(&mut self) -> io::Result<String> {
        let mut value = String::new();
        assert!(self.reader.read_line(&mut value)? > 0, "worker exited before expected observation");
        Ok(value.trim().to_owned())
    }
    fn finish_secondary(&mut self) -> io::Result<()> {
        assert_eq!(self.read_line()?, format!("ack:{}", self.nonce));
        assert!(self.process.wait()?.success());
        Ok(())
    }
    fn kill(&mut self) -> io::Result<()> {
        self.process.kill()?;
        assert_eq!(self.process.wait()?.signal(), Some(9));
        Ok(())
    }
}

fn private_dir(root: &Path) -> io::Result<()> { fs::DirBuilder::new().mode(0o700).create(root) }

fn run(root: &Path) -> io::Result<()> {
    private_dir(root)?;
    let collection = root.join("profile-a");
    private_dir(&collection)?;
    let mut workers = (0..8).map(|i| Worker::spawn(&collection, &format!("nonce-{i}"))).collect::<io::Result<Vec<_>>>()?;
    // Every process reaches the pipe barrier before any can claim the lease.
    for worker in &mut workers { worker.release()?; }
    let mut owner_index = None;
    for (index, worker) in workers.iter_mut().enumerate() {
        match worker.read_line()?.as_str() {
            "owner" => { assert!(owner_index.replace(index).is_none(), "two simultaneous owners"); }
            "secondary" => worker.finish_secondary()?,
            unexpected => panic!("unexpected worker role: {unexpected}"),
        }
    }
    let owner_index = owner_index.expect("no lease owner");
    let markers = fs::read_dir(&collection)?.filter_map(Result::ok)
        .filter(|e| e.file_name().to_string_lossy().starts_with("owner-")).count();
    assert_eq!(markers, 1);
    println!("PASS simultaneous-launch children=8 owners=1 secondaries=7 all-activation-acks=matched");
    let inode = fs::metadata(collection.join("instance.lease"))?.ino();

    let mut sequential = Worker::spawn(&collection, "nonce-sequential")?;
    sequential.release()?;
    assert_eq!(sequential.read_line()?, "secondary");
    sequential.finish_secondary()?;
    println!("PASS sequential-launch no-owner-marker ack-after-simulated-activation=true");

    for entry in fs::read_dir(&collection)? {
        assert_eq!(entry?.metadata()?.permissions().mode() & 0o777, 0o600);
    }
    assert_eq!(fs::metadata(&collection)?.permissions().mode() & 0o777, 0o700);
    println!("PASS private-files mode=0600 directory=0700 no-network-endpoint=true");

    workers[owner_index].kill()?;
    let mut takeover = Worker::spawn(&collection, "nonce-takeover")?;
    takeover.release()?;
    assert_eq!(takeover.read_line()?, "owner");
    assert_eq!(fs::metadata(collection.join("instance.lease"))?.ino(), inode);
    println!("PASS abrupt-owner-termination signal=SIGKILL new-owner-acquired=true lease-inode=preserved");

    let other = root.join("profile-b");
    private_dir(&other)?;
    let mut independent = Worker::spawn(&other, "nonce-independent")?;
    independent.release()?;
    assert_eq!(independent.read_line()?, "owner");
    println!("PASS independent-data-location independent-lease=true");
    independent.kill()?;
    takeover.kill()?;
    // No Todo, window, foreign-user, or database semantics are asserted here.
    println!("PASS instance-qualification cases=5 application-acceptance=false");
    Ok(())
}

fn main() -> io::Result<()> {
    assert_eq!(std::env::consts::OS, "macos");
    let arguments: Vec<String> = std::env::args().collect();
    if arguments.get(1).map(String::as_str) == Some("--child") {
        return child(Path::new(&arguments[2]), &arguments[3]);
    }
    run(Path::new(arguments.get(1).expect("usage: instance-probe FRESH_DIRECTORY")))
}
