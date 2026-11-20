"""Owned native fixture preflight on the unchanged R5 DMG; no business patches."""
from pathlib import Path
import argparse,hashlib,json,os,platform,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
PRODUCT='f879ef3bc2755df8106816b7fa11687a009cc258'
def fixture_code(modules,sources):
 return 'API_VERSION = 1\nMODULES='+repr(modules)+'\nSOURCES='+repr(sources)+'''\ndef setup(api):
    from importlib import import_module
    for name,entry in MODULES.items():
        scope={"__package__":"twobyteasr.acceptance","__name__":"twobyteasr.acceptance.release112_fixture_"+name}
        exec(compile(SOURCES[name],"release112_fixture_"+name+".py","exec"),scope)
        setattr(import_module("twobyteasr.acceptance."+name),entry,scope[entry])
    # The owned bootstrap is no longer needed after binding the fixtures.
    # Restore the real default gate before testing the user's overlay permissions.
    from twobyteasr.app import user_overlay
    user_overlay.remove(api.script_id)
    user_overlay.set_scripts_allowed(False)
    assert user_overlay.entries()==[] and not user_overlay.load()['scripts_allowed']
    import json,os
    from pathlib import Path
    (Path(os.environ['TWOBYTEASR_ACCEPTANCE_DIR'])/'bootstrap-neutral.json').write_text(json.dumps(dict(entries=0,scripts_allowed=False)),encoding='utf-8')
'''

def worker(scene,app,out):
 modules=({'caption_caret_split_audit':'start'} if scene=='caret-split' else {'bunny_harness_p2_audit':'run','home_plan_zoom_audit':'start','edit_save_audit':'start'})
 sources={name:(ROOT/'twobyteasr/acceptance'/f'{name}.py').read_text('utf-8') for name in modules}
 checker=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
 def wrapped(original):
  def environment(folder,invoker,target):
   env=original(folder,invoker,target)
   from twobyteasr.app import user_overlay
   assert user_overlay.root().resolve().is_relative_to(folder.resolve())
   code=fixture_code(modules,sources)
   user_overlay.check_script(code)
   identity='1.1.2 '+PRODUCT[:10]
   user_overlay.add('script','','Owned release112 audit fixtures only',code=code,by='user',enabled=True,app_version=identity)
   user_overlay.set_scripts_allowed(True);user_overlay.mark_seen_version(identity)
   (folder/'external-fixture-binding.json').write_text(json.dumps(dict(product_source=PRODUCT,checker_source=checker,executed_sources={k:hashlib.sha256(v.encode()).hexdigest() for k,v in sources.items()},business_code_patched=False),indent=2),'utf-8')
   return env
  return environment
 from scripts import macos_caption_policy_smoke as smoke,macos_edit_save_smoke as edits,macos_caret_split_smoke as caret
 smoke.blank_environment=wrapped(smoke.blank_environment);edits.blank_environment=wrapped(edits.blank_environment);caret.blank_environment=wrapped(caret.blank_environment)
 if scene=="caret-split":
  sys.argv=["macos_caret_split_smoke.py","--app",str(app),"--output",str(out)];return caret.main()
 if scene=="edit-save":return edits.main(["--app",str(app),"--output",str(out)])
 sys.argv=["macos_caption_policy_smoke.py","--app",str(app),"--scenario",scene,"--output",str(out)]
 return smoke.main()

def main():
 p=argparse.ArgumentParser();p.add_argument('--dmg',type=Path,required=True);p.add_argument('--receipt',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 assert sys.platform=='darwin' and platform.machine()=='arm64' and os.environ.get('GITHUB_ACTIONS')=='true'
 out=a.output.resolve();assert 'tmp' in out.parts and not out.exists();out.mkdir(parents=True)
 sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
 receipt=json.loads(a.receipt.read_text('utf-8'));assert receipt['passed'] and receipt['source_identity']['git_sha']==PRODUCT
 assert a.dmg.stat().st_size==receipt['artifact']['bytes'] and sha(a.dmg)==receipt['artifact']['sha256']
 mount=out/'mounted';mount.mkdir();app=out/'installed/2ByteASR.app';app.parent.mkdir()
 def run(cmd,log,timeout=900):
  with (out/log).open('ab') as stream:r=subprocess.run(list(map(str,cmd)),stdout=stream,stderr=subprocess.STDOUT,timeout=timeout)
  return r.returncode
 assert run(['/usr/bin/hdiutil','verify',a.dmg],'install.log')==0
 assert run(['/usr/bin/hdiutil','attach','-readonly','-nobrowse','-noautoopen','-mountpoint',mount,a.dmg],'install.log')==0
 try:assert run(['/usr/bin/ditto',mount/'2ByteASR.app',app],'install.log')==0
 finally:assert run(['/usr/bin/hdiutil','detach',mount],'install.log')==0
 assert run(['/usr/bin/codesign','--verify','--deep','--strict',app],'install.log')==0
 def inventory():
  return {p.relative_to(app).as_posix():('link:'+os.readlink(p) if p.is_symlink() else sha(p)) for p in sorted(app.rglob('*')) if p.is_symlink() or p.is_file()}
 before=inventory()
 checker=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
 rows=[]
 scenes=os.environ.get('RELEASE112_PROBE_SCENES','bunny-112,home-layout,edit-save').split(',')
 assert all(x in {'bunny-112','home-layout','edit-save','caret-split'} for x in scenes)
 for scene in scenes:
  code=run([sys.executable,'-B',Path(__file__).resolve(),'worker',scene,app,out/scene],'worker-'+scene+'.log',1200)
  rows.append(dict(scene=scene,exit=code));print(json.dumps(rows[-1]),flush=True)
 units=os.environ.get('RELEASE112_PROBE_UNITS','').split(',') if os.environ.get('RELEASE112_PROBE_UNITS') else (['test_caption_editor_a','test_home_responsive_cards'] if len(scenes)==3 else [])
 assert all(x in {'test_caption_editor_a','test_home_responsive_cards','test_editor_review_interaction'} for x in units)
 for selector in units:
  env=dict(os.environ,QT_QPA_PLATFORM='offscreen',TWOBYTEASR_TEST_ROOT=str(out/('unit-profile-'+selector)))
  with (out/(selector+'.log')).open('wb') as log:
   try:
    r=subprocess.run([sys.executable,'-B','-m','pytest','-vv','tests/'+selector+'.py','--junitxml',str(out/(selector+'.xml'))],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=180);code=r.returncode
   except subprocess.TimeoutExpired:code=124
  rows.append(dict(scene=selector,exit=code))
 if all(row['exit']==0 for row in rows):
  markers=True
  if 'bunny-112' in scenes:
   geometry=json.loads((out/'bunny-112/P2-row-layout-sand.json').read_text('utf-8'));markers &= geometry['after']['ready']
  if 'home-layout' in scenes:
   home=json.loads((out/'home-layout/result.json').read_text('utf-8'));markers &= any('layout_' in k and '_80_' in k for k in home['metrics'])
  if 'edit-save' in scenes:
   edit=json.loads((out/'edit-save/result.json').read_text('utf-8'));markers &= {x['trigger'] for x in edit['edits']}=={'enter','shift-e','confirm-button'}
  rows.append(dict(scene='corrected-fixtures-observed',exit=0 if markers else 1))
 after=inventory();same=before==after
 result=dict(scope_scenes=scenes,source_tests_executed=bool(units),source_test_files=units,passed=all(x['exit']==0 for x in rows) and same,product_source=PRODUCT,checker_source=checker,dmg_sha256=receipt['artifact']['sha256'],bundle_unchanged=same,bundle_files=len(before),results=rows)
 (out/'preflight-result.json').write_text(json.dumps(result,indent=2),'utf-8');print(json.dumps(result),flush=True)
 return int(not result['passed'])
if __name__=='__main__':
 if len(sys.argv)>1 and sys.argv[1]=='worker':raise SystemExit(worker(sys.argv[2],Path(sys.argv[3]),Path(sys.argv[4])))
 raise SystemExit(main())
