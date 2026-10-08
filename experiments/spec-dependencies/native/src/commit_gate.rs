//! Test-only native I/O delegation. The barrier runs inside commit's WAL sync.
use std::{io::Write, sync::{Arc, atomic::{AtomicBool, Ordering}}};
use turso_core::{Buffer, Completion, File, IO, OpenFlags, PlatformIO, Result};
use turso_core::io::{FileSyncType, clock::{Clock, MonotonicInstant, WallClockInstant}};

pub struct CommitGateIO { native: PlatformIO, pub armed: Arc<AtomicBool> }
impl CommitGateIO {
    pub fn new() -> Result<Self> { Ok(Self { native: PlatformIO::new()?, armed: Arc::new(AtomicBool::new(false)) }) }
}
impl Clock for CommitGateIO {
    fn current_time_monotonic(&self) -> MonotonicInstant { self.native.current_time_monotonic() }
    fn current_time_wall_clock(&self) -> WallClockInstant { self.native.current_time_wall_clock() }
}
impl IO for CommitGateIO {
    fn open_file(&self, path: &str, flags: OpenFlags, direct: bool) -> Result<Arc<dyn File>> {
        Ok(Arc::new(CommitGateFile { native: self.native.open_file(path, flags, direct)?, is_wal: path.ends_with("-wal"), armed: self.armed.clone() }))
    }
    fn remove_file(&self, path: &str) -> Result<()> { self.native.remove_file(path) }
    fn step(&self) -> Result<()> { self.native.step() }
}
struct CommitGateFile { native: Arc<dyn File>, is_wal: bool, armed: Arc<AtomicBool> }
impl File for CommitGateFile {
    fn lock_file(&self, exclusive: bool) -> Result<()> { self.native.lock_file(exclusive) }
    fn unlock_file(&self) -> Result<()> { self.native.unlock_file() }
    fn pread(&self, pos: u64, completion: Completion) -> Result<Completion> { self.native.pread(pos, completion) }
    fn pwrite(&self, pos: u64, buffer: Arc<Buffer>, completion: Completion) -> Result<Completion> { self.native.pwrite(pos, buffer, completion) }
    fn pwritev(&self, pos: u64, buffers: Vec<Arc<Buffer>>, completion: Completion) -> Result<Completion> { self.native.pwritev(pos, buffers, completion) }
    fn sync(&self, completion: Completion, sync_type: FileSyncType) -> Result<Completion> {
        if self.is_wal && self.armed.swap(false, Ordering::SeqCst) {
            println!("checkpoint=during_commit_wal_sync");
            std::io::stdout().flush().expect("write independent cutpoint marker");
            // This child is forcibly terminated by the independent parent. The real
            // sync is delegated if the test barrier were released; no engine is mocked.
            loop { std::thread::park(); }
        }
        self.native.sync(completion, sync_type)
    }
    fn size(&self) -> Result<u64> { self.native.size() }
    fn truncate(&self, len: u64, completion: Completion) -> Result<Completion> { self.native.truncate(len, completion) }
}
