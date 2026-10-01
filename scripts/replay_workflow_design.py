"""Replay the three retained September workflow failures without model calls."""
import argparse
import copy
import json
import os
from pathlib import Path
import sys
import traceback


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('Use a fresh tmp directory')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    os.environ['QT_QPA_PLATFORM']='offscreen'
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.authored_repair import apply_patch_transaction,get_leaf
    from twobyteasr.structured_output import response_object
    from twobyteasr.caption_creative_pipeline import ThemeLedger,accept_authored_set,canonical,digest
    from twobyteasr.authored_preview import render_candidate_preview
    read=lambda p:json.loads(p.read_text('utf8'))
    result={'kind':'saved-response-offline-replay','model_calls':0,'candidates':[]}
    repairs=['7f415904e7b9453095d2035fcee5de45','06b25d9c4abe462fa519b62c1a0a3d4c','7ac6b928509349f1a31f2e60fc6a0a84']
    for index,repair in enumerate(repairs):
        request_file=next(args.evidence.rglob('repair-input-'+repair+'.json'));child=request_file.parent
        request=read(request_file);payload=read(child/'provider-assembled.json')
        candidate=payload['candidates'][index];ident=candidate['id'];dest=out/ident
        diagnostic=json.loads(request['messages'][0]['content'].replace('\r\n','\n').split('[diagnostics]\n',1)[1])
        fields=[];archived={i['path']:i for i in diagnostic['issues']}
        for branch in request['schema']['properties']['patches']['items']['anyOf']:
            p=branch['properties'];path=p['path']['const'];field=copy.deepcopy(archived[path])
            field.update(candidate_index=p['candidate_index']['const'],path=path,
                replacement_schema=p['value'],original_value=copy.deepcopy(get_leaf(payload,path)),exists=True)
            fields.append(field)
        fixed,changed=apply_patch_transaction(payload,response_object(read(child/('repair-response-'+repair+'.json'))),fields)
        assert all(fixed['candidates'][i]==payload['candidates'][i] for i in range(3) if i!=index)
        row=dict(id=ident,saved_input_sha256=digest(request_file.read_bytes()),saved_patch_paths=changed)
        result['candidates'].append(row)
        if index==0:
            # The original SVG texture fills the whole video. Limit this
            # material's geometry to the existing subtitle slab, keeping the
            # texture, figure, club, text and all motion tracks intact.
            fixed['candidates'][index]['generated_source']['cueCss']+='\n.stone-texture { width:740px; height:260px; left:50%; top:50%; transform:translate(-50%,-50%); }'
            row['local_layout_patch']='Only .stone-texture geometry; no node or motion removal'
        if index==1:
            css=fixed['candidates'][index]['generated_source']['cueCss']
            before='.bound-slab-frame {\n  position: relative;'
            # Change the authored root only; keep every frame/material/motion.
            import re
            css,n=re.subn(r'(\.bound-slab-frame\s*\{\s*)position:\s*relative;',
                r'\1position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);',css,count=1)
            assert n==1,'The saved root has changed; do not guess a replacement'
            fixed['candidates'][index]['generated_source']['cueCss']=css
            row['local_layout_patch']='Only .bound-slab-frame position/left/top/transform; original retained'
        prior=read(child/'ledger.json');ledger=ThemeLedger(dest/'ledger',prior['raw_user_prompt'])
        ledger.value['creative_context']=copy.deepcopy(prior.get('creative_context',{}));ledger.save()
        # No original image references are used or uploaded in this replay.
        ledger.raw_response(canonical(fixed),'deepseek','deepseek-v4-pro')
        try:
            suggestion=accept_authored_set(fixed,ledger,'deepseek','deepseek-v4-pro',allow_partial=True)
            concept=next(c for c in suggestion.concepts if c['id']==ident)
            if concept.get('technical_status')=='failed':raise ValueError(concept['technical_errors'])
            (dest/'concept.json').write_text(json.dumps(concept,ensure_ascii=False,indent=2),'utf8')
            receipt=render_candidate_preview(concept,dest/'preview',prior['creative_context']['subtitle_text'],progress=print)
            row.update(status='rendered',receipt=receipt)
        except Exception as exc:row.update(status='failed',error=str(exc),traceback=traceback.format_exc())
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
        print(ident,row['status'],flush=True)
    return 0 if all(r['status']=='rendered' for r in result['candidates']) else 1


if __name__=='__main__':raise SystemExit(main())
