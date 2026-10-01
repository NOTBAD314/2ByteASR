"""Explicit acceptance-only call accounting. No credentials or prompt content."""
import json
from pathlib import Path
import threading
import time
import uuid


def install_acceptance_budget(path):
    path=Path(path).resolve()
    from .studio_acceptance_audit import audit_tmp_root
    if not path.is_relative_to(audit_tmp_root()):raise ValueError('Audit budget must be under tmp')
    from .provider_service import AIClient
    if getattr(AIClient.complete,'_acceptance_budget',False):
        if AIClient.complete._acceptance_budget_path != str(path):
            raise ValueError('本进程已安装其他调用账本，不能隐式复用')
        return
    data=json.loads(path.read_text('utf8'))
    if not all(k in data.get('limits',{}) for k in ('generation','repair','redo')):
        raise ValueError('调用账本必须明确三个调用上限')
    complete=AIClient.complete
    lock=threading.Lock()
    def guarded(self,messages,**kwargs):
        operation=kwargs.get('operation_kind','general')
        scope=kwargs.get('input_scope',{})
        kind=scope.get('kind')
        bucket=('repair' if kind in {'render_repair','implementation_completion'} else
                'redo' if kind=='one_full_creative_redo' else 'generation') if operation=='generate' else 'repair'
        with lock:
            data=json.loads(path.read_text('utf8'))
            used=sum(row['bucket']==bucket and row.get('dispatched',True) for row in data['calls'])
            if used>=data['limits'][bucket]:raise ValueError(f'本轮{bucket}调用预算已用完')
            call=dict(id=uuid.uuid4().hex,bucket=bucket,operation=operation,model=self.model,
                provider=self.provider_id,input_scope=scope,status='started',started=time.time())
            data['calls'].append(call);path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf8')
        started=time.monotonic()
        try:
            result=complete(self,messages,**kwargs);call['status']='returned';return result
        except Exception as exc:
            category=getattr(exc,'category',type(exc).__name__)
            call.update(status='failed',category=category)
            # Application preflight happens before queueing or transport.
            # Keep the rejected attempt, but don't label it a model call.
            if category=='request_too_large':call['dispatched']=False
            raise
        finally:
            trace=self.invocation_trace()
            call.update(elapsed_seconds=time.monotonic()-started,request_id=trace.get('request_id'),
                provider_request_id=trace.get('provider_request_id'),
                usage=trace.get('reported_usage'),actual_cost_usd=trace.get('actual_cost_usd'))
            with lock:
                data=json.loads(path.read_text('utf8'))
                data['calls']=[call if row['id']==call['id'] else row for row in data['calls']]
                path.write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf8')
    guarded._acceptance_budget=True
    guarded._acceptance_budget_path=str(path)
    guarded._acceptance_repair_limit=data['limits']['repair']
    AIClient.complete=guarded
