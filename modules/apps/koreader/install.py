#!/usr/bin/env python3
"""Stage a fresh KOReader + NickelMenu installation on a mounted Kobo (firmware 4)."""
import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile

KOREADER_URL = "https://github.com/koreader/koreader/releases/download/v2026.07.1/koreader-kobo-v2026.07.1.zip"
KOREADER_SHA256 = "0f36a62ce73b12516f969e4ad7862cc06920afb03c7bd4db29a0d990bdd84b2f"
NICKELMENU_URL = "https://github.com/pgaskin/NickelMenu/releases/download/v0.6.0/KoboRoot.tgz"
NICKELMENU_SHA256 = "322ff9aa863860e8f5f7e0b55cae561c54bf95983b9bce1d19819d1225d064af"
MENU = "menu_item :main :KOReader :cmd_spawn :quiet:exec /mnt/onboard/.adds/koreader/koreader.sh\n"


def fail(message):
    raise SystemExit(message)


def download(url, destination, expected):
    subprocess.run(["curl", "--fail", "--location", "--proto", "=https", "--proto-redir", "=https", "--retry", "3", "--connect-timeout", "20", "--max-time", "600", "--output", str(destination), url], check=True)
    if hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
        fail("Download checksum mismatch; nothing has been written to the Kobo.")


def extract_zip(archive, destination, root):
    """Only extract a single expected directory; reject links and path traversal."""
    with zipfile.ZipFile(archive) as z:
        entries = []
        total = 0
        for info in z.infolist():
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
                fail("Unsafe path in ZIP archive.")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                fail("Symlinks are not permitted in ZIP archives.")
            if not path.parts or path.parts[0] != root:
                continue
            total += info.file_size
            if total > 512 * 1024 * 1024:
                fail("ZIP expands beyond the installer's 512 MiB safety limit.")
            entries.append((info, path, mode))
        if not entries:
            fail(f"ZIP does not contain {root}/.")
        for info, path, mode in entries:
            target = destination.joinpath(*path.parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o755 if mode & 0o111 else 0o644)


def exclude_adds(text):
    """Preserve the original config and existing exclusion expression."""
    pattern = r"(?m)^\[FeatureSettings\][^\n]*\n"
    match = re.search(pattern, text)
    exclusion = "(^|/)[.]adds($|/)"
    if not match:
        return text.rstrip() + f"\n\n[FeatureSettings]\nExcludeSyncFolders={exclusion}\n"
    end = re.search(r"(?m)^\[", text[match.end():])
    end = match.end() + end.start() if end else len(text)
    section = text[match.end():end]
    setting = re.search(r"(?m)^ExcludeSyncFolders\s*=([^\n]*)", section)
    if setting:
        old = setting.group(1).strip()
        # Avoid silently changing Qt-quoted values or complex escaped expressions.
        if old.startswith('"'):
            fail("Existing ExcludeSyncFolders value is quoted; configure .adds exclusion manually first.")
        value = old if exclusion in old else (f"({old})|{exclusion}" if old else exclusion)
        section = section[:setting.start()] + "ExcludeSyncFolders=" + value + section[setting.end():]
    else:
        section = "ExcludeSyncFolders=" + exclusion + "\n" + section
    return text[:match.end()] + section + text[end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mount", type=Path, help="mounted Kobo USB storage, not a block device")
    parser.add_argument("--plugin", type=Path, required=True, help="preconfigured bookorbit.koplugin.zip downloaded from your BookOrbit account")
    parser.add_argument("--dry-run", action="store_true", help="validate device/config/plugin without downloading or writing")
    args = parser.parse_args()
    mount = args.mount.resolve()
    if not os.path.ismount(mount):
        fail("The supplied path is not a mount point. Connect and mount the Kobo first.")
    version_path = mount / ".kobo/version"
    config = mount / ".kobo/Kobo/Kobo eReader.conf"
    if not version_path.is_file() or not config.is_file():
        fail("Missing Kobo version/config files; refusing to write to this mount.")
    fields = version_path.read_text().strip().split(",")
    firmware = fields[2] if len(fields) > 2 else ""
    if not re.fullmatch(r"4\.\d+\.\d+", firmware):
        fail(f"Firmware {firmware!r} is unsupported by this installer. NickelMenu does not support firmware 5.x; do not downgrade blindly.")
    for relative in [".adds/koreader", ".adds/nm/koreader", ".kobo/KoboRoot.tgz"]:
        if (mount / relative).exists():
            fail(f"{relative} already exists. This installer is for a fresh installation and will not overwrite it.")
    if not args.plugin.is_file():
        fail("BookOrbit plugin ZIP does not exist.")
    # Refuse symlinked paths before copying any device files.
    for relative in [".adds", ".adds/nm", ".kobo", ".kobo/Kobo", ".kobo/version", ".kobo/Kobo/Kobo eReader.conf"]:
        if (mount / relative).is_symlink():
            fail(f"Refusing symlinked Kobo path: {relative}")
    original = config.read_text()
    modified = exclude_adds(original)
    with tempfile.TemporaryDirectory(prefix="kobo-install-") as temporary:
        work = Path(temporary)
        extract_zip(args.plugin, work / "plugin", "bookorbit.koplugin")
        if not (work / "plugin/bookorbit.koplugin/main.lua").is_file():
            fail("BookOrbit plugin is missing main.lua.")
        print(f"Kobo firmware: {firmware}\nBookOrbit: https://books.threegoldenhairs.me\nTarget: {mount}")
        print("Plan: exclude .adds from Nickel scanning; install KOReader 2026.07.1, BookOrbit plugin, NickelMenu 0.6.0 and launcher.")
        if args.dry_run:
            print("Dry run complete; no device files changed. Model must be confirmed at installation.")
            return
        if input("Confirm this is your Kobo Clara BW; type INSTALL to proceed: ") != "INSTALL":
            fail("Cancelled; no device files changed.")
        download(KOREADER_URL, work / "koreader.zip", KOREADER_SHA256)
        download(NICKELMENU_URL, work / "KoboRoot.tgz", NICKELMENU_SHA256)
        extract_zip(work / "koreader.zip", work / "reader", "koreader")
        if not (work / "reader/koreader/koreader.sh").is_file():
            fail("KOReader archive is missing its launcher.")
        shutil.copytree(work / "plugin/bookorbit.koplugin", work / "reader/koreader/plugins/bookorbit.koplugin")
        required = sum(p.stat().st_size for p in (work / "reader").rglob("*") if p.is_file()) + 32 * 1024 * 1024
        if shutil.disk_usage(mount).free < required:
            fail("Insufficient Kobo free space; nothing has been written.")
        # Back up the small configuration on the computer, not in Nickel's scan path.
        backup = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "kobo-install-koreader"
        backup.mkdir(parents=True, exist_ok=True, mode=0o700)
        backup.chmod(0o700)
        backup_file = backup / ("Kobo-eReader-" + os.urandom(6).hex() + ".conf")
        backup_file.write_text(original)
        backup_file.chmod(0o600)
        config.write_text(modified)
        shutil.copytree(work / "reader/koreader", mount / ".adds/koreader")
        (mount / ".adds/nm").mkdir(parents=True, exist_ok=True)
        (mount / ".adds/nm/koreader").write_text(MENU)
        # Stage the firmware hook last, so a failed application copy cannot activate it.
        shutil.copyfile(work / "KoboRoot.tgz", mount / ".kobo/KoboRoot.tgz")
        os.sync()
        print(f"Installed files; config backup: {backup_file}")
        print("Safely unmount/eject the Kobo, then disconnect USB. Let NickelMenu install and reboot.")
        print("Open NickelMenu > KOReader. In KOReader use Tools > BookOrbit Sync.")
        print("For auto sync: Network > Action when Wi-Fi is off > Turn on, then enable BookOrbit auto sync.")
        print("Use KOReader's OTA updater and BookOrbit's plugin update check for future updates; do not rerun this fresh installer.")


if __name__ == "__main__":
    main()
