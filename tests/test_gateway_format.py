from dataclasses import replace
import unittest
from bench.escalate import Step
from bench.models import FailureReason as F
from gateway.models import GatewayOutcome


class FormatTests(unittest.TestCase):
    def test_markdown_oversized_decimal_reference(self):
        from gateway.format import render_content
        html = '<p>L&#' + '9' * 5000 + 'R</p>'
        obj = GatewayOutcome(True, 'https://a/x', 'https://a/x', html,
                             'plain', 'curl', None, F.none, Step.stop, (), 0)
        try:
            result = render_content(obj, 'markdown')
        except ValueError as exc:
            self.fail(f'oversized decimal reference raised ValueError: {exc}')
        self.assertEqual(result, 'L\ufffdR')

    def test_markdown_decimal_reference_leading_zeros(self):
        from gateway.format import render_content
        html = '<p>&#' + '0' * 5000 + '65;</p>'
        obj = GatewayOutcome(True, 'https://a/x', 'https://a/x', html,
                             'plain', 'curl', None, F.none, Step.stop, (), 0)
        self.assertEqual(render_content(obj, 'markdown'), 'A')

    def test_markdown_seven_digit_unicode_reference(self):
        from gateway.format import render_content
        obj = GatewayOutcome(True, 'https://a/x', 'https://a/x', '<p>&#1114109;</p>',
                             'plain', 'curl', None, F.none, Step.stop, (), 0)
        self.assertEqual(render_content(obj, 'markdown'), '\U0010fffd')

    def test_all_formats_with_giant_references_in_text_and_attributes(self):
        from gateway.format import MODES, render_content
        for digits, decoded in [('9' * 5000, '\ufffd'), ('0' * 5000 + '65', 'A')]:
            for suffix in (';', ''):
                ref = '&#' + digits + suffix
                for location in ('text', 'attribute'):
                    if location == 'text':
                        html = f'<head><title>{ref}</title></head><p>x {ref} y</p><a href=/l>{ref}</a>'
                        expected = {
                            'markdown': f'x {decoded} y\n\n[{decoded}](https://a/l)',
                            'links': [{'text': decoded, 'href': 'https://a/l'}],
                            'meta': {'title': decoded, 'h1': []},
                        }
                    else:
                        html = (f'<head><title>t</title><meta name=description content="{ref}"></head>'
                                f'<p>x <img src=/i alt="{ref}"> y</p><a href=/l title="{ref}">L</a>')
                        expected = {
                            'markdown': f'x ![{decoded}](https://a/i) y\n\n[L](https://a/l)',
                            'links': [{'text': 'L', 'href': 'https://a/l'}],
                            'meta': {'title': 't', 'h1': [], 'description': decoded},
                        }
                    obj = GatewayOutcome(True, 'https://a/x', 'https://a/x', html,
                                         'plain', 'curl', None, F.none, Step.stop, (), 0)
                    expected.update(text='plain', html=html)
                    for mode in MODES:
                        with self.subTest(digits=digits[:8], suffix=suffix, location=location, mode=mode):
                            self.assertEqual(render_content(obj, mode), expected[mode])

    def test_markdown_character_reference_boundaries(self):
        from gateway.format import render_content
        cases = [('65', 'A'), ('0000065', 'A'), ('1114109', '\U0010fffd'),
                 ('1114112', '\ufffd'), ('9999999', '\ufffd'), ('10000000', '\ufffd'),
                 ('x' + 'f' * 5000, '\ufffd'), ('x41', 'A'), ('X41', 'A'),
                 ('9' * 5000, '\ufffd'), ('0' * 5000 + '65', 'A'), ('0' * 5000, '\ufffd')]
        for digits, expected in cases:
            for suffix in (';', ''):
                html = '<p>L&#' + digits + suffix + 'R</p>'
                obj = GatewayOutcome(True, 'https://a/x', 'https://a/x', html,
                                     'plain', 'curl', None, F.none, Step.stop, (), 0)
                with self.subTest(digits=digits[:16], length=len(digits), suffix=suffix):
                    self.assertEqual(render_content(obj, 'markdown'), 'L' + expected + 'R')

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
