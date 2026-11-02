"""Owned navigation recovery is bounded; actual encodes live in export regressions."""
import json
from pathlib import Path
from twobyteasr.system.processes import renderer_node_command,run_hidden_subprocess

ROOT=Path(__file__).resolve().parents[1]

def test_null_local_navigation_retries_once_and_real_failures_propagate():
    helper=json.dumps(str(ROOT/'renderer/navigation_response.cjs'))
    code="""const assert=require('node:assert/strict');const {wrapBundleNavigation}=require(HELPER);
(async()=>{let calls=0;const events=[];const response={status:()=>200};const options={url:'http://localhost:3000/index.html',timeout:30000};const owner={value:9};
const guarded=wrapBundleNavigation(async function(o){assert.equal(this,owner);assert.equal(o,options);return ++calls===1?null:response;},event=>events.push(event));
assert.equal(await guarded.call(owner,options),response);assert.equal(calls,2);assert.equal(events[1].recovered,true);
calls=0;assert.equal(await wrapBundleNavigation(async()=>{calls++;return null;})({url:'https://invalid.example/'}),null);assert.equal(calls,1);
const error=new Error('real server failure');await assert.rejects(wrapBundleNavigation(async()=>{throw error;})(options),e=>e===error);
calls=0;assert.equal(await wrapBundleNavigation(async()=>{calls++;return null;})(options),null);assert.equal(calls,2);
calls=0;const badResponse={status:()=>500};assert.equal(await wrapBundleNavigation(async()=>{calls++;return badResponse;})(options),badResponse);assert.equal(calls,1);
console.log('passed');})().catch(error=>{console.error(error);process.exit(1);});""".replace('HELPER',helper)
    result=run_hidden_subprocess([str(ROOT/'tools/node/node.exe'),'-e',code],purpose='navigation guard contract',capture_output=True,text=True,check=True,timeout=15)
    assert result.stdout.strip()=='passed'


def test_real_private_node_preloads_original_policy_and_navigation_adapter():
    code="const path=require('node:path');const {Page}=require(path.join(path.dirname(require.resolve('@remotion/renderer')),'browser/BrowserPage.js'));if(!Page.prototype[Symbol.for('2byte.navigation-response-guard')])process.exit(7);console.log('guard installed');"
    command=renderer_node_command(ROOT/'renderer','-e',code)
    assert command.count('--require')==2
    assert 'process_policy.cjs' in command[2] and 'export_bootstrap.cjs' in command[4]
    result=run_hidden_subprocess(command,cwd=ROOT/'renderer',purpose='real renderer preload contract',capture_output=True,text=True,check=True,timeout=15)
    assert result.stdout.strip()=='guard installed'


def test_first_renderer_error_survives_rendered_progress():
    from twobyteasr.rendering.advanced_renderer import _run_streaming_process
    from twobyteasr.exports.export_failure import renderer_failure
    code,evidence=_run_streaming_process([str(ROOT/'tools/node/node.exe'),'-e',
        "console.error('Error: first page navigation failed');for(let i=0;i<400;i++)console.log('Rendered '+i+'/400');process.exit(9)"])
    error=renderer_failure(code,evidence)
    assert error.evidence['reason']=='Error: first page navigation failed'
    assert error.evidence['renderer_exitcode']==9 and error.evidence['returncode'] is None
    assert error.evidence['category']=='subtitle_renderer' and not error.evidence['retry_cpu']
