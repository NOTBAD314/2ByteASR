"""Repeat the strict release checks on the unchanged, installed 1.1.3 DMG."""
import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from release112_mac_preflight import fixture_code

def sha(path):
    result = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()

def checkout():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()

def save(path, content):
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2), "utf-8")

def worker(scene, app, output):
    product = os.environ["RELEASE113_PRODUCT"]
    if scene == "caret-split":
        from scripts import macos_caret_split_smoke as runner
        modules = {"caption_caret_split_audit": "start"}
    else:
        from scripts import macos_caption_policy_smoke as runner
        modules = {"workshop_columns_audit": "start"} if scene == "workshop-columns" else {}
    old_environment = runner.blank_environment
    def environment(folder, invoker, target):
        env = old_environment(folder, invoker, target)
        sources = {name: (ROOT/"twobyteasr/acceptance"/f"{name}.py").read_text("utf-8")
                   for name in modules}
        if sources:
            from twobyteasr.app import user_overlay
            assert user_overlay.root().resolve().is_relative_to(folder.resolve())
            code = fixture_code(modules, sources)
            user_overlay.check_script(code)
            identity = "1.1.3 " + product[:10]
            user_overlay.add("script", "", "Owned 1.1.3 validation fixtures",
                             code=code, by="user", enabled=True, app_version=identity)
            user_overlay.set_scripts_allowed(True)
            user_overlay.mark_seen_version(identity)
        save(folder/"fixture-identity.json",dict(product_source=product, checker_source=checkout(),
             audit_modules={name:hashlib.sha256(data.encode()).hexdigest() for name,data in sources.items()},
             business_code_patched=False))
        return env
    runner.blank_environment = environment
    sys.argv = [str(runner.__file__), "--app", str(app), "--output", str(output)]
    if scene != "caret-split":
        sys.argv += ["--scenario", scene]
    return runner.main()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dmg", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    assert sys.platform=="darwin" and platform.machine()=="arm64" and os.environ["GITHUB_ACTIONS"]=="true"
    product = os.environ["RELEASE113_PRODUCT"]
    out = args.output.resolve()
    assert "tmp" in out.parts and not out.exists()
    receipt = json.loads(args.receipt.read_text("utf-8"))
    assert receipt["passed"] and receipt["source_identity"]["git_sha"]==product
    digest = sha(args.dmg)
    assert args.dmg.stat().st_size==receipt["artifact"]["bytes"] and digest==receipt["artifact"]["sha256"]
    if args.full:
        from scripts import macos_verify_candidate
        sys.argv = [str(macos_verify_candidate.__file__),"--dmg",str(args.dmg),
                    "--receipt",str(args.receipt),"--output",str(out),"--source-sha",product]
        return macos_verify_candidate.main()
    from scripts.macos_build import bundle_inventory
    out.mkdir(parents=True)
    mount = out/"mounted"
    mount.mkdir()
    app = Path("/Applications/2ByteASR.app")
    assert not app.exists()
    subprocess.run(["/usr/bin/hdiutil","verify",str(args.dmg)],check=True,timeout=240)
    subprocess.run(["/usr/bin/hdiutil","attach","-readonly","-nobrowse","-noautoopen",
                   "-mountpoint",str(mount),str(args.dmg)],check=True,timeout=240)
    try:
        subprocess.run(["/usr/bin/ditto",str(mount/"2ByteASR.app"),str(app)],check=True,timeout=240)
    finally:
        subprocess.run(["/usr/bin/hdiutil","detach",str(mount)],check=True,timeout=90)
    subprocess.run(["/usr/bin/codesign","--verify","--deep","--strict",str(app)],check=True,timeout=240)
    before = bundle_inventory(app)
    outcomes = {}
    for scene in ("caret-split","workshop-columns","editor-review"):
        with (out/f"{scene}-stdout.log").open("wb") as stream:
            result = subprocess.run([sys.executable, "-B", __file__, "worker", scene,
                        str(app),str(out/scene)],stdout=stream,stderr=subprocess.STDOUT,timeout=800)
        outcomes[scene] = result.returncode
        print(json.dumps({"scene":scene,"exit":result.returncode}), flush=True)
    unchanged = before==bundle_inventory(app)
    summary = dict(passed=unchanged and all(code==0 for code in outcomes.values()),
                   unchanged_bundle=unchanged,bundle_files=len(before),macos=platform.mac_ver()[0],
                   product_source=product,checker_source=checkout(),dmg_sha256=digest,outcomes=outcomes)
    save(out/"recheck-result.json",summary)
    print(json.dumps(summary),flush=True)
    return int(not summary["passed"])

if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="worker":
        raise SystemExit(worker(sys.argv[2],Path(sys.argv[3]),Path(sys.argv[4])))
    raise SystemExit(main())
