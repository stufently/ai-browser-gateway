"""Small tolerant HTML tree; no network or browser dependencies."""
from html.parser import HTMLParser
import re
from urllib.parse import quote, urljoin, urlsplit

VOID = frozenset('area base br col embed hr img input link meta param source track wbr'.split())
HIDDEN = frozenset('script style noscript iframe svg nav header footer head'.split())
HEAD_CONTENT = frozenset('base link meta title style script noscript template'.split())
_DECIMAL_CHARREF = re.compile(r"&#([0-9]+)(;?)")


# Keep paired with _clip_oversized_charrefs in bench/providers/docker/probe.py.
# The provider probe is mounted as one standalone file, so it cannot share imports.
def _clip_oversized_charrefs(text: str) -> str:
    """Keep decimal references safe for unescape's integer conversion."""
    def replace(match: re.Match[str]) -> str:
        # The integer digit limit includes leading zeros. Strip them even
        # when the value fits Unicode; eight significant digits never fit.
        digits = match.group(1).lstrip("0") or "0"
        if len(digits) >= 8:
            return "\ufffd"
        return "&#" + digits + match.group(2)

    return _DECIMAL_CHARREF.sub(replace, text)


def normalized(text):
    return ' '.join(text.split())


def escaped(text):
    return re.sub(r'([\\`*_{}\[\]()#+\-.!<>|&~=])', r'\\\1', text)


def http_url(base, value):
    try:
        url = urljoin(base, value)
        return url if urlsplit(url).scheme in ('http', 'https') and urlsplit(url).netloc else None
    except ValueError:
        return None


def destination(base, value):
    url = http_url(base, value)
    return re.sub(r'[\s()<>\\]', lambda m: quote(m[0], safe=''), url) if url else None


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        pending, chunks = [self], []
        while pending:
            node = pending.pop()
            if isinstance(node, str):
                chunks.append(node)
            else:
                pending.extend(reversed(node.children))
        return ''.join(chunks)

    def walk(self):
        # Iterative traversal also handles deeply nested upstream documents.
        pending = [self]
        while pending:
            node = pending.pop()
            yield node
            pending.extend(reversed([n for n in node.children if isinstance(n, Node)]))


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(_clip_oversized_charrefs(html))
        self.close()

    def handle_starttag(self, tag, attrs):
        if self.stack[-1].tag == 'head' and tag not in HEAD_CONTENT:
            self.handle_endtag('head')
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if self.stack[-1].tag == 'head' and data.strip():
            self.handle_endtag('head')
        self.stack[-1].children.append(data)


def markdown(node, base, pre=False):
    # Explicit postorder stack avoids Python's recursion limit on valid deep DOMs.
    pending, chunks = [(node, pre, pre, None)], []
    while pending:
        node, pre, literal, start = pending.pop()
        if isinstance(node, str):
            text = node if pre else re.sub(r'\s+', ' ', node)
            chunks.append(text if literal else escaped(text))
        elif start is not None:
            text = ''.join(chunks[start:])
            del chunks[start:]
            chunks.append(markdown_element(node, text, base, pre))
        elif node.tag not in HIDDEN:
            pending.append((node, pre, literal, len(chunks)))
            pending.extend((child, pre or node.tag == 'pre', literal or node.tag in ('pre', 'code'), None)
                           for child in reversed(node.children))
    return ''.join(chunks)


def markdown_element(node, text, base, pre):
    tag, attrs = node.tag, node.attrs
    if tag == 'pre':
        fence = '`' * max(3, max((len(m[0]) + 1 for m in re.finditer(r'`+', text)), default=0))
        return '\n\n' + fence + '\n' + text + '\n' + fence + '\n\n'
    if tag == 'code':
        if pre:
            return text
        fence = '`' * max((len(m[0]) + 1 for m in re.finditer(r'`+', text)), default=1)
        return fence + (' ' + text + ' ' if '`' in text else text) + fence
    if tag in ('strong', 'b', 'em', 'i'):
        marker = '**' if tag in ('strong', 'b') else '*'
        return marker + text + marker
    if tag == 'a':
        href = destination(base, attrs.get('href') or '') if 'href' in attrs else None
        return '[' + text + '](' + href + ')' if href else text
    if tag == 'img':
        src = destination(base, attrs.get('src') or '') if 'src' in attrs else None
        alt = escaped(attrs.get('alt') or '')
        return '![' + alt + '](' + src + ')' if src else alt
    if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
        return '\n\n' + '#' * int(tag[1]) + ' ' + text.strip() + '\n\n'
    if tag == 'li':
        return '\n- ' + text.strip() + '\n'
    if tag == 'blockquote':
        return '\n\n' + '\n'.join('> ' + line for line in text.strip().splitlines()) + '\n\n'
    if tag == 'br':
        return '\n'
    if tag in ('p', 'div', 'section', 'article', 'ul', 'ol'):
        return '\n\n' + text.strip() + '\n\n'
    return text
