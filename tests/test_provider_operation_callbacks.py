from types import SimpleNamespace
from twobyteasr.providers.request_operations import RequestOperations
from twobyteasr.studio.studio_ai_flow import StudioAIFlowMixin


def test_wrong_request_id_and_late_generation_cannot_replace_current_ui():
    registry=RequestOperations();old=registry.begin('detect',1);new=registry.begin('test',2)
    updates=[];label=SimpleNamespace(setText=lambda value:updates.append(value))
    page=SimpleNamespace(_ai_operation_registry=lambda:registry,_ai_provider_probe_generation=2,
        _refresh_ai_design_provider_summary=lambda:None,ai_test_connection=label,
        _apply_ai_provider_status=lambda state,message:updates.append((state,message)),
        ai_provider=SimpleNamespace(currentData=lambda:'codex_cli'),_merge_discovered_models=lambda *args:None)
    handler=StudioAIFlowMixin._ai_provider_probe_finished
    handler(page,2,'ERROR','wrong',{'request_id':old.request_id,'models':()})
    assert not updates and not new.done
    handler(page,1,'ERROR','old',{'request_id':old.request_id,'models':()})
    assert not updates and old.done
    handler(page,2,'SESSION READY','new',{'request_id':new.request_id,'models':()})
    assert ('SESSION READY','new') in updates and new.done
    count=len(updates)
    handler(page,2,'ERROR','duplicate',{'request_id':new.request_id,'models':()})
    assert len(updates)==count
