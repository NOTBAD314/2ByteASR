# SPDX-License-Identifier: GPL-3.0-only
"""Distinguish a real app from relocation/startup and desktop acceptance."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path


def summarize(root: Path) -> dict:
    def read(name):
        path=root/name
        return json.loads(path.read_text('utf8')) if path.is_file() else {}
    build=read('build/native-build-inputs.json');validation=build.get('native_validation',{})
    def status(record,key='passed'):
        return 'not_executed' if not record or record.get('status') == 'not_executed' else ('passed' if record.get(key) is True else 'failed')
    app='passed' if validation.get('app_built') else ('failed' if build else 'not_executed')
    relocation=validation.get('relocation',{})
    archive=read('build/release-artifacts.mac.json').get('artifact')
    return dict(media=status(read('media/media-install.json')),app=app,
        archive=archive,relocation=('passed' if relocation.get('bytes_permissions_symlinks_match') else ('failed' if app=='passed' else 'not_executed')),
        dmg=status(read('dmg/dmg-result.json')),
        installer=read('dmg/dmg-result.json').get('artifact'),
        blank_project=status(read('blank-project/blank-project-summary.json')),
        startup=status(validation.get('packaged_normal_entry_startup_smoke',{})),
        model_preparation=status(read('desktop-flow/workshop-result.json')),
        home_studio=status(read('desktop-flow/result.json')),
        restart_reuse=status(read('desktop-flow/restart-summary.json')),
        export_decode=status(read('desktop-flow/export-validation.json')),
        runtime_identity=status(read('runtime-identity.json')),
        embedded_preview=status(read('native-media-smoke/result.json')),
        hardware=status(read('hardware-probe/result.json'),'hardware_encode_passed'),
        cloud_only=status(read('cloud-only/result.json')),
        keychain=status(read('keychain/result.json')),
        mlx=status(read('mlx/result.json')),
        cloud_mlx=status(read('cloud-mlx/result.json')),
        cloud_mlx_requested=os.environ.get('CLOUD_MLX_REQUESTED','false')=='true',
        test_step=os.environ.get('TEST_OUTCOME','unknown'),
        model_requested=os.environ.get('MODEL_REQUESTED','false')=='true',
        source_sha=os.environ.get('SOURCE_SHA'),workflow_identity=read('workflow-identity.json'))


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--qa-root',required=True,type=Path);parser.add_argument('--enforce',action='store_true')
    args=parser.parse_args(argv)
    if not args.qa_root.is_dir():return 1 if args.enforce else 0
    saved=args.qa_root/'ci-status.json'
    record=json.loads(saved.read_text('utf8')) if args.enforce and saved.is_file() else summarize(args.qa_root)
    if not args.enforce:(args.qa_root/'ci-status.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n','utf8')
    print(json.dumps(record,ensure_ascii=False))
    if args.enforce:
        required=['runtime_identity','media','app','relocation','startup','dmg','blank_project']+(['model_preparation','home_studio','restart_reuse','export_decode'] if record['model_requested'] else [])+(['cloud_only','keychain','mlx','cloud_mlx'] if record.get('cloud_mlx_requested') else [])
        selection_path=args.qa_root/'artifacts/receipts/artifact-selection.json'
        selection=json.loads(selection_path.read_text('utf8')) if selection_path.is_file() else {}
        delivered=any(row['path'].endswith('.dmg') for row in selection.get('files',[]))
        return 0 if all(record.get(k)=='passed' for k in required) and record['test_step']=='success' and delivered else 1
    return 0


if __name__=='__main__':raise SystemExit(main())
