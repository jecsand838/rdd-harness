"""Real terminal polling plus portable console behavior, without model inference."""
import contextlib
import io
import os
import sys
import types
import unittest
from unittest.mock import patch

from tools.rdd.workflow import ApprovalTerminal, approval_text


class ApprovalTerminalTests(unittest.TestCase):
    def test_redirected_input_is_never_read(self):
        with patch('sys.stdin', io.StringIO('a\n')), patch('sys.stderr', io.StringIO()), patch('os.read') as read:
            terminal = ApprovalTerminal()
            self.assertFalse(terminal.available())
            with self.assertRaises(EOFError):
                terminal.poll()
            read.assert_not_called()

    def test_display_escapes_controls_and_preserves_unicode(self):
        text = approval_text('é漢字\x1b[2J\rforged\x00\t\u202e\nnew line')
        self.assertEqual(text, 'é漢字\\u001b[2J\\u000dforged\\u0000\\u0009\\u202e\n  | new line')
        self.assertNotIn('\x1b', text)

    @unittest.skipUnless(os.name == 'posix', 'POSIX terminal')
    def test_pty_waits_for_enter_discards_stale_and_pasted_answers(self):
        import pty
        master, slave = pty.openpty()
        try:
            with os.fdopen(os.dup(slave), 'r') as stdin, os.fdopen(os.dup(slave), 'w') as stderr:
                with patch('sys.stdin', stdin), patch('sys.stderr', stderr):
                    terminal = ApprovalTerminal()
                    self.assertTrue(terminal.available())
                    self.assertIsNone(terminal.poll())
                    os.write(master, b'a')
                    self.assertIsNone(terminal.poll())
                    os.write(master, b'\n')
                    import select
                    self.assertTrue(select.select([slave], [], [], 1)[0])
                    self.assertEqual(terminal.poll(), 'a')
                    os.write(master, b'a\nd\n')
                    self.assertTrue(select.select([slave], [], [], 1)[0])
                    terminal.reset()
                    self.assertIsNone(terminal.poll())
                    os.write(master, b'\n')
                    self.assertTrue(select.select([slave], [], [], 1)[0])
                    self.assertEqual(terminal.poll(), '')
                    terminal.close()
        finally:
            os.close(master)
            os.close(slave)

    @contextlib.contextmanager
    def console(self, keys):
        output = []
        console = types.SimpleNamespace(kbhit=lambda: bool(keys), getwch=lambda: keys.pop(0), putwch=output.append)
        with patch('os.name', 'nt'), patch.dict(sys.modules, msvcrt=console):
            terminal = ApprovalTerminal()
            with patch.object(terminal, 'available', return_value=True):
                yield terminal, output

    def test_windows_extended_keys_do_not_block_for_suffix_or_authorize(self):
        keys = ['\x00']
        with self.console(keys) as (terminal, _):
            self.assertIsNone(terminal.poll())
            self.assertIsNone(terminal.poll())
            keys += ['a', 'd', '\r']  # The 'a' suffix is never a choice.
            self.assertIsNone(terminal.poll())
            self.assertIsNone(terminal.poll())
            self.assertEqual(terminal.poll(), 'd')

    def test_windows_overlong_input_cannot_be_truncated_into_approval(self):
        keys = list('a' + ' ' * 31 + 'deny') + ['\r']
        with self.console(keys) as (terminal, _):
            while len(keys) > 1:
                self.assertIsNone(terminal.poll())
            self.assertNotEqual(terminal.poll().strip(), 'a')

    def test_windows_editing_enter_eof_and_interrupt(self):
        keys = ['a', '\b', 'd', '\r']
        with self.console(keys) as (terminal, output):
            for _ in range(3):
                self.assertIsNone(terminal.poll())
            self.assertEqual(terminal.poll(), 'd')
            self.assertTrue(output)
            keys += ['\x1a']
            with self.assertRaises(EOFError):
                terminal.poll()
            keys += ['\x03']
            with self.assertRaises(KeyboardInterrupt):
                terminal.poll()
            keys += ['a', '\r']
            terminal.reset()
            self.assertEqual(keys, [])
            self.assertEqual(terminal.buffer, '')


if __name__ == '__main__':
    unittest.main()
