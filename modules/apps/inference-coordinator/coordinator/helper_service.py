"""Privileged, local-only supervisor entrypoint. Nothing runs on import.

Two explicit modes: provision NEW pins/journal, or serve EXISTING pins. No
implicit initialization, repinning, uncertainty clearing, retries or auto-resume.
Run in a stable host mount/cgroup namespace under systemd's watchdog/cgroup
shutdown bound; do not add namespace-changing sandbox options without new pins.
"""
import argparse
import asyncio
import os
from pathlib import Path
import pwd
import signal
import socket
import sys

from .backend_http import ControlClient, LifecycleError
from .cgroup_mount import VerifiedCgroupReader
from .config import ConfigError, fields, duration, text
from .deployment import StoreArtifact, StoreUnitDeployment
from .job_journal import JobJournal
from .managed_helper import ManagedUnitHelper
from .operator_files import read_operator_file
from .provisioning import boot_id, load_pins, observe_fence, observe_mount, write_pins
from .supervision import APIState, ManagedQuiescence, SupervisionError, UnitContract
from .supervisor_rpc import SupervisorRPC, _json
from .systemd_inspect import SystemdInspector
from .systemd_jobs import SystemdJobSession


def parse_manifest(data):
    value = _json(data)
    fields(value, ('unit', 'cgroup', 'fragment', 'configuration', 'upstream', 'backend_version',
                   'backend', 'allowed_user', 'busctl', 'stop_timeout', 'phase_timeout', 'total_timeout'))
    fields(value['fragment'], ('path', 'sha256'))
    if type(value['configuration']) is not list:
        raise SupervisionError('Invalid supervisor deployment manifest')
    for artifact in value['configuration']:
        fields(artifact, ('path', 'sha256'))
    deployment = StoreUnitDeployment(text(value['unit']), StoreArtifact(**value['fragment']),
                                      tuple(StoreArtifact(**a) for a in value['configuration']))
    for key in ('cgroup', 'upstream', 'backend', 'allowed_user', 'busctl'):
        text(value[key])
    for key in ('stop_timeout', 'phase_timeout', 'total_timeout'):
        duration(value[key])
    if value['backend_version'] != '0.40.11':
        raise SupervisionError('Unsupported supervised backend version')
    contract = UnitContract(value['unit'], value['cgroup'], deployment.identity,
                            'control-group', True, value['stop_timeout'], 'no', True, False, True)
    return value, deployment, contract


def _notify(value):
    address = os.environ.get('NOTIFY_SOCKET')
    if address:
        if address.startswith('@'):
            address = '\0' + address[1:]
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notify:
            notify.settimeout(0.1)
            notify.sendto(value.encode('ascii'), address)


async def _watchdog():
    while True:
        _notify('WATCHDOG=1')
        await asyncio.sleep(2)


async def ready_api(control, expected_version, *, poll_interval=0.2):
    """Non-loading readiness; caller MUST supply a phase/total deadline."""
    while True:
        try:
            _, version = await control.request('GET', '/api/version')
            _, residents = await control.request('GET', '/api/ps')
        except LifecycleError:
            await asyncio.sleep(poll_interval)
            continue
        if version.get('version') != expected_version or residents.get('models') != []:
            raise SupervisionError('Lazy backend API readiness unconfirmed')
        return APIState(version['version'], ())


async def run(mode, manifest_path, state_path, socket_path):
    if os.geteuid() != 0:
        raise SupervisionError('Supervisor requires root operator/service identity')
    data = read_operator_file(manifest_path, limit=65536)
    value, deployment, contract = parse_manifest(data)
    uid = pwd.getpwnam(value['allowed_user']).pw_uid
    gid = pwd.getpwnam(value['allowed_user']).pw_gid
    if uid == 0:
        raise SupervisionError('Separate unprivileged coordinator identity required')
    if mode == 'provision':
        # A private root StateDirectory/tmpfiles directory must already exist.
        if Path(state_path, 'pins.json').exists() or Path(state_path, 'jobs.jsonl').exists():
            raise SupervisionError('Existing supervisor state requires explicit recovery')
        fence, mount = await observe_fence(), observe_mount()
        boot = boot_id()
    else:
        fence, mount, boot = load_pins(state_path, deployment=deployment.identity)
    journal = JobJournal(str(Path(state_path, 'jobs.jsonl')), unit=contract.unit,
                          identity=deployment.identity, boot_id=boot, bus_identity=fence.bus,
                          manager_load_usec=fence.units_load_usec, manager_version=fence.version)
    session = SystemdJobSession(journal, expected=fence, timeout=value['phase_timeout'])
    try:
        journal.open(initialize=mode == 'provision')
        await session.open()
        inspector = SystemdInspector(executable=value['busctl'], unit=contract.unit,
                                      expected_bus=fence.bus, timeout=5)
        population = VerifiedCgroupReader('/sys/fs/cgroup', expected=mount)
        helper = ManagedUnitHelper(contract, deployment=deployment, session=session,
                                    inspector=inspector, population=population, service_type='exec')
        await helper.snapshot()  # No lifecycle/API calls or release claims.
        if mode == 'provision':
            write_pins(state_path, deployment=deployment.identity, fence=fence, mount=mount)
            print('Supervisor pins and journal provisioned; no backend mutation or admission')
            return
        async with ControlClient(value['upstream'], timeout=5) as control:
            async def readiness():
                # Type=exec completion precedes HTTP bind/readiness. Retry only
                # these non-loading reads within ManagedQuiescence's phase and
                # total deadlines; never replay stop/start or model inference.
                return await ready_api(control, value['backend_version'])
            transaction = ManagedQuiescence(contract, helper=helper, population=population,
                                             readiness=readiness, expected_version=value['backend_version'],
                                             phase_timeout=value['phase_timeout'],
                                             total_timeout=value['total_timeout'])
            rpc = SupervisorRPC(backend=value['backend'], allowed_uid=uid, transaction=transaction,
                                 timeout=value['total_timeout'] + 5)
            server = await asyncio.start_unix_server(rpc.handle, path=socket_path, limit=1024, backlog=8)
            os.chown(socket_path, 0, gid)
            os.chmod(socket_path, 0o660)
            stop = asyncio.Event()
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, stop.set)
            heartbeat = asyncio.create_task(_watchdog())
            try:
                _notify('READY=1')
                print('Supervisor ready; awaiting explicit coordinated quiescence', flush=True)
                await stop.wait()
            finally:
                server.close()
                await server.wait_closed()
                # systemd TimeoutStopSec remains the outer bound on this drain.
                await rpc.aclose()
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
    finally:
        await session.close()
        journal.close()


def main():
    parser = argparse.ArgumentParser(description='Local managed inference supervisor')
    parser.add_argument('mode', choices=('provision', 'serve'))
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--state', required=True)
    parser.add_argument('--socket', default='/run/inference-supervisor/control.sock')
    args = parser.parse_args()
    try:
        asyncio.run(run(args.mode, args.manifest, args.state, args.socket))
    except (Exception, KeyboardInterrupt) as error:
        detail = str(error) if isinstance(error, (SupervisionError, ConfigError)) else type(error).__name__
        print('Supervisor failed closed: ' + detail + '; inspect/recover state explicitly', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
