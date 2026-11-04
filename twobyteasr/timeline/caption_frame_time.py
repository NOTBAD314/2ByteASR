"""Rational media-frame timing; cue endpoints remain untouched."""
from fractions import Fraction
import math
from functools import wraps


def caption_sample_transaction(method):
    """One observed frame owns cue selection and every visibility decision."""
    @wraps(method)
    def invoke(self,*args,**kwargs):
        previous=getattr(self,'_caption_tick_time_ms',None)
        sample=getattr(self,'_caption_sample_ms',None)
        if previous is not None or not callable(sample):return method(self,*args,**kwargs)
        self._caption_tick_time_ms=sample()
        try:return method(self,*args,**kwargs)
        finally:self._caption_tick_time_ms=previous
    return invoke


def project_frame_rate(project):
    source=str(getattr(getattr(project,'media',None),'path','')).replace('\\','/').casefold()
    for asset in getattr(project,'media_pool',()):
        if str(asset.canonical_source).replace('\\','/').casefold()==source:
            value=asset.video_metadata.get('fps')
            if isinstance(value,(int,float)) and math.isfinite(value) and value>0:
                return Fraction(str(value)).limit_denominator(100_100)
    value=getattr(project,'render_settings',{}).get('fps')
    if isinstance(value,(int,float)) and math.isfinite(value) and value>0:
        return Fraction(str(value)).limit_denominator(100_100)
    return None


def observed_frame_ms(milliseconds, rate):
    """Recover a CFR frame from an observed PTS, including IPC decimal rounding.

    This is for discrete media observations, never an interpolated wall clock.
    """
    if rate is None:return milliseconds
    rate=Fraction(str(rate)).limit_denominator(100_100)
    index=round(Fraction(str(milliseconds))*rate/1000)
    return Fraction(index*1000,1)/rate


def first_frame_ms(milliseconds, rate):
    if rate is None:return milliseconds
    rate=Fraction(str(rate)).limit_denominator(100_100)
    index=math.ceil(Fraction(str(milliseconds))*rate/1000)
    return Fraction(index*1000,1)/rate


def ass_frame_ms(milliseconds, rate):
    """One shared endpoint mapping into ASS's centisecond timebase.

    The chosen centisecond lies after the preceding media frame and no later
    than the first eligible one. Both adjacent endpoints use this function.
    """
    return int(first_frame_ms(milliseconds,rate)/10)*10 if rate is not None else milliseconds
