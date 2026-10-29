import json
from pathlib import Path

from twobyteasr.caption_design.design_guidance import load_design_guidance
from twobyteasr.caption_design.design_progress import complete_candidate_prefix, update_phase, status_text
from twobyteasr.caption_design.theme_generation_policy import authored_request_budget


def test_short_theme_loads_distinct_packaged_reference_and_hashes():
    miku, miku_receipt=load_design_guidance('初音未来风格')
    minecraft, mc_receipt=load_design_guidance('Minecraft像素风格')
    assert miku_receipt['theme']=='Miku' and mc_receipt['theme']=='Minecraft'
    assert miku_receipt['files'][:2]==mc_receipt['files'][:2]
    assert miku_receipt['files'][-1]['sha256']!=mc_receipt['files'][-1]['sha256']
    assert '棕金木箱' in miku and '统一像素格点' in minecraft
    root=Path(__file__).resolve().parents[1]
    for name in ('2byteskill','subtitle-theme-aesthetics'):
        assert (root/f'.agents/skills/{name}/SKILL.md').read_bytes()==(root/f'assets/design-skills/{name}/SKILL.md').read_bytes()


def test_long_mode_shared_budget_and_explicit_short_deadline():
    for provider in ('deepseek','grok_oauth','antigravity','openai'):
        _,limits=authored_request_budget(provider,{'ai_design_cli_timeout_seconds':300,'ai_design_wait_mode':'long30'})
        assert limits.concepts==1800
        assert limits.transport_policy().read_idle==300
        assert limits.inactivity==600
        assert authored_request_budget(provider,{'ai_design_wait_mode':'long30'},17)[1].concepts==17


def test_heartbeat_never_claims_artwork_progress():
    phase=dict(started_monotonic=10,last_output_monotonic=None,output_chars=0)
    update_phase(phase,'thinking','PRIVATE TEXT',50)
    update_phase(phase,'heartbeat','',140)
    assert phase['last_output_monotonic'] is None and phase['output_chars']==0
    message=status_text(phase,145)
    assert '尚未收到作品正文' in message and '远端进度未知' in message
    assert '长时间未收到新内容' in message
    assert 'PRIVATE' not in message
    update_phase(phase,'delta','{"candidate":',150)
    assert phase['last_output_monotonic']==150 and phase['output_chars']>0


def test_partial_stream_checkpoints_complete_candidates_without_inventing():
    row={'id':'A','generated_source':{'cueHtml':'{{text}} " nested } braces'}}
    partial='{"candidates":['+json.dumps(row)+', {"id":"B","generated_source":'
    assert complete_candidate_prefix(partial)==[row]
    assert complete_candidate_prefix('{"candidates":[')==[]
