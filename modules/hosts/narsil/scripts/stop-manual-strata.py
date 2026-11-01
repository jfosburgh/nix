"""Stop only James's installed Strata server/serve engine, never arbitrary GPU apps."""
import os
import pwd
import signal
import time
from pathlib import Path

ROOT = Path('/home/james/dev/Strata')


def identify(proc, uid):
    """Return (kind, starttime), or None; tolerate processes exiting mid-scan."""
    try:
        if proc.stat().st_uid != uid:
            return None
        args = proc.joinpath('cmdline').read_bytes().decode().strip('\0').split('\0')
        if not args or not args[0]:
            return None
        cwd = proc.joinpath('cwd').resolve()
        executable = Path(args[0])
        executable = executable if executable.is_absolute() else cwd / executable
        kind = None
        if executable.resolve() == (ROOT / 'engine/strata').resolve() and '--serve' in args:
            kind = 'engine'
        elif executable.name.startswith('python') and len(args) > 1:
            # Match the executed script, not an unrelated program which happens
            # to mention the server path in its later arguments.
            script = Path(args[1])
            if not script.is_absolute():
                script = cwd / script
            if script.resolve() == ROOT / 'serve/server.py':
                kind = 'server'
        if kind:
            # /proc/stat field 22; the command name can itself contain spaces.
            start = proc.joinpath('stat').read_text().rsplit(')', 1)[1].split()[19]
            return kind, start
    except (OSError, ValueError, IndexError, UnicodeError):
        pass
    return None


def stop(proc_root=Path('/proc'), timeout=120):
    uid = pwd.getpwnam('james').pw_uid
    matches = {}
    for proc in proc_root.iterdir():
        if proc.name.isdigit() and (info := identify(proc, uid)):
            matches[int(proc.name)] = info
    if not matches:
        return
    # Let the server ask its engine to quit cleanly; directly stop orphan engines.
    has_server = any(kind == 'server' for kind, _ in matches.values())
    for pid, (kind, _) in matches.items():
        if kind == 'server' or not has_server:
            print(f'Stopping installed Strata {kind} PID {pid}', flush=True)
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + timeout
    while matches and time.monotonic() < deadline:
        matches = {pid: old for pid, old in matches.items()
                   if identify(proc_root / str(pid), uid) == old}
        if matches:
            time.sleep(1)
    if matches:
        raise RuntimeError(f'Strata did not release its processes within {timeout}s: {list(matches)}; refusing to continue')


if __name__ == '__main__':
    stop()
