"""Pure output formats for an already fetched product outcome."""
from gateway.format_html import Document, http_url, markdown, normalized

MODES = ('text', 'html', 'markdown', 'links', 'meta')


def render_content(outcome, format_name):
    if format_name not in MODES:
        raise ValueError('invalid format')
    if not outcome.ok:
        return [] if format_name == 'links' else {} if format_name == 'meta' else ''
    if format_name in ('text', 'html'):
        return getattr(outcome, format_name)
    root = Document(outcome.html).root
    if format_name == 'markdown':
        return markdown(root, outcome.final_url).strip()
    if format_name == 'links':
        result = []
        for node in root.walk():
            if node.tag == 'a' and 'href' in node.attrs:
                href = http_url(outcome.final_url, node.attrs['href'] or '')
                if href:
                    result.append({'text': normalized(node.text())[:100], 'href': href})
        return result
    result, meta = {'title': '', 'h1': []}, {}
    title_seen = False
    for node in root.walk():
        attrs = node.attrs
        if node.tag == 'title' and not title_seen:
            result['title'], title_seen = normalized(node.text()), True
        elif node.tag == 'h1':
            result['h1'].append(normalized(node.text()))
        elif node.tag == 'html' and attrs.get('lang') is not None:
            result.setdefault('lang', attrs['lang'])
        elif node.tag == 'meta' and attrs.get('content') is not None:
            key = (attrs.get('name') or attrs.get('property') or '').lower()
            meta.setdefault(key, attrs['content'])
        elif node.tag == 'link' and 'canonical' in (attrs.get('rel') or '').lower().split():
            href = http_url(outcome.final_url, attrs.get('href') or '')
            if href:
                result.setdefault('canonical', href)
    for source, target in [('og:description', 'description'), ('description', 'description'),
                           ('og:title', 'ogTitle'), ('og:image', 'ogImage')]:
        if source in meta:
            result[target] = meta[source]
    return result
