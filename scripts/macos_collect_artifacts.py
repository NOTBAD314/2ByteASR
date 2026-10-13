# SPDX-License-Identifier: GPL-3.0-only
"""Select bounded deliverables/receipts; never upload model/runtime/user caches."""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
from pathlib import Path


def selected_files(root: Path) -> list[Path]:
    selected=[]
    for folder in ("media","build","dmg","blank-project","native-media-smoke","embedded-preview","hardware-probe","desktop-flow","desktop-flow/restart","desktop-flow/runtime-evidence","relocated-startup-profile/startup-smoke","finder-startup-profile/startup-smoke","cloud-only","keychain","mlx","cloud-mlx","studio-perf","studio-perf/export"):
        directory=root/folder
        if not directory.is_dir():continue
        # Build/source, node_modules, PyInstaller output, runtime and model
        # trees are deliberately outside this shallow receipt selection.
        for path in directory.iterdir():
            if path.is_file() and (path.name.endswith(".app.zip") or path.suffix.lower() in {".dmg",".json",".log",".txt",".png",".xml"}
                                  or (folder=='desktop-flow/runtime-evidence' and (path.name.endswith('pyvenv.cfg') or path.name=='subtitle-render-diagnostics.jsonl'))
                                  or (folder=='desktop-flow' and path.name in {'中文 字幕・日本語.mp4','再起動・第二任务.mp4'})):
                selected.append(path)
        if folder=="desktop-flow":
            for name in ('recognized', 'final', 'restart'):
                path=directory/'owned-projects'/(name+'.2byteproj')
                if path.is_file() and path.stat().st_size<=8*1024*1024:selected.append(path)
            for path in (directory/"exports").glob("*"):
                if path.is_file() and path.suffix.lower() in {".srt",".ass",".txt",".json",".mp4"}:selected.append(path)
    for name in ("doctor.json","runtime.json","runtime.pip-install.json","brew-installed.txt","tests.xml","ci-status.json","workflow-identity.json","runtime-identity.json","fixture-origin.json"):
        if (root/name).is_file():selected.append(root/name)
    return sorted(set(selected))


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--qa-root",type=Path,required=True)
    parser.add_argument("--maximum-bytes",type=int,required=True)
    args=parser.parse_args(argv)
    root=args.qa_root.resolve()
    if "tmp" not in {p.lower() for p in root.parts}:raise SystemExit("An isolated tmp QA boundary is required")
    files=selected_files(root)
    if args.maximum_bytes<16*1024*1024:raise SystemExit("Artifact allowance must reserve at least 16 MiB for diagnostic receipts")
    if args.maximum_bytes>600*1024*1024:raise SystemExit("Artifact allowance must not exceed the verified 600 MiB cap")
    total=0
    destination=root/"artifacts"
    if destination.exists():raise SystemExit("Artifact staging already exists; no retry/overwrite")
    rows=[]
    withheld=[]
    # Deliver the verified DMG alone. The build ZIP stays on
    # the disposable runner, rather than doubling paid artifact storage.
    def application(path):return path.name.endswith('.app.zip') or path.suffix.lower()=='.dmg'
    # Receipts are uploaded separately before the large app. No app size
    # failure can suppress already captured diagnostics.
    for path in sorted(files,key=lambda p:(application(p),str(p))):
        name=path.relative_to(root).as_posix()
        app=application(path)
        target=destination/('application' if app else 'receipts')/name
        hasher=hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda:stream.read(4*1024*1024),b""):hasher.update(chunk)
        digest=hasher.hexdigest()
        row={"path":name,"bytes":path.stat().st_size,"sha256":digest}
        if path.name.endswith('.app.zip'):
            withheld.append(dict(row,reason='Only DMG delivery is allowed; app archive retained on runner'));continue
        if total+row['bytes']+8*1024*1024>args.maximum_bytes:
            withheld.append(dict(row,reason='Exceeds this run verified storage allowance'));continue
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
        total+=row['bytes'];rows.append(row)
    receipts=destination/'receipts';receipts.mkdir(parents=True,exist_ok=True)
    (receipts/"artifact-selection.json").write_text(json.dumps({"selected_bytes":total,"maximum_bytes":args.maximum_bytes,
        "retention_days":1,"model_runtime_cache_uploaded":False,"files":rows,"withheld":withheld},ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    (receipts/"SHA256SUMS.txt").write_text("".join(row["sha256"]+"  "+row["path"]+"\n" for row in rows),encoding="utf8")
    print(json.dumps({"files":len(rows),"bytes":total,"app_archive_exists":any(p.name.endswith(".app.zip") for p in files)}))
    return 0


if __name__=="__main__":raise SystemExit(main())
