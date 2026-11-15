"""Exact-content, model-local audio embeddings reused only across one pass pair."""
from contextlib import contextmanager


@contextmanager
def reuse_audio_features(aligner,torch):
    thinker=getattr(getattr(aligner,'model',None),'thinker',None)
    original=getattr(thinker,'get_audio_features',None)
    if original is None or getattr(thinker,'training',False):
        yield
        return
    previous=[]
    def clone(value):
        if isinstance(value,torch.Tensor):return value.detach().clone()
        if isinstance(value,(str,int,float,bool,type(None))):return value
        if isinstance(value,tuple):return tuple(clone(x) for x in value)
        if isinstance(value,list):return [clone(x) for x in value]
        if isinstance(value,dict):return {k:clone(v) for k,v in value.items()}
        raise TypeError('Unsupported audio feature parameter')
    def equal(a,b):
        if isinstance(a,torch.Tensor):
            return isinstance(b,torch.Tensor) and a.shape==b.shape and a.dtype==b.dtype and a.device==b.device and torch.equal(a,b)
        if type(a) is not type(b):return False
        if isinstance(a,dict):return a.keys()==b.keys() and all(equal(v,b[k]) for k,v in a.items())
        if isinstance(a,(tuple,list)):return len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
        return a==b
    def invoke(*args,**kwargs):
        if previous and equal(previous[0],args) and equal(previous[1],kwargs):
            aligner._audio_feature_hits=getattr(aligner,'_audio_feature_hits',0)+1
            return previous[2]
        value=original(*args,**kwargs)
        aligner._audio_feature_misses=getattr(aligner,'_audio_feature_misses',0)+1
        previous.clear()
        try:previous.extend([clone(args),clone(kwargs),value])
        except TypeError:previous.clear()
        return value
    thinker.get_audio_features=invoke
    try:yield
    finally:
        thinker.get_audio_features=original
        previous.clear()
