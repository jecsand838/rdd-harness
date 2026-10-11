"""Owned-process cleanup fixtures; no Codex sessions or application acceptance."""
import ctypes
import os
from dataclasses import replace
import errno
import signal
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock, patch

from tools.rdd.common import RddError
from tools.rdd.native_process import OwnedProcessTree, ProcessIdentity, ProcessTable


@unittest.skipUnless(sys.platform == "darwin", "macOS ownership qualification")
class OwnedFixtureTests(unittest.TestCase):
    def exercise(self, separate_group, ignore=False):
        script = r"""
import subprocess, sys
code = "import signal,time;\n"
if sys.argv[2]=='True':
    code += "signal.signal(signal.SIGINT, signal.SIG_IGN);signal.signal(signal.SIGTERM, signal.SIG_IGN);\n"
code += "print('ready',flush=True);time.sleep(30)"
child = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, text=True,
    stderr=subprocess.DEVNULL, process_group=0 if sys.argv[1]=='True' else None)
child.stdout.readline()
print(child.pid, flush=True)
sys.stdin.readline()
"""
        parent = subprocess.Popen([sys.executable, '-c', script, str(separate_group), str(ignore)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, process_group=0)
        lib = ctypes.CDLL('/usr/lib/libproc.dylib')
        lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        lib.proc_signal_with_audittoken.argtypes = [ctypes.c_void_p, ctypes.c_int]
        child_pid = None
        token = None
        try:
            child_pid = int(parent.stdout.readline())
            # Combined BSD/unique identity ABI: Apple's xnu bsd/sys/proc_info_private.h.
            raw = ctypes.create_string_buffer(192)
            self.assertEqual(lib.proc_pidinfo(child_pid, 18, 0, raw, 192), 192)
            version = int.from_bytes(raw.raw[168:172], sys.byteorder)
            token = (ctypes.c_uint32 * 8)()
            token[5], token[7] = child_pid, version
            table = ProcessTable.preflight()
            tree = OwnedProcessTree(parent, table)
            tree.observe()
            self.assertIn(child_pid, tree.owned)
            self.assertEqual(os.getpgid(child_pid) == parent.pid, not separate_group)
            parent.stdin.write('\n'); parent.stdin.flush()
            parent.wait(timeout=2)
            tree.close()
            deadline = time.monotonic() + .5
            while time.monotonic() < deadline:
                if lib.proc_pidinfo(child_pid, 18, 0, raw, 192) == 0:
                    break
                time.sleep(.01)
            self.assertEqual(lib.proc_pidinfo(child_pid, 18, 0, raw, 192), 0,
                             'an observed child must be stopped after its parent exits')
        finally:
            if token is not None:
                lib.proc_signal_with_audittoken(token, signal.SIGKILL)
            if parent.poll() is None:
                parent.terminate()
            parent.wait(timeout=2)
            parent.stdin.close(); parent.stdout.close()

    def test_child_surviving_parent_in_same_process_group(self):
        self.exercise(False)

    def test_child_surviving_parent_in_separate_process_group(self):
        self.exercise(True)

    def test_stubborn_child_escalates_to_exact_kill(self):
        self.exercise(True, ignore=True)

    def test_host_rejects_stale_pid_version_and_signals_exact_child(self):
        table = ProcessTable.preflight()
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            identity = table.read(child.pid)
            self.assertIsNotNone(identity)
            self.assertEqual(table.children(child.pid), [])
            token = (ctypes.c_uint32 * 8)()
            token[5], token[7] = identity.pid, identity.version + 1
            self.assertEqual(table.lib.proc_signal_with_audittoken(token, signal.SIGKILL), errno.ESRCH)
            self.assertIsNone(child.poll(), 'a stale token must leave the live child untouched')
            self.assertTrue(table.send(identity, signal.SIGKILL))
            child.wait(timeout=2)
        finally:
            if child.poll() is None:
                table.send(identity, signal.SIGKILL)
            child.wait(timeout=2)


def identity(pid, *, parent=0, parent_unique=0, unique=None, birth=None):
    return ProcessIdentity(pid, parent, pid, birth or (10, pid),
                           unique or pid + 100, parent_unique, 1)


class FakeTable:
    def __init__(self, *records):
        self.records = {record.pid: record for record in records}
        self.sent = []

    def read(self, pid):
        return self.records.get(pid)

    def children(self, pid):
        return [record for record in self.records.values() if record.ppid == pid]

    def send(self, record, sig):
        current = self.read(record.pid)
        if current is None or current.key != record.key:
            return False
        self.sent.append((record.pid, sig))
        if sig == signal.SIGKILL:
            self.records.pop(record.pid, None)
        return True


class OwnedIdentityTests(unittest.TestCase):
    def setUp(self):
        self.root = identity(10)
        self.child = identity(11, parent=10, parent_unique=self.root.unique_id)
        self.grandchild = identity(12, parent=11, parent_unique=self.child.unique_id)
        self.proc = Mock(pid=10)

    def test_observed_reparented_children_remain_owned_and_can_observe_children(self):
        table = FakeTable(self.root, self.child)
        tree = OwnedProcessTree(self.proc, table)
        tree.observe()
        table.records.pop(10)
        table.records[11] = replace(self.child, ppid=1, parent_unique_id=1)
        table.records[12] = self.grandchild
        self.assertEqual({record.pid for record in tree.observe()}, {11, 12})
        tree.close(grace=.001, poll_interval=.001)
        self.assertEqual({pid for pid, sig in table.sent}, {11, 12})
        self.assertFalse(tree.owned)

    def test_root_pid_reuse_never_adopts_replacements_descendants(self):
        table = FakeTable(self.root)
        tree = OwnedProcessTree(self.proc, table)
        replacement = replace(self.root, unique_id=999, birth=(10, 999))
        table.records[10] = replacement
        table.records[11] = replace(self.child, parent_unique_id=999)
        tree.close(grace=.001)
        self.assertEqual(table.sent, [])

    def test_child_pid_reuse_is_dropped_without_signaling_replacement(self):
        table = FakeTable(self.root, self.child)
        tree = OwnedProcessTree(self.proc, table)
        tree.observe()
        table.records.pop(10)
        table.records[11] = replace(self.child, unique_id=888, birth=(10, 888), ppid=1)
        tree.close(grace=.001)
        self.assertEqual(table.sent, [])

    def test_incorrect_parent_unique_identity_is_not_adopted(self):
        table = FakeTable(self.root, replace(self.child, parent_unique_id=999))
        tree = OwnedProcessTree(self.proc, table)
        self.assertEqual(tree.observe(), (self.root,))

    def test_parent_exit_does_not_finish_cleanup_until_child_stops(self):
        table = FakeTable(self.root, self.child)
        tree = OwnedProcessTree(self.proc, table)
        tree.observe()
        table.records.pop(10)
        tree.close(grace=.001, poll_interval=.001)
        self.assertIn((11, signal.SIGKILL), table.sent)
        self.assertTrue(self.proc.poll.called)

    def test_cleanup_reports_bound_if_exact_process_cannot_stop(self):
        table = FakeTable(self.root)
        table.send = Mock(return_value=True)
        tree = OwnedProcessTree(self.proc, table)
        with self.assertRaisesRegex(RddError, 'cleanup bound'):
            tree.close(grace=.001, poll_interval=.001)
        self.assertEqual([args[0][1] for args in table.send.call_args_list],
                         [signal.SIGINT, signal.SIGCONT, signal.SIGTERM,
                          signal.SIGCONT, signal.SIGKILL])

    def test_zombies_are_not_signaled(self):
        table = FakeTable(replace(self.root, status=5))
        tree = OwnedProcessTree(self.proc, table)
        tree.close(grace=.001)
        self.assertEqual(table.sent, [])

    def test_unobserved_root_is_an_explicit_error(self):
        with self.assertRaisesRegex(RddError, 'before its identity was observed'):
            OwnedProcessTree(self.proc, FakeTable())

    def test_tree_population_bound_is_an_explicit_error(self):
        table = FakeTable(self.root, *(identity(pid, parent=10,
            parent_unique=self.root.unique_id) for pid in range(11, 4107)))
        tree = OwnedProcessTree(self.proc, table)
        with self.assertRaisesRegex(RddError, 'observation bound'):
            tree.observe()


class ProcessTableTests(unittest.TestCase):
    def setUp(self):
        self.table = object.__new__(ProcessTable)
        self.table.lib = Mock()
        self.original = identity(10)

    def test_reused_birth_or_unique_id_never_reaches_signal_api(self):
        for changed in (replace(self.original, birth=(10, 1)),
                        replace(self.original, unique_id=999)):
            with self.subTest(changed=changed):
                self.table.read = Mock(return_value=changed)
                self.assertFalse(self.table.send(self.original, signal.SIGKILL))
        self.table.lib.proc_signal_with_audittoken.assert_not_called()

    def test_legitimate_exec_uses_fresh_version_with_kernel_identity_validation(self):
        self.table.read = Mock(return_value=replace(self.original, version=27))
        observed = []
        self.table.lib.proc_signal_with_audittoken.side_effect = lambda token, sig: observed.append((list(token), sig)) or 0
        self.assertTrue(self.table.send(self.original, signal.SIGTERM))
        self.assertEqual(observed[0][0][5], 10)
        self.assertEqual(observed[0][0][7], 27)

    def test_reuse_between_verified_read_and_signal_is_safe_kernel_rejection(self):
        self.table.read = Mock(return_value=self.original)
        self.table.lib.proc_signal_with_audittoken.return_value = errno.ESRCH
        self.assertFalse(self.table.send(self.original, signal.SIGKILL))
        self.table.lib.proc_signal_with_audittoken.assert_called_once()

    def test_signal_permission_error_is_reported(self):
        self.table.read = Mock(return_value=self.original)
        self.table.lib.proc_signal_with_audittoken.return_value = errno.EPERM
        with self.assertRaisesRegex(RddError, 'Cannot signal owned process'):
            self.table.send(self.original, signal.SIGKILL)

    def test_unsupported_hosts_fail_preflight_before_launch(self):
        for host in ('linux', 'win32'):
            with self.subTest(host=host), patch('tools.rdd.native_process.sys.platform', host):
                with self.assertRaisesRegex(RddError, 'macOS only'):
                    ProcessTable.preflight()

    def test_missing_host_api_fails_preflight(self):
        with patch('tools.rdd.native_process.sys.platform', 'darwin'), patch(
                'tools.rdd.native_process.ctypes.CDLL', side_effect=OSError('missing')):
            with self.assertRaisesRegex(RddError, 'ownership preflight failed'):
                ProcessTable.preflight()

    def test_truncated_process_identity_is_rejected(self):
        self.table.lib.proc_pidinfo.return_value = 136
        with self.assertRaisesRegex(RddError, 'Cannot verify owned process'):
            self.table.read(10)

    def test_child_enumeration_rejects_oversized_or_malformed_inventory(self):
        for responses in ([5 * 1024 * 1024], [16, 3], [16, 20]):
            with self.subTest(responses=responses):
                self.table.lib.proc_listpids.side_effect = responses
                with self.assertRaises(RddError):
                    self.table.children(10)

    def test_empty_child_inventory_is_valid(self):
        self.table.lib.proc_listpids.side_effect = [16, 0]
        self.assertEqual(self.table.children(10), [])

    def test_zero_child_count_with_permission_errno_is_not_an_empty_inventory(self):
        def fail(type_, parent, buffer, capacity):
            if buffer is None:
                return 16
            ctypes.set_errno(errno.EPERM)
            return 0
        self.table.lib.proc_listpids.side_effect = fail
        with self.assertRaisesRegex(RddError, 'child enumeration'):
            self.table.children(10)
