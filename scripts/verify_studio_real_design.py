"""One real design using the existing endpoint, with read-only credentials and isolated outputs."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import time
import uuid


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--settings',type=Path,required=True)
    parser.add_argument('--secrets-file',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):parser.error('fresh tmp output required')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out);os.environ['QT_QPA_PLATFORM']='offscreen'
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.storage.settings import load_runtime_settings
    settings,_,warnings=load_runtime_settings(project_root=args.settings.parent)
    from twobyteasr.providers import llm_config
    read=llm_config._read_secrets
    llm_config._read_secrets=lambda **_:read(read_only_path=args.secrets_file)
    from twobyteasr.providers.provider_registry import GLOBAL_PROVIDER_REGISTRY
    endpoint=llm_config.endpoint_from_settings(settings,'polish')
    receipt=dict(kind='real-provider-generation',request_id=uuid.uuid4().hex,
        provider=endpoint.get('provider'),model=endpoint.get('model'),
        credential_available=bool(endpoint.get('api_key')),settings_read_only=True,
        sample='one candidate, 300-second total deadline, original configured endpoint and model')
    def save():(out/'result.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf8')
    save();print(json.dumps(receipt,ensure_ascii=False),flush=True)
    if not endpoint.get('api_key'):
        receipt.update(passed=False,status='credentials_unavailable');save();return 2
    settings.setdefault('models',{}).update(ai_design_mode='single',ai_design_candidate_count=1)
    GLOBAL_PROVIDER_REGISTRY.bind(settings)
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue,save_project
    p=SubtitleProject(media=StudioMedia('',duration_ms=4000,width=1920,height=1080),
        cues=[StudioCue('design-a',0,4000,'朝起きて 歯を磨いて')])
    save_project(p,out/'request.2byteproj')
    from twobyteasr.caption_design.studio_ai import request_web_theme_design
    began=time.monotonic()
    try:
        suggestion=request_web_theme_design(p,'design-a','「日常」动漫的风格',runtime_settings=settings,
            request_id=receipt['request_id'],raw_user_prompt='「日常」动漫的风格',
            ledger_root=out/'creative',deadline_seconds=300,
            stage_callback=lambda text:print(str(text)[:180],flush=True))
        (out/'suggestion.json').write_text(json.dumps(asdict(suggestion),ensure_ascii=False,indent=2),'utf8')
        valid=[c for c in suggestion.concepts if c.get('technical_status')!='failed' and c.get('authored_theme')]
        receipt.update(passed=bool(valid),status='generated' if valid else 'validation_failed',
            candidates=[dict(id=c.get('id'),status=c.get('technical_status'),errors=c.get('technical_errors')) for c in suggestion.concepts])
    except Exception as exc:
        from twobyteasr.providers.provider_diagnostics import redact_diagnostics
        receipt.update(passed=False,status='failed',category=getattr(exc,'category',type(exc).__name__),
            error=redact_diagnostics(str(exc)))
    receipt['elapsed_seconds']=round(time.monotonic()-began,2);save()
    print(json.dumps(receipt,ensure_ascii=False),flush=True)
    return 0 if receipt['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
