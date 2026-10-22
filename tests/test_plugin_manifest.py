# -*- coding: utf-8 -*-
"""The repository must install as a Claude Code plugin: manifests that parse, a hook that points at
a file that exists, one skill per folder with a matching name, and a CHANGELOG entry for the
version, because `claude plugin update` compares that number only."""
import json
import os
import re
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding='utf-8') as handle:
        return handle.read()


class Manifest(unittest.TestCase):
    def setUp(self):
        self.plugin = json.loads(read('.claude-plugin', 'plugin.json'))
        self.market = json.loads(read('.claude-plugin', 'marketplace.json'))

    def test_names_agree(self):
        self.assertEqual('gitlab-kit', self.plugin['name'])
        self.assertEqual('gitlab-kit', self.market['name'])
        self.assertEqual(['gitlab-kit'], [p['name'] for p in self.market['plugins']])
        self.assertEqual('./', self.market['plugins'][0]['source'])

    def test_version_is_semver_and_in_the_changelog(self):
        version = self.plugin['version']
        self.assertRegex(version, r'^\d+\.\d+\.\d+$')
        self.assertIn('## %s' % version, read('CHANGELOG.md'))

    def test_hook_points_at_the_guard_for_shell_and_mcp_tools(self):
        entries = self.plugin['hooks']['PreToolUse']
        self.assertEqual(1, len(entries))
        matcher = re.compile(entries[0]['matcher'])
        for tool in ('Bash', 'PowerShell', 'mcp__gitlab__get_issue'):
            self.assertTrue(matcher.search(tool), tool)
        for tool in ('Read', 'Edit', 'BashOutput'):
            self.assertFalse(matcher.search(tool), tool)
        command = entries[0]['hooks'][0]['command']
        script = re.search(r'\$HOOK_ROOT/(\S+?)"', command).group(1)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, script)), script)

    def test_every_skill_folder_has_a_skill_with_its_name(self):
        skills = sorted(os.listdir(os.path.join(ROOT, 'skills')))
        self.assertEqual(['gl-create', 'gl-plan', 'gl-setup', 'gl-signoff', 'gl-status', 'gl-triage',
                          'gl-work'], skills)
        for name in skills:
            text = read('skills', name, 'SKILL.md')
            front = re.match(r'^---\n(.*?)\n---\n', text, re.S)
            self.assertIsNotNone(front, name)
            self.assertIn('name: %s\n' % name, front.group(1) + '\n')
            self.assertIn('description:', front.group(1))

    def test_skills_reference_files_that_exist(self):
        for name in os.listdir(os.path.join(ROOT, 'skills')):
            for ref in re.findall(r'\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)', read('skills', name, 'SKILL.md')):
                self.assertTrue(os.path.isfile(os.path.join(ROOT, ref)), '%s -> %s' % (name, ref))


if __name__ == '__main__':
    unittest.main()
