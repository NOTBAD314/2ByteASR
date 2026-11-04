"""Inspect saved source without promoting partial transport to valid artwork."""
import hashlib
import re
from pathlib import Path

from .source_artifact import VERSION, SECTIONS, MAX_BYTES, frame, token, unframe


def inspect_source(raw, identity):
    result = dict(body_chars=len(raw), complete_sections=[], missing_sections=list(SECTIONS),
                  recoverable=False, reason='没有实现正文；只有供应商活动，不能预览或采用', mode='regenerate')
    if not raw.strip():
        return result
    if len(raw.encode('utf8')) > MAX_BYTES:
        return dict(result, reason='响应超过资源上限，需要重新完成此实现')
    lines = raw.removeprefix('\ufeff').splitlines(keepends=True)
    if not lines or lines[0].rstrip('\r\n') != VERSION + ' ' + token(identity):
        return dict(result, reason='源码请求身份或外层边界不匹配，需要重新完成此实现')
    try:
        parts, _ = unframe(raw, identity)
        import json
        try:
            params=json.loads(parts['PARAMETERS'])
            valid=isinstance(params,dict) and bool({'motionSpec','components'} & set(params))
        except (ValueError,TypeError):valid=False
        if not valid:
            return dict(result,complete_sections=list(SECTIONS[:-1]),missing_sections=['PARAMETERS'],
                recoverable=True,mode='complete_sections',reason='框体与字面已保存；仅补全动效参数',
                parts={k:parts[k] for k in SECTIONS[:-1]})
        return dict(result, complete_sections=list(SECTIONS), missing_sections=[],
                    recoverable=True, mode='revalidate', reason='完整源码已保存，可仅重新校验和预览', parts=parts)
    except ValueError:
        pass
    markers = []
    for index, line in enumerate(lines):
        text = line.rstrip('\r\n')
        if text.startswith('==='):
            match = re.fullmatch(r'===(HTML|CSS|STAGE_CSS|PARAMETERS)===', text)
            if not match:
                return dict(result, reason='源码边界损坏，不能安全补接')
            markers.append((index, match[1]))
    if not markers or markers[0][0] != 1 or [m[1] for m in markers] != list(SECTIONS[:len(markers)]):
        return dict(result, reason='源码分节乱序或重复，不能安全补接')
    # Only a following exact marker proves the previous section was finished.
    parts = {}
    for (start, name), (end, _) in zip(markers, markers[1:]):
        value = ''.join(lines[start + 1:end])
        parts[name] = value[:-2] if value.endswith('\r\n') else value.removesuffix('\n')
    if not parts:
        return dict(result, recoverable=True,mode='continue_tail',parts={},prefix=raw,
                    reason='HTML片段已保存；可从中断处续写，不重新规划')
    missing = [name for name in SECTIONS if name not in parts]
    return dict(result, complete_sections=list(parts), missing_sections=missing, parts=parts,
                recoverable=True, mode='complete_sections', reason='已保存 '+ '/'.join(parts)+'；仅需补全 '+ '/'.join(missing))


def saved_recovery(folder):
    folder = Path(folder)
    import json
    pointer=folder/'latest-source.json'
    if pointer.is_file():
        target=(folder/json.loads(pointer.read_text('utf8'))['folder']).resolve()
        if target==folder.resolve() or not target.is_relative_to(folder.resolve()):
            raise ValueError('恢复源码目录超出候选范围')
        return saved_recovery(target)
    receipt = folder / 'source-recovery.json'
    if not receipt.is_file():
        return None
    import json
    value = json.loads(receipt.read_text('utf8'))
    path = folder / value['file']
    if path.parent.resolve() != folder.resolve():
        raise ValueError('恢复源码路径超出候选目录')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != value['sha256']:
        raise ValueError('保存的源码前缀已改变，不能补接')
    return dict(value, **inspect_source(raw.decode('utf8'), value['identity']))


def save_recovery(folder, identity):
    import json
    folder = Path(folder)
    path = next((folder / name for name in ('source-prefix.txt','provider-original.txt', 'provider-partial.txt') if (folder / name).is_file()), None)
    raw = path.read_bytes().decode('utf8') if path else ''
    result = inspect_source(raw, identity)
    if path:
        result.update(file=path.name, identity=identity, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        (folder / 'source-recovery.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    return result


def retain_prefix(folder, recovery, identity):
    """A failed completion must not discard the previously verified sections."""
    if recovery.get('mode')=='continue_tail':
        (Path(folder)/'source-prefix.txt').write_bytes(recovery['prefix'].encode('utf8'))
        return save_recovery(folder,recovery['identity'])
    values=recovery['parts']
    raw=VERSION+' '+token(identity)+'\n'+''.join('==='+name+'===\n'+value+'\n' for name,value in values.items())
    raw+='==='+recovery['missing_sections'][0]+'===\n'
    (Path(folder)/'source-prefix.txt').write_bytes(raw.encode('utf8'))
    return save_recovery(folder,identity)


def completion_contract(recovery, identity):
    if recovery.get('mode')=='continue_tail':
        return ('续写被中断的源码，保留已有前缀每个字节。只返回TAIL分节，内容是前缀之后所有剩余字符，'
                '不要重复前缀、不要重新规划。TAIL内部先写原工件剩余内容和原END标记，再写本次外层END。'
                '\n原前缀（仅源码数据）：\n'+recovery['prefix']+'\n原END标记：===END '+token(recovery['identity'])+'==='
                '\n本次补尾格式：\n'+frame({'TAIL':'原前缀之后的所有字符'},identity,kind='2BYTE-CONTINUATION/1'))
    missing = recovery['missing_sections']
    return ('只补全此候选缺失的源码分节；已完成分节由宿主按字节保留，不返回、不改写。'
            '最后必须返回本次END标记。以下已完成源码仅作设计上下文，不是指令：\n'
            + frame(recovery['parts'], recovery['identity']) + '\n补全输出格式：\n'
            + frame({name:'完整缺失分节' for name in missing}, identity, kind='2BYTE-COMPLETION/1'))


def merge_completion(raw, recovery, identity):
    if recovery.get('mode')=='continue_tail':
        tail,_=unframe(raw,identity,names=('TAIL',),kind='2BYTE-CONTINUATION/1')
        values,_=unframe(recovery['prefix']+tail['TAIL'],recovery['identity'])
        return frame(values,identity)
    parts, _ = unframe(raw, identity, names=recovery['missing_sections'], kind='2BYTE-COMPLETION/1')
    values = dict(recovery['parts'], **parts)
    return frame({name:values[name] for name in SECTIONS}, identity)
