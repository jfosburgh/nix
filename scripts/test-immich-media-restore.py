#!/usr/bin/env python3
"""Restore a small, size-bounded media sample and verify captured SHA-256 hashes.
Only reads the existing restored manifest; never touches live Immich media.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess


def read_manifest(path):
    entries = {}
    for line in path.read_text().splitlines():
        escaped = line.startswith("\\")
        record = line[1:] if escaped else line
        digest, relative = record[:64], record[66:]
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("Invalid checksum manifest")
        if escaped:
            # GNU sha256sum escapes backslashes/newlines/CR in file names.
            out, index = [], 0
            while index < len(relative):
                if relative[index] == "\\":
                    index += 1
                    out.append({"n": "\n", "r": "\r", "\\": "\\"}[relative[index]])
                else:
                    out.append(relative[index])
                index += 1
            relative = "".join(out)
        entries[relative] = digest
    return entries


def choose_sample(nodes, checksums, generation):
    images, videos = [], []
    image_extensions = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".dng", ".webp", ".avif"}
    video_extensions = {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi"}
    for node in nodes:
        if node.get("type") != "file":
            continue
        path = PurePosixPath(node.get("path", ""))
        if not path.is_absolute() or ".." in path.parts:
            continue
        try:
            relative = path.relative_to(generation).as_posix()
        except ValueError:
            continue
        parts = PurePosixPath(relative).parts
        if len(parts) < 4 or parts[:2] != ("immich", "media"):
            continue
        if parts[2] in {"thumbs", "encoded-video", "profile", "backups"}:
            continue
        # AppleDouble files (._name.mp4) contain metadata, not video. Also avoid
        # other hidden files and macOS archive metadata regardless of extension.
        if any(part.startswith(".") or part == "__MACOSX" for part in parts[2:]):
            continue
        if relative not in checksums or any(c in str(path) for c in "\n\r*?[]\\"):
            continue
        size = node.get("size", 0)
        if not isinstance(size, int) or size <= 0:
            continue
        if path.suffix.lower() in image_extensions and size <= 50 * 1024**2:
            images.append(node)
        elif path.suffix.lower() in video_extensions and 1024**2 <= size <= 256 * 1024**2:
            videos.append(node)
    images.sort(key=lambda n: (n.get("mtime", ""), n["path"]))
    selected = []
    for index in sorted({0, len(images) // 2, len(images) - 1}):
        if images and index >= 0:
            selected.append(images[index])
    if videos:
        selected.append(min(videos, key=lambda n: (n["size"], n["path"])))
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", help="Exact snapshot ID, not latest")
    parser.add_argument("generation", type=Path, help="Restored coherent generation")
    parser.add_argument("--output-name", help="Fresh immich-media-sample-* directory name for a repeat test")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run as root on Blade")
    if len(args.snapshot) < 8 or any(c not in "0123456789abcdef" for c in args.snapshot):
        parser.error("Use an explicit hexadecimal snapshot ID")
    generation = args.generation.resolve(strict=True)
    restore_root = Path("/data/restore-tests")
    try:
        relative_generation = generation.relative_to(restore_root / args.snapshot)
    except ValueError:
        parser.error("Generation must belong to the named snapshot under /data/restore-tests")
    expected_prefix = ("data", "backup-staging", "coherent-applications")
    if relative_generation.parts[:3] != expected_prefix or len(relative_generation.parts) != 4:
        parser.error("Unexpected restored generation layout")
    source_generation = PurePosixPath("/") / PurePosixPath(relative_generation.as_posix())
    checksums = read_manifest(generation / "SHA256SUMS")
    helper = Path(__file__).resolve().with_name("pinas-restic.sh")
    output_name = args.output_name or f"immich-media-sample-{args.snapshot}"
    if not output_name.startswith("immich-media-sample-") or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in output_name):
        parser.error("Invalid output name")
    destination = restore_root / output_name
    if destination.exists() or destination.is_symlink():
        parser.error(f"Refusing to overwrite {destination}")
    listing = subprocess.run(["bash", str(helper), "critical", "ls", "--json", "--recursive", args.snapshot,
                              str(source_generation / "immich/media")],
                             check=True, capture_output=True, text=True)
    nodes = [json.loads(line) for line in listing.stdout.splitlines() if line.strip()]
    selected = choose_sample(nodes, checksums, source_generation)
    if not selected:
        parser.error("No suitable original media found in snapshot and manifest")
    destination.mkdir(mode=0o700)
    command = ["bash", str(helper), "critical", "restore", args.snapshot, "--target", str(destination)]
    for node in selected:
        command.extend(["--include", node["path"]])
    print(f"Restoring {len(selected)} files, {sum(n['size'] for n in selected) / 1024**2:.1f} MiB", flush=True)
    subprocess.run(command, check=True)
    review = destination / "review"
    review.mkdir(mode=0o700)
    manifest = []
    for index, node in enumerate(selected, 1):
        path = PurePosixPath(node["path"])
        restored = destination / str(path).lstrip("/")
        with restored.open("rb") as stream:
            if stream.read(4) in (b"\x00\x05\x16\x07", b"\x00\x05\x16\x00"):
                raise RuntimeError("Selected file is AppleDouble/AppleSingle metadata, not media; choose another sample")
            stream.seek(0)
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        expected = checksums[path.relative_to(source_generation).as_posix()]
        if digest != expected:
            raise RuntimeError(f"Restored media checksum mismatch: {restored}")
        review_path = review / f"{index:02d}-{path.name}"
        shutil.copyfile(restored, review_path)
        review_path.chmod(0o600)
        manifest.append({"source": str(path), "review": review_path.name,
                         "size": node["size"], "sha256": digest})
    report = destination / "selection.json"
    report.write_text(json.dumps(manifest, indent=2) + "\n")
    report.chmod(0o600)
    print(f"PASS: {len(selected)} originals match captured SHA-256 hashes.")
    print(f"Private review copies: {review}")
    print("Open the images and play the video manually. No video selected if none met the 1–256 MiB sampling range.")


if __name__ == "__main__":
    main()
