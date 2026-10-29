"""Per-sample project-time gain envelopes for preview and final audio."""
from ..timeline.studio_transitions import transition_volume_expression


def envelope_filter(envelopes, *, origin_ms, clock_rate=1., channels=2):
    if not envelopes:
        return ''
    rate=max(.01,float(clock_rate))
    local=[{**item,'start_ms':(item['start_ms']-origin_ms)/rate,
            'end_ms':(item['end_ms']-origin_ms)/rate} for item in envelopes]
    expression=transition_volume_expression(local)
    # aeval evaluates t for every sample; frame-evaluated volume introduced
    # audible steps at a short seam. Normalize layout before channel indexing.
    values='|'.join(f'val({index})*({expression})' for index in range(channels))
    return f"aformat=channel_layouts={channels}c,aeval=exprs='{values}',"
