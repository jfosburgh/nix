"""Credential tests use private temporary fixtures, never deployed secrets."""
from dataclasses import FrozenInstanceError, replace
import json
import os
from pathlib import Path
import sys
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.config import parse_config
from coordinator.credentials import CredentialError, load_credentials, read_token, load_systemd_credentials, _file, _read_token, _systemd_acl
from test_config import fixture


class SystemdCredentialTests(unittest.TestCase):
    directory = '/run/credentials/inference-coordinator.service'

    def config(self):
        config = parse_config(json.dumps(fixture()).encode())
        return replace(config, token_file=self.directory + '/client',
                       admin_token_file=self.directory + '/admin')

    def metadata(self, **changes):
        data = dict(st_mode=0o100440, st_uid=0, st_gid=0, st_nlink=1, st_size=64)
        data.update(changes)
        return SimpleNamespace(**data)

    def test_exact_root_root_snapshot_metadata_policy(self):
        _file(self.metadata(), 0, 4096, 987)
        with self.assertRaises(CredentialError):
            _file(self.metadata(), 987, 4096)
        with self.assertRaises(CredentialError):
            _file(self.metadata(), 0, 4096)  # ordinary root file policy unchanged

    def test_wrong_owner_group_mode_type_links_and_size_refused(self):
        for change in (dict(st_uid=987), dict(st_gid=981), dict(st_gid=982),
                       dict(st_mode=0o100640), dict(st_mode=0o100444),
                       dict(st_mode=0o100400), dict(st_mode=0o100600),
                       dict(st_mode=0o104440), dict(st_mode=0o010440),
                       dict(st_nlink=2), dict(st_size=0), dict(st_size=4097)):
            with self.subTest(change=change), self.assertRaises(CredentialError):
                _file(self.metadata(**change), 0, 4096, 987)

    def load(self, config=None, **kwargs):
        return load_systemd_credentials(config or self.config(),
                                       directory=kwargs.pop('directory', self.directory), **kwargs)

    def test_load_uses_only_explicit_root_service_user_acl_snapshots(self):
        with patch('coordinator.credentials.os.geteuid', return_value=987), \
             patch('coordinator.credentials.os.getegid', return_value=981), \
             patch('coordinator.credentials._read_token', side_effect=['x'*48, 'y'*48]) as read:
            credentials = self.load()
        self.assertEqual(credentials.token, 'x'*48)
        self.assertEqual(read.call_args_list[0].args, (self.directory + '/client',))
        self.assertEqual(read.call_args_list[0].kwargs, dict(expected_uid=0, systemd_uid=987))
        self.assertEqual(repr(credentials), 'Credentials(<redacted>)')

    def acl(self, uid=987):
        return struct.pack('<I', 2) + b''.join(struct.pack('<HHI', *entry) for entry in (
            (1, 4, 0xffffffff), (2, 4, uid), (4, 0, 0xffffffff),
            (16, 4, 0xffffffff), (32, 0, 0xffffffff)))

    def test_exact_named_user_acl_read_via_descriptor(self):
        acl = self.acl()
        with patch('coordinator.credentials.os.getxattr', return_value=acl) as get:
            self.assertEqual(_systemd_acl(123, 987), acl)
        get.assert_called_once_with(123, 'system.posix_acl_access')

    def test_changed_acl_version_identity_permissions_and_extra_entries_refused(self):
        expected = self.acl()
        values = [b'', b'bad', struct.pack('<I', 1)+expected[4:], self.acl(988),
                  expected+struct.pack('<HHI', 2, 4, 988),
                  expected[:24]+struct.pack('<I', 0),
                  expected.replace(struct.pack('<HHI', 4, 0, 0xffffffff),
                                   struct.pack('<HHI', 4, 4, 0xffffffff)),
                  expected.replace(struct.pack('<HHI', 32, 0, 0xffffffff),
                                   struct.pack('<HHI', 32, 4, 0xffffffff)),
                  expected.replace(struct.pack('<HHI', 2, 4, 987),
                                   struct.pack('<HHI', 2, 6, 987))]
        for acl in values:
            with patch('coordinator.credentials.os.getxattr', return_value=acl), \
                 self.subTest(acl_length=len(acl)), self.assertRaises(CredentialError):
                _systemd_acl(123, 987)

    def test_missing_acl_and_invalid_uid_refused_without_fallback(self):
        with patch('coordinator.credentials.os.getxattr', side_effect=OSError('fixture')), \
             self.assertRaises(CredentialError):
            _systemd_acl(123, 987)
        for uid in (0, -1, True, 0xffffffff):
            with self.subTest(uid=uid), self.assertRaises(CredentialError):
                _systemd_acl(123, uid)

    def test_absent_or_different_directory_refused_before_read(self):
        with patch('coordinator.credentials.os.geteuid', return_value=987), \
             patch('coordinator.credentials.os.getegid', return_value=981), \
             patch('coordinator.credentials._read_token') as read:
            for directory in (None, '/tmp/credentials', self.directory+'/',
                              '/run/credentials/different.service'):
                with self.subTest(directory=directory), self.assertRaises(CredentialError):
                    self.load(directory=directory)
            read.assert_not_called()

    def test_scope_outside_expected_source_unit_refused(self):
        config = replace(self.config(), token_file='/tmp/client')
        with patch('coordinator.credentials.os.geteuid', return_value=987), \
             patch('coordinator.credentials.os.getegid', return_value=981), \
             patch('coordinator.credentials._read_token') as read:
            with self.assertRaises(CredentialError):
                self.load(config)
            read.assert_not_called()

    def test_root_or_root_group_caller_refused(self):
        for uid, gid in ((0, 981), (987, 0)):
            with patch('coordinator.credentials.os.geteuid', return_value=uid), \
                 patch('coordinator.credentials.os.getegid', return_value=gid), \
                 self.assertRaises(CredentialError):
                self.load()

    def test_reviewed_transient_unit_remaps_only_scope_directory(self):
        target = '/run/credentials/inference-coordinator-repair.service'
        with patch('coordinator.credentials.os.geteuid', return_value=987), \
             patch('coordinator.credentials.os.getegid', return_value=981), \
             patch('coordinator.credentials._read_token', side_effect=['x'*48, 'y'*48]) as read:
            self.load(directory=target, unit='inference-coordinator-repair.service',
                      source_unit='inference-coordinator.service')
        self.assertEqual([call.args[0] for call in read.call_args_list],
                         [target+'/client', target+'/admin'])

    def test_equal_snapshot_scopes_still_refused(self):
        with patch('coordinator.credentials.os.geteuid', return_value=987), \
             patch('coordinator.credentials.os.getegid', return_value=981), \
             patch('coordinator.credentials._read_token', return_value='x'*48), \
             self.assertRaises(CredentialError):
            self.load()


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='coordinator-credential-tests-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.token = 'synthetic-client-token-for-testing'
        self.path = self.make('client', self.token.encode())

    def make(self, name, body, mode=0o600):
        path = self.root / name
        path.write_bytes(body)
        path.chmod(mode)
        return path

    def config(self, admin=True, backend=True):
        value = fixture()
        value['token_file'] = str(self.path)
        if admin:
            value['admin_token_file'] = str(self.make('admin', b'synthetic-administration-test-token'))
        else:
            del value['admin_token_file']
        if backend:
            value['backends'][0]['credential_file'] = str(self.make('upstream', b'synthetic-upstream-test-token'))
        return parse_config(json.dumps(value).encode())

    def test_systemd_read_checks_fd_acl_before_and_after_contents(self):
        acl = SystemdCredentialTests().acl(os.geteuid())
        # Metadata policy is tested separately with synthetic root stat records;
        # these unprivileged file fixtures exercise descriptor/read/race handling.
        with patch('coordinator.credentials._file'), \
             patch('coordinator.credentials.os.getxattr', return_value=acl) as get:
            self.assertEqual(_read_token(str(self.path), expected_uid=0,
                                        systemd_uid=os.geteuid()), self.token)
        self.assertEqual(get.call_count, 2)
        self.assertIsInstance(get.call_args_list[0].args[0], int)
        self.assertEqual(get.call_args_list[0].args[0], get.call_args_list[1].args[0])

    def test_bad_acl_refused_before_secret_read_and_changed_acl_after_read(self):
        acl = SystemdCredentialTests().acl(os.geteuid())
        with patch('coordinator.credentials._file'), \
             patch('coordinator.credentials.os.getxattr', return_value=b'bad'), \
             patch('coordinator.credentials.os.read') as read, self.assertRaises(CredentialError):
            _read_token(str(self.path), expected_uid=0, systemd_uid=os.geteuid())
        read.assert_not_called()
        before = len(os.listdir('/proc/self/fd'))
        with patch('coordinator.credentials._file'), \
             patch('coordinator.credentials.os.getxattr', side_effect=[acl, b'changed']), \
             self.assertRaises(CredentialError):
            _read_token(str(self.path), expected_uid=0, systemd_uid=os.geteuid())
        self.assertEqual(len(os.listdir('/proc/self/fd')), before)

    def test_ordinary_private_loader_does_not_select_acl_policy(self):
        with patch('coordinator.credentials.os.getxattr') as get:
            self.assertEqual(read_token(str(self.path)), self.token)
        get.assert_not_called()

    def test_accepts_private_files_and_single_trailing_lf(self):
        for mode in (0o400, 0o600):
            self.path.chmod(mode)
            self.assertEqual(read_token(str(self.path)), self.token)
        other = self.make('newline', self.token.encode() + b'\n')
        self.assertEqual(read_token(str(other)), self.token)
        self.assertEqual(read_token(str(self.path), expected_uid=os.geteuid()), self.token)

    def test_validates_complete_snapshot_and_hides_repr(self):
        credentials = load_credentials(self.config())
        self.assertEqual(credentials.token, self.token)
        self.assertEqual(credentials.admin_token, 'synthetic-administration-test-token')
        self.assertEqual(credentials.backend_tokens['strata'], 'synthetic-upstream-test-token')
        self.assertEqual(repr(credentials), 'Credentials(<redacted>)')
        with self.assertRaises(FrozenInstanceError):
            credentials.token = 'replacement'
        with self.assertRaises(TypeError):
            credentials.backend_tokens['ollama'] = 'replacement'

    def test_optional_scopes_remain_absent(self):
        credentials = load_credentials(self.config(admin=False, backend=False))
        self.assertIsNone(credentials.admin_token)
        self.assertEqual(dict(credentials.backend_tokens), {})

    def test_equal_tokens_in_different_files_or_newline_variants_are_rejected(self):
        for scope in ('admin', 'upstream'):
            config = self.config()
            (self.root / scope).write_bytes(self.token.encode() + b'\n')
            with self.assertRaises(CredentialError):
                load_credentials(config)
        config = self.config()
        (self.root / 'upstream').write_bytes((self.root / 'admin').read_bytes())
        with self.assertRaises(CredentialError):
            load_credentials(config)

    def test_insecure_file_permissions(self):
        for mode in (0o644, 0o640, 0o604, 0o700, 0o4600, 0o2600, 0o1600, 0):
            with self.subTest(mode=oct(mode)):
                self.path.chmod(mode)
                with self.assertRaises(CredentialError):
                    read_token(str(self.path))
        self.path.chmod(0o600)

    def test_rejects_wrong_owner_and_invalid_owner_policy(self):
        with self.assertRaises(CredentialError):
            read_token(str(self.path), expected_uid=os.geteuid() + 1)
        for uid in (True, -1, '0'):
            with self.assertRaises(CredentialError):
                read_token(str(self.path), expected_uid=uid)

    def test_symlink_file_and_intermediate_directory_are_refused(self):
        link = self.root / 'link'
        link.symlink_to(self.path)
        with self.assertRaises(CredentialError):
            read_token(str(link))
        subdir = self.root / 'subdir'
        subdir.mkdir(mode=0o700)
        self.path.rename(subdir / 'client')
        directory_link = self.root / 'directory-link'
        directory_link.symlink_to(subdir, target_is_directory=True)
        with self.assertRaises(CredentialError):
            read_token(str(directory_link / 'client'))
        self.assertEqual(read_token(str(subdir / 'client')), self.token)

    def test_rejects_hardlinked_file(self):
        os.link(self.path, self.root / 'hardlink')
        with self.assertRaises(CredentialError):
            read_token(str(self.path))

    def test_rejects_untrusted_writable_ancestor(self):
        for mode in (0o777, 0o770):
            self.root.chmod(mode)
            with self.assertRaises(CredentialError):
                read_token(str(self.path))
        self.root.chmod(0o700)

    def test_rejects_fifo_directory_and_missing_file_without_blocking(self):
        fifo = self.root / 'fifo'
        os.mkfifo(fifo, 0o600)
        for path in (fifo, self.root, self.root / 'missing'):
            with self.subTest(path=path.name):
                with self.assertRaises(CredentialError):
                    read_token(str(path))

    def test_contents_and_size_are_bounded(self):
        for body in (b'', b'a' * 23, b'a' * 4097, b' ' + self.token.encode(),
                     self.token.encode() + b' ', self.token.encode() + b'\n\n',
                     self.token.encode() + b'\r\n', b'\xff' * 24, b'\x00' * 24,
                     b'a' * 24 + b'\t'):
            path = self.make('invalid', body)
            with self.subTest(body_length=len(body)):
                with self.assertRaises(CredentialError):
                    read_token(str(path))
        self.assertEqual(read_token(str(self.make('maximum', b'x' * 4096))), 'x' * 4096)

    def test_rejects_file_mutation_during_read(self):
        original = os.read
        changed = False
        def mutate(fd, size):
            nonlocal changed
            data = original(fd, size)
            if data and not changed:
                self.path.chmod(0o644)
                changed = True
            return data
        with patch('coordinator.credentials.os.read', side_effect=mutate):
            with self.assertRaises(CredentialError):
                read_token(str(self.path))

    def test_failed_loads_close_all_descriptors(self):
        # Linux target: catches both leaf and ancestor descriptor leaks.
        descriptors = Path('/proc/self/fd')
        baseline = len(list(descriptors.iterdir()))
        for _ in range(10):
            self.assertEqual(read_token(str(self.path)), self.token)
            with self.assertRaises(CredentialError):
                read_token(str(self.root / 'missing'))
            self.path.chmod(0o644)
            with self.assertRaises(CredentialError):
                read_token(str(self.path))
            self.path.chmod(0o600)
        self.assertEqual(len(list(descriptors.iterdir())), baseline)

    def test_open_time_symlink_replacement_is_refused(self):
        original = os.open
        def replace(path, flags, *args, **kwargs):
            if path == 'client' and 'dir_fd' in kwargs:
                self.path.unlink()
                self.path.symlink_to(self.make('replacement', self.token.encode()))
            return original(path, flags, *args, **kwargs)
        with patch('coordinator.credentials.os.open', side_effect=replace):
            with self.assertRaises(CredentialError):
                read_token(str(self.path))

    def test_open_time_regular_file_replacement_is_refused(self):
        original = os.open
        def replace(path, flags, *args, **kwargs):
            if path == 'client' and 'dir_fd' in kwargs:
                replacement = self.make('replacement', b'other-synthetic-client-test-token')
                replacement.replace(self.path)
            return original(path, flags, *args, **kwargs)
        with patch('coordinator.credentials.os.open', side_effect=replace):
            with self.assertRaises(CredentialError):
                read_token(str(self.path))

    def test_errors_are_sanitized_and_missing_scope_has_no_fallback(self):
        config = self.config()
        (self.root / 'admin').unlink()
        with self.assertRaises(CredentialError) as error:
            load_credentials(config)
        self.assertNotIn(str(self.root), str(error.exception))
        self.assertNotIn(self.token, str(error.exception))
        self.assertTrue(error.exception.__suppress_context__)

    def test_unsafe_or_noncanonical_paths_are_refused(self):
        for path in (str(self.root / '..' / 'client'), str(self.root) + '//client',
                     'relative-token', '/', '/' + str(self.path), str(self.path) + '\n'):
            with self.assertRaises(CredentialError):
                read_token(path)
