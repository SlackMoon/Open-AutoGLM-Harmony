#!/usr/bin/env python3
"""Fetch pinned HOScrcpy device libraries without checking binaries into Git."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'third_party' / 'HOScrcpy' / 'assets.json'


def fetch_assets(jar: Path, destination: Path, checksums: dict[str, str]) -> int:
    # Validate every resource before replacing any local files. Never extract
    # arbitrary paths from the archive or execute the upstream JAR.
    verified = {}
    with zipfile.ZipFile(jar) as archive:
        for filename, checksum in checksums.items():
            matches = [name for name in archive.namelist() if Path(name).name == filename]
            if len(matches) != 1:
                raise ValueError(f'Expected one upstream resource: {filename}')
            data = archive.read(matches[0])
            if hashlib.sha256(data).hexdigest() != checksum:
                raise ValueError(f'SHA-256 mismatch: {filename}')
            verified[filename] = data
    destination.mkdir(parents=True, exist_ok=True)
    for filename, data in verified.items():
        temporary = destination / (filename + '.download')
        try:
            temporary.write_bytes(data)
            temporary.replace(destination / filename)
        finally:
            temporary.unlink(missing_ok=True)
    return len(verified)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jar', type=Path, help='Use an already downloaded upstream JAR')
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'hos_scrcpy' / 'bridge' / 'scrcpy_server')
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    checksums = manifest['sha256']
    if all((args.output / name).is_file() and
           hashlib.sha256((args.output / name).read_bytes()).hexdigest() == digest
           for name, digest in checksums.items()):
        print(f'All {len(checksums)} HarmonyOS device libraries are already verified.')
        return
    with tempfile.TemporaryDirectory(prefix='autoglm-harmony-assets-') as directory:
        jar = args.jar
        if jar is None:
            jar = Path(directory) / 'hosScrcpy.jar'
            print(f'Downloading HOScrcpy resources at revision {manifest["revision"]}...')
            request = urllib.request.Request(manifest['url'], headers={'User-Agent': 'Open-AutoGLM-Harmony'})
            with urllib.request.urlopen(request, timeout=30) as response, jar.open('wb') as output:
                shutil.copyfileobj(response, output)
        count = fetch_assets(jar, args.output, checksums)
    print(f'Installed and verified {count} device libraries in {args.output}')


if __name__ == '__main__':
    main()
