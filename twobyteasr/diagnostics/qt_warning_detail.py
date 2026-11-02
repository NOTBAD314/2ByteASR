"""Recognizable Qt warning families without retaining user strings or paths."""
import re

def warning_detail(message):
    families=(('thread_affinity',r'(?i)different thread|another thread|thread affinity|moveToThread'),
        ('timer_thread',r'(?i)timer.*thread|startTimer|killTimer'),
        ('destroyed_object',r'(?i)deleted|destroyed|already.*closed'),
        ('painter',r'(?i)QPainter|QPaintDevice|paint engine'),
        ('connection',r'(?i)QObject::connect|Cannot queue arguments|disconnect'),
        ('font',r'(?i)font|glyph'),('layout',r'(?i)layout|geometry'))
    family=next((name for name,pattern in families if re.search(pattern,message)),'other')
    # Only known Qt diagnostics get details; arbitrary native/plugin text is
    # still represented by its existing fingerprint and character count.
    detail=''
    if family!='other':
        detail=re.sub(r'"[^"\n]*"|\'[^\'\n]*\'','<quoted>',message)
        detail=re.sub(r'0x[0-9a-fA-F]+','<address>',detail)
        detail=re.sub(r'(?i)(?:[a-z]:[\\/]|https?://)[^\s<>]+','<path>',detail)
        detail=re.sub(r'(?<!\w)/(?:[^\s/]+/)+[^\s]*','<path>',detail)
    return {'qt_warning_family':family,'qt_diagnostic':detail[:500]}
