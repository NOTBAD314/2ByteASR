"""Strict, explicit recovery of two complete rows and the third row's metadata.

This never turns a truncated provider response into a successful response. Only
an explicit saved-draft retry may fill the missing source fields through repair.
"""
import json,re
from pathlib import Path


def retained_candidate_prefix(raw):
    from .design_progress import complete_candidate_prefix
    rows=complete_candidate_prefix(raw)
    if len(rows)==3:
        return {'candidates':rows}
    try:
        return _retained_partial_third(raw)
    except (ValueError, TypeError, KeyError):
        if rows:return {'candidates':rows}
        raise ValueError('尚未保留完整候选；可保留正文诊断，不能猜补未完成作品') from None


def _retained_partial_third(raw):
    if not isinstance(raw,str) or len(raw)>1024*1024:raise ValueError('保留正文大小无效')
    match=re.match(r'\s*\{\s*"candidates"\s*:\s*\[',raw)
    if not match:raise ValueError('截断响应没有可验证的候选集合前缀')
    decoder=json.JSONDecoder();index=match.end();rows=[]
    for _ in range(2):
        while index<len(raw) and raw[index] in ' \r\n\t,':index+=1
        row,index=decoder.raw_decode(raw,index)
        if not isinstance(row,dict):raise ValueError('保留候选必须为对象')
        rows.append(row)
    while index<len(raw) and raw[index] in ' \r\n\t,':index+=1

    def complete_values(start,depth=0):
        if depth>2 or start>=len(raw) or raw[start]!='{':raise ValueError('第三候选结构不完整')
        start+=1;value={}
        while start<len(raw):
            while start<len(raw) and raw[start] in ' \r\n\t,':start+=1
            if start>=len(raw) or raw[start]=='}':return value
            try:
                key,end=decoder.raw_decode(raw,start)
                if not isinstance(key,str):raise ValueError('候选字段名无效')
                start=end
                while start<len(raw) and raw[start].isspace():start+=1
                if start>=len(raw) or raw[start]!=':':return value
                start+=1
                while start<len(raw) and raw[start].isspace():start+=1
                item,end=decoder.raw_decode(raw,start);value[key]=item;start=end
            except json.JSONDecodeError:
                if start<len(raw) and raw[start]=='{':value[key]=complete_values(start,depth+1)
                return value
        return value
    partial=complete_values(index)
    from .caption_creative_pipeline import AUTHORED_OUTPUT_SCHEMA
    required=set(AUTHORED_OUTPUT_SCHEMA['properties']['candidates']['items']['required'])
    if not required<=set(partial):raise ValueError('第三候选的设计说明未完整保留，禁止猜补')
    source=partial.get('generated_source')
    if not isinstance(source,dict) or not {'id','name','appearance','palette','stageHtml','stageCss'}<=set(source):
        raise ValueError('第三候选的身份、字体和配色未完整保留，禁止猜补')
    missing={'cueHtml','cueCss','motionSpec'}-set(source)
    if not missing:raise ValueError('此响应不属于可定点补齐的源码截断')
    rows.append(partial)
    ids=[r.get('id') for r in rows]
    if any(not isinstance(v,str) or not v for v in ids) or len(set(ids))!=3:raise ValueError('保留候选身份冲突')
    return {'candidates':rows}


def retained_response_record(ledger):
    original=ledger.value.get('raw_response')
    if original:return original
    partial=ledger.root/'provider-partial.txt';trace=ledger.root/'provider-invocation.json'
    if not partial.is_file() or not trace.is_file():raise ValueError('没有可恢复的原始响应')
    from .caption_creative_pipeline import digest
    raw=partial.read_bytes()
    expected=ledger.value.get('partial_body',{}).get('sha256')
    # Historical Windows write_text expanded LF after hashing the provider
    # string. Accept only that exact, reversible newline conversion; bind the
    # recovered receipt to the actual file bytes from this point onward.
    if digest(raw)!=expected and digest(raw.replace(b'\r\n',b'\n'))!=expected:
        raise ValueError('保留正文已改变')
    retained_candidate_prefix(raw.decode('utf8'))
    invocation=json.loads(trace.read_text('utf8'))
    return dict(path=str(partial),sha256=digest(raw),provider=invocation['provider_id'],
        model=invocation['model'],completed=False,recovery='explicit-missing-source-fields',
        provider_request_id=invocation.get('provider_request_id'),provider_text_sha256=expected)
