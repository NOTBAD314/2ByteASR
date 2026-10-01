"""Small persisted UI attempt receipt. Source revisions are immutable hashes."""
from __future__ import annotations
import hashlib
import json
import time
import uuid
from pathlib import Path
from .theme_persistence import write_text_atomic


def revision(concept):
    value=concept.get('authored_theme') or {'ledger':concept.get('ledger_path'),
        'errors':concept.get('technical_errors'),'source_recovery':concept.get('source_recovery')}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode('utf8')).hexdigest()


def primary_action(concept):
    if concept.get('pending'):return ('cancel','停止并保留','停止本地等待；供应商端计算和计费是否停止取决于协议')
    if ((concept.get('motion_preview',{}).get('status')=='motion_ready'
         and concept.get('preview_integrity_verified') and concept.get('authored_theme'))
            and concept.get('technical_status')!='failed' and not concept.get('preview_integrity_error')):
        return ('adopt','采用这个方向','采用当前已验证的准确版本')
    if concept.get('authored_theme'):
        categories={e.get('category') for e in concept.get('technical_errors',[])}
        if not categories or categories <= {'render_timeout','browser_startup','render_error','runtime_render'}:
            return ('preview','重新生成预览','使用已保存源码；不调用模型')
    recovery=concept.get('source_recovery',{})
    if recovery.get('missing_sections') or not concept.get('technical_errors'):
        return ('implementation','补全并预览','保留已保存方向和正文分节；最多一次远端请求')
    return ('continue','修复并生成预览','先做可证明的本地修复，必要时最多一次远端请求；原版本保留')


class CandidateAttempt:
    def __init__(self,root,job_id,concept,action,*,accepted=True,reason=''):
        self.value=dict(job_id=job_id,candidate_id=concept.get('id',''),attempt_id=uuid.uuid4().hex,
            artifact_revision=revision(concept),action=action,status='accepted' if accepted else 'rejected',
            reason=reason,accepted_at=time.time(),events=[])
        self.path=Path(root)/'candidate-actions'/(self.value['attempt_id']+'.json')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.event(self.value['status'],reason)

    def event(self,status,detail='',**fields):
        self.value.update(status=status,**fields)
        self.value['events'].append(dict(status=status,detail=str(detail)[:2000],at=time.time()))
        self.value['events']=self.value['events'][-200:]
        if status in {'ready','failed','cancelled','rejected','stale'}:self.value['finished_at']=time.time()
        write_text_atomic(self.path,json.dumps(self.value,ensure_ascii=False,indent=2))
