"""Opt-in frozen-build acceptance on a temporary copied project.

No arbitrary code is loaded. The audit requires an output and project under
cwd/tmp and isolated APPDATA/LOCALAPPDATA; normal launches do not run it.
"""
from __future__ import annotations
import json, os, time, threading
from pathlib import Path

_audit_provider_scope = threading.local()

def _audit_submit_gate(submit, scenario):
    def checked(*args, **kwargs):
        if scenario == 'glossary-execution' and getattr(_audit_provider_scope, 'public_glossary', False):
            return submit(*args, **kwargs)
        raise RuntimeError('Background provider requests are not authorized in this audit')
    return checked

def require(value, message='acceptance requirement failed'):
    """Frozen builds use optimize=1; acceptance gates must not be asserts."""
    if not value:
        raise AssertionError(message)

def audit_tmp_root() -> Path:
    # The daily launcher changes cwd to the bundle; it preserves its invoker's
    # directory explicitly. Output remains restricted to that directory/tmp.
    return (Path(os.environ.get('TWOBYTEASR_INVOKER_CWD') or Path.cwd())/'tmp').resolve()

def audit_directory() -> Path | None:
    value = os.environ.get('TWOBYTEASR_ACCEPTANCE_DIR', '')
    if not value: return None
    output = Path(value).resolve()
    if not output.is_relative_to(audit_tmp_root()):
        raise ValueError('Acceptance output must be under cwd/tmp')
    project = Path(os.environ.get('TWOBYTEASR_STARTUP_PROJECT', '')).resolve()
    if not project.is_file() or not project.is_relative_to(output):
        raise ValueError('Acceptance requires its own copied project')
    profile_value=os.environ.get('TWOBYTEASR_ACCEPTANCE_PROFILE_DIR','')
    if profile_value:
        profile=Path(profile_value).resolve()
        if (os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO')!='unified-studio'
                or not profile.is_relative_to(audit_tmp_root()) or not output.is_relative_to(profile)
                or Path(os.environ.get('TWOBYTEASR_TEST_ROOT','')).resolve()!=profile):
            raise ValueError('Acceptance requires its explicit owned unified tmp profile')
        for key,leaf in (('LOCALAPPDATA','local'),('APPDATA','roaming')):
            if Path(os.environ.get(key,'')).resolve()!=profile/leaf:
                raise ValueError('Acceptance profile app data must match isolated paths exactly')
        return output
    for key in ('LOCALAPPDATA', 'APPDATA'):
        if not Path(os.environ.get(key, '')).resolve().is_relative_to(output):
            raise ValueError('Acceptance requires isolated app data')
    return output

def isolate_acceptance_settings() -> None:
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'seven-issues':
        from .blank_project_audit import install_offline_guards
        install_offline_guards()
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'timeline-sync':
        from .blank_project_audit import install_offline_guards
        install_offline_guards()
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') in ('razor-word-split', 'ja-bilingual', 'bilingual-playback', 'speaker-roles', 'mcp', 'ctc-refine'):
        from .blank_project_audit import install_offline_guards
        install_offline_guards()
        output = audit_directory()
        if output is not None and os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') in ('ja-bilingual', 'ctc-refine'):
            # Re-alignment runs the real aligner from the declared read-only
            # model folder and existing main runtime (hashed manifest).
            from .glossary_live_resources import install
            install(output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'six-fixes':
        output = audit_directory()
        if output is not None:
            from PySide6.QtCore import QSettings
            QSettings.setDefaultFormat(QSettings.Format.IniFormat)
            QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(output/'qt-settings'))
            QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.SystemScope, str(output/'qt-system'))
        from .blank_project_audit import install_offline_guards
        install_offline_guards()
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'user-feedback-editor':
        from .blank_project_audit import install_offline_guards
        install_offline_guards()
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'workshop-daily':
        output = audit_directory()
        if output is not None:
            from PySide6.QtCore import QSettings
            # Keep UI preferences in the owned profile. Stable registered
            # runtimes/models are allowed without TEST_ROOT's tmp-only filter.
            QSettings.setDefaultFormat(QSettings.Format.IniFormat)
            QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(output/'qt-settings'))
            QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.SystemScope, str(output/'qt-system'))
            from .blank_project_audit import install_offline_guards
            install_offline_guards()
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'unified-studio':
        from .blank_project_audit import install_offline_guards
        install_offline_guards()
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'moss-full-context':
        from .blank_project_audit import install_offline_guards
        install_offline_guards()
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'perf-pages':
        # Page-entry timing on a prepared copy of the real profile: keep its
        # settings, reports and project library (TWOBYTEASR_TEST_ROOT); no network.
        from .blank_project_audit import install_offline_guards
        install_offline_guards()
        output = audit_directory()
        if output is not None:
            # Windowed builds have no stderr: keep native-fault stacks.
            import faulthandler
            stream = (output/'audit-native-fault.log').open('w', encoding='utf8')
            globals()['_audit_fault_stream'] = stream  # kept open for the process lifetime
            faulthandler.enable(file=stream, all_threads=True)
        return
    scenario=os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO')
    if scenario in {'real-glossary-repair','real-glossary-repair-live'}:
        output=audit_directory()
        if output is not None:
            from .real_glossary_repair_audit import install
            install(output)
        return
    if scenario in {'toolbar-scope','storage-media-relink','real-storage-after'}:
        from .blank_project_audit import install_offline_guards
        install_offline_guards()
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') in {'glossary-input','glossary-input-restore'}:
        from .blank_project_audit import install_offline_guards
        install_offline_guards()
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'storage-settings':
        from .blank_project_audit import install_offline_guards
        install_offline_guards()
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'storage-media':
        from .media_storage_audit import install_offline_guards
        install_offline_guards()
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'recognition-correctness':
        from .blank_project_audit import install_offline_guards
        install_offline_guards()
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') in {'five-fix-ui', 'persisted-layout', 'export-target-real'}:
        from .blank_project_audit import install_offline_guards
        install_offline_guards()
    output = audit_directory()
    if output is None: return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') in {'glossary-live-home', 'perf-recognition'}:
        from .glossary_live_resources import install
        install(output)
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'glossary-live-recheck':
        from .glossary_live_recheck_audit import install
        install(output)
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'glossary-review-live':
        from .glossary_review_live_guard import install
        install(output)
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'completion-real':
        from .blank_project_audit import install_offline_guards
        install_offline_guards()
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'login-json-production':
        # Only the normal Studio review button spends the live test budget.
        from .ui import EndpointEditor
        from .studio_ai_flow import StudioAIFlowMixin
        EndpointEditor._queue_model_discovery=lambda *a:None
        StudioAIFlowMixin._start_ai_provider_probe=lambda *a,**kw:None
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'full-library-real':
        from .ui import EndpointEditor
        from .studio_ai_flow import StudioAIFlowMixin
        EndpointEditor._queue_model_discovery=lambda *a:None
        StudioAIFlowMixin._start_ai_provider_probe=lambda *a,**kw:None
        from . import llm_config
        source=Path(os.environ['TWOBYTEASR_ACCEPTANCE_CREDENTIAL_SOURCE']).resolve()
        operator=Path(os.environ['TWOBYTEASR_ACCEPTANCE_OPERATOR_PROFILE']).resolve()
        if source!=(operator/'AppData/Local/2ByteASR/secrets.dat').resolve():
            raise ValueError('Real full-build audit only reads the existing application credential store')
        reader=llm_config._read_secrets
        llm_config._read_secrets=lambda:reader(read_only_path=source)
        from .provider_service import ProviderService
        submit=ProviderService.submit
        approved_store=json.loads((output/'local/2ByteASR/learned_game_terms.json').read_text('utf8'))
        approved_names={str(row['to']) for row in approved_store['games']['瓦罗兰特']['mappings']}
        request_count=[0]
        def approved_build_submit(service, settings, stage, messages, **kwargs):
            if kwargs.get('_adapter_stage')!='glossary_update' or request_count[0]>=2:
                raise RuntimeError('Only two approved full-library model requests are authorized')
            endpoint=llm_config.endpoint_from_settings(settings,'polish')
            if endpoint.get('base_url')!='https://api.deepseek.com/v1' or endpoint.get('provider')!='deepseek':
                raise RuntimeError('Only the approved official DeepSeek destination is authorized')
            users=[json.loads(row['content']) for row in messages if row.get('role')=='user']
            for body in users:
                if set(body)!={'game','documents','existing_terms','collected_terms','phase'} or body['game']!='瓦罗兰特':
                    raise RuntimeError('Unapproved private/project payload blocked')
                if not set(body['existing_terms']).issubset(approved_names):
                    raise RuntimeError('Unapproved existing terms blocked')
                for document in body['documents']:
                    from .smart_glossary import is_safe_web_url
                    if not document['url'].startswith('https://') or not is_safe_web_url(document['url'])[0]:
                        raise RuntimeError('Only actual public source documents are authorized')
            request_count[0]+=1
            (output/f'approved-model-input-{request_count[0]}.json').write_text(json.dumps(messages,ensure_ascii=False,indent=2),'utf8')
            return submit(service,settings,stage,messages,**kwargs)
        ProviderService.submit=approved_build_submit
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') in {'project-entity-confirmation', 'external-project-entry', 'blank-project', 'terminology-effective', 'terminology-restore', 'real-correction-copy', 'full-library-replay', 'glossary-manual-case', 'glossary-manual-case-restore', 'glossary-chain', 'glossary-chain-restore', 'glossary-chain-apply', 'glossary-review-real', 'overlap-review-real'}:
        from .blank_project_audit import install_offline_guards
        install_offline_guards()
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') in {'macos-desktop', 'home-release-flow'}:
        from .ui import EndpointEditor
        from .studio_ai_flow import StudioAIFlowMixin
        from .provider_service import ProviderService
        EndpointEditor._queue_model_discovery=lambda *a:None
        StudioAIFlowMixin._start_ai_provider_probe=lambda *a,**kw:None
        ProviderService.submit=_audit_submit_gate(ProviderService.submit, os.environ['TWOBYTEASR_ACCEPTANCE_SCENARIO'])
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') in {'cue-affix-checks', 'data-roots', 'product-brand', 'localization', 'support-entry', 'gpl-migration'}:
        from .ui import EndpointEditor
        from .studio_ai_flow import StudioAIFlowMixin
        from .provider_service import ProviderService
        EndpointEditor._queue_model_discovery=lambda *a:None
        StudioAIFlowMixin._start_ai_provider_probe=lambda *a,**kw:None
        def deny_cue_audit_provider(*a, **kw):
            raise RuntimeError('No provider calls authorized in cue/affix acceptance')
        ProviderService.submit=deny_cue_audit_provider
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') in {'moss-cue-paging','config-audio-fidelity','installer-model-qa','glossary-execution','glossary-layout'}:
        from .ui import EndpointEditor
        from .studio_ai_flow import StudioAIFlowMixin
        from .provider_service import ProviderService
        EndpointEditor._queue_model_discovery=lambda *a:None
        StudioAIFlowMixin._start_ai_provider_probe=lambda *a,**kw:None
        ProviderService.submit=_audit_submit_gate(ProviderService.submit, os.environ['TWOBYTEASR_ACCEPTANCE_SCENARIO'])
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO')=='asr-backends':
        from .ui import EndpointEditor
        from .studio_ai_flow import StudioAIFlowMixin
        from .provider_service import ProviderService
        EndpointEditor._queue_model_discovery=lambda *a:None
        StudioAIFlowMixin._start_ai_provider_probe=lambda *a,**kw:None
        def denied(*a,**kw):raise RuntimeError('No model calls authorized by this local contract audit')
        ProviderService.submit=denied
    # Windowed frozen builds have no stderr. Keep a dedicated descriptor alive
    # for the process lifetime so native faults in an opt-in audit retain stacks.
    import faulthandler
    global _audit_fault_stream
    phase=os.environ.get('TWOBYTEASR_NORMAL_AI_PHASE','audit')
    _audit_fault_stream=(output/(phase+'-native-fault.log')).open('w',encoding='utf8')
    faulthandler.enable(file=_audit_fault_stream,all_threads=True)
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') in {'primary-native-home','audio-output-workflow','independent-caption-workflow','selection-transitions-workflow','release-blockers','workflow-fixes','workflow-sustained-audio','workflow-glossary-selection'}:
        from .ui import EndpointEditor
        EndpointEditor._queue_model_discovery = lambda *a: None
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO')=='single-track-recognition':
        from .studio_ai_flow import StudioAIFlowMixin
        StudioAIFlowMixin._start_ai_provider_probe=lambda *args,**kwargs:None
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') in {'primary-native-home','audio-output-workflow','independent-caption-workflow','selection-transitions-workflow','cue-affix-checks','moss-cue-paging','multisource','workflow-glossary-selection','workflow-sustained-audio','workflow-fixes','release-blockers','timeline-delivery', 'export-sync', 'gradient-word','cut-range-frame','cover-editor','cover-workflow','cover-gimp','cover-frame','workshop-playhead'}:
        from .studio_ai_flow import StudioAIFlowMixin
        StudioAIFlowMixin._start_ai_provider_probe=lambda *args,**kwargs:None
        import socket
        original_connect=socket.socket.connect
        def local_only(sock,address):
            if address[0] not in {'127.0.0.1','::1','localhost'}:
                raise RuntimeError('External network prohibited in timeline UI audit')
            return original_connect(sock,address)
        socket.socket.connect=local_only
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') in {'normal-ai','r5-repair-live'}:
        if os.environ.get('TWOBYTEASR_AI_TEXT_ONLY')=='1':
            from .studio_ai_flow import StudioAIFlowMixin
            StudioAIFlowMixin._capture_ai_vision_frame=lambda *a,**k:None
        credential_source=os.environ.get('TWOBYTEASR_ACCEPTANCE_CREDENTIAL_SOURCE')
        if credential_source:
            from . import llm_config
            source=Path(credential_source).resolve()
            expected=(Path(os.environ['USERPROFILE'])/'AppData/Local/2ByteASR/secrets.dat').resolve()
            if source!=expected:raise ValueError('Acceptance credential source must be the existing application store')
            reader=llm_config._read_secrets
            llm_config._read_secrets=lambda:reader(read_only_path=source)
        budget_path=os.environ.get('TWOBYTEASR_AI_CALL_BUDGET')
        if budget_path:
            from .ai_design_call_budget import install_acceptance_budget
            install_acceptance_budget(Path(budget_path))
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'user-feedback-r3':
        from .studio_ai_flow import StudioAIFlowMixin
        StudioAIFlowMixin._start_ai_provider_probe=lambda *args,**kwargs:None
        import socket
        connect=socket.socket.connect
        def local_only(sock,address):
            if address[0] not in {'127.0.0.1','::1','localhost'}:raise RuntimeError('External network prohibited in r3 media audit')
            return connect(sock,address)
        socket.socket.connect=local_only
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') in {'short-closeout','dual-track-recovery','visible-playback','speaker-workflow','caption-runtime','normal-ai','r5-repair-live','p62-regression','selection-geometry','caption-boundary','terminology-polish','user-failures'}:
        # Rendering saved themes must not spend the task's model-request
        # budget through an automatic readiness probe.
        from .studio_ai_flow import StudioAIFlowMixin
        StudioAIFlowMixin._start_ai_provider_probe=lambda *args,**kwargs:None
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') in {'speaker-workflow', 'caption-runtime', 'p62-regression','selection-geometry','caption-boundary','user-failures','support-entry','gpl-migration'}:
        import socket
        connect = socket.socket.connect
        def local_only(sock, address):
            if address[0] not in {'127.0.0.1', '::1', 'localhost'}:
                raise RuntimeError('External network prohibited during speaker workflow audit')
            return connect(sock, address)
        socket.socket.connect = local_only
    temporary = output/'temp'
    temporary.mkdir(exist_ok=True)
    os.environ.update(TMP=str(temporary), TEMP=str(temporary))
    from PySide6 import QtCore
    original = QtCore.QSettings
    class AuditSettings(original):
        def __init__(self, *args, **kwargs):
            super().__init__(str(output/'qt.ini'), original.Format.IniFormat)
    if not os.environ.get('TWOBYTEASR_TEST_ROOT'):
        QtCore.QSettings = AuditSettings
    from . import settings
    settings.stable_settings_root = lambda: output/'config'
    from . import studio_project
    preferences=output/'studio-settings.json'
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') != 'external-project-entry' or not preferences.is_file():
        preferences.write_text(json.dumps({'recent_projects': [], 'project_root': str(output/'projects'),
            'studio_preferences': {'autosave_enabled': False,
                'auto_cover': os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'workflow-fixes',
                'recovery_policy': 'official'}}))
    studio_project.studio_settings_path=lambda *a:preferences
    studio_project.project_library_root=lambda *a:output/'projects'
    if os.environ.get('TWOBYTEASR_READINESS_VISUAL')=='1':
        from .studio_readiness import StudioReadiness
        original_mark,original_fail=StudioReadiness.mark,StudioReadiness.fail
        def capture(gate,name):
            if gate.overlay.isVisible():
                # This proves the Qt loading surface only, never native video.
                gate.overlay.grab().save(str(output/f'loading-{name}.png'))
        def mark(gate,name):
            fresh=name not in gate.completed
            original_mark(gate,name)
            if fresh:
                index=len(gate.completed)
                QtCore.QTimer.singleShot(0,lambda:capture(gate,index))
        def fail(gate,stage,error):
            original_fail(gate,stage,error)
            QtCore.QTimer.singleShot(0,lambda:capture(gate,'error'))
        StudioReadiness.mark,StudioReadiness.fail=mark,fail

def start_acceptance(window) -> None:
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'update-flow':
        from .update_flow_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'perf-regression':
        from .perf_regression_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'perf-pages':
        from .perf_pages_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'perf-recognition':
        from .perf_recognition_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'seven-issues':
        from .studio_seven_issues_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'razor-word-split':
        from .razor_split_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'ja-bilingual':
        from .ja_bilingual_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'bilingual-playback':
        from .bilingual_playback_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'speaker-roles':
        from .speaker_roles_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'mcp':
        from .mcp_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'ctc-refine':
        from .ctc_refine_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'six-fixes':
        from .six_fixes_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'timeline-sync':
        from .timeline_sync_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'user-feedback-editor':
        from .user_feedback_editor_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'workshop-daily':
        from .unified_studio_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'unified-studio':
        from .unified_studio_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'moss-full-context':
        from .moss_progress_ui_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    scenario=os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO')
    if scenario in {'real-glossary-repair','real-glossary-repair-live','toolbar-scope','storage-media-relink','real-storage-after'}:
        output=audit_directory()
        if output is not None:
            if scenario == 'toolbar-scope':
                from .toolbar_scope_audit import start
            elif scenario == 'storage-media-relink':
                from .storage_media_relink_audit import start
            elif scenario == 'real-storage-after':
                from .real_storage_after_audit import start
            else:
                from .real_glossary_repair_audit import start
            start(window,output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') in {'glossary-input','glossary-input-restore'}:
        from .glossary_input_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'storage-settings':
        from .storage_settings_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'storage-media':
        from .media_storage_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'recognition-correctness':
        from .recognition_correctness_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'export-target-real':
        from .export_target_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'project-entity-confirmation':
        from .project_entity_confirmation_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'five-fix-ui':
        from .five_fix_ui_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'persisted-layout':
        from .persisted_layout_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'login-json-production':
        from .login_json_production_audit import start
        output = audit_directory()
        if output is not None:
            start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'external-project-entry':
        from .external_project_entry_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'overlap-review-real':
        from .overlap_review_real_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') in {'glossary-review-real', 'glossary-review-live'}:
        from .glossary_review_real_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'completion-real':
        from .completion_real_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') in {'glossary-manual-case', 'glossary-manual-case-restore'}:
        from .glossary_manual_case_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'full-library-replay':
        from .full_library_replay_audit import start
        output=audit_directory()
        if output is not None:start(window,output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'real-correction-copy':
        from .real_correction_copy_audit import start
        output=audit_directory()
        if output is not None:start(window,output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'full-library-real':
        from .full_library_flow_audit import start
        output=audit_directory()
        if output is not None:start(window,output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'terminology-restore':
        from .terminology_effective_studio_audit import start_restore
        output = audit_directory()
        if output is not None: start_restore(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'terminology-effective':
        from .terminology_effective_studio_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') in {'glossary-chain', 'glossary-chain-restore'}:
        from .glossary_chain_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'glossary-live-home':
        from .glossary_live_home_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'glossary-live-recheck':
        from .glossary_live_recheck_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'glossary-chain-apply':
        from .glossary_chain_apply_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'blank-project':
        from .blank_project_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'macos-desktop':
        from .macos_desktop_audit import start
        output=audit_directory()
        if output is not None:start(window,output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'home-release-flow':
        from .home_release_flow_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'gpl-migration':
        from .gpl_migration_audit import start
        output = audit_directory()
        if output is not None: start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'support-entry':
        from .support_entry_audit import start
        output = audit_directory()
        if output is not None:
            start(window, output)
        return
    if os.environ.get("TWOBYTEASR_ACCEPTANCE_SCENARIO") == "localization":
        from .localization_audit import start
        output = audit_directory()
        if output is not None:
            start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'product-brand':
        from .product_brand_audit import start
        output = audit_directory()
        if output is not None:
            start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'data-roots':
        from .data_roots_audit import start
        start(window, audit_directory())
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'cue-affix-checks':
        from .cue_affix_checks_audit import start
        output = audit_directory()
        if output is not None:
            start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'moss-cue-paging':
        from .moss_cue_paging_audit import start
        output = audit_directory()
        if output is not None:
            start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'config-audio-fidelity':
        from .config_audio_fidelity_audit import start
        output = audit_directory()
        if output is not None:
            start(window, output)
        return
    scenario = os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO')
    if scenario in {'primary-native-home', 'audio-output-workflow', 'independent-caption-workflow', 'selection-transitions-workflow'}:
        from importlib import import_module
        modules = {'primary-native-home': 'primary_native_home_audit',
                   'audio-output-workflow': 'audio_output_workflow_audit',
                   'independent-caption-workflow': 'independent_caption_workflow_audit',
                   'selection-transitions-workflow': 'selection_transitions_workflow_audit'}
        output = audit_directory()
        if output is not None:
            import_module('.' + modules[scenario], __package__).start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'multisource':
        from .studio_multisource_audit import start
        output = audit_directory()
        if output is not None:
            start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'timeline-edit':
        from .timeline_edit_audit import start
        output = audit_directory()
        if output is not None:
            start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'installer-model-qa':
        from .installer_model_qa import start
        start(window, audit_directory())
        return
    output = audit_directory()
    if output is None: return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO')=='glossary-layout':
        from .glossary_layout_audit import start
        start(window,output);return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO')=='glossary-execution':
        from .glossary_execution_audit import start
        start(window,output);return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO')=='asr-backends':
        from .asr_backends_acceptance_audit import start
        start(window,output);return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'r5-repair-live':
        from .r5_repair_acceptance_audit import start
        start(window,output);return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'project-isolation':
        from .project_isolation_audit import start
        start(window,output);return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'workflow-glossary-selection':
        from .workflow_glossary_selection_audit import start
        start(window,output);return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'workflow-sustained-audio':
        from .workflow_sustained_audio_audit import start
        start(window,output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'workflow-fixes':
        from .workflow_acceptance_audit import start
        start(window,output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'release-blockers':
        from .release_blocker_audit import start
        start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'workshop-playhead':
        from .workshop_playhead_audit import start
        start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'compact-overlap':
        from .compact_overlap_audit import start
        start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'window-proofread':
        from .window_proofread_audit import start
        start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'proofread-workspace':
        from .proofread_workspace_audit import start
        start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'proofread-open':
        from .proofread_open_audit import start
        start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'cover-edit-performance':
        from .cover_edit_performance_audit import start
        start(window,output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'cover-frame':
        from .cover_frame_audit import start
        start(window,output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'cover-gimp':
        from .cover_gimp_audit import start
        start(window,output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'cover-workflow':
        from .cover_workflow_audit import start
        start(window,output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'cover-editor':
        if os.environ.get('TWOBYTEASR_COVER_LONG') == '1':
            from .cover_performance_audit import start
        else:
            from .cover_acceptance_audit import start
        start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'single-track-recognition':
        from .single_track_recognition_audit import start
        start(window,output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'cut-range-frame':
        from .cut_range_frame_audit import start
        start(window,output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'gradient-word':
        from .gradient_word_audit import start
        start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'export-sync':
        from .export_sync_audit import start
        start(window,output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'timeline-delivery':
        from .timeline_delivery_audit import start
        start(window,output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'recognition-delivery':
        from .recognition_delivery_audit import start
        start(window,output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'user-feedback-r3':
        from .user_feedback_r3_audit import start
        start(window,output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'windows-file-workflow':
        from .windows_file_workflow_audit import start
        start(window,output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'terminology-polish':
        from .terminology_polish_audit import start
        start(window,output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'user-failures':
        from .user_acceptance_audit import start
        start(window, output)
        return
    gate = getattr(window.studio_page, '_readiness', None)
    if gate is not None and gate.active:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(20, lambda: start_acceptance(window))
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'caption-boundary':
        from .caption_boundary_audit import start
        start(window,output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'selection-geometry':
        from .selection_geometry_audit import start
        start(window,output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'normal-ai':
        from .normal_ai_entry_audit import start
        start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'p62-regression':
        from .p62_regression_audit import start
        start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'caption-runtime':
        from .caption_runtime_audit import start
        start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'speaker-workflow':
        from .speaker_workflow_audit import start
        start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'visible-playback':
        from .visible_playback_audit import start
        start(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'long-project':
        from .long_project_acceptance_audit import start_long_project_acceptance
        start_long_project_acceptance(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'short-closeout':
        from .short_closeout_audit import start_short_closeout
        start_short_closeout(window,output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'dual-track-recovery':
        if os.environ.get('TWOBYTEASR_RECOVERY_MODE')=='theme':
            from .recovery_theme_audit import start
        else:
            from .recovery_acceptance_audit import start
        start(window,output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'theme-draft':
        from .theme_draft_acceptance_audit import start_theme_draft_acceptance
        start_theme_draft_acceptance(window,output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'reliability':
        from .reliability_acceptance_audit import start_reliability_acceptance
        start_reliability_acceptance(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'endurance':
        from .endurance_acceptance_audit import start_endurance_acceptance
        start_endurance_acceptance(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'providers':
        from .provider_acceptance_audit import start_provider_acceptance
        start_provider_acceptance(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'web-clock':
        from .web_clock_acceptance_audit import start_web_clock_acceptance
        start_web_clock_acceptance(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'live-edit':
        from .live_edit_acceptance_audit import start_live_edit_acceptance
        start_live_edit_acceptance(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'studio-polish':
        from .studio_polish_acceptance_audit import start_studio_polish_acceptance
        start_studio_polish_acceptance(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'feedback':
        from .feedback_acceptance_audit import start_feedback_acceptance
        start_feedback_acceptance(window, output)
        return
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'pipeline':
        from .pipeline_acceptance_audit import start_pipeline_acceptance
        start_pipeline_acceptance(window, output)
        return
    from PySide6.QtCore import QObject, QTimer, Qt
    from PySide6.QtGui import QFontInfo
    from .build_identity import load_build_identity

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.timer=QTimer(self); self.timer.setTimerType(Qt.TimerType.PreciseTimer)
            self.timer.setInterval(16); self.timer.timeout.connect(self.tick)
            self.started=time.perf_counter(); self.phase=-1; self.samples=[]; self.publications=[]; self.applied=[]
            self.summary=[]; self.page=window.studio_page; self.ready=False
            self.timer.start()

        def fail(self, reason):
            self.timer.stop(); (output/'acceptance.json').write_text(json.dumps({'error':reason}),encoding='utf8')

        def begin(self):
            self.ready=True; page=self.page; comp=page.video_compositor
            clip=page.project.video_tracks[1].clips[0]; self.clip=clip
            start=clip.timeline_in_ms; base=start+5000
            self.phases=[('cold',base,False,3),('play',None,True,6),('forward',base+25000,True,6),
                ('backward',base+10000,True,6),('pause',None,False,2),('resume',None,True,5),
                ('entry',start-700,True,4)]
            page._queue_advanced_preview_job=lambda *a,**kw:None
            # Ensure direct h264 is tested from an empty secondary decoder pool.
            comp.clear()
            publish=page.video.publish_compositor_overlay
            def measured_publish(slot,*a,**kw):
                result=publish(slot,*a,**kw)
                if slot==0: self.publications.append((self.phase,time.perf_counter(),tuple(p.pts_ms for p in comp._players.values())))
                return result
            page.video.publish_compositor_overlay=measured_publish
            apply=page.video.controller.set_raw_overlay
            def measured_apply(slot,*a,**kw):
                result=apply(slot,*a,**kw)
                if slot==0: self.applied.append((self.phase,time.perf_counter()))
                return result
            page.video.controller.set_raw_overlay=measured_apply
            self.advance()

        def advance(self):
            if self.phase>=0:
                rows=[r for r in self.samples if r['phase']==self.phase]
                steady=[r for r in rows if r['ms']>1000 and r['video_lag'] is not None]
                good=[r for r in rows if r['video_lag'] is not None and abs(r['video_lag'])<100]
                pubs=[p for p in self.publications if p[0]==self.phase and p[1]-self.phase_start>1]
                unique=[p for i,p in enumerate(pubs) if i==0 or p[2]!=pubs[i-1][2]]
                applied=[p[1] for p in self.applied if p[0]==self.phase and p[1]-self.phase_start>1]
                def p95(values):
                    items=sorted(abs(v) for v in values if v is not None)
                    return items[int(len(items)*.95)] if items else None
                self.summary.append({'phase':self.phases[self.phase][0],
                    'performance':self.page.video_compositor.performance_snapshot(),
                    'first_video_ms':good[0]['ms'] if good else None,
                    'video_lag_p95':p95(r['video_lag'] for r in steady),
                    'audio_lag_p95':p95(r['audio_lag'] for r in steady),
                    'av_lag_p95':p95(r['av_lag'] for r in steady),
                    'unique_video_fps':(len(unique)-1)/(unique[-1][1]-unique[0][1]) if len(unique)>1 else 0,
                    'mpv_applied_fps':(len(applied)-1)/(applied[-1]-applied[0]) if len(applied)>1 else 0})
            self.phase+=1
            if self.phase>=len(self.phases): self.finish(); return
            _,target,playing,_=self.phases[self.phase]
            self.phase_start=time.perf_counter()
            self.page.video_compositor.reset_performance_samples()
            if bool(self.page.video.playback_position_snapshot().paused)==playing: self.page._toggle_playback()
            if target is not None: self.page._seek(target/1000)

        def tick(self):
            try:
                now=time.perf_counter()
                if not self.ready:
                    if now-self.started<5: return
                    if self.page.project is None or len(self.page.project.video_tracks)<2:
                        if now-self.started>15: self.fail('No two-track project opened')
                        return
                    self.begin();return
                if now-self.phase_start>=self.phases[self.phase][3]: self.advance();return
                player=self.page.video_compositor._players.get(self.clip.id)
                audio=self.page.audio_engine.telemetry_snapshot()
                active=any(str(l.get('clip_id'))==self.clip.id for l in self.page.video_compositor._layers)
                target=self.clip.source_in_ms+round((self.page.timeline.playhead_ms-self.clip.timeline_in_ms)*self.clip.playback_rate)
                pts=player.pts_ms if player is not None and active and not player.image.isNull() else None
                estimate=audio.get('estimated_source_ms')
                self.samples.append({'phase':self.phase,'ms':(now-self.phase_start)*1000,
                    'video_lag':target-pts if pts is not None else None,'audio_lag':audio.get('drift_ms'),
                    'av_lag':estimate-pts if estimate is not None and pts is not None else None,
                    'audio_bytes':audio.get('sink_consumed_bytes'),'audio_generation':audio.get('source_generation')})
            except Exception:
                import traceback
                self.fail(traceback.format_exc())

        def finish(self):
            self.timer.stop(); page=self.page
            decoder_paths=[p.path for p in page.video_compositor._players.values()]
            if not page.video.playback_position_snapshot().paused: page._toggle_playback()
            output.joinpath('acceptance-progress.json').write_text(json.dumps(self.summary),encoding='utf8')
            def capture():
                page.video.controller.screenshot_to_file(output/'native-video.png')
                page._video_clip_selected(page.project.video_tracks[1].id,self.clip.id)
                window.grab().save(str(output/'studio-panel.png'))
                rect=window.frameGeometry()
                window.screen().grabWindow(0,rect.x(),rect.y(),rect.width(),rect.height()).save(str(output/'studio-screen.png'))
                before=time.perf_counter(); page._open_render_dialog()
                self.export_sync_ms=(time.perf_counter()-before)*1000
                QTimer.singleShot(450,capture_export)
            def capture_export():
                try:
                    comp=page.video_compositor
                    assert not comp._interaction_enabled and not comp._selected_clip_id
                    assert not page.position_overlay.isVisible()
                    assert page.video.rect().contains(comp.geometry())
                    self.export_probe={'sync_ms':self.export_sync_ms,
                        'canvas':page.video.rect().getRect(),'overlay':comp.geometry().getRect(),
                        'read_only':True}
                    page.video.controller.screenshot_to_file(output/'export-native.png')
                    window.grab().save(str(output/'export.png'))
                    page._close_export_workspace()
                    assert comp._interaction_enabled
                    assert page.video.parentWidget().layout().indexOf(page.video)>=0
                except Exception:
                    import traceback
                    self.fail(traceback.format_exc());return
                capture_launch_transition()
            def capture_launch_transition():
                window._switch_page(1)
                def capture_launch():
                    window.grab().save(str(output/'launch-transition.png'))
                    window._return_to_settings()
                    QTimer.singleShot(350,finish_home)
                QTimer.singleShot(180,capture_launch)
            def finish_home():
                window.grab().save(str(output/'home.png'))
                from .application_settings_ui import ApplicationSettingsDialog
                dialog=ApplicationSettingsDialog(window,{},output/'projects',browse=lambda *a:None,clear_recent=lambda:None,reset_layout=None)
                dialog.navigation.setCurrentRow(3);dialog.show()
                def done():
                    dialog.grab().save(str(output/'advanced-settings.png'));dialog.reject()
                    info=QFontInfo(window.start_button.font())
                    result={'runtime':'frozen' if getattr(__import__('sys'),'frozen',False) else 'dev',
                        'build':vars(load_build_identity()),'summary':self.summary,'samples':self.samples,
                        'font':{'family':info.family(),'weight':int(info.weight()),'size':info.pixelSize()},
                        'decoder_paths':decoder_paths,'export_preview':self.export_probe}
                    (output/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
                    page.close_page();window.hide()
                QTimer.singleShot(450,done)
            QTimer.singleShot(350,capture)
    window._acceptance_audit=Audit()
