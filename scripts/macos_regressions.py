# SPDX-License-Identifier: GPL-3.0-only
"""Run the existing Mac regression set in isolated per-file Qt processes."""
from pathlib import Path
import argparse,json,os,subprocess,sys,time,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
SELECTORS=['tests/test_media_tool_root.py', 'tests/test_audit_isolation.py', 'tests/test_worker_device_telemetry.py', 'tests/test_asr_worker_utf8_payload.py', 'tests/test_bilingual_display_and_translation_flow.py', 'tests/test_macos_caption_visibility.py', 'tests/test_macos_binary_audit.py', 'tests/test_macos_compatibility.py', 'tests/test_macos_compat_native.py', 'tests/test_macos_wheels.py', 'tests/test_macos_platform.py', 'tests/test_macos_build_contract.py', 'tests/test_macos_gui_prepare.py', 'tests/test_macos_delivery_boundary.py', 'tests/test_macos_media_installation.py', 'tests/test_studio_qt_preview.py', 'tests/test_python_runtime_identity.py', 'tests/test_macos_desktop_evidence.py', 'tests/test_macos_setup_delivery.py', 'tests/test_blank_project_projection.py', 'tests/test_razor_caption_conservation.py', 'tests/test_playhead_edit_target.py', 'tests/test_static_caption_long_command.py::test_file_graph_keeps_external_relative_inputs_and_callbacks', 'tests/test_no_cuda_cloud_asr.py', 'tests/test_api_setup_guide.py', 'tests/test_macos_keychain_store.py', 'tests/test_mlx_backend.py', 'tests/test_mac_gpu_workshop.py']
DESELECTED='tests/test_playhead_edit_target.py::test_overlap_priority_stable_with_reorder_visibility_locks_and_track_choice'
SELECTORS.insert(1, 'tests/test_audio_endpoint_observation_owner.py')
SELECTORS[2:2] = ['tests/test_audio_output_failure_latch.py', 'tests/test_audio_clock_endpoint_epoch.py',
                  'tests/test_silent_preview_audio_clock.py', 'tests/test_audio_readiness_contract.py']
SELECTORS.extend(['tests/test_async_save_callers.py', 'tests/test_bilingual_text_targets.py',
                  'tests/test_bilingual_text_ui.py', 'tests/test_caption_commit_normalization.py',
                  'tests/test_package_layout.py', 'tests/test_persistence_queue.py',
                  'tests/test_studio_manual_save.py', 'tests/test_studio_save_lag.py',
                  'tests/test_studio_search_lag.py'])
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--qa-root',required=True,type=Path);a=parser.parse_args()
 root=a.qa_root.resolve()
 if 'tmp' not in {x.casefold() for x in root.parts}:raise ValueError('Owned tmp QA root required')
 out=root/'regressions';out.mkdir(parents=True,exist_ok=False);(root/'pytest').mkdir(parents=True,exist_ok=True);rows=[];combined=ET.Element('testsuites')
 for i,selector in enumerate(SELECTORS):
  junit=out/f'{i:02d}.xml';log=out/f'{i:02d}.log';start=time.monotonic()
  env=dict(os.environ,QT_QPA_PLATFORM='offscreen',PYTHONUTF8='1',TWOBYTEASR_TEST_ROOT=str(root/'regression-profiles'/str(i)))
  command=[sys.executable,'-B','-m','pytest','-q',selector,'--deselect',DESELECTED,'--basetemp',str(root/'pytest'/str(i)),'--junitxml',str(junit)]
  try:
   with log.open('wb')as stream:done=subprocess.run(command,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=180)
   code=done.returncode
  except subprocess.TimeoutExpired:code=124
  if junit.is_file():
   tree=ET.parse(junit).getroot()
   for suite in list(tree)if tree.tag=='testsuites'else[tree]:combined.append(suite)
  row=dict(selector=selector,exit_code=code,seconds=round(time.monotonic()-start,3),log=str(log),junit=str(junit));rows.append(row)
  ET.ElementTree(combined).write(root/'tests.xml',encoding='utf-8',xml_declaration=True)
  (root/'macos-regressions.json').write_text(json.dumps(dict(passed=all(x['exit_code']==0 for x in rows),files=rows,deselected=[DESELECTED]),indent=2),'utf8')
  print(json.dumps(row),flush=True)
  if code:print(log.read_text('utf8',errors='replace')[-24000:],flush=True)
 return int(any(x['exit_code'] for x in rows))
if __name__=='__main__':raise SystemExit(main())
