"""Protect explicit intent; generated defaults are not user locks."""
import copy


def capture_constraints(current, baseline=None, explicit_paths=()):
    """Infer locks only from edits against a known generated snapshot.

    Cue text/time/placement/overrides remain outside the model document.
    """
    result=[]
    def get(value,path):
        for key in path:
            if not isinstance(value,dict) or key not in value:return False,None
            value=value[key]
        return True,value
    def protect(path,origin):
        exists,value=get(current,path)
        if not any(row['path']==list(path) for row in result):
            result.append(dict(path=list(path),exists=exists,value=copy.deepcopy(value),origin=origin))
    def diff(old,new,path=()):
        if isinstance(old,dict) and isinstance(new,dict):
            for key in sorted(old.keys()|new.keys()):
                if not path and key=='notes':continue  # provenance is not an inferred user lock
                if key not in old or key not in new:protect((*path,key),'manual_edit')
                else:diff(old[key],new[key],(*path,key))
        elif old!=new:protect(path,'manual_edit')
    if baseline is not None:diff(baseline,current)
    for path in explicit_paths:
        keys=path.split('.') if isinstance(path,str) else list(path)
        if not keys or not get(current,keys)[0]:raise ValueError('用户锁定路径不存在：'+str(path))
        protect(keys,'explicit_lock')
    # Manual source CSS cannot safely be grafted onto unrelated new markup.
    # Protect its topology; unchanged appearance defaults remain editable.
    for source,markup in (('cueCss','cueHtml'),('stageCss','stageHtml')):
        if any(r['path']==[source] for r in result):protect((markup,),'manual_css_topology')
    return result


def enforce_constraints(proposed, constraints):
    value=copy.deepcopy(proposed);changes=[]
    for lock in constraints or ():
        path=lock['path'];node=value
        for key in path[:-1]:
            if not isinstance(node.get(key),dict):node[key]={}
            node=node[key]
        key=path[-1];exists=key in node
        if exists==lock['exists'] and (not exists or node[key]==lock['value']):continue
        changes.append(dict(path=path,action='restore_user_intent',origin=lock['origin']))
        if lock['exists']:node[key]=copy.deepcopy(lock['value'])
        else:node.pop(key,None)
    return value,changes
