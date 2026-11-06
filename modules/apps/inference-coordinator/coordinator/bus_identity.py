"""Explicit system-bus/name-owner pins; no discovery or process-epoch proof."""
from dataclasses import dataclass
import re

from .supervision import SupervisionError


@dataclass(frozen=True)
class BusIdentity:
    """Operator-injected D-Bus GetId GUID and systemd's unique name owner.

    A unique name alone can be reused after a bus restart. A GUID alone does not
    pin the systemd connection. Both are required and must survive journal reopen
    unchanged. These do not identify a manager process epoch: reexecution may
    preserve the connection/name. No automatic discovery/repinning is provided.
    Supports the numeric unique-name format emitted by dbus-daemon/dbus-broker.
    """
    bus_id: str
    manager_owner: str

    def __post_init__(self):
        if (type(self.bus_id) is not str or not re.fullmatch(r'[0-9a-f]{32}', self.bus_id)
                or type(self.manager_owner) is not str or not re.fullmatch(
                    r':(?:0|[1-9][0-9]{0,19})\.(?:0|[1-9][0-9]{0,19})', self.manager_owner)):
            raise SupervisionError('Explicit valid bus and manager-owner pins required')
