from types import SimpleNamespace
import torch
from twobyteasr.recognition.audio_feature_reuse import reuse_audio_features


def test_reuse_is_content_mask_dtype_and_request_scoped():
    calls=[]
    def encode(x,feature_attention_mask=None):
        calls.append(1);return x.sum()+feature_attention_mask.sum()
    thinker=SimpleNamespace(training=False,get_audio_features=encode)
    aligner=SimpleNamespace(model=SimpleNamespace(thinker=thinker))
    x=torch.tensor([1.,2.]);mask=torch.tensor([1,1])
    with reuse_audio_features(aligner,torch):
        first=thinker.get_audio_features(x,feature_attention_mask=mask)
        assert thinker.get_audio_features(x.clone(),feature_attention_mask=mask.clone()) is first
        x[0]=3
        thinker.get_audio_features(x,feature_attention_mask=mask)
        mask[0]=0
        thinker.get_audio_features(x,feature_attention_mask=mask)
        thinker.get_audio_features(x.double(),feature_attention_mask=mask)
    assert len(calls)==4 and aligner._audio_feature_hits==1
    thinker.get_audio_features(x,feature_attention_mask=mask)
    assert len(calls)==5 and thinker.get_audio_features is encode


def test_training_mode_never_reuses_stochastic_features():
    calls=[]
    def encode(x):calls.append(1);return x
    thinker=SimpleNamespace(training=True,get_audio_features=encode)
    aligner=SimpleNamespace(model=SimpleNamespace(thinker=thinker))
    with reuse_audio_features(aligner,torch):
        thinker.get_audio_features(torch.ones(1));thinker.get_audio_features(torch.ones(1))
    assert len(calls)==2
