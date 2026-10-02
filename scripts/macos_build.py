# SPDX-License-Identifier: GPL-3.0-only
"""Build a real arm64 .app on macOS, with immutable input/dependency receipts."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
LOCK=ROOT/"packaging/macos/native-dependencies.lock.json"


def sha256(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b""): digest.update(block)
    return digest.hexdigest()


def is_macho(path: Path) -> bool:
    try:
        with path.open("rb") as stream: header=stream.read(4)
        return header in {bytes.fromhex(x) for x in ("feedface","feedfacf","cefaedfe","cffaedfe","cafebabe","bebafeca","cafebabf","bfbafeca")}
    except OSError: return False


def native_host_problem() -> str:
    if sys.platform!="darwin" or platform.machine()!="arm64": return "Native Apple Silicon macOS is required; Windows cannot cross-build this .app."
    if sys.version_info[:2]!=(3,10): return "Use the locked Python 3.10 runtime."
    if tuple(int(x) for x in platform.mac_ver()[0].split(".")[:2]) < (15,0): return "The selected native media bottles require macOS 15 or newer."
    return ""


def input_paths(root: Path) -> list[Path]:
    selected=[]
    trees=("twobyteasr","scripts","packaging","renderer","assets","licenses","lexicons","third_party","docs/design","installer")
    for directory in trees:
        parent=root/directory
        if not parent.exists(): continue
        for path in parent.rglob("*"):
            if not path.is_file(): continue
            parts=set(path.relative_to(root).parts)
            if parts & {"node_modules",".git","__pycache__","tmp","logs","reports",".pytest_cache"}: continue
            if path.suffix.casefold() in {".pyc",".pyo",".exe",".dll",".pyd",".whl",".log",".2byteproj",".2byteasr"}: continue
            if path.name.casefold() in {"secrets.json","secrets.dat",".env"}: continue
            selected.append(path)
    for path in root.iterdir():
        if path.is_file() and (path.suffix==".py" or path.name in {
            "2byteasr_version.json","dependencies.lock.json","game_profiles.json","glossary.txt",
            "requirements-main.txt","LICENSE","PROJECT_LICENSE.md","SOURCE_DELIVERY.md",
            "BUILD_FROM_SOURCE.md","THIRD_PARTY_NOTICES.md","CONTRIBUTING.md"}): selected.append(path)
    return sorted(set(selected),key=lambda p:p.relative_to(root).as_posix())


def copy_snapshot(root: Path,destination: Path) -> list[dict]:
    paths=input_paths(root)
    before={p.relative_to(root).as_posix():sha256(p) for p in paths}
    rows=[]
    for path in paths:
        name=path.relative_to(root).as_posix()
        target=destination/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,target)
        if sha256(target)!=before[name] or sha256(path)!=before[name]: raise RuntimeError("Source changed while snapshotting: "+name)
        rows.append({"path":name,"bytes":target.stat().st_size,"sha256":before[name]})
    if [p.relative_to(root).as_posix() for p in input_paths(root)]!=list(before): raise RuntimeError("Input set changed while snapshotting")
    if any(sha256(path)!=before[path.relative_to(root).as_posix()] for path in paths):
        raise RuntimeError("Source changed before snapshot was sealed")
    return rows


def unpack_verified_node(archive: Path,destination: Path):
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            target=(destination/member.name).resolve()
            if not target.is_relative_to(destination.resolve()): raise RuntimeError("Unsafe native Node archive member")
            if member.issym() or member.islnk():
                link=(target.parent/member.linkname).resolve() if member.issym() else (destination/member.linkname).resolve()
                if not link.is_relative_to(destination.resolve()): raise RuntimeError("Unsafe native Node archive link")
        bundle.extractall(destination)


def run(command,*,log: Path,cwd=None,env=None,timeout=1800):
    with log.open("ab") as stream:
        result=subprocess.run(list(map(str,command)),cwd=cwd,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=timeout)
    if result.returncode: raise RuntimeError(f"Command failed ({result.returncode}); see {log}")


def bundle_inventory(app: Path) -> list[dict]:
    """Account for permissions and symlinks, rather than dereferencing the ZIP."""
    rows=[]
    for path in sorted(app.rglob("*")):
        row={"path":path.relative_to(app).as_posix(),"mode":path.lstat().st_mode & 0o777}
        if path.is_symlink():
            row.update(kind="symlink",target=os.readlink(path))
            resolved=path.resolve()
            if not resolved.is_relative_to(app.resolve()):
                raise RuntimeError("Bundle link escapes the app: "+row["path"])
        elif path.is_file(): row.update(kind="file",bytes=path.stat().st_size,sha256=sha256(path))
        else: row.update(kind="directory")
        rows.append(row)
    return rows


def finder_environment(boundary: Path) -> dict:
    # Deliberately omit the build venv, Homebrew, Python overrides and all
    # build-time TWOBYTEASR_MAC_* values. Test isolation is explicit and is
    # unrelated to an ordinary user's persistent Application Support data.
    env={key:os.environ[key] for key in ("HOME","LANG","LC_ALL","TMPDIR","DISPLAY") if key in os.environ}
    env.update(PATH="/usr/bin:/bin:/usr/sbin:/sbin",PYTHONNOUSERSITE="1",
               TWOBYTEASR_TEST_ROOT=str(boundary))
    return env


def selected_media_libraries(ffmpeg: Path) -> list[Path]:
    """Explicit full-build libraries win PyInstaller's first-entry deduplication.

    mpv depends on the standard FFmpeg formula with the same library basenames.
    Analysis sorts explicit inputs, so executable input order is insufficient.
    Seed the selected keg libraries explicitly before dependency discovery.
    """
    keg=ffmpeg.resolve().parent.parent
    libraries=sorted((keg/'lib').glob('*.dylib'))
    if not libraries:raise RuntimeError('Selected FFmpeg keg has no native libraries')
    for path in libraries:
        if not path.resolve().is_relative_to(keg):
            raise RuntimeError('Selected FFmpeg library escapes its keg: '+str(path))
    return libraries


def verify_packaged_media(app: Path, required_filters: list[str], environment: dict) -> dict:
    from scripts.macos_media_contract import verify_required_filters
    tool=app/'Contents/Frameworks/tools/ffmpeg/bin/ffmpeg'
    version=subprocess.check_output([str(tool),'-version'],env=environment,text=True,stderr=subprocess.STDOUT,timeout=30)
    filters=subprocess.check_output([str(tool),'-hide_banner','-filters'],env=environment,text=True,stderr=subprocess.STDOUT,timeout=30)
    verify_required_filters(filters,required_filters)
    return dict(passed=True,path=str(tool),sha256=sha256(tool),version=version.splitlines()[0],
                required_filters=required_filters,filter_listing=filters,
                environment_path=environment['PATH'])


def archive_and_relocate(app: Path, output: Path) -> tuple[Path, Path, dict]:
    inventory=bundle_inventory(app)
    (output/"bundle-inventory.json").write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    run(["/usr/bin/codesign","--verify","--deep","--strict",app],log=output/"signing.log",timeout=90)
    zipped=output/"2ByteASR-0.5.0-macos-arm64-experimental.app.zip"
    run(["/usr/bin/ditto","-c","-k","--sequesterRsrc","--keepParent",app,zipped],log=output/"archive.log")
    # Expand the actual deliverable into a different, Unicode location before
    # launching. This checks the archive users will receive, not a copy of the
    # build's already-expanded app.
    moved_parent=output/"relocated/兔白 字幕・移動テスト"
    moved_parent.mkdir(parents=True)
    run(["/usr/bin/ditto","-x","-k",zipped,moved_parent],log=output/"archive.log")
    relocated=moved_parent/app.name
    if bundle_inventory(relocated)!=inventory:
        raise RuntimeError("Unzipped bundle bytes, permissions or symlinks differ")
    run(["/usr/bin/codesign","--verify","--deep","--strict",relocated],log=output/"signing.log",timeout=90)
    return zipped,relocated,{"archive_extracted":True,"relocated_unicode_path":True,
                             "bytes_permissions_symlinks_match":True,"ad_hoc_signature_verified":True}


def native_brand_icon(source: Path, output: Path) -> dict:
    # Native format conversion of the adopted artwork, no replacement design.
    original=source/"assets/2byteasr-icon-transparent.png"
    iconset=output/"2ByteASR.iconset";iconset.mkdir()
    for size in (16,32,128,256,512):
        for scale in (1,2):
            target=iconset/(f"icon_{size}x{size}"+("@2x" if scale==2 else "")+".png")
            run(["/usr/bin/sips","-s","format","png","-z",size*scale,size*scale,original,"--out",target],log=output/"icon.log",timeout=30)
    target=output/"2ByteASR.icns"
    run(["/usr/bin/iconutil","-c","icns",iconset,"-o",target],log=output/"icon.log",timeout=30)
    return {"path":str(target),"sha256":sha256(target),"source":"assets/2byteasr-icon-transparent.png",
            "source_sha256":sha256(original),"scope":"existing adopted brand; internal experimental bundle only"}


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--source-sha",required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--runtime",type=Path,help="Existing isolated native CPU venv for packaged-startup QA")
    parser.add_argument("--media-receipt",type=Path,help="Sealed receipt from macos_install_media.py")
    parser.add_argument("--allow-dirty",action="store_true")
    parser.add_argument("--plan",action="store_true")
    args=parser.parse_args(argv)
    lock=json.loads(LOCK.read_text(encoding="utf8"))
    if not re.fullmatch("[0-9a-fA-F]{40}",args.source_sha): raise SystemExit("source-sha must be an exact 40-character commit SHA")
    if args.plan:
        print(json.dumps({"executed":False,"target":"darwin-arm64","lock":lock,
                          "output":str(args.output),"source_sha":args.source_sha,
                          "required_native_actions":["install pinned Python dependencies","verify native media","download hash-locked Node",
                          "npm ci and native Chromium","fresh PyInstaller .app","bundle architecture/relocation checks","packaged startup smoke"]},ensure_ascii=False,indent=2))
        return 0
    problem=native_host_problem()
    if problem: raise SystemExit(problem)
    head=subprocess.check_output(["git","-C",str(ROOT),"rev-parse","HEAD"],text=True).strip()
    if head.lower()!=args.source_sha.lower(): raise SystemExit("Requested source SHA does not match checkout HEAD")
    dirty=bool(subprocess.check_output(["git","-C",str(ROOT),"status","--porcelain","--untracked-files=all"],text=True).strip())
    if dirty and not args.allow_dirty: raise SystemExit("Checkout is dirty; commit or use explicit --allow-dirty and inspect the fixed snapshot")
    version=json.loads((ROOT/"2byteasr_version.json").read_text(encoding="utf8"))["version"]
    if version!="0.5.0": raise SystemExit("This experiment is paired with product 0.5.0")
    output=args.output.expanduser().resolve()
    if output.exists(): raise SystemExit("Output already exists; choose a new build directory")
    output.mkdir(parents=True)
    source=output/"source"
    inputs=copy_snapshot(ROOT,source)
    from twobyteasr.build_identity import create_build_metadata
    build_id="0.5.0-macos-arm64-"+args.source_sha[:12]
    identity=create_build_metadata(ROOT,channel=build_id)
    metadata=output/"2byteasr_build.json"
    metadata.write_text(json.dumps(identity,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    receipt={"source_identity":identity,"build_id":build_id,"target":"darwin-arm64","macos":platform.mac_ver()[0],
             "python":platform.python_version(),"source_files":inputs,"lock_sha256":sha256(LOCK),
             "developer_id_signed":False,"notarized":False,"native_validation":{}}
    receipt_path=output/"native-build-inputs.json"
    receipt["native_validation"]["app_built"]=False
    receipt["stage"]="source_snapshot_sealed"
    receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    if not args.media_receipt:raise RuntimeError("A verified media installation receipt is required")
    from scripts.macos_media_contract import load_verified_tools
    tools=load_verified_tools(args.media_receipt,LOCK)
    receipt.update(stage="native_media_verified",native_tools=tools,
                   media_install_receipt_sha256=sha256(args.media_receipt))
    receipt['selected_media_libraries']=[dict(path=str(path),sha256=sha256(path))
                                       for path in selected_media_libraries(Path(tools['ffmpeg']['path']))]
    receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    archive=output/Path(lock["node"]["url"]).name
    with urllib.request.urlopen(lock["node"]["url"],timeout=60) as response,archive.open("wb") as stream:
        shutil.copyfileobj(response,stream)
    if sha256(archive)!=lock["node"]["sha256"]: raise RuntimeError("Native Node checksum mismatch")
    native=output/"native"
    native.mkdir()
    unpack_verified_node(archive,native)
    node_root=native/"node-v22.16.0-darwin-arm64"
    node=node_root/"bin/node"
    if "arm64" not in subprocess.check_output(["/usr/bin/lipo","-archs",str(node)],text=True).split(): raise RuntimeError("Node is not arm64")
    env=dict(os.environ)
    env["PATH"]=str(node_root/"bin")+os.pathsep+env.get("PATH","")
    run([node_root/"bin/npm","ci","--no-audit","--no-fund"],cwd=source/"renderer",env=env,log=output/"npm-ci.log")
    # Browser selection/download is bound by locked Remotion 4.0.513, rather
    # than copying the developer's Windows browser or host node_modules.
    browser_script=source/"renderer/.macos-prepare-browser.mjs"
    browser_script.write_text("import {ensureBrowser} from '@remotion/renderer'; import fs from 'node:fs'; const r=await ensureBrowser({chromeMode:'headless-shell',logLevel:'info'}); fs.writeFileSync(process.argv[2],JSON.stringify(r,null,2));\n",encoding="utf8")
    run([node,browser_script,output/"native-browser.json"],cwd=source/"renderer",env=env,log=output/"browser-prepare.log")
    browser_script.unlink()
    from twobyteasr.platform_browser import bundled_browser
    browser=bundled_browser(source/"renderer",platform="darwin",machine="arm64")
    if not browser.is_file() or "arm64" not in subprocess.check_output(["/usr/bin/lipo","-archs",str(browser)],text=True).split(): raise RuntimeError("Native arm64 Chromium was not prepared")
    tools["browser"]={"path":str(browser),"sha256":sha256(browser),"version":subprocess.check_output([str(browser),"--version"],text=True).strip(),"origin":"locked Remotion ensureBrowser"}
    tools["node"]={"path":str(node),"sha256":sha256(node),"version":lock["node"]["version"]}
    receipt["native_tools"]=tools
    receipt["app_icon"]=native_brand_icon(source,output)
    receipt["resolved_python_packages"]=subprocess.check_output([sys.executable,"-m","pip","freeze","--all"],text=True).splitlines()
    receipt["native_validation"]["native_dependencies_prepared"]=True
    receipt_path=output/"native-build-inputs.json"
    receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    env.update(TWOBYTEASR_MAC_SOURCE=str(source),TWOBYTEASR_BUILD_METADATA=str(metadata),
               TWOBYTEASR_MAC_BUILD_ROOT=str(output),TWOBYTEASR_MAC_NATIVE_INPUTS=str(receipt_path))
    run([sys.executable,"-m","PyInstaller","--clean","--noconfirm","--distpath",output/"dist",
         "--workpath",output/"pyinstaller",source/"packaging/macos/2byteasr_macos.spec"],env=env,cwd=source,log=output/"pyinstaller.log")
    app=output/"dist/2ByteASR.app"
    executable=app/"Contents/MacOS/2ByteASR"
    if not executable.is_file(): raise RuntimeError("PyInstaller did not produce a native .app")
    native_objects=[]
    for path in app.rglob("*"):
        if path.is_file() and is_macho(path):
            architectures=subprocess.check_output(["/usr/bin/lipo","-archs",str(path)],text=True).strip()
            if "arm64" not in architectures.split(): raise RuntimeError("Non-arm64 binary in bundle: "+str(path))
            linkage=subprocess.check_output(["/usr/bin/otool","-L",str(path)],text=True)
            if any(prefix in linkage for prefix in ("/opt/homebrew/","/usr/local/Cellar/")):
                raise RuntimeError("Unrelocated Homebrew dependency in bundle: "+str(path))
            native_objects.append({"path":path.relative_to(app).as_posix(),"architecture":architectures,"sha256":sha256(path)})
    receipt["native_objects"]=native_objects
    receipt["native_validation"].update(app_built=True,architecture_and_external_linkage_checked=True)
    # Preserve a real built .app before later model/desktop QA. A failed smoke
    # must not discard a usable artifact or turn it into an empty placeholder.
    receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    zipped,relocated,relocation=archive_and_relocate(app,output)
    receipt["native_validation"]["relocation"]=relocation
    receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    boundary=output.parent
    if "tmp" not in {part.casefold() for part in boundary.parts}:
        raise RuntimeError("Packaged QA requires an explicit disposable tmp boundary")
    try:
        receipt['native_validation']['packaged_media']=verify_packaged_media(
            relocated,lock['media']['ffmpeg'].get('required_filters',[]),finder_environment(boundary/'relocated-media-profile'))
    except Exception as exc:
        receipt['native_validation']['packaged_media']=dict(passed=False,error=str(exc))
        raise
    finally:
        receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    from scripts.macos_startup_contract import verify_relocated_startup
    receipt["native_validation"]["packaged_normal_entry_startup_smoke"]=verify_relocated_startup(
        relocated,boundary,output,finder_environment(boundary/"relocated-startup-profile"))
    receipt["native_validation"].update(model_inference=False,embedded_video=False,studio_full_flow=False,physical_ime=False,human_listening=False,mps_model=False)
    receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    (output/"SHA256SUMS.txt").write_text(sha256(zipped)+"  "+zipped.name+"\n",encoding="utf8")
    artifact={"app_version":"0.5.0","build_id":build_id,"target":"darwin-arm64","source_identity":identity,
              "artifact":{"file":zipped.name,"bytes":zipped.stat().st_size,"sha256":sha256(zipped)},
              "developer_id_signed":False,"notarized":False,"platform_materials_complete":False,
              "validation":receipt["native_validation"]}
    (output/"release-artifacts.mac.json").write_text(json.dumps(artifact,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("Native experimental app built:",zipped)
    return 0


if __name__=="__main__": raise SystemExit(main())
