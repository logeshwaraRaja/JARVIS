"""Download + unpack the Nemotron English streaming model (sherpa-onnx build).

Source (first match wins):
  1. environment variable DICTATION_MODEL_URL   e.g. your own mirror URL of the .tar.bz2
  2. MODEL_URL in config.py (defaults to the public GitHub release)
Optional (only if your repo needs auth):
  DICTATION_MODEL_USER + DICTATION_MODEL_TOKEN -> basic auth (like curl -u user:key)
  DICTATION_MODEL_TOKEN alone                  -> "Authorization: Bearer ..."
Optional: MODEL_SHA256 in config.py -> the download is rejected if the checksum does not match.
"""
import hashlib
import os
import sys
import tarfile
import urllib.request
from pathlib import Path

import config

NAME = config.MODEL_DIR.name
URL = os.environ.get("DICTATION_MODEL_URL") or config.MODEL_URL
dest = config.MODEL_DIR.parent
dest.mkdir(exist_ok=True)
archive = dest / f"{NAME}.tar.bz2"

if (config.MODEL_DIR / "tokens.txt").exists():
    print("Model already present.")
    sys.exit(0)

print(f"Downloading from: {URL.split('?')[0]}")
req = urllib.request.Request(URL)
tok, usr = os.environ.get("DICTATION_MODEL_TOKEN"), os.environ.get("DICTATION_MODEL_USER")
if tok and usr:      # username + API key / password (same as curl -u user:key)
    import base64
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{usr}:{tok}".encode()).decode())
elif tok:            # access token only
    req.add_header("Authorization", "Bearer " + tok)
sha = hashlib.sha256()
try:
    with urllib.request.urlopen(req) as r, open(archive, "wb") as f:
        total, done = int(r.headers.get("Content-Length") or 0), 0
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
            sha.update(b)
            done += len(b)
            if total:
                print(f"\r  {done * 100 // total}%", end="", flush=True)
except Exception as e:
    print(f"\nDownload failed: {e}\nIf this source is blocked, download the file another way and extract the "
          f".tar.bz2 into: {dest}")
    archive.unlink(missing_ok=True)
    sys.exit(1)

digest = sha.hexdigest()
print(f"\nSHA-256: {digest}")
if config.MODEL_SHA256 and digest.lower() != config.MODEL_SHA256.lower():
    archive.unlink(missing_ok=True)
    sys.exit("Checksum mismatch - file rejected. Check the source, or update MODEL_SHA256 if you trust it.")

print("Extracting...")
with tarfile.open(archive, "r:bz2") as t:
    t.extractall(dest, filter="data") if sys.version_info >= (3, 12) else t.extractall(dest)
archive.unlink()
print("Done ->", config.MODEL_DIR)
