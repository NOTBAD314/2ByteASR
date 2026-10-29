# SPDX-License-Identifier: GPL-3.0-only
"""Update-manifest signing key on the controlled build machine.

The Ed25519 private key is stored outside the repository, encrypted with
Windows DPAPI for the current user (default:
``%USERPROFILE%\\.2byteasr-release\\update-signing-key.dpapi``).  Only the
public key is embedded in ``twobyteasr/app/update_manifest.py``.

    python scripts/release_signing.py generate
    python scripts/release_signing.py public
    python scripts/release_signing.py sign --manifest <file> [--out <file.sig>]
    python scripts/release_signing.py export-backup --out <file.pem>   (password-protected PEM)
"""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from twobyteasr.providers.llm_config import _dpapi  # noqa: E402  (Windows DPAPI helper)
from twobyteasr.app.update_manifest import (  # noqa: E402
    TRUSTED_UPDATE_KEYS, key_id_for, sign_manifest, verify_manifest_signature,
)

DEFAULT_KEY = Path(os.environ.get("TWOBYTEASR_SIGNING_KEY")
                   or Path.home() / ".2byteasr-release" / "update-signing-key.dpapi")


def _refuse_inside_repo(path: Path) -> None:
    resolved = path.resolve()
    if resolved.is_relative_to(ROOT.resolve()):
        raise SystemExit(f"Refusing to keep a signing key inside the repository: {resolved}")


def load_private(path: Path = DEFAULT_KEY) -> bytes:
    _refuse_inside_repo(path)
    payload = json.loads(path.read_text("utf-8"))
    raw = _dpapi("unprotect", base64.b64decode(payload["dpapi"]))
    if len(raw) != 32:
        raise SystemExit("Signing key file is damaged")
    return raw


def public_raw(private: bytes) -> bytes:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    return Ed25519PrivateKey.from_private_bytes(private).public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def generate(path: Path) -> dict:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    _refuse_inside_repo(path)
    if path.exists():
        raise SystemExit(f"Key already exists, never overwritten: {path}")
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                            serialization.NoEncryption())
    pub = public_raw(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"schema": "2byteasr-signing-key/1", "algorithm": "ed25519", "key_id": key_id_for(pub),
              "public": base64.b64encode(pub).decode("ascii"),
              "dpapi": base64.b64encode(_dpapi("protect", raw)).decode("ascii")}
    with path.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2)
    return {"key_file": str(path), "key_id": record["key_id"], "public": record["public"]}


def sign(manifest: Path, out: Path, key_file: Path = DEFAULT_KEY) -> dict:
    data = manifest.read_bytes()
    signature = sign_manifest(data, load_private(key_file))
    key_id = verify_manifest_signature(data, signature)  # must be an embedded, trusted key
    with out.open("xb") as stream:
        stream.write(signature)
    return {"manifest": str(manifest), "signature": str(out), "key_id": key_id}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["generate", "public", "sign", "export-backup"])
    parser.add_argument("--key-file", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.command == "generate":
        print(json.dumps(generate(args.key_file), indent=2))
    elif args.command == "public":
        pub = public_raw(load_private(args.key_file))
        key_id = key_id_for(pub)
        print(json.dumps({"key_id": key_id, "public": base64.b64encode(pub).decode("ascii"),
                          "embedded_and_trusted": key_id in TRUSTED_UPDATE_KEYS}, indent=2))
    elif args.command == "sign":
        if not args.manifest:
            raise SystemExit("--manifest is required")
        out = args.out or args.manifest.with_name(args.manifest.name + ".sig")
        print(json.dumps(sign(args.manifest, out, args.key_file), indent=2))
    else:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        if not args.out:
            raise SystemExit("--out is required")
        _refuse_inside_repo(args.out)
        password = getpass.getpass("Backup password: ").encode("utf-8")
        if len(password) < 12 or password != getpass.getpass("Repeat: ").encode("utf-8"):
            raise SystemExit("Password must match and have at least 12 characters")
        key = Ed25519PrivateKey.from_private_bytes(load_private(args.key_file))
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.BestAvailableEncryption(password))
        with args.out.open("xb") as stream:
            stream.write(pem)
        print(f"Encrypted backup written: {args.out}")


if __name__ == "__main__":
    main()
