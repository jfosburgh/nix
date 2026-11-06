"""Pure data validation; no bus connections or service operations."""
from dataclasses import FrozenInstanceError
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.bus_identity import BusIdentity
from coordinator.supervision import SupervisionError


class IdentityTests(unittest.TestCase):
    def test_explicit_immutable_pins(self):
        identity = BusIdentity('a' * 32, ':1.99')
        self.assertEqual(identity, BusIdentity('a' * 32, ':1.99'))
        self.assertNotEqual(identity, BusIdentity('b' * 32, ':1.99'))
        self.assertNotEqual(identity, BusIdentity('a' * 32, ':1.100'))
        with self.assertRaises(FrozenInstanceError):
            identity.manager_owner = ':1.100'

    def test_bus_id_requires_exact_lowercase_guid(self):
        for value in (None, True, b'a' * 32, 'a' * 31, 'a' * 33, 'A' * 32, 'z' * 32,
                      'a' * 32 + '\n', '11111111-1111-1111-1111-111111111111'):
            with self.subTest(value=value), self.assertRaises(SupervisionError):
                BusIdentity(value, ':1.99')

    def test_only_bounded_canonical_numeric_unique_owners(self):
        for value in (None, True, 'org.freedesktop.systemd1', '1.99', ':1', ':01.99',
                      ':1.099', ':1.-1', ':1.1\n', ':1.1;argument', ':1.' + '1' * 21,
                      ':1.\N{ARABIC-INDIC DIGIT ONE}'):
            with self.subTest(value=value), self.assertRaises(SupervisionError):
                BusIdentity('a' * 32, value)


if __name__ == '__main__':
    unittest.main()
