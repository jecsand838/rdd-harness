"""Bounded cleanup of observed native TUI descendants, independent of process groups.

macOS is qualified through libproc on the current host. The combined identity
flavor is from Apple's XNU bsd/sys/proc_info_private.h (PROC_PIDT_BSDINFOWITHUNIQID,
private selector); the signal signature is in the public SDK libproc.h.
https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/proc_info_private.h
https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/proc_info.c
No PID/group signal fallback is safe. Other hosts fail preflight until qualified.
Polling observes ancestry; this does not contain unobserved daemon descendants.
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
import errno
import os
import signal
import sys
import time

from .common import RddError


class _BsdInfo(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        'flags', 'status', 'xstatus', 'pid', 'ppid', 'uid', 'gid', 'ruid',
        'rgid', 'svuid', 'svgid', 'reserved')] + [
        ('comm', ctypes.c_char * 16), ('name', ctypes.c_char * 32)] + [
        (name, ctypes.c_uint32) for name in (
            'nfiles', 'pgid', 'jobc', 'tdev', 'tpgid')] + [
        ('nice', ctypes.c_int32), ('start_sec', ctypes.c_uint64),
        ('start_usec', ctypes.c_uint64)]


class _UniqueInfo(ctypes.Structure):
    _fields_ = [('uuid', ctypes.c_uint8 * 16), ('unique_id', ctypes.c_uint64),
        ('parent_unique_id', ctypes.c_uint64), ('version', ctypes.c_int32),
        ('original_parent_version', ctypes.c_int32), ('reserved2', ctypes.c_uint64),
        ('reserved3', ctypes.c_uint64)]


class _BsdUniqueInfo(ctypes.Structure):
    _fields_ = [('bsd', _BsdInfo), ('unique', _UniqueInfo)]


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    ppid: int
    pgid: int
    birth: tuple[int, int]
    unique_id: int
    parent_unique_id: int
    version: int
    status: int = 2

    @property
    def key(self):
        return self.pid, self.birth, self.unique_id

    @property
    def running(self):
        return self.status != 5  # SZOMB from the macOS public sys/proc.h.


class ProcessTable:
    """Qualified macOS identity reads and kernel-validated, exact-process signals."""
    def __init__(self):
        self.lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
        self.lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int,
            ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        self.lib.proc_pidinfo.restype = ctypes.c_int
        self.lib.proc_listpids.argtypes = [ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_void_p, ctypes.c_int]
        self.lib.proc_listpids.restype = ctypes.c_int
        self.lib.proc_signal_with_audittoken.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.lib.proc_signal_with_audittoken.restype = ctypes.c_int

    @classmethod
    def preflight(cls):
        """Read-only host qualification; invoke before creating workflow run state."""
        if sys.platform != 'darwin':
            raise RddError('Owned native TUI cleanup is qualified on macOS only', 'environment')
        try:
            table = cls()
            current = table.read(os.getpid())
            if (ctypes.sizeof(_BsdUniqueInfo) != 192 or current is None
                    or current.ppid != os.getppid() or current.pgid != os.getpgrp()
                    or current.birth[0] <= 0 or not 0 <= current.birth[1] < 1_000_000
                    or current.unique_id <= 0 or current.version <= 0):
                raise RddError('Native TUI process identity ABI is unavailable', 'environment')
            # PID 0 cannot identify a process for this API. This exercises the
            # kernel's token-validation path without signaling any process.
            token = (ctypes.c_uint32 * 8)()
            if table.lib.proc_signal_with_audittoken(token, signal.SIGCONT) != errno.ESRCH:
                raise RddError('Native TUI identity-aware signaling is unavailable', 'environment')
            table.children(current.pid)
            return table
        except (OSError, AttributeError) as exc:
            raise RddError(f'Native TUI ownership preflight failed: {exc}', 'environment') from exc

    def read(self, pid):
        record = _BsdUniqueInfo()
        ctypes.set_errno(0)
        size = ctypes.sizeof(record)
        count = self.lib.proc_pidinfo(pid, 18, 0, ctypes.byref(record), size)
        if count == 0 and ctypes.get_errno() in (0, errno.ESRCH, errno.ENOENT):
            return None
        if count != size:
            raise RddError(f'Cannot verify owned process {pid} identity', 'environment')
        bsd, unique = record.bsd, record.unique
        if bsd.pid != pid or not unique.unique_id or unique.version <= 0:
            raise RddError(f'Invalid owned process {pid} identity', 'environment')
        return ProcessIdentity(bsd.pid, bsd.ppid, bsd.pgid,
            (bsd.start_sec, bsd.start_usec), unique.unique_id,
            unique.parent_unique_id, unique.version, bsd.status)

    def children(self, pid):
        # PROC_PPID_ONLY limits enumeration to this parent, never session/name
        # matching. The second read verifies each returned process identity.
        ctypes.set_errno(0)
        capacity = self.lib.proc_listpids(6, pid, None, 0)
        if capacity <= 0 or capacity > 4 * 1024 * 1024:
            raise RddError('Cannot enumerate owned process children', 'environment')
        pids = (ctypes.c_int * (capacity // ctypes.sizeof(ctypes.c_int)))()
        ctypes.set_errno(0)
        count = self.lib.proc_listpids(6, pid, pids, ctypes.sizeof(pids))
        if count == 0 and ctypes.get_errno() not in (0, errno.ESRCH, errno.ENOENT):
            raise RddError('Cannot verify owned process child enumeration', 'environment')
        if count < 0 or count > ctypes.sizeof(pids) or count % ctypes.sizeof(ctypes.c_int):
            raise RddError('Invalid owned process child enumeration', 'environment')
        children = []
        for child_pid in pids[:count // ctypes.sizeof(ctypes.c_int)]:
            if child_pid > 0:
                child = self.read(child_pid)
                if child is not None:
                    children.append(child)
        return children

    def send(self, identity, sig):
        current = self.read(identity.pid)
        if current is None or current.key != identity.key or not current.running:
            return False
        # XNU consumes token[5] (PID) and token[7] (PID version) for lookup,
        # then holds/validates a unique process reference during delivery.
        # Use the fresh version so a legitimate exec of the same birth is owned.
        token = (ctypes.c_uint32 * 8)()
        token[5], token[7] = current.pid, current.version
        result = self.lib.proc_signal_with_audittoken(token, sig)
        if result == errno.ESRCH:
            return False  # Exit, exec, or reuse raced the verified read.
        if result:
            raise RddError(f'Cannot signal owned process {identity.pid}: '
                           f'{os.strerror(result)}', 'environment')
        return True


class OwnedProcessTree:
    """Retain identities observed through verified owned parent relationships."""
    def __init__(self, process, table):
        self.process, self.table = process, table
        root = table.read(process.pid)
        if root is None:
            raise RddError('Native TUI exited before its identity was observed', 'environment')
        self.owned = {root.pid: root}

    def observe(self):
        pending, visited = list(self.owned.values()), set()
        while pending:
            previous = pending.pop()
            if previous.key in visited:
                continue
            visited.add(previous.key)
            current = self.table.read(previous.pid)
            if current is None or current.key != previous.key or not current.running:
                self.owned.pop(previous.pid, None)
                continue
            self.owned[current.pid] = current
            for child in self.table.children(current.pid):
                if (child.ppid == current.pid and child.parent_unique_id == current.unique_id
                        and child.birth >= current.birth and child.running):
                    if len(self.owned) >= 4096 and child.pid not in self.owned:
                        raise RddError('Owned native TUI tree exceeds observation bound', 'environment')
                    self.owned[child.pid] = child
                    pending.append(child)
        return tuple(self.owned.values())

    def close(self, *, grace=.5, poll_interval=.05):
        """Escalate only observed, still-identical processes within three waits."""
        if grace <= 0 or poll_interval <= 0:
            raise ValueError('Cleanup timing must be positive')
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
            for identity in reversed(self.observe()):
                self.table.send(identity, sig)
                if sig != signal.SIGKILL:
                    self.table.send(identity, signal.SIGCONT)
            deadline = time.monotonic() + grace
            while True:
                self.process.poll()  # Reap the owned direct child, without blocking.
                if not self.observe():
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(poll_interval, remaining))
        raise RddError('Observed native TUI processes did not stop within cleanup bound', 'environment')
