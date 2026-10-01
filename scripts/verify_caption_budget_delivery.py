"""Replay saved pre-dispatch failure; no provider, no user data writes."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from twobyteasr.caption_creative_pipeline import ThemeLedger, saved_reference_images
from twobyteasr.authored_prompt import assemble
from twobyteasr.provider_input_budget import prepare_input, InputBudgetError, project_transport_messages


def main():
    base=ROOT/'tmp/caption-delivery-20260925'
    saved=ThemeLedger.open(base/'failure-original/creative/ledger.json')
    images=saved_reference_images(saved)
    result=dict(kind='saved-request-budget-replay',external_model_calls=0,provider=saved.value['provider'],
        original_task='f0c75aee28f84b568af138b0356b171f',entries=[],unknowns=['provider context capability','provider queue/reasoning time'])
    for direction in saved.value['directions']['candidates']:
        folder=saved.root/'candidates'/direction['id']/'v1'
        original=json.loads((folder/'invocation.json').read_text('utf8'))
        prompt=(folder/'provider-prompt.txt').read_text('utf8')
        schema=json.loads((folder/'request-schema.json').read_text('utf8'))
        messages=[dict(role='user',content=[dict(type='text',text=prompt),*images])]
        try:
            prepare_input(messages,schema=schema,max_tokens=10000,operation='generate')
            raise AssertionError('Old unprojected request must reproduce the local failure')
        except InputBudgetError as exc:
            before=exc.report
        # Current transport projection independently removes native-schema duplication.
        try:
            _,projected=prepare_input(project_transport_messages(messages,schema,'grok_cli'),schema=schema,max_tokens=10000,operation='generate')
        except InputBudgetError as exc:projected=exc.report
        scratch=ThemeLedger(base/'budget-replay'/direction['id'],saved.value['raw_user_prompt'])
        scratch.value['creative_context']=saved.value['creative_context']
        after_prompt,assembly=assemble(scratch,direction=direction,artifact_identity='replay/'+direction['id'])
        _,after=prepare_input([dict(role='user',content=[dict(type='text',text=after_prompt),*images])],
            max_tokens=10000,operation='generate',scope={'candidate_id':direction['id']})
        (scratch.root/'implementation-prompt.txt').write_text(after_prompt,'utf8')
        (scratch.root/'assembly.json').write_text(json.dumps(assembly,ensure_ascii=False,indent=2),'utf8')
        result['entries'].append(dict(id=direction['id'],saved_invocation=original,reproduced_before=before,
            native_schema_projection_only=projected,after=after,before_blocks=json.loads((folder/'request-components.json').read_text('utf8')),after_blocks=assembly))
    result['passed']=all(r['after']['passed'] and r['after']['policy']['input_tokens']==16384 for r in result['entries'])
    (base/'budget-comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps([dict(id=r['id'],before=r['reproduced_before']['input_token_estimate'],after=r['after']['input_token_estimate'],bytes=r['after']['text_utf8_bytes'],limit=r['after']['policy']['input_tokens']) for r in result['entries']]))

if __name__=='__main__':main()
