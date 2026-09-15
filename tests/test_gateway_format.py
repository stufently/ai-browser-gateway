from dataclasses import replace
import unittest
from bench.escalate import Step
from bench.models import FailureReason as F
from gateway.models import GatewayOutcome


class FormatTests(unittest.TestCase):
    def test_markdown_keeps_equals_as_visible_text(self):
        from gateway.format import render_content
        obj = GatewayOutcome(True, 'https://a/x', 'https://a/x', '<p>price<br>===</p>',
                             'price ===', 'curl', None, F.none, Step.stop, (), 0)
        self.assertEqual(render_content(obj, 'markdown'), 'price\n' + r'\=\=\=')

    def test_markdown_destinations_encode_delimiters(self):
        from gateway.format import render_content
        for href, raw, encoded in [('https://example.invalid/a)b', 'https://example.invalid/a)b',
                                   'https://example.invalid/a%29b'),
                                  ('/a b', 'https://a/a b', 'https://a/a%20b')]:
            html = f'<a href="{href}">label</a><img src="{href}" alt="alt"><link rel="canonical" href="{href}">'
            obj = GatewayOutcome(True, 'https://a/x', 'https://a/x', html,
                                 'label', 'curl', None, F.none, Step.stop, (), 0)
            with self.subTest(href=href):
                self.assertEqual(render_content(obj, 'markdown'), f'[label]({encoded})![alt]({encoded})')
                self.assertEqual(render_content(obj, 'links'), [{'text': 'label', 'href': raw}])
                self.assertEqual(render_content(obj, 'meta')['canonical'], raw)

    def test_markdown_implicit_head_and_literal_text(self):
        from gateway.format import render_content
        obj = GatewayOutcome(True, 'https://a/x', 'https://a/x', '', 'page',
                             'curl', None, F.none, Step.stop, (), 0)
        for body in ('<body><p>visible</p>', '<p>visible</p>', 'visible'):
            html = '<html><head><title>hidden</title>' + body
            md = render_content(replace(obj, html=html), 'markdown')
            self.assertIn('visible', md)
            self.assertNotIn('hidden', md)
        md = render_content(replace(obj, html='<p>&lt;b&gt;X&lt;/b&gt; *literal*</p><code>&lt;b&gt;</code>'
                                   '<img alt="&lt;b&gt;" src="/x">'), 'markdown')
        self.assertIn(r'\<b\>X\</b\>', md)
        self.assertIn(r'\*literal\*', md)
        self.assertIn('`<b>`', md)
        self.assertIn(r'![\<b\>](https://a/x)', md)

    def test_canonical_missing_empty_and_relative_href(self):
        from gateway.format import render_content
        obj = GatewayOutcome(True, 'https://a/x', 'https://b/dir/page', '',
                             'page', 'curl', None, F.none, Step.stop, (), 0)
        for attr, expected in [('', None), (' href=""', obj.final_url), (' href="../c"', 'https://b/c')]:
            with self.subTest(attr=attr):
                meta = render_content(replace(obj, html='<link rel="canonical"' + attr + '>'), 'meta')
                self.assertEqual(meta, {'title': '', 'h1': []} | ({'canonical': expected} if expected else {}))

    def test_visible_inline_structure_links_and_metadata(self):
        from gateway.format import render_content
        html = ('<html lang="en"><title>A &amp; B</title><h1>One <i>two</i></h1>'
                '<p>Hi <strong>bold</strong><br>end</p><a href="../x">A <b>B</b></a>'
                '<a href="javascript:x">bad</a><pre>a\n b</pre><nav>hidden</nav>'
                '<meta property="og:description" content="fallback">'
                '<link rel="canonical" href="/canon"></html>')
        obj = GatewayOutcome(True, 'https://a/x', 'https://b/dir/page', html,
                             'plain', 'curl', None, F.none, Step.stop, (), 0)
        self.assertEqual(render_content(obj, 'text'), 'plain')
        self.assertEqual(render_content(obj, 'html'), html)
        self.assertEqual(render_content(obj, 'links'), [{'text': 'A B', 'href': 'https://b/x'}])
        self.assertEqual(render_content(obj, 'meta'), {'title': 'A & B', 'h1': ['One two'],
                         'lang': 'en', 'description': 'fallback', 'canonical': 'https://b/canon'})
        md = render_content(obj, 'markdown')
        for part in ('# One', '**bold**', 'end', '[A **B**](https://b/x)', 'a\n b'):
            self.assertIn(part, md)
        self.assertNotIn('hidden', md)
        for mode, empty in [('text', ''), ('html', ''), ('markdown', ''), ('links', []), ('meta', {})]:
            self.assertEqual(render_content(replace(obj, ok=False), mode), empty)
        for mode in (None, [], 'secret-invalid'):
            with self.assertRaisesRegex(ValueError, '^invalid format$'):
                render_content(obj, mode)
