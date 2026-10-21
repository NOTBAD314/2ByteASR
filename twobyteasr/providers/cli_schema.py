"""Service request schemas are projections, never the local safety contract.

Unsupported constraints are delegated as whole expressions (including negation),
so projection cannot accidentally turn ``not: {}`` into reject-everything.
Run this preflight before starting a CLI or sending a paid request.
"""
import copy
import re

PROJECTION_VERSION = 'request-schema-re2-v4-html16k'
_UNSUPPORTED = re.compile(r'\(\?(?:[=!>]|<[=!] |P|\()|\\[1-9]|\\[gk][<{]', re.X)


def _unsupported_patterns(node):
    if isinstance(node, list):
        return any(_unsupported_patterns(item) for item in node)
    if isinstance(node, dict):
        pattern = node.get('pattern')
        return (isinstance(pattern, str) and bool(_UNSUPPORTED.search(pattern))) or any(
            _unsupported_patterns(value) for value in node.values())
    return False


def preflight_request_schema(schema):
    """Executable, conservative RE2-subset and JSON Schema contract check."""
    from jsonschema import Draft202012Validator
    Draft202012Validator.check_schema(schema)
    def visit(node, path='$'):
        if isinstance(node, list):
            for index, item in enumerate(node):visit(item, f'{path}/{index}')
        elif isinstance(node, dict):
            if isinstance(node.get('pattern'), str):
                pattern = node['pattern']
                if _UNSUPPORTED.search(pattern):
                    raise ValueError(f'Unsupported remote regex at {path}/pattern')
                try:re.compile(pattern)
                except re.error as exc:raise ValueError(f'Invalid remote regex at {path}/pattern: {exc}') from exc
            for key, value in node.items():visit(value, f'{path}/{key}')
    visit(schema)


def request_schema(schema, *, dialect='re2'):
    if dialect != 're2':
        raise ValueError(f'Unknown request schema dialect: {dialect}')
    value=copy.deepcopy(schema)
    delegated=[]
    def visit(node, path='$'):
        if isinstance(node,list):
            for index,row in enumerate(node):visit(row,f'{path}/{index}')
        elif isinstance(node,dict):
            # HTML/CSS predicates are substring semantics locally. Native
            # grammar compilers may constrain the entire string to the regex
            # match (e.g. only {{text}}), destroying authored markup. Keep
            # shape/size on the wire and enforce ALL content rules locally.
            if path.rsplit('/',1)[-1] in {'cueHtml','cueCss','stageCss'}:
                for constraint in ('pattern','not','allOf'):
                    if constraint in node:
                        delegated.append(f'{path}/{constraint}');del node[constraint]
            pattern=node.get('pattern')
            if pattern==r'^(?!\s*$)[^\r\n\x00-\x1f]+$':
                node['pattern']=r'^[^\r\n\x00-\x1f]+$'
                node.setdefault('allOf',[]).append({'pattern':r'\S'})
            # Negation and exclusive branches must be delegated as a unit.
            for keyword in ('not','oneOf','if'):
                if keyword in node and _unsupported_patterns(node[keyword]):
                    delegated.append(f'{path}/{keyword}')
                    del node[keyword]
                    if keyword=='if':
                        node.pop('then',None);node.pop('else',None)
            if isinstance(node.get('pattern'),str) and _UNSUPPORTED.search(node['pattern']):
                delegated.append(f'{path}/pattern');del node['pattern']
            for key,child in node.items():visit(child,f'{path}/{key}')
    visit(value)
    preflight_request_schema(value)
    return value, {'version': PROJECTION_VERSION, 'dialect': dialect,
                   'preflight': 'passed', 'local_only_constraints': delegated}

def re2_schema(schema):
    return request_schema(schema)[0]
