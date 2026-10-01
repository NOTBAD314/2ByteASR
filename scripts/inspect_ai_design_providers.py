"""Read configured app selections/capabilities without exporting credentials."""
import copy
import json
import os
from pathlib import Path
import sys


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    from twobyteasr import settings as settings_module
    from twobyteasr.llm_config import AI_SERVICE_SPECS,activate_ai_service,get_active_service,service_model_catalog
    from twobyteasr.provider_registry import GLOBAL_PROVIDER_REGISTRY
    from twobyteasr.provider_service import GLOBAL_PROVIDER_SERVICE
    source=Path(os.environ['LOCALAPPDATA'])/'2ByteASR'/settings_module.SETTINGS_FILENAME
    raw=source.read_bytes()
    settings,_=settings_module._merge_known_settings(settings_module.DEFAULT_SETTINGS,json.loads(raw))
    rows=[]
    for service in AI_SERVICE_SPECS:
        trial=copy.deepcopy(settings);activate_ai_service(trial,service)
        selected=GLOBAL_PROVIDER_REGISTRY.selection(trial)
        client=GLOBAL_PROVIDER_SERVICE.client_for_stage(trial,'polish')
        caps=client.capabilities()
        rows.append(dict(service=service,provider=selected.provider,model=selected.model,
            transport=selected.transport,credential_configured=selected.credential_ready,
            models=list(service_model_catalog(trial,service)),capabilities=vars(caps),
            availability='not yet live-tested'))
    result=dict(default_service=get_active_service(settings),source_settings_unchanged=source.read_bytes()==raw,
        provider_calls=0,providers=rows)
    out=root/'tmp/ai-design-quality-20260916/provider-inventory.json'
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    print(json.dumps(result,ensure_ascii=False,default=str))


if __name__=='__main__':main()
