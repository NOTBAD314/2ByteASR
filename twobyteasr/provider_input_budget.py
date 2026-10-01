"""Deterministic operation budgets before any CLI/API call.

Token figures are conservative application estimates, not provider billing.
Screenshots are pixels, never base64 counted as language tokens.
"""
import base64
import copy
import hashlib
import io
import json
import math
import re
import subprocess
import threading
from dataclasses import dataclass,asdict,replace


@dataclass(frozen=True)
class InputPolicy:
    input_tokens: int
    output_tokens: int
    context_tokens: int
    images: int
    image_side: int
    image_bytes: int
    payload_bytes: int


POLICIES={
    'generate':InputPolicy(16384,49152,65536,3,960,160_000,1_000_000),
    'regenerate_candidate':InputPolicy(10000,8000,24576,1,960,160_000,600_000),
    'local_patch':InputPolicy(6000,4096,16384,1,960,120_000,320_000),
    'numeric_patch':InputPolicy(6000,4096,12288,0,0,0,128_000),
    'visual_feedback':InputPolicy(8000,6000,16384,1,960,120_000,400_000),
    'general':InputPolicy(32768,16384,65536,3,768,160_000,1_500_000),
    'polish':InputPolicy(20000,8192,32768,0,0,0,180_000),
    'domain_terms':InputPolicy(18000,8192,32768,0,0,0,160_000),
    # 联网词库更新：64 词条 × 全证据字段（sources/evidence）≈ 9-12k 输出；
    # 沿用 domain_terms 的 8k 输出上限，实测会让模型丢弃全部来源字段。
    'glossary_update':InputPolicy(18000,16000,49152,0,0,0,240_000),
    'group':InputPolicy(20000,8192,32768,0,0,0,180_000),
}


class InputBudgetError(ValueError):
    def __init__(self, report, reasons):
        self.report=report
        super().__init__('输入预算检查失败：'+'；'.join(reasons)+'。占用与限额：'+json.dumps(report,ensure_ascii=False,separators=(',',':')))


def compact(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))


def project_transport_messages(messages, schema, transport):
    """Idempotent projection before *every* budget gate, not after it.

    Grok receives the schema in its structured-output argument. Only exact JSON
    copies may be replaced in text; images, user requirements and all other
    constraints remain byte-for-byte intact. Other transports keep their text.
    """
    prepared = copy.deepcopy(list(messages))
    if getattr(transport, 'value', transport) != 'grok_cli' or schema is None:
        return prepared
    duplicates = tuple(dict.fromkeys((compact(schema), json.dumps(schema, ensure_ascii=False,
                                                               sort_keys=True, separators=(',', ':')))))
    def projected(text):
        for duplicate in duplicates:
            text = text.replace(duplicate, '[完整JSON Schema由本次结构化输出参数提供]')
        return text
    for message in prepared:
        if isinstance(message.get('content'), str):
            message['content'] = projected(message['content'])
        elif isinstance(message.get('content'), list):
            for block in message['content']:
                if block.get('type') == 'text':
                    block['text'] = projected(str(block.get('text', '')))
    return prepared


def measure(messages,schema,max_tokens,operation,images,scope=None):
    text=[]
    for message in messages:
        content=message.get('content','')
        if isinstance(content,list):text.extend(str(block.get('text','')) for block in content if block.get('type')=='text')
        else:text.append(str(content))
    text_value='\n'.join(text)
    text_bytes=len(text_value.encode('utf8'))
    schema_bytes=len(compact(schema).encode('utf8')) if schema is not None else 0
    image_tokens=sum(256+1024*math.ceil(item['width']*item['height']/(512*512)) for item in images)
    # Reserve the CLI role delimiters and protocol envelope as well as text.
    # Model tokenization is unknown; this is an application bound, not billing.
    envelope_bytes=256+sum(len(str(m.get('role','user')).encode('utf8'))+6 for m in messages)
    estimate=math.ceil((text_bytes+schema_bytes+envelope_bytes)/3)+image_tokens
    return dict(operation=operation,policy=asdict(POLICIES[operation]),input_characters=len(text_value),text_utf8_bytes=text_bytes,
        schema_utf8_bytes=schema_bytes,images=images,image_count=len(images),
        payload_utf8_bytes=len(compact(messages).encode('utf8'))+schema_bytes,
        input_token_estimate=estimate,image_token_reserve=image_tokens,output_token_reserve=int(max_tokens),
        combined_token_reserve=estimate+int(max_tokens),token_method='ceil(text+schema UTF8/3) + conservative pixel tiles; not billing',
        source_scope=scope or {'kind':'full_request' if operation in ('general','generate') else 'unspecified'})


def prepare_input(messages, *, schema=None, max_tokens=3500, operation='general', scope=None, crops=None, comparison=False,
                  model_limits=None, user_limits=None):
    if operation not in POLICIES:raise ValueError('Unknown input operation: '+str(operation))
    policy=POLICIES[operation]
    default_policy=policy
    known=model_limits or {}
    hard=user_limits or {}
    def positive(values,key,fallback):
        value=values.get(key)
        return value if isinstance(value,int) and not isinstance(value,bool) and value>0 else fallback
    context=min(policy.context_tokens,positive(known,'context_tokens',policy.context_tokens),
                positive(hard,'context_tokens',policy.context_tokens))
    # Application input allocation is soft only when the selected endpoint has
    # reported its context. Unknown/other-model capabilities never lift it.
    verified_context=bool(known.get('source') and positive(known,'context_tokens',0))
    available=max(0,context-int(max_tokens)-1024)
    inputs=available if verified_context else min(policy.input_tokens,available)
    inputs=min(inputs,positive(known,'input_tokens',inputs),positive(hard,'input_tokens',inputs))
    policy=replace(policy,input_tokens=inputs,context_tokens=context,
        output_tokens=min(policy.output_tokens,positive(known,'output_tokens',policy.output_tokens),
                          positive(hard,'output_tokens',policy.output_tokens)))
    source_images=sum(block.get('type')=='image_url' for message in messages
        for block in (message.get('content') if isinstance(message.get('content'),list) else []))
    max_images=2 if comparison and operation in ('local_patch','visual_feedback') else policy.images
    if source_images>max_images:
        raise InputBudgetError(dict(operation=operation,image_count=source_images,image_limit=max_images),['截图数量超限；不会静默丢弃参考图'])
    if operation in ('local_patch','numeric_patch','visual_feedback') and not (scope or {}).get('allowed_paths'):
        raise InputBudgetError(dict(operation=operation),['局部操作缺少精确允许路径'])
    if (source_images and operation in ('local_patch','visual_feedback') and not crops
            and not (scope or {}).get('images_already_cropped')):
        raise InputBudgetError(dict(operation=operation),['局部截图缺少问题区域裁剪坐标'])
    prepared=copy.deepcopy(list(messages));images=[];index=0
    for message in prepared:
        content=message.get('content')
        if not isinstance(content,list):continue
        for block in content:
            if block.get('type')!='image_url':continue
            value=block.get('image_url',{}).get('url','')
            match=re.fullmatch(r'data:image/(png|jpeg|webp);base64,(.+)',value,re.S)
            if not match:raise ValueError('Screenshot must be local png/jpeg/webp data')
            raw=base64.b64decode(match.group(2),validate=True)
            from PIL import Image
            with Image.open(io.BytesIO(raw)) as original:
                before_size=original.size;source_format=original.format
                image=original.convert('RGBA')
                crop=(crops or {}).get(index)
                if crop is not None:
                    if (len(crop)!=4 or any(type(n) is not int for n in crop)
                            or not (0<=crop[0]<crop[2]<=image.width and 0<=crop[1]<crop[3]<=image.height)):
                        raise ValueError('Screenshot crop must be a nonempty source-pixel rectangle')
                    image=image.crop(tuple(crop))
                image.thumbnail((policy.image_side,policy.image_side),Image.Resampling.LANCZOS)
                matte=Image.new('RGBA',image.size,(42,48,56,255));matte.alpha_composite(image);image=matte.convert('RGB')
                encoded=b''
                for quality in (82,72,62):
                    buffer=io.BytesIO();image.save(buffer,format='JPEG',quality=quality,optimize=True);encoded=buffer.getvalue()
                    if len(encoded)<=policy.image_bytes:break
                if len(encoded)>policy.image_bytes:
                    raise InputBudgetError(dict(operation=operation,image_bytes=len(encoded),limit=policy.image_bytes),['截图压缩后仍超限'])
                block['image_url']={'url':'data:image/jpeg;base64,'+base64.b64encode(encoded).decode('ascii')}
                images.append(dict(index=index,source_width=before_size[0],source_height=before_size[1],source_format=source_format,
                    source_bytes=len(raw),source_sha256=hashlib.sha256(raw).hexdigest(),crop=crop,width=image.width,height=image.height,
                    format='JPEG',quality=quality,bytes=len(encoded),base64_bytes=4*math.ceil(len(encoded)/3),sha256=hashlib.sha256(encoded).hexdigest()))
                index+=1
    report=measure(prepared,schema,max_tokens,operation,images,scope)
    report.update(policy=asdict(policy), application_defaults=asdict(default_policy),
        budget_sources=dict(application='provider_input_budget.POLICIES; soft input allocation',
                            model=known or 'unknown', user_hard_limits=hard or None),
        safety_margin_tokens=1024, envelope_utf8_bytes=256+sum(len(str(m.get('role','user')).encode('utf8'))+6 for m in prepared),
        available_input_tokens=inputs, unused_input_tokens=inputs-report['input_token_estimate'],
        reallocated=inputs>default_policy.input_tokens, dispatched=False)
    report['message_components'] = [dict(role=m.get('role', 'user'),
        text_utf8_bytes=len((''.join(str(b.get('text','')) for b in m['content'] if b.get('type')=='text')
                            if isinstance(m.get('content'),list) else str(m.get('content',''))).encode('utf8')))
        for m in prepared]
    report['image_limit']=max_images
    reasons=[]
    if report['input_token_estimate']>policy.input_tokens:reasons.append('输入token估算超过操作限额')
    if max_tokens>policy.output_tokens or max_tokens<=0:reasons.append('输出预留超过操作限额或非正数')
    if report['combined_token_reserve']>policy.context_tokens:reasons.append('输入与输出预留总和超过上下文限额')
    if report['payload_utf8_bytes']>policy.payload_bytes:reasons.append('实际输入字节超过操作限额')
    if reasons:raise InputBudgetError(report,reasons)
    report['passed']=True
    return prepared,report


def windows_argv_units(command):
    return len(subprocess.list2cmdline(list(command)).encode('utf-16-le'))//2+1


def launch_budget(command):
    """Measure the actual wrapper passed to CreateProcess, including cmd.exe."""
    from .processes import canonical_subprocess_command
    launch = [str(x) for x in canonical_subprocess_command(command)]
    shell = any(str(x).lower().endswith(('cmd.exe', '.cmd', '.bat')) for x in launch[:5])
    return dict(argv_utf16_units=windows_argv_units(launch), argv_limit=8000 if shell else 31500,
                launch_chain=[str(x) for x in launch[:1]], shell_wrapper=shell)


def pack_items(items, build_messages, *, operation, max_tokens, schema=None):
    """Greedily pack complete items using their final serialized requests.

    A rejected singleton is returned separately with its budget report. No text,
    JSON, or editable item is truncated. The caller must report its fallback.
    """
    batches, rejected, current = [], [], []
    for item in items:
        trial = [*current, item]
        try:
            prepare_input(build_messages(trial), schema=schema, max_tokens=max_tokens, operation=operation)
        except InputBudgetError:
            if current:
                batches.append(current)
                current = []
            try:
                prepare_input(build_messages([item]), schema=schema, max_tokens=max_tokens, operation=operation)
            except InputBudgetError as exc:
                rejected.append((item, exc.report))
            else:
                current = [item]
        else:
            current = trial
    if current:
        batches.append(current)
    return batches, rejected


DETERMINISTIC_FAILURES = frozenset({
    'request_too_large', 'payload_too_large', 'transport_length',
    'authentication_required', 'cancelled', 'permission_denied', 'forbidden',
    'configuration_error', 'not_installed', 'unsupported_cli', 'unsupported_search',
    'model_unavailable',
})


def failure_category(error):
    if getattr(error, 'winerror', None) == 206:
        return 'transport_length'
    return str(getattr(error, 'category', 'request_error'))


def retry_delay(error, attempt):
    """Bound server retry hints; deterministic failures never sleep."""
    if failure_category(error) in DETERMINISTIC_FAILURES:
        return None
    response = getattr(error, 'response', None)
    if getattr(response, 'status_code', None) in {400, 401, 403, 404}:
        return None
    hint = getattr(response, 'headers', {}).get('Retry-After') if response is not None else None
    try:
        return min(30.0, max(0.0, float(hint))) if hint is not None else min(8, 2 ** (attempt - 1))
    except (ValueError, TypeError):
        try:
            from email.utils import parsedate_to_datetime
            from datetime import datetime, timezone
            return min(30.0,max(0.0,(parsedate_to_datetime(hint)-datetime.now(timezone.utc)).total_seconds()))
        except (ValueError,TypeError,OverflowError):
            return min(8, 2 ** (attempt - 1))


class RetryBudget:
    """One bounded pool of retries, shared by siblings and split children."""
    def __init__(self, count):
        self.remaining=max(0,int(count))
        self._lock=threading.Lock()

    def take(self):
        with self._lock:
            if not self.remaining:
                return False
            self.remaining-=1
            return True


def wait_retry(seconds, cancel_check):
    import time
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if cancel_check():
            return False
        time.sleep(min(.05, max(0, until-time.monotonic())))
    return not cancel_check()
