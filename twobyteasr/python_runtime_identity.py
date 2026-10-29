# SPDX-License-Identifier: GPL-3.0-only
"""Stdlib-only Python identity evidence; never import the probed package."""
from __future__ import annotations
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import site
import sys
import time
from pathlib import Path

ENVIRONMENT_KEYS = ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "__PYVENV_LAUNCHER__",
                    "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH", "LD_LIBRARY_PATH")

def python_entry_path(value) -> str:
    """Absolute executable entry, retaining the venv's final symlink."""
    return os.path.abspath(os.path.expanduser(os.fspath(value)))

def file_identity(path) -> dict:
    entry=Path(python_entry_path(path)); target=entry.resolve()
    result=dict(entry=str(entry),resolved_target=str(target),is_symlink=entry.is_symlink(),
                exists=entry.is_file())
    if entry.is_symlink():result["link_target"]=os.readlink(entry)
    if target.is_file():
        digest=hashlib.sha256()
        with target.open("rb") as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b""):digest.update(chunk)
        result["resolved_binary_sha256"]=digest.hexdigest()
    cfg=entry.parent.parent/"pyvenv.cfg"
    if cfg.is_file():
        result["pyvenv_cfg"]=dict(path=str(cfg),text=cfg.read_text("utf8"),
                                 sha256=hashlib.sha256(cfg.read_bytes()).hexdigest())
    return result

def environment_difference(before, after) -> dict:
    return {key:dict(before=before.get(key),after=after.get(key))
            for key in ENVIRONMENT_KEYS if before.get(key)!=after.get(key)}

def interpreter_identity(module="funasr") -> dict:
    try:
        spec=importlib.util.find_spec(module)
        origin=spec.origin if spec else None
    except Exception as exc:origin="find_spec failed: "+repr(exc)
    try:
        distribution=importlib.metadata.distribution(module)
        version=distribution.version
        package=dict(version=version,metadata_path=str(distribution._path),
                     installer=distribution.read_text("INSTALLER"))
    except importlib.metadata.PackageNotFoundError:
        package=dict(version=None)
    try:packages=site.getsitepackages()
    except AttributeError:packages=[]
    return dict(executable=sys.executable,prefix=sys.prefix,base_prefix=sys.base_prefix,
                version=sys.version,machine=platform.machine(),flags=str(sys.flags),
                sys_path=list(sys.path),site_packages=packages,user_site=site.getusersitepackages(),
                module=module,find_spec=origin,distribution=package,
                frozen=bool(getattr(sys,"frozen",False)),frozen_entry=sys.executable if getattr(sys,"frozen",False) else None,
                argv=list(sys.argv),cwd=os.getcwd(),entry=file_identity(sys.executable),
                environment={key:os.environ.get(key) for key in ENVIRONMENT_KEYS})

def save_identity(label, payload, directory=None) -> Path:
    if directory is None:
        from .runtime_paths import user_data_root
        directory=user_data_root()/"logs/python-runtime"
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    path=directory/(str(time.time_ns())+"-"+str(os.getpid())+"-"+label+".json")
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("[2BYTEASR_PYTHON_IDENTITY] "+json.dumps(dict(label=label,path=str(path),**payload),ensure_ascii=False),
          file=sys.stderr,flush=True)
    return path
