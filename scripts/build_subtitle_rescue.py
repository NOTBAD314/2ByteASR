"""Build a source-pinned, isolated rescue EXE. Does not touch daily installs."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    root=args.output.resolve()
    if root.exists():parser.error("use a fresh build directory")
    root.mkdir(parents=True)
    source=root/"source"; source.mkdir()
    # Explicit source roots only: no projects, reports, settings, logs or keys.
    files=list((ROOT/"twobyteasr").rglob("*.py"))
    files += [ROOT/name for name in ("scripts/subtitle_rescue.py","scripts/build_subtitle_rescue.py",
              "packaging/subtitle_rescue.spec","LICENSE","PROJECT_LICENSE.md","THIRD_PARTY_NOTICES.md",
              "assets/fonts/SourceHanSansSC-Heavy.otf","assets/fonts/SourceHanSansSC-Medium.otf","assets/fonts/LICENSE.txt")]
    manifest={}
    for path in files:
        rel=path.relative_to(ROOT); data=path.read_bytes()
        dest=source/rel; dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(data)
        manifest[rel.as_posix()]=hashlib.sha256(data).hexdigest()
    tree=ast.parse((source/"twobyteasr/exports/subtitle_rescue.py").read_text(encoding="utf-8"))
    build_id=next(ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign)
                  and any(isinstance(target,ast.Name) and target.id=="BUILD_ID" for target in node.targets))
    metadata={"build_id":build_id,"python":sys.version,"source_files":manifest,
              "source_digest":hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()}
    (source/"rescue-build.json").write_text(json.dumps(metadata,indent=2),encoding="utf-8")
    command=[sys.executable,"-m","PyInstaller","--noconfirm","--clean",
             "--distpath",str(root/"dist"),"--workpath",str(root/"work"),str(source/"packaging/subtitle_rescue.spec")]
    with (root/"build.log").open("w",encoding="utf-8") as log:
        code=subprocess.call(command,cwd=source,stdout=log,stderr=subprocess.STDOUT)
    print(json.dumps({"exit_code":code,"directory":str(root),"source_digest":metadata["source_digest"]}))
    return code


if __name__=="__main__":raise SystemExit(main())
