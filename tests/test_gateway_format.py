from dataclasses import replace
import unittest
from bench.escalate import Step
from bench.models import FailureReason as F
from gateway.models import GatewayOutcome


class FormatTests(unittest.TestCase):
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
