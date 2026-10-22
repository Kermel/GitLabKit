# -*- coding: utf-8 -*-
"""The skills are instructions, so a rule that lives only in their text is tested on their text.

Measured on a Community Edition 19.1 project: `add_labels=workflow::review` left the issue with both
workflow::doing and workflow::review. Every command a skill gives that adds a status or type label
must therefore remove the old ones in the same call."""
import os
import re
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
DOCS = [os.path.join('docs', 'skill-conventions.md')] + [
    os.path.join('skills', name, 'SKILL.md') for name in sorted(os.listdir(os.path.join(ROOT, 'skills')))]


def read(path):
    with open(os.path.join(ROOT, path), encoding='utf-8') as handle:
        return handle.read()


def lonely_add_labels(text):
    """Command lines that add a label and remove nothing: the CE defect."""
    return [line.strip() for line in text.splitlines()
            if 'add_labels=' in line and 'glab api' in line and 'remove_labels=' not in line]


class ScopedLabelsOnCommunityEdition(unittest.TestCase):
    def test_the_checker_catches_the_defect(self):
        bad = "glab api -X PUT --hostname H projects/1/issues/7 -f 'add_labels=workflow::review'"
        good = bad + " -f 'remove_labels=workflow::doing'"
        self.assertEqual([bad], lonely_add_labels(bad))
        self.assertEqual([], lonely_add_labels(good))

    def test_no_command_adds_a_label_without_removing_the_old_ones(self):
        for path in DOCS:
            self.assertEqual([], lonely_add_labels(read(path)), path)

    def test_the_paid_tier_claim_is_gone(self):
        for path in DOCS:
            text = read(path)
            self.assertNotIn('replaces its sibling', text, path)
            self.assertNotIn('Never remove one by hand', text, path)

    def test_gl_work_changes_status_with_add_and_remove(self):
        text = read(os.path.join('skills', 'gl-work', 'SKILL.md'))
        self.assertRegex(text, r"add_labels=<doing name>' -f 'remove_labels=")

    def test_triage_lists_two_labels_of_one_kind(self):
        self.assertIn('two labels of one kind', read(os.path.join('skills', 'gl-triage', 'SKILL.md')))


class PhaseRole(unittest.TestCase):
    def test_wizard_offers_the_phase_role(self):
        text = read(os.path.join('skills', 'gl-setup', 'SKILL.md'))
        self.assertIn('| phase | `type::phase` |', text)
        self.assertRegex(text, r'Type roles: .*`phase`')

    def test_conventions_find_phase_parents_by_role(self):
        self.assertIn('`phase`-role label', read(os.path.join('docs', 'skill-conventions.md')))


class ClosingNoteByDefault(unittest.TestCase):
    def setUp(self):
        self.text = read(os.path.join('skills', 'gl-signoff', 'SKILL.md'))

    def test_note_is_the_first_option_and_plain_yes_stays(self):
        options = re.search(r'Options, in this order: (.*?)Wait\.', self.text, re.S).group(1)
        self.assertTrue(options.startswith('**yes, with this closing note** (the default, first)'), options)
        self.assertIn('yes, without a', options)
        self.assertIn('no.', options)
        self.assertNotIn("if that is the project's habit", self.text)

    def test_note_has_three_parts_at_most_three_lines(self):
        self.assertIn('At most three lines', self.text)
        for part in ('acceptance criteria', 'where the evidence is', 'any debt left'):
            self.assertIn(part, self.text)


if __name__ == '__main__':
    unittest.main()
