"""Material bindings describe actual styled nodes, never a required DOM tree."""
import re


class MaterialBindingError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__('；'.join(f"{i['path']}: {i['actual']}；{i['expected']}" for i in issues))


def material_binding_issues(contract, source):
    from .authored_repair import css_values
    html, css = source.get('cueHtml', ''), source.get('cueCss', '')
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    declarations = list(css_values(css))
    from .theme_dom import ThemeDOM
    dom=ThemeDOM(html,conditional_text=True)
    # SVG presentation attributes are real paint, not missing CSS. Recognize
    # them only on SVG geometry/inheritable SVG containers; the normal HTML
    # sanitizer still validates every attribute and URL before rendering.
    svg_tags={'svg','g','path','rect','circle','ellipse','line','polyline','polygon'}
    painted=set()
    for node,row in enumerate(dom.rows):
        if row['tag'] not in svg_tags:continue
        parent=node
        resolved={}
        while parent is not None and dom.rows[parent]['tag'] in svg_tags:
            attrs=dom.rows[parent]['attrs']
            for prop in ('fill','stroke'):
                if prop in attrs and prop not in resolved:resolved[prop]=str(attrs[prop]).strip().casefold()
            parent=dom.rows[parent]['parent']
        if any(value not in ('','none','transparent') for value in resolved.values()):painted.add(node)
    for node in tuple(painted):
        parent=dom.rows[node]['parent']
        while parent is not None and dom.rows[parent]['tag'] in {'g','svg'}:
            painted.add(parent);parent=dom.rows[parent]['parent']
    styled=set(painted)
    for declaration in declarations:
        for rule in declaration['selector'].split(','):
            matched = dom.targets(re.sub(r'::(?:before|after)$', '', rule.strip()),allow_tags=True)
            if matched:styled.update(matched)
    issues = []
    for index, selector in enumerate(contract.get('selectors', [])):
        targets = dom.targets(selector,allow_tags=True)
        related = [d for d in declarations if selector in [s.strip() for s in d['selector'].split(',')]]
        # Shared, compound and ancestor rules are valid when they style the
        # bound node. Substring occurrences in comments/values are not proof.
        actual = None
        if targets is None:
            actual = f'{selector!r} 使用了未支持的材质绑定语法'
        elif not targets:
            actual = f'{selector!r} 在cueHtml中匹配0个节点；CSS声明数={len(related)}'
        elif not targets.intersection(styled):
            actual = f'{selector!r} 匹配{len(targets)}个节点，但没有样式规则作用于这些节点'
        if actual:
            issues.append(dict(path=f'MaterialContract.selectors[{index}]', selector=selector,
                actual=actual, expected='绑定到已有且有材质样式的实际节点；不要求固定标签层级',
                missing_node=targets==set(), related_declarations=related,
                repair_scope=['generated_source.cueHtml'] if targets==set() and related else []))
    return issues


def validate_material_bindings(contract, source):
    issues = material_binding_issues(contract, source)
    if issues:
        raise MaterialBindingError(issues)


def validate_material_html_edit(before, after, allowed_classes):
    """Only insert missing material nodes/classes; existing artwork is immutable.

    The normal sanitizer and complete theme validator run after this check.
    Inserted layers must be decorative, contain no caption, and use a missing
    class. No sibling removal, font/color/layout change or text rewrite.
    """
    from html.parser import HTMLParser

    class Tree(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.root = []
            self.stack = [self.root]
        def handle_starttag(self, tag, attrs):
            node = [tag, dict(attrs), []]
            self.stack[-1].append(node)
            if tag not in ('br', 'hr', 'img', 'input', 'meta', 'link'):
                self.stack.append(node[2])
        def handle_startendtag(self, tag, attrs):
            self.handle_starttag(tag, attrs)
            if tag not in ('br', 'hr', 'img', 'input', 'meta', 'link'):
                self.stack.pop()
        def handle_endtag(self, tag):
            if len(self.stack)>1:
                self.stack.pop()
        def handle_data(self, data):
            if data.strip():
                self.stack[-1].append(data)

    a, b = Tree(), Tree()
    a.feed(before)
    b.feed(after)

    def unchanged(old, new):
        if isinstance(old, str) or isinstance(new, str):
            return old==new
        if old[0]!=new[0]:
            return False
        attrs = dict(new[1])
        classes = attrs.get('class', '').split()
        attrs['class'] = ' '.join(c for c in classes if c not in allowed_classes)
        if not attrs['class'] and 'class' not in old[1]:
            attrs.pop('class')
        return old[1]==attrs and sequence(old[2], new[2])

    def inserted(node):
        return (isinstance(node, list) and node[1].get('aria-hidden')=='true'
            and set(node[1].get('class', '').split())<=allowed_classes
            and bool(set(node[1].get('class', '').split()) & allowed_classes)
            and not node[2])

    def sequence(old, new):
        pos = 0
        for node in new:
            if pos<len(old) and unchanged(old[pos], node):
                pos += 1
            elif not inserted(node):
                return False
        return pos==len(old)

    if not sequence(a.root, b.root):
        raise ValueError('材质修复超出缺失图层范围：已有节点、正文、属性和层级必须保持')
