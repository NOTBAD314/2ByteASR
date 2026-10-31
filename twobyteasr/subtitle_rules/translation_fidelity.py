"""Translation quantity checks, independent of source-edit character gates.

    Italian 150.000, Chinese 十五万 and 150,000 are one quantity. FP3 is an
    identifier. Time readings, ranges and 半 need their own surface handling.
"""
from __future__ import annotations
from collections import Counter
from decimal import Decimal,InvalidOperation
import re

RULE_VERSION='translation-quantities-v1'
ARABIC=re.compile(r'(?<![A-Za-z0-9_])[-−+]?\d+(?:[.,]\d+)*(?:[万亿千百])?(?![A-Za-z0-9_])')
HAN=re.compile(r'[零〇一二两三四五六七八九十百千万亿]+(?:点[零〇一二两三四五六七八九十百千万亿]+)?')
LOCALE_GROUPING=frozenset({'it','de','es','pt','fr'})


def decimal_value(text,language):
    scale=Decimal({'万':10000,'亿':100000000,'千':1000,'百':100}.get(text[-1:],1))
    text=text.rstrip('万亿千百').replace('−','-')
    if ',' in text and '.' in text:
        # The final separator is the decimal separator; earlier ones group.
        decimal=',' if text.rfind(',')>text.rfind('.') else '.'
        text=text.replace('.' if decimal==',' else ',','').replace(decimal,'.')
    elif re.fullmatch(r'\d{1,3}(?:[.,]\d{3})+',text):
        separator='.' if '.' in text else ','
        if not text.startswith('0.') and (len(text.split(separator))>2 or separator==',' or language in LOCALE_GROUPING):
            text=text.replace(separator,'')
    elif ',' in text:
        text=text.replace(',','.')
    try:return Decimal(text)*scale
    except InvalidOperation:return None


def quantities(text,language='',*,include_han=True):
    from .number_fidelity import integer_value,DIGITS
    text=str(text).replace('百分百','百分之百')
    result=[]
    for match in ARABIC.finditer(text):
        value=decimal_value(match.group(),language)
        if value is None:continue
        following=text[match.end():]
        if re.match(r'\s+e\s+mezz[oa]\b',following,re.I) or following.startswith('分半'):
            value+=Decimal('.5')
        percent=following.lstrip().startswith(('%','％')) or text[:match.start()].endswith('百分之')
        result.append(('percent' if percent else 'number',value))
    for match in HAN.finditer(text) if include_han else ():
        raw=match.group();following=text[match.end():]
        if following.startswith('分之'):continue  # percentage prefix itself
        parts=raw.split('点')
        first=integer_value(parts[0]) or {'百':'100','千':'1000','万':'10000','亿':'100000000'}.get(parts[0])
        if first is None:continue
        if len(parts)>1 and following.startswith('分'):
            # 十点十五分: hour/minute quantities, not a decimal score.
            second=integer_value(parts[1])
            result.append(('number',Decimal(first)))
            if second is not None:result.append(('number',Decimal(second)))
            continue
        value=Decimal(first)
        if text[:match.start()].endswith('负'):value=-value
        if len(parts)>1:
            if any(c not in DIGITS for c in parts[1]):continue
            value+=Decimal('0.'+''.join(str(DIGITS[c]) for c in parts[1]))
        if following.startswith('分半'):value+=Decimal('.5')
        kind='percent' if text[:match.start()].endswith('百分之') else 'number'
        result.append((kind,value))
        # 三四年 is a spoken range as well as a possible digit sequence. Do
        # not reject a correct range solely because a compact parser reads 34.
        if len(raw)==2 and all(c in DIGITS for c in raw) and following.startswith(('年','个','次','圈','天')):
            result.extend(('number',Decimal(DIGITS[c])) for c in raw)
    return Counter(result)


def quantity_mismatch(source,output,source_language='',target_language='zh'):
    if target_language!='zh':return False
    expected=quantities(source,source_language,include_han=False)
    actual=quantities(output,target_language)
    for (kind,value),count in expected.items():
        if kind=='percent' and value==100 and re.search(r'完全|全部|彻底|全然',output):
            continue
        if actual[(kind,value)]<count:
            return True
    return False
