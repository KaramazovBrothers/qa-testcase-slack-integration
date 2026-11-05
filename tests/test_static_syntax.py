"""Guard the hand-written workspace bundle against syntax breakage.

`app/static/workspace.js` and `workspace.css` are not built from `static-src/`,
so nothing catches a stray bracket. A syntax error there left the whole QA
workspace stuck on "Загрузка…" while every HTTP endpoint still answered 200.
"""
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / 'app' / 'static'


@unittest.skipIf(shutil.which('node') is None, 'node is not installed')
class StaticSyntaxTests(unittest.TestCase):
    def test_workspace_js_parses(self):
        for name in ('workspace.js', 'generator.js'):
            with self.subTest(name=name):
                result = subprocess.run(
                    ['node', '--check', str(STATIC / name)],
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, f'{name}: {result.stderr}')

    def test_workspace_css_braces_balance(self):
        css = (STATIC / 'workspace.css').read_text(encoding='utf-8')
        # Comments may contain braces; drop them before counting.
        stripped = []
        index = 0
        while index < len(css):
            if css.startswith('/*', index):
                end = css.find('*/', index + 2)
                index = len(css) if end < 0 else end + 2
                continue
            stripped.append(css[index])
            index += 1
        self.assertEqual(''.join(stripped).count('{'), ''.join(stripped).count('}'))

    def test_unread_replies_mark_is_explicit(self):
        """A reply stays "news" until the operator toggles its own button.

        The badge and the toggle must read the same flag, and nothing but that
        button may clear or restore it — a click on the card is an edit.
        """
        js = (STATIC / 'workspace.js').read_text(encoding='utf-8')
        self.assertIn('function hasNews(record)', js)
        self.assertIn('Прочитано', js)
        self.assertIn('Отметить как непрочитанное', js)
        # No side effect on card clicks.
        self.assertNotIn("if(record)markRepliesRead(record)", js)
        cleared = [line for line in js.splitlines()
                   if 'delete caseReplies[' in line]
        self.assertEqual(len(cleared), 1, cleared)
        self.assertIn('function clearRepliesMark(record)', cleared[0])

    def test_case_can_be_collapsed(self):
        """A long case folds into a small block and stays folded.

        The fold must survive `renderCases()`, otherwise saving or refreshing
        quietly expands every card again.
        """
        js = (STATIC / 'workspace.js').read_text(encoding='utf-8')
        self.assertIn('Свернуть кейс', js)
        self.assertIn('Развернуть кейс', js)
        # The wrapped block holds the text, the Slack request and the notes.
        self.assertIn("long.append(body,rl,cl)", js)
        # Folded cards are remembered by id and restored on the next render.
        self.assertIn('foldedCases[key]', js)
        css = (STATIC / 'workspace.css').read_text(encoding='utf-8')
        self.assertIn('.case-long[hidden]', css)


    def test_case_can_be_folded(self):
        """A long case must collapse to a small card.

        `label` declares display:flex, which overrides the `hidden` attribute,
        so both the wrapper and its children need an explicit rule.
        """
        js = (STATIC / 'workspace.js').read_text(encoding='utf-8')
        css = (STATIC / 'workspace.css').read_text(encoding='utf-8')
        self.assertIn("'Свернуть кейс'", js)
        self.assertIn("'Развернуть кейс'", js)
        self.assertIn('case-long', js)
        self.assertIn('.case-long[hidden]', css)
        self.assertIn('.case-long[hidden]>*', css)


if __name__ == '__main__':
    unittest.main()
