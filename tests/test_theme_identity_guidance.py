from pathlib import Path
import hashlib
import pytest
from twobyteasr.caption_design.design_guidance import load_design_guidance
from twobyteasr.caption_design.authored_prompt import assemble, direction_adjustment
from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger
from twobyteasr.providers.provider_input_budget import prepare_input


@pytest.mark.parametrize('name',['塞尔达','赛尔达传说','薩爾達','Zelda'])
def test_zelda_guidance_is_sent_to_planning_and_implementation(tmp_path,name):
    ledger=ThemeLedger(tmp_path,name+'风格，保留正文，无人物')
    ledger.value['creative_context']={'subtitle_text':'真实字幕','user_locks':['无人物']}
    for direction in [None,{'name':'古代纹环','design':'环纹归位，文字刻印，退出回收'}]:
        message,receipt=assemble(ledger,direction=direction)
        assert '无人物' in message and '真实字幕' in message
        assert '三角力量、剑形、翼纹' in message
        assert '主题名称本身不是授权' not in message
        assert '不需要用户另写造型授权' in message
        assert '去掉名字和说明' in message
        assert '仅全组opacity' in message
        _,budget=prepare_input([{'role':'user','content':message}],operation='generate',max_tokens=32000)
        assert budget['passed']
        assert 'design_skills' in receipt['components']


def test_guidance_hashes_match_files_and_other_themes_do_not_get_zelda():
    root=Path(__file__).resolve().parents[1]
    text,receipt=load_design_guidance('赛尔达风格',root=root)
    assert receipt['theme']=='Zelda'
    for item in receipt['files']:
        assert hashlib.sha256((root/item['path']).read_bytes()).hexdigest()==item['sha256']
    other,receipt=load_design_guidance('木刻',root=root)
    assert 'zelda-caption.md' not in str(receipt['files'])
    assert '三角力量' not in other
    assert '不自动将角色' in direction_adjustment({'design_spec':{'shape':'旧角色'}})
