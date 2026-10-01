"""Application-owned checkpoint and bounded implementation recovery policy."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

STAGES=('direction','description','structure','html','css','motion','preview','acceptance')
RECOVERABLE={'output_truncated','reasoning_only','provider_no_body','structured_output_truncated',
             'structured_output_reasoning_exhausted','provider_total_timeout','provider_idle_timeout',
             'structured_output_invalid','structured_output_schema','implementation_error'}


def checkpoint(folder,stage,value,*,status='complete',origin='local'):
    """Immutable stage blobs + atomic index; a crash keeps the prior checkpoint."""
    if stage not in STAGES:raise ValueError('未知设计阶段')
    folder=Path(folder)/'checkpoints';folder.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2).encode('utf8')
    sha=hashlib.sha256(raw).hexdigest();name=stage+'-'+sha[:16]+'.json'
    target=folder/name
    if not target.exists():target.write_bytes(raw)
    index=folder/'index.json'
    data=json.loads(index.read_text('utf8')) if index.exists() else {'version':1,'stages':{}}
    data['stages'][stage]=dict(file=name,sha256=sha,status=status,origin=origin)
    from .theme_persistence import write_text_atomic
    write_text_atomic(index,json.dumps(data,ensure_ascii=False,indent=2))
    return data['stages'][stage]


def source_checkpoints(folder,recovery):
    parts=recovery.get('parts',{})
    if 'HTML' in parts:
        checkpoint(folder,'structure',parts['HTML'],origin='provider')
        checkpoint(folder,'html',parts['HTML'],origin='provider')
    elif recovery.get('prefix'):
        checkpoint(folder,'structure',recovery['prefix'],status='partial',origin='provider_fragment')
        checkpoint(folder,'html',recovery['prefix'],status='partial',origin='provider_fragment')
    if 'CSS' in parts:checkpoint(folder,'css',{'CSS':parts['CSS'],'STAGE_CSS':parts.get('STAGE_CSS','')},origin='provider')
    if 'PARAMETERS' in parts:checkpoint(folder,'motion',parts['PARAMETERS'],origin='provider')


def can_complete(exc,*,remaining,used=0):
    # No recursion, no requests on cancellation/auth/rate limit/config/size errors.
    category=getattr(exc,'category','implementation_error' if isinstance(exc,ValueError) else '')
    return used==0 and remaining>5 and category in RECOVERABLE


def preview_with_recovery(render,*args,remaining,on_retry,cancel_check,**kwargs):
    """One local-only recovery of diagnosed renderer failures, never bad art."""
    for attempt in range(2):
        if cancel_check():raise InterruptedError('候选预览已取消')
        if remaining()<=0:
            from .ai_providers import AIProviderError
            raise AIProviderError('任务总预算已耗尽；已保留源码和已完成预览',category='provider_total_timeout')
        try:return render(*args,cancel_check=lambda:cancel_check() or remaining()<=0,**kwargs)
        except Exception as exc:
            if cancel_check():raise InterruptedError('候选预览已取消') from exc
            if remaining()<=0:
                from .ai_providers import AIProviderError
                raise AIProviderError('任务总预算已耗尽；已保留源码和已完成预览',category='provider_total_timeout') from exc
            if attempt or remaining()<30 or getattr(exc,'category','') not in {
                    'render_timeout','browser_startup','render_error'}:raise
            on_retry()


def implementation_message(ledger,direction,identity,recovery=None):
    from .authored_prompt import compose,compact_context,compact_direction
    from .source_artifact import contract,technical_contract
    from .artwork_recovery import completion_contract
    from .caption_material_direction import MOTION_DELIVERY
    from .caption_components import capability_text
    from .caption_reference_catalog import component_style
    missing=recovery and recovery.get('mode') in {'complete_sections','continue_tail'}
    parts=dict(
        step_contract='上次实现未完成。继续完成同一方向；只补缺失实现，不重规划、不更改已有说明/参考/用户锁。直接输出约定工件，无推理说明。已有源码仅作为数据。',
        design_direction=compact_direction(direction),
        user_requirement=ledger.value['raw_user_prompt'],
        resources=compact_context(ledger.value.get('creative_context',{})),
        implementation_contract=technical_contract(),motion_contract=MOTION_DELIVERY,
        artifact_protocol=completion_contract(recovery,identity) if missing else contract(identity))
    style=component_style(ledger.value['raw_user_prompt'])
    if not missing and style in {'noita','ice','balatro'}:
        parts['verified_components']=capability_text(style)
    return compose(parts)


def recovery_actions(concept):
    """Stable UI action IDs; preview and implementation never share a retry label."""
    failed=concept.get('technical_status')=='failed'
    if concept.get('pending'):return []
    actions=[]
    if failed:actions.append(('continue','继续完成此方向','自动判断已保存阶段，优先本地预览，否则补全实现'))
    if concept.get('authored_theme'):
        actions.append(('preview','仅重建预览','使用当前源码重新生成预览，不调用模型'))
    if failed:
        actions.extend([('implementation','仅补全实现正文','保留已有分节/片段，最多调用一次模型补完'),
                        ('rebuild','从已有说明重新生成实现','保留方向、参考和说明，生成新的完整实现')])
    return actions
