"""Apply shared layout spans without restarting an ASS cue's animation clock."""
import re


def _ms(value):
    h, m, s = value.split(':')
    return round((int(h)*3600+int(m)*60+float(s))*1000)


def _shift_clip(match, offset):
    kind, payload = match.group(1), match.group(2)
    fields = payload.split(',')
    if len(fields) == 4 and all(re.fullmatch(r'[-+\d. ]+', v) for v in fields):
        fields[1] = f'{float(fields[1])-offset:.3f}'
        fields[3] = f'{float(fields[3])-offset:.3f}'
        return '\\'+kind+'('+','.join(fields)+')'
    scale, drawing = (int(fields[0]), ','.join(fields[1:])) if len(fields)>1 and fields[0].strip().isdigit() else (1, payload)
    index = -1
    def coordinate(number):
        nonlocal index
        index += 1
        return f'{float(number.group())-offset*2**(scale-1):.3f}' if index%2 else number.group()
    drawing = re.sub(r'[-+]?\d+(?:\.\d+)?', coordinate, drawing)
    return '\\'+kind+'('+(f'{scale},' if scale != 1 else '')+drawing+')'


def apply_layout_events(lines, schedule, width, height):
    spans = ()
    for line in lines:
        if line.startswith('; CollisionCue='):
            spans = schedule.get(line.split('=', 1)[1], ())
        if not line.startswith('Dialogue:') or not spans or all(not o for _, _, o in spans):
            yield line
            continue
        fields = line.split(',', 9)
        start, end = _ms(fields[1]), _ms(fields[2])
        original = fields[9]
        for a, b, offset in spans:
            a, b = max(start, a), min(end, b)
            if b <= a:
                continue
            def position(match):
                values = match.group(2).split(',')
                values[1] = f'{float(values[1])-offset:.3f}'
                if match.group(1) == 'move':
                    values[3] = f'{float(values[3])-offset:.3f}'
                return '\\'+match.group(1)+'('+','.join(values)+')'
            text = re.sub(r'\\(pos|move)\(([^)]+)\)', position, original)
            authored_clip = re.search(r'\\(i?clip)\(([^)]+)\)', text)
            text = re.sub(r'\\(i?clip)\(([^)]+)\)', lambda m: _shift_clip(m, offset), text)
            # Keep the original event start/end and all motion/fade/word times.
            # Rectangular clip is a time gate only; it never measures content.
            if a > start or b < end:
                if authored_clip:
                    # Frame-sampled glyph/shard events already own a vector
                    # clip and static opacity. Multiply a time gate via fade;
                    # replacing their cut shape with a rectangle corrupts it.
                    text = re.sub(r'\\fade\([^)]+\)', '', text)
                    gate = f'\\fade(255,0,255,{a-start},{a-start},{b-start},{b-start})'
                else:
                    full = f'\\clip(0,0,{width},{height})'
                    empty = r'\clip(0,0,0,0)'
                    gate = empty+f'\\t({a-start},{a-start},{full})' if a > start else full
                    if b < end:
                        gate += f'\\t({b-start},{b-start},{empty})'
                text = '{'+gate+'}'+text
            yield ','.join([*fields[:9], text])
