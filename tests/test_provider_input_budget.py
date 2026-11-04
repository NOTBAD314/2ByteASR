import base64,io,json
from pathlib import Path
import pytest
from PIL import Image
from twobyteasr.providers.provider_input_budget import prepare_input,InputBudgetError,windows_argv_units
from twobyteasr.providers.ai_providers import GrokCLIProvider,AIProviderError


def screenshot(size=(1920,1080)):
    image=Image.new('RGB',size,'#C63928');buffer=io.BytesIO();image.save(buffer,'PNG')
    return {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()}}


def test_json_file_contains_complete_blocks_and_is_removed_after_execution(monkeypatch,tmp_path):
    monkeypatch.setattr('tempfile.tempdir',str(tmp_path))
    provider=GrokCLIProvider(executable='grok.exe',model='grok-4.6')
    schema={'type':'object','properties':{'name':{'type':'string'}},'required':['name']}
    text='约束'*6000+'\n'+json.dumps(schema,ensure_ascii=False,separators=(',',':'))
    paths=[]
    def execute(command,*args):
        path=Path(command[command.index('--prompt-file')+1]);paths.append(path)
        assert path.is_file()
        blocks=json.loads(path.read_text('utf8'))
        assert '约束'*6000 in blocks[0]['text']
        assert blocks[1]['type']=='image'
        assert json.loads(command[command.index('--json-schema')+1])==schema
        assert windows_argv_units(command)<31500
        return '{"name":"合成"}'
    monkeypatch.setattr(provider,'_complete_cli_command',execute)
    assert provider.complete([{'role':'user','content':[{'type':'text','text':text},screenshot()]}],
        max_tokens=14000,json_schema=schema,operation_kind='generate')=='{"name":"合成"}'
    assert paths and all(not path.exists() for path in paths)
    assert provider.last_timings['request_budget']['images'][0]['width']==960


def test_numeric_request_rejects_images_before_cli(monkeypatch):
    provider=GrokCLIProvider(executable='grok.exe')
    monkeypatch.setattr(provider,'_request_command',lambda *a,**k:pytest.fail('must fail before command construction'))
    with pytest.raises(AIProviderError,match='截图数量'):
        provider.complete([{'role':'user','content':[screenshot()]}],operation_kind='numeric_patch',
            input_scope={'allowed_paths':['candidates[0].generated_source.motionSpec.tracks[0].from.x']})


def test_local_crop_is_actual_pixels_and_comparison_is_explicit():
    source=[{'role':'user','content':[{'type':'text','text':'局部颜色'},screenshot()]}]
    scope={'allowed_paths':['cueCss']}
    with pytest.raises(InputBudgetError,match='裁剪'):prepare_input(source,operation='local_patch',scope=scope)
    prepared,report=prepare_input(source,operation='local_patch',scope=scope,crops={0:[100,200,400,300]})
    block=prepared[0]['content'][1]
    with Image.open(io.BytesIO(base64.b64decode(block['image_url']['url'].split(',')[1]))) as image:assert image.size==(300,100)
    assert report['images'][0]['crop']==[100,200,400,300]
    assert source[0]['content'][1]['image_url']['url'].startswith('data:image/png')
    source[0]['content'].append(screenshot())
    with pytest.raises(InputBudgetError,match='数量'):prepare_input(source,operation='visual_feedback',scope=scope)
    _,report=prepare_input(source,operation='visual_feedback',scope=scope,crops={0:[0,0,100,100],1:[0,0,100,100]},comparison=True)
    assert report['image_count']==report['image_limit']==2


def test_output_reserve_and_local_scope_are_enforced():
    with pytest.raises(InputBudgetError,match='输出预留'):
        prepare_input([{'role':'user','content':'修复'}],max_tokens=6000,operation='numeric_patch',scope={'allowed_paths':['x']})
    with pytest.raises(InputBudgetError,match='允许路径'):
        prepare_input([{'role':'user','content':'修复'}],operation='local_patch')


def test_quote_expansion_is_measured_in_the_real_windows_command():
    command=['grok.exe','-p','"' * 16000]
    assert sum(map(len,command))<31500 and windows_argv_units(command)>31500
