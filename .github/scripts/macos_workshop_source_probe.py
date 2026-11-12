from pathlib import Path
import argparse,hashlib,json,os,platform,shutil,subprocess,sys
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--tools',type=Path,required=True);a=p.parse_args()
assert sys.platform=='darwin' and platform.machine()=='arm64'
root=a.source.resolve();out=a.out.resolve();assert 'tmp' in out.parts and not out.exists();out.mkdir(parents=True)
tools=root/'tools';backup=root/'tmp/probe-original-tools';backup.parent.mkdir(exist_ok=True)
if tools.exists():
 assert tools.resolve().is_relative_to(root) and not backup.exists()
 tools.rename(backup)
tools.symlink_to(a.tools.resolve(),target_is_directory=True)
sys.path[:0]=[str(root),str(root/'scripts')]
from scripts.verify_blank_project_macos import blank_environment
from twobyteasr.projects.studio_project import StudioMedia,SubtitleProject,save_project
target=save_project(SubtitleProject(StudioMedia('')),out/'startup.2byteproj')
invoker=out.parent.parent
env=blank_environment(out,invoker,target)
env.update(TWOBYTEASR_ACCEPTANCE_SCENARIO='vm2-model-settings',TWOBYTEASR_WORKSHOP_COLUMNS_ONLY='1',PYTHONUTF8='1',TWOBYTEASR_MAIN_PYTHON=sys.executable)
with (out/'source-run.log').open('wb') as log:
 process=subprocess.run([sys.executable,'-B',str(root/'scripts/macos_launch.py')],cwd=invoker,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=660)
result=json.loads((out/'result.json').read_text('utf8')) if(out/'result.json').exists() else {}
failures=[x for x in result.get('checks',[]) if not x['passed']]
record=dict(source_only=True,packaged_verification=False,source=str(root),process_exit=process.returncode,passed=result.get('passed',False),checks=len(result.get('checks',[])),failed_count=len(failures),first_failed=failures[:5],error=result.get('error'),host=dict(system=platform.system(),machine=platform.machine(),macos=platform.mac_ver()[0]))
(out/'source-probe-summary.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),'utf8');print(json.dumps(record,ensure_ascii=False))
if not result:print((out/'source-run.log').read_text('utf8',errors='replace')[-5000:])
assert result,'Source application did not produce an audit; inspect source-run.log'
