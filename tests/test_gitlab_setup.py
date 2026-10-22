# -*- coding: utf-8 -*-
"""scripts/gitlab_setup.py: the writes must merge, never clobber, and must leave CLAUDE.md alone
outside the markers. Run: python -m unittest discover -s tests -v"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.join(HERE, '..', 'scripts', 'gitlab_setup.py')
GUARD = os.path.join(HERE, '..', 'hooks', 'gitlab-scope-guard.py')
EXAMPLE = os.path.join(HERE, '..', 'config', 'gitlab.example.json')

spec = importlib.util.spec_from_file_location('setup', SETUP)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)

gspec = importlib.util.spec_from_file_location('guard', GUARD)
guard = importlib.util.module_from_spec(gspec)
gspec.loader.exec_module(guard)

MINIMAL = {'enabled': True, 'host': 'gitlab.example.cz', 'projectId': '42',
           'projectPath': 'https://gitlab.example.cz/team/app/-/issues'}
LABELS = {
    'ticketLanguage': 'English',
    'issueTypes': [{'id': 1, 'name': 'type::bug', 'role': 'bug'},
                   {'id': 2, 'name': 'type::task', 'role': 'task'}],
    'workflow': {'statuses': [{'id': 11, 'name': 'workflow::todo', 'role': 'todo'},
                              {'id': 12, 'name': 'workflow::doing', 'role': 'doing'},
                              {'id': 13, 'name': 'workflow::review', 'role': 'review'}]},
}


def run(*args):
    proc = subprocess.run([sys.executable, SETUP] + list(args), capture_output=True)
    return proc.returncode, proc.stdout.decode('utf-8', 'replace'), proc.stderr.decode('utf-8', 'replace')


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as handle:
        handle.write(data if isinstance(data, bytes) else data.encode('utf-8'))


def read_bytes(path):
    with open(path, 'rb') as handle:
        return handle.read()


class Workspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = self._tmp.name
        self.config_path = os.path.join(self.ws, '.claude', 'gitlab.json')
        self.claude_md = os.path.join(self.ws, 'CLAUDE.md')
        self.count = 0

    def tearDown(self):
        self._tmp.cleanup()

    def answers(self, data):
        self.count += 1
        path = os.path.join(self.ws, 'answers-%d.json' % self.count)
        write(path, json.dumps(data))
        return path

    def config(self):
        return json.loads(read_bytes(self.config_path).decode('utf-8'))

    def bind(self, *extra):
        code, out, err = run('write-config', self.ws, self.answers(MINIMAL))
        self.assertEqual(0, code, err)
        for data in extra:
            code, out, err = run('write-config', self.ws, self.answers(data))
            self.assertEqual(0, code, err)
        return out


class WriteConfig(Workspace):
    def test_minimal_answers_are_normalised_and_get_defaults(self):
        out = self.bind()
        cfg = self.config()
        self.assertEqual('https://gitlab.example.cz', cfg['host'])
        self.assertEqual(42, cfg['projectId'])
        self.assertEqual('team/app', cfg['projectPath'])
        self.assertEqual('gitlab-kit', cfg['agentLabel'])
        self.assertEqual('Relates to', cfg['workflow']['closeKeyword'])
        self.assertTrue(cfg['workflow']['requiresApprovalForClose'])
        self.assertEqual('source::user-request', cfg['labels']['userRequest'])
        self.assertIn('still missing', out)                     # labels, language not yet known

    def test_project_path_forms(self):
        for given in ('team/app', '/team/app/', 'https://gitlab.example.cz/team/app.git',
                      'https://gitlab.example.cz/team/app/-/issues/7', 'gitlab.example.cz/team/app'):
            answers = dict(MINIMAL, projectPath=given)
            if given == 'gitlab.example.cz/team/app':
                answers['projectPath'] = 'https://' + given
            code, _, err = run('write-config', self.ws, self.answers(answers))
            self.assertEqual(0, code, err)
            self.assertEqual('team/app', self.config()['projectPath'], given)

    def test_invalid_values_are_refused_and_nothing_is_written(self):
        for bad, message in (({'projectId': 'abc'}, 'numeric'), ({'projectId': 0}, 'numeric'),
                             ({'projectPath': 'app'}, 'group/project'),
                             ({'host': 'http://gitlab.example.cz'}, 'https'),
                             ({'host': 'https://gitlab.example.cz/sub'}, 'https')):
            code, _, err = run('write-config', self.ws, self.answers(dict(MINIMAL, **bad)))
            self.assertEqual(1, code, bad)
            self.assertIn(message, err)
            self.assertFalse(os.path.exists(self.config_path))

    def test_second_write_keeps_what_it_is_not_given(self):
        self.bind({'projectName': 'App', 'labels': {'userRequest': 'from-user'}}, {'ticketLanguage': 'Czech'})
        cfg = self.config()
        self.assertEqual('App', cfg['projectName'])
        self.assertEqual('Czech', cfg['ticketLanguage'])
        self.assertEqual('from-user', cfg['labels']['userRequest'])
        self.assertEqual('source::app-feedback', cfg['labels']['appFeedback'])  # sibling default kept
        self.assertEqual(42, cfg['projectId'])

    def test_unknown_keys_survive(self):
        write(self.config_path, json.dumps(dict(MINIMAL, projectId=42, projectPath='team/app', myOwnThing=7)))
        run('write-config', self.ws, self.answers({'ticketLanguage': 'English'}))
        self.assertEqual(7, self.config()['myOwnThing'])

    def test_workflow_is_derived_from_roles_and_ids(self):
        self.bind(LABELS)
        workflow = self.config()['workflow']
        self.assertEqual(11, workflow['initialStatusId'])
        self.assertEqual([12, 13], workflow['activeStatusIds'])
        self.assertEqual('workflow::todo', workflow['initialStatus'])
        self.assertEqual(['workflow::doing', 'workflow::review'], workflow['activeStatuses'])

    def test_a_renamed_label_refreshes_the_name_and_keeps_the_id(self):
        self.bind(LABELS)
        renamed = json.loads(json.dumps(LABELS['workflow']))
        renamed['statuses'][1]['name'] = 'workflow::in-progress'
        run('write-config', self.ws, self.answers({'workflow': renamed}))
        workflow = self.config()['workflow']
        self.assertEqual([12, 13], workflow['activeStatusIds'])
        self.assertEqual('workflow::in-progress', workflow['activeStatuses'][0])

    def test_unknown_roles_become_other(self):
        self.bind({'issueTypes': [{'id': 1, 'name': 'type::spike', 'role': 'spike'}]})
        self.assertEqual('other', self.config()['issueTypes'][0]['role'])

    def test_phase_is_a_type_role(self):
        phase = {'id': 30, 'name': 'type::phase', 'role': 'phase'}
        self.bind(dict(LABELS, issueTypes=LABELS['issueTypes'] + [phase]))
        self.assertEqual('phase', self.config()['issueTypes'][-1]['role'])
        code, out, _ = run('validate', self.ws)
        self.assertEqual(0, code, out)
        self.assertIn('phase=type::phase', out)

    def test_phase_label_stored_as_other_keeps_working(self):
        old = {'id': 30, 'name': 'type::phase', 'role': 'other'}
        self.bind(dict(LABELS, issueTypes=LABELS['issueTypes'] + [old]))
        run('write-config', self.ws, self.answers({'ticketLanguage': 'English'}))   # a rerun
        self.assertEqual('other', self.config()['issueTypes'][-1]['role'])
        self.assertEqual(0, run('validate', self.ws)[0])

    def test_ci_read_is_off_by_default_and_kept_on_rerun(self):
        self.bind()
        self.assertIs(False, self.config()['ciRead'])
        run('write-config', self.ws, self.answers({'ciRead': True}))
        run('write-config', self.ws, self.answers({'ticketLanguage': 'English'}))
        self.assertIs(True, self.config()['ciRead'])

    def test_disable_keeps_the_rest(self):
        self.bind(LABELS)
        code, _, _ = run('disable', self.ws)
        self.assertEqual(0, code)
        cfg = self.config()
        self.assertFalse(cfg['enabled'])
        self.assertEqual('team/app', cfg['projectPath'])


class Validate(Workspace):
    def test_complete_config_validates(self):
        self.bind(LABELS)
        code, out, err = run('validate', self.ws)
        self.assertEqual(0, code, out + err)
        self.assertIn('team/app', out)
        self.assertIn('Community Edition', out)

    def test_missing_pieces_are_named(self):
        self.bind()
        code, out, _ = run('validate', self.ws)
        self.assertEqual(1, code)
        for text in ('role "bug"', 'role "task"', 'role "doing"', 'ticketLanguage'):
            self.assertIn(text, out)

    def test_label_without_id_is_a_problem(self):
        self.bind(LABELS, {'issueTypes': LABELS['issueTypes'] + [{'name': 'type::idea', 'role': 'idea'}]})
        code, out, _ = run('validate', self.ws)
        self.assertEqual(1, code)
        self.assertIn("'type::idea' has no id", out)

    def test_non_ascii_label_is_a_problem(self):
        self.bind(LABELS, {'labels': {'userRequest': 'zdroj::uživatel'}})
        code, out, _ = run('validate', self.ws)
        self.assertEqual(1, code)
        self.assertIn('not ASCII', out)

    def test_ci_read_must_be_a_boolean(self):
        self.bind(LABELS, {'ciRead': 'yes'})
        code, out, _ = run('validate', self.ws)
        self.assertEqual(1, code)
        self.assertIn('ciRead must be true or false', out)

    def test_summary_names_the_ci_state(self):
        self.bind(LABELS)
        self.assertIn('CI reads:          off', run('validate', self.ws)[1])
        run('write-config', self.ws, self.answers({'ciRead': True}))
        self.assertIn('CI reads:          on', run('validate', self.ws)[1])

    def test_disabled_config_needs_nothing(self):
        write(self.config_path, json.dumps({'enabled': False}))
        self.assertEqual(0, run('validate', self.ws)[0])

    def test_no_config(self):
        code, _, err = run('validate', self.ws)
        self.assertEqual(1, code)
        self.assertIn('gl-setup', err)

    def test_the_example_config_validates(self):
        with open(EXAMPLE, encoding='utf-8') as handle:
            example = json.load(handle)
        self.assertEqual([], setup.problems(example))


class GuardAcceptsWhatSetupWrites(Workspace):
    def test_written_config_binds_the_guard(self):
        self.bind(LABELS)
        cfg = self.config()
        api = 'glab api --hostname gitlab.example.cz '
        self.assertEqual('allow', guard.decide('Bash', {'command': api + 'projects/42/issues'}, cfg)[0])
        self.assertEqual('allow', guard.decide('Bash', {'command': api + 'projects/team%2Fapp/labels'}, cfg)[0])
        self.assertEqual('deny', guard.decide('Bash', {'command': api + 'projects/43/issues'}, cfg)[0])

    def test_minimal_config_from_step_3_already_binds_the_guard(self):
        self.bind()
        api = 'glab api --hostname gitlab.example.cz '
        self.assertEqual('allow', guard.decide('Bash', {'command': api + 'projects/42'}, self.config())[0])

    def test_ci_read_flag_opens_ci_routes_only_when_on(self):
        self.bind(LABELS)
        command = {'command': 'glab api --hostname gitlab.example.cz projects/42/pipelines'}
        self.assertEqual('deny', guard.decide('Bash', command, self.config())[0])
        run('write-config', self.ws, self.answers({'ciRead': True}))
        self.assertEqual('allow', guard.decide('Bash', command, self.config())[0])

    def test_disabled_config_closes_the_guard(self):
        self.bind()
        run('disable', self.ws)
        decision, reason = guard.decide('Bash', {'command': 'glab api --hostname gitlab.example.cz projects/42'},
                                        self.config())
        self.assertEqual('deny', decision)
        self.assertIn('disabled', reason)

    def test_create_with_the_configured_agent_label(self):
        self.bind(LABELS, {'agentLabel': 'ai-agent', 'labels': {'agentCreated': 'ai-agent'}})
        cfg = self.config()
        api = 'glab api --hostname gitlab.example.cz projects/42/issues -f title=x '
        self.assertEqual('allow', guard.decide('Bash', {'command': api + '-f labels=ai-agent'}, cfg)[0])
        self.assertEqual('deny', guard.decide('Bash', {'command': api + '-f labels=gitlab-kit'}, cfg)[0])


class RenderClaudeMd(Workspace):
    def section(self):
        text = read_bytes(self.claude_md).decode('utf-8-sig')
        start, end = text.find(setup.MARK_START), text.find(setup.MARK_END)
        return text[start:end + len(setup.MARK_END)]

    def test_creates_the_file(self):
        self.bind(LABELS)
        self.assertEqual(0, run('render-claude-md', self.ws)[0])
        section = self.section()
        self.assertIn('team/app', section)
        self.assertIn('glab api --hostname gitlab.example.cz projects/42/', section)
        self.assertIn('`Relates to #n`', section)
        self.assertIn('Only `/gl-signoff` closes', section)
        self.assertIn('**English**', section)

    def test_appends_once_and_replaces_on_rerun(self):
        write(self.claude_md, '# Mine\n\nKeep me.\n')
        self.bind(LABELS)
        run('render-claude-md', self.ws)
        run('write-config', self.ws, self.answers({'ticketLanguage': 'Czech'}))
        run('render-claude-md', self.ws)
        text = read_bytes(self.claude_md).decode('utf-8')
        self.assertTrue(text.startswith('# Mine\n\nKeep me.\n'))
        self.assertEqual(1, text.count(setup.MARK_START))
        self.assertIn('**Czech**', text)
        self.assertNotIn('**English**', text)

    def test_keeps_crlf_bom_and_everything_outside_the_markers(self):
        before = b'\xef\xbb\xbf# Mine\r\n\r\nKeep me.\r\n'
        after = b'\r\n## After\r\nAlso kept.\r\n'
        write(self.claude_md, before + setup.MARK_START.encode() + b'\r\nold\r\n' + setup.MARK_END.encode() + after)
        self.bind(LABELS)
        run('render-claude-md', self.ws)
        raw = read_bytes(self.claude_md)
        self.assertTrue(raw.startswith(before))
        self.assertTrue(raw.endswith(after))
        self.assertEqual(1, raw.count(b'\xef\xbb\xbf'))
        self.assertNotIn(b'\nold', raw)
        body = raw[len(before):-len(after)]
        self.assertNotIn(b'\n', body.replace(b'\r\n', b''))   # every line ending in the section is CRLF

    def test_one_marker_only_is_refused(self):
        write(self.claude_md, '# Mine\n' + setup.MARK_START + '\n')
        self.bind(LABELS)
        code, _, err = run('render-claude-md', self.ws)
        self.assertEqual(1, code)
        self.assertIn('one gitlab-kit marker', err)

    def test_ci_lines_only_when_on(self):
        self.bind(LABELS)
        run('render-claude-md', self.ws)
        self.assertNotIn('CI reads are on', self.section())
        run('write-config', self.ws, self.answers({'ciRead': True}))
        run('render-claude-md', self.ws)
        section = self.section()
        self.assertIn('CI reads are on', section)
        self.assertIn('`POST ci/lint`', section)
        self.assertIn('Never run, retry, cancel or delete', section)

    def test_disabled_section(self):
        self.bind()
        run('disable', self.ws)
        run('render-claude-md', self.ws)
        self.assertIn('**disabled**', self.section())

    def test_section_has_no_secret_and_no_quick_action_line(self):
        self.bind(LABELS)
        run('render-claude-md', self.ws)
        for line in self.section().splitlines():
            self.assertFalse(line.startswith('/'), line)
        self.assertNotIn('token=', self.section().lower())


if __name__ == '__main__':
    unittest.main()
