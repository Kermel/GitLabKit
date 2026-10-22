# -*- coding: utf-8 -*-
"""Allowed and denied cases for hooks/gitlab-scope-guard.py.

Run:  python -m unittest discover -s tests -v
Every rule has a must-block and a must-allow case. The must-allow list includes the guard's own
documentation and commit messages that quote the defects: jira-kit's lesson is that a guard which
blocks people from writing about it gets switched off.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, '..', 'hooks', 'gitlab-scope-guard.py')

spec = importlib.util.spec_from_file_location('guard', GUARD)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

CONFIG = {
    'enabled': True,
    'host': 'https://gitlab.example.cz',
    'projectId': 42,
    'projectPath': 'team/app',
    'agentLabel': 'gitlab-kit',
    'enforceAgentLabelOnCreate': True,
}
H = '--hostname gitlab.example.cz'
API = 'glab api ' + H + ' '


class GuardCase(unittest.TestCase):
    base_dir = HERE

    def verdict(self, command, tool='Bash', config=CONFIG):
        return guard.decide(tool, {'command': command}, config, base_dir=self.base_dir)

    def allow(self, command, tool='Bash', config=CONFIG):
        decision, reason = self.verdict(command, tool, config)
        self.assertEqual('allow', decision, 'expected allow, got deny: ' + reason)
        return reason

    def deny(self, command, must_mention=None, tool='Bash', config=CONFIG):
        decision, reason = self.verdict(command, tool, config)
        self.assertEqual('deny', decision, 'expected deny, but it was allowed: ' + command)
        if must_mention:
            self.assertIn(must_mention, reason, reason)
        return reason

    def not_ours(self, command, tool='Bash', config=CONFIG):
        self.assertEqual(guard.NOT_GITLAB, self.allow(command, tool, config))


class AllowedReads(GuardCase):
    def test_list_issues_by_id(self):
        self.allow(API + 'projects/42/issues')

    def test_list_issues_by_encoded_path(self):
        self.allow(API + 'projects/team%2Fapp/issues')
        self.allow(API + 'projects/TEAM%2Fapp/issues')   # GitLab paths are case-insensitive

    def test_query_string_quoted(self):
        self.allow(API + "'projects/42/issues?state=opened&labels=type::bug&per_page=50' --paginate")

    def test_explicit_get_with_fields(self):
        self.allow('glab api -X GET ' + H + ' projects/42/issues -f search=login -f state=opened')

    def test_one_issue_notes_links(self):
        for route in ('issues/7', 'issues/7/notes', 'issues/7/links', 'issues/7/related_merge_requests',
                      'labels', 'milestones', 'merge_requests?source_branch=feature/7-x', ''):
            self.allow(API + "'projects/42/%s'" % route if route else API + 'projects/42')

    def test_flag_spellings(self):
        self.allow('glab api --hostname=gitlab.example.cz --method=GET projects/42/issues')
        self.allow('glab api -XGET --hostname gitlab.example.cz projects/42/labels')
        self.allow('glab.exe api ' + H + ' projects/42/issues')
        self.allow('/c/tools/glab.exe api ' + H + ' projects/42/issues')

    def test_project_search(self):
        self.allow('glab api -X GET ' + H + " projects/42/search -f scope=issues -f 'search=time out'")

    def test_instance_metadata_reads(self):
        self.allow(API + 'metadata')
        self.allow(API + 'version')
        self.allow(API + 'personal_access_tokens/self')
        self.allow(API + '/metadata')

    def test_auth_status_version_help(self):
        self.allow('glab auth status --hostname gitlab.example.cz')
        self.allow('glab auth status')
        self.allow('glab version')
        self.allow('glab --version')
        self.allow('glab api --help')
        self.allow('glab')


class AllowedWrites(GuardCase):
    def test_create_with_agent_label(self):
        self.allow(API + "projects/42/issues -f 'title=Login times out' "
                         "-f 'labels=gitlab-kit,type::bug,source::user-request' -f 'description=Steps...'")

    def test_create_description_mentioning_other_project_is_prose(self):
        self.allow(API + "projects/42/issues -f title=x -f labels=gitlab-kit "
                         "-f 'description=Same root cause as other/proj#3 and !12.'")

    def test_create_with_quick_action_inside_code_fence(self):
        self.allow(API + "projects/42/issues -f title=x -f labels=gitlab-kit "
                         "-f $'description=Run:\\n```\\n/usr/bin/app --check\\n```\\n'")

    def test_create_from_input_file(self):
        with tempfile.TemporaryDirectory() as folder:
            body = os.path.join(folder, 'issue.json')
            with open(body, 'w', encoding='utf-8') as handle:
                json.dump({'title': 'Přihlášení', 'labels': ['gitlab-kit', 'type::bug'],
                           'description': 'Text s $dolarem a `kódem`.'}, handle, ensure_ascii=False)
            self.allow('glab api -X POST ' + H + ' projects/42/issues --input ' + body.replace('\\', '/'))

    def test_link_inside_project(self):
        self.allow(API + 'projects/42/issues/7/links -f target_project_id=42 -f target_issue_iid=9 '
                         '-f link_type=relates_to')
        self.allow(API + 'projects/42/issues/7/links -f target_project_id=team%2Fapp -f target_issue_iid=9')

    def test_update_and_close(self):
        self.allow('glab api -X PUT ' + H + " projects/42/issues/7 -f 'add_labels=workflow::doing'")
        self.allow('glab api -X PUT ' + H + ' projects/42/issues/7 -f state_event=close')

    def test_status_change_adds_and_removes_in_one_put(self):
        # Community Edition keeps both scoped labels unless the old one is removed (measured).
        self.allow('glab api -X PUT ' + H + " projects/42/issues/7 -f 'add_labels=workflow::review' "
                   "-f 'remove_labels=workflow::todo,workflow::doing'")
        self.allow('glab api -X PUT ' + H + " projects/42/issues/7 -f 'add_labels=type::task' "
                   "-f 'remove_labels=type::bug,type::feature,type::idea,type::debt,type::phase'")

    def test_status_change_still_needs_put_and_this_project(self):
        self.deny(API + "projects/42/issues/7 -f 'add_labels=workflow::review' "
                        "-f 'remove_labels=workflow::doing'", 'POST')
        self.deny('glab api -X PUT ' + H + " projects/43/issues/7 -f 'add_labels=workflow::review' "
                  "-f 'remove_labels=workflow::doing'", '43')

    def test_note(self):
        self.allow(API + "projects/42/issues/7/notes -f 'body=Scope narrowed: the export is out.'")

    def test_create_label(self):
        self.allow(API + "projects/42/labels -f 'name=workflow::doing' -f 'color=#428BCA'")


class NotOurBusiness(GuardCase):
    """Must-allow canaries: commands that only TALK about glab or GitLab."""

    def test_plain_commands(self):
        self.not_ours('ls -la')
        self.not_ours('git status')
        self.not_ours('python -m unittest discover -s tests -v')

    def test_reading_the_guard_and_its_docs(self):
        self.not_ours('grep -n "glab api" hooks/gitlab-scope-guard.py')
        self.not_ours('grep -rn glab docs/ skills/')
        self.not_ours('cat docs/gitlab-integration.md | head -50')
        self.not_ours('sed -n 1,40p hooks/gitlab-scope-guard.py')

    def test_commit_message_quoting_a_defect(self):
        self.not_ours('git commit -m "guard: glab api -X DELETE projects/9/issues/1 was allowed; refuse it"')
        self.not_ours("git commit -m 'fix: bash -c \"glab api ...\" slipped through'")

    def test_commit_message_by_quoted_heredoc(self):
        self.not_ours('git commit -m "$(cat <<\'EOF\'\n'
                      'guard: refuse glab behind xargs (and env)\n\n'
                      'glab api -X DELETE projects/9/issues/1 && curl https://gitlab.example.cz\n'
                      'EOF\n)"')

    def test_git_to_the_gitlab_host(self):
        self.not_ours('git fetch https://gitlab.example.cz/team/app.git')
        self.not_ours('git remote -v')

    def test_other_mcp_tools(self):
        decision, reason = guard.decide('mcp__github__create_issue', {'repo': 'x'}, CONFIG)
        self.assertEqual(('allow', guard.NOT_GITLAB), (decision, reason))

    def test_non_shell_tool(self):
        self.assertEqual(guard.NOT_GITLAB, guard.decide('Read', {'file_path': 'x'}, CONFIG)[1])

    def test_powershell_commit_and_search(self):
        self.not_ours("git commit -m @'\nguard: glab api DELETE was allowed\n'@", tool='PowerShell')
        self.not_ours('Select-String -Path hooks/gitlab-scope-guard.py -Pattern glab', tool='PowerShell')
        self.not_ours("git commit -m 'refuse glab in PowerShell'", tool='PowerShell')

    def test_no_config_leaves_other_commands_alone(self):
        self.not_ours('ls', config=None)


class DeniedScope(GuardCase):
    def test_other_project_by_id(self):
        self.deny(API + 'projects/43/issues', '43')

    def test_other_project_by_path(self):
        self.deny(API + 'projects/team%2Fother/issues', 'team/other')

    def test_project_list_users_groups_graphql(self):
        for path in ('projects', 'users', 'groups/5/epics', 'graphql', 'issues', 'search?scope=issues',
                     'runners', 'application/settings'):
            self.deny(API + "'%s'" % path)

    def test_instance_metadata_only_plain_get(self):
        self.deny('glab api -X POST ' + H + ' metadata', 'instance read')
        self.deny(API + 'personal_access_tokens/self -f name=x', 'instance read')
        self.deny(API + "'metadata?sudo=root'")
        self.deny(API + 'personal_access_tokens')
        self.deny(API + 'personal_access_tokens/5')
        self.assertEqual('deny', self.verdict(API + 'metadata', config=None)[0])

    def test_path_tricks(self):
        self.deny(API + 'projects/42/../43/issues', 'path tricks')
        self.deny(API + 'projects/42/%2e%2e/43/issues', 'path tricks')
        self.deny(API + 'projects/42//issues', 'path tricks')
        self.deny(API + 'https://gitlab.example.cz/api/v4/projects/42/issues', 'not a URL')

    def test_placeholders(self):
        self.deny(API + 'projects/:id/issues', 'placeholder')
        self.deny(API + 'projects/:fullpath/issues', 'placeholder')

    def test_hostname(self):
        self.deny('glab api projects/42/issues', '--hostname')
        self.deny('glab api --hostname gitlab.com projects/42/issues', 'gitlab.com')
        self.deny('glab api --hostname gitlab.example.cz --hostname gitlab.com projects/42/issues')

    def test_route_not_on_allowlist(self):
        # pipelines: a CI read, refused here because CONFIG has no ciRead; see CiRead below.
        for route in ('variables', 'members', 'access_tokens', 'deploy_keys', 'hooks',
                      'repository/files/a.txt', 'issues/7/move', 'issues/7/clone'):
            self.deny('glab api -X POST ' + H + ' projects/42/' + route, 'allowlist')
            self.deny('glab api -X GET ' + H + ' projects/42/' + route, 'allowlist')

    def test_delete_never(self):
        for route in ('issues/7', 'issues/7/notes/3', 'labels/5', 'repository/branches/x', 'merge_requests/3'):
            self.deny('glab api -X DELETE ' + H + ' projects/42/' + route, 'never')

    def test_fields_without_method_send_post(self):
        self.deny(API + 'projects/42/issues/7 -f state_event=close', 'POST')

    def test_move_and_clone_by_parameter(self):
        self.deny('glab api -X PUT ' + H + ' projects/42/issues/7 -f to_project_id=43', 'another project')

    def test_link_to_other_project(self):
        self.deny(API + 'projects/42/issues/7/links -f target_project_id=43 -f target_issue_iid=1', '43')
        self.deny(API + 'projects/42/issues/7/links -f target_project_id=team%2Fother -f target_issue_iid=1')

    def test_link_without_target(self):
        self.deny(API + 'projects/42/issues/7/links -f target_issue_iid=1', 'target_project_id')
        self.deny(API + 'projects/42/issues/7/links -f target_project_id=42 -f target_issue_iid=abc')

    def test_parameter_smuggled_in_query_string(self):
        self.deny(API + "'projects/42/issues/7/links?target_project_id=43&target_issue_iid=1'", '43')
        self.deny(API + "'projects/42/issues?sudo=root'", 'sudo')
        self.deny(API + "'projects/42/issues?private_token=x'", 'token')

    def test_method_override(self):
        self.deny(API + 'projects/42/issues/7/notes -f _method=DELETE -f body=x', '_method')
        self.deny(API + "'projects/42/issues/7/notes?_method=DELETE' -f body=x", '_method')

    def test_epic_group_namespace_keys(self):
        self.deny('glab api -X PUT ' + H + ' projects/42/issues/7 -f epic_id=5', 'epic')
        self.deny(API + 'projects/42/issues -f title=x -f labels=gitlab-kit -f epic_iid=2', 'epic')

    def test_headers(self):
        self.deny(API + "projects/42/issues -H 'Sudo: root'", 'header')
        self.deny(API + "projects/42/issues --header='PRIVATE-TOKEN: x'", 'header')

    def test_unknown_api_option(self):
        self.deny(API + 'projects/42/issues --repo other/proj', 'option')

    def test_two_endpoints(self):
        self.deny(API + 'projects/42/issues projects/43/issues', 'two endpoints')


CI_CONFIG = dict(CONFIG, ciRead=True)
CI_READS = ('pipelines', "'pipelines?ref=main&per_page=20'", 'pipelines/88', 'pipelines/88/jobs',
            'pipelines/88/test_report', 'jobs/301', 'jobs/301/trace')


class CiRead(GuardCase):
    """Opt-in CI reads: on only with "ciRead": true, and never anything that runs or deletes."""

    def test_reads_allowed_when_on(self):
        for route in CI_READS:
            self.allow(API + 'projects/42/' + route, config=CI_CONFIG)
        self.allow('glab api -X GET ' + H + ' projects/42/pipelines -f status=failed', config=CI_CONFIG)

    def test_lint_allowed_when_on(self):
        self.allow(API + "projects/42/ci/lint -f 'content=stages: [test]' -f dry_run=true",
                   config=CI_CONFIG)
        with tempfile.TemporaryDirectory() as folder:
            body = os.path.join(folder, 'lint.json')
            with open(body, 'w', encoding='utf-8') as handle:
                json.dump({'content': 'test:\n  script:\n    - /usr/bin/make test\n', 'dry_run': True}, handle)
            self.allow('glab api -X POST ' + H + ' projects/42/ci/lint --input ' + body.replace('\\', '/'),
                       config=CI_CONFIG)

    def test_reads_refused_when_off_or_missing(self):
        for config in (CONFIG, dict(CONFIG, ciRead=False), dict(CONFIG, ciRead='true'), dict(CONFIG, ciRead=1)):
            for route in CI_READS:
                self.deny(API + 'projects/42/' + route, 'ciRead', config=config)
            self.deny(API + "projects/42/ci/lint -f 'content=stages: [test]'", 'ciRead', config=config)

    def test_nothing_that_runs_retries_cancels_or_deletes(self):
        for command in ('glab api -X POST %s projects/42/pipeline -f ref=main',
                        'glab api -X POST %s projects/42/pipelines -f ref=main',
                        'glab api -X POST %s projects/42/pipelines/88/retry',
                        'glab api -X POST %s projects/42/pipelines/88/cancel',
                        'glab api -X DELETE %s projects/42/pipelines/88',
                        'glab api -X POST %s projects/42/jobs/301/retry',
                        'glab api -X POST %s projects/42/jobs/301/cancel',
                        'glab api -X POST %s projects/42/jobs/301/play',
                        'glab api -X POST %s projects/42/jobs/301/erase',
                        'glab api -X DELETE %s projects/42/jobs/301/artifacts',
                        'glab api -X PUT %s projects/42/pipelines/88/metadata -f name=x',
                        'glab api -X GET %s projects/42/ci/lint',
                        'glab api -X POST %s projects/42/trigger/pipeline -f ref=main'):
            self.deny(command % H, config=CI_CONFIG)

    def test_no_variables_artifacts_runners_or_schedules(self):
        for route in ('variables', 'variables/SECRET', 'pipelines/88/variables', 'jobs/301/artifacts',
                      'jobs/artifacts/main/download?job=test', 'jobs/301/artifacts/out.zip', 'runners',
                      'pipeline_schedules', 'triggers', 'jobs'):
            self.deny(API + "'projects/42/%s'" % route, 'allowlist', config=CI_CONFIG)

    def test_other_project_still_refused(self):
        self.deny(API + 'projects/43/pipelines', '43', config=CI_CONFIG)
        self.deny(API + 'projects/43/ci/lint -f content=x', '43', config=CI_CONFIG)


class DeniedContent(GuardCase):
    def test_create_without_agent_label(self):
        self.deny(API + 'projects/42/issues -f title=x', 'gitlab-kit')
        self.deny(API + 'projects/42/issues -f title=x -f labels=gitlab-kit-ish', 'gitlab-kit')

    def test_quick_actions_in_description_and_note(self):
        self.deny(API + "projects/42/issues -f title=x -f labels=gitlab-kit "
                        "-f $'description=Text\\n/move other/proj'", 'quick action')
        self.deny(API + "projects/42/issues/7/notes -f $'body=Done.\\n  /relate other/proj#3'", 'quick action')
        self.deny(API + "projects/42/issues/7/notes -f 'body=/close'", 'quick action')

    def test_input_file_with_foreign_target(self):
        with tempfile.TemporaryDirectory() as folder:
            body = os.path.join(folder, 'link.json')
            with open(body, 'w', encoding='utf-8') as handle:
                json.dump({'target_project_id': 43, 'target_issue_iid': 1}, handle)
            self.deny(API + 'projects/42/issues/7/links --input ' + body.replace('\\', '/'), '43')

    def test_input_file_with_quick_action(self):
        with tempfile.TemporaryDirectory() as folder:
            body = os.path.join(folder, 'issue.json')
            with open(body, 'w', encoding='utf-8') as handle:
                json.dump({'title': 'x', 'labels': ['gitlab-kit'], 'description': 'a\n/clone other/p'}, handle)
            self.deny(API + 'projects/42/issues --input ' + body.replace('\\', '/'), 'quick action')

    def test_input_unreadable_or_stdin_or_not_object(self):
        self.deny(API + 'projects/42/issues --input missing-file.json', 'cannot be read')
        self.deny(API + 'projects/42/issues --input -', 'standard input')
        with tempfile.TemporaryDirectory() as folder:
            body = os.path.join(folder, 'list.json')
            with open(body, 'w', encoding='utf-8') as handle:
                json.dump([1, 2], handle)
            self.deny(API + 'projects/42/issues --input ' + body.replace('\\', '/'), 'object')

    def test_typed_field_from_file_is_read(self):
        with tempfile.TemporaryDirectory() as folder:
            text = os.path.join(folder, 'note.md')
            with open(text, 'w', encoding='utf-8') as handle:
                handle.write('Looks fine.\n/move other/proj\n')
            self.deny(API + 'projects/42/issues/7/notes -F body=@' + text.replace('\\', '/'), 'quick action')


class DeniedCommands(GuardCase):
    def test_other_glab_commands(self):
        self.deny('glab issue list -R team/app', 'glab api')
        self.deny('glab issue delete 3 -R team/app', 'glab api')
        self.deny('glab mr merge 3', 'glab api')
        self.deny('glab repo clone other/proj', 'glab api')
        self.deny('glab config set token x', 'glab api')

    def test_auth_other_than_status(self):
        self.deny('glab auth login --hostname gitlab.example.cz --stdin', 'operator')
        self.deny('glab auth status -t', 'token')
        self.deny('glab auth status --show-token', 'token')
        self.deny('glab auth status --hostname gitlab.com', 'gitlab.com')

    def test_help_trick_does_not_hide_a_call(self):
        self.deny('glab api -X DELETE ' + H + ' projects/42/issues/1 --help')


class DeniedShell(GuardCase):
    OK = API + 'projects/42/issues'

    def test_chaining(self):
        self.deny(self.OK + ' && rm -rf x', 'compound')
        self.deny('ls; ' + self.OK, 'compound')
        self.deny(self.OK + ' | tee out.json', 'compound')
        self.deny(self.OK + '\n' + API + 'projects/43/issues')
        self.deny('(' + self.OK + ')')

    def test_substitution(self):
        self.deny('echo $(' + API + 'projects/43/issues)')
        self.deny('echo `' + API + 'projects/43/issues`')
        self.deny('git commit -m "$(' + API + 'projects/43/issues)"')
        self.deny(self.OK + ' -f "title=$(cat /etc/passwd)"', 'substitution')

    def test_unquoted_heredoc_still_runs_substitutions(self):
        self.deny('cat <<EOF\n$(' + API + 'projects/43/issues)\nEOF')

    def test_wrappers_and_nested_shells(self):
        self.deny('bash -c "' + self.OK + '"', 'wrapper')
        self.deny("sh -c '" + self.OK + "'", 'wrapper')
        self.deny('env ' + self.OK, 'wrapper')
        self.deny('echo 42 | xargs -I{} ' + API + 'projects/{}/issues')
        self.deny('timeout 10 ' + self.OK, 'wrapper')
        self.deny('eval "' + self.OK + '"', 'wrapper')
        self.deny('if true; then ' + self.OK + '; fi')

    def test_environment_prefix(self):
        self.deny('GITLAB_HOST=gitlab.com ' + self.OK, 'environment prefix')
        self.deny('GITLAB_TOKEN=x ' + self.OK, 'environment prefix')

    def test_redirections(self):
        self.deny(self.OK + ' > out.json', 'redirect')
        self.deny(self.OK + ' 2>&1', 'redirect')
        self.deny(API + 'projects/42/issues --input /dev/stdin < body.json', 'redirect')

    def test_expansions(self):
        self.deny(API + 'projects/$PID/issues', 'expanded')
        self.deny(API + 'projects/42/issues -f "title=costs $5"', 'expanded')
        self.deny(API + 'projects/42/issues?state=opened', 'expanded')     # unquoted glob ?
        self.deny(API + 'projects/{42,43}/issues', 'expanded')

    def test_unreadable_command(self):
        self.deny(API + "projects/42/issues -f 'title=unterminated", 'cannot read')

    def test_http_clients_to_the_host(self):
        self.deny('curl -H "PRIVATE-TOKEN: x" https://gitlab.example.cz/api/v4/projects/43/issues', 'glab only')
        self.deny('wget -qO- https://gitlab.example.cz/api/v4/projects', 'glab only')
        self.deny('ls && curl https://gitlab.example.cz/api/v4/users', 'glab only')
        self.deny('bash -c "curl https://gitlab.example.cz/api/v4/users"', 'glab only')
        self.not_ours('curl https://pypi.org/simple/')

    def test_powershell(self):
        self.deny(self.OK, 'Bash tool', tool='PowerShell')
        self.deny('& "glab" api ' + H + ' projects/42/issues', 'Bash tool', tool='PowerShell')
        self.deny('Get-Date; glab.exe api ' + H + ' projects/42/issues', 'Bash tool', tool='PowerShell')
        self.deny('Invoke-Expression "glab api x"', 'Bash tool', tool='PowerShell')
        self.deny('Invoke-RestMethod https://gitlab.example.cz/api/v4/projects/43', 'glab only',
                  tool='PowerShell')


class DeniedBinding(GuardCase):
    OK = API + 'projects/42/issues'

    def test_no_config(self):
        self.deny(self.OK, 'gl-setup', config=None)

    def test_disabled(self):
        self.deny(self.OK, 'disabled', config=dict(CONFIG, enabled=False))

    def test_broken_config(self):
        self.deny(self.OK, 'host', config=dict(CONFIG, host='http://gitlab.example.cz'))
        self.deny(self.OK, 'projectId', config=dict(CONFIG, projectId='abc'))
        self.deny(self.OK, 'projectPath', config=dict(CONFIG, projectPath='app'))

    def test_gitlab_mcp_tools(self):
        decision, reason = guard.decide('mcp__gitlab__get_issue', {'project_id': 42, 'issue_iid': 1}, CONFIG)
        self.assertEqual('deny', decision)
        self.assertIn('glab', reason)
        decision, _ = guard.decide('mcp__GitLab-Official__search', {}, None)
        self.assertEqual('deny', decision)


class EndToEnd(unittest.TestCase):
    """Run the script as Claude Code does: JSON on stdin, exit 2 + stderr means blocked."""

    def run_hook(self, tool, command, config, raw_config=None):
        with tempfile.TemporaryDirectory() as workspace:
            if config is not None or raw_config is not None:
                os.makedirs(os.path.join(workspace, '.claude'))
                with open(os.path.join(workspace, '.claude', 'gitlab.json'), 'w', encoding='utf-8') as f:
                    f.write(raw_config if raw_config is not None else json.dumps(config))
            payload = {'tool_name': tool, 'tool_input': {'command': command}, 'cwd': workspace}
            env = dict(os.environ, CLAUDE_PROJECT_DIR=workspace)
            proc = subprocess.run([sys.executable, GUARD], input=json.dumps(payload).encode('utf-8'),
                                  capture_output=True, env=env)
            log_path = os.path.join(workspace, '.claude', 'gitlab-guard.log')
            log = ''
            if os.path.exists(log_path):
                with open(log_path, encoding='utf-8') as handle:
                    log = handle.read()
            return proc.returncode, proc.stderr.decode('utf-8', 'replace'), log

    def test_allowed_call_exits_zero_and_is_audited(self):
        code, err, log = self.run_hook('Bash', API + 'projects/42/issues', CONFIG)
        self.assertEqual(0, code, err)
        self.assertIn('\tBash\tALLOW\tteam/app\t', log)

    def test_denied_call_exits_two_with_message_and_is_audited(self):
        code, err, log = self.run_hook('Bash', API + 'projects/43/issues', CONFIG)
        self.assertEqual(2, code)
        self.assertIn('gitlab-kit BLOCKED', err)
        self.assertIn('\tDENY\tteam/app\t', log)

    def test_audit_never_carries_issue_text(self):
        secret = 'THE-SECRET-TEXT-OF-AN-ISSUE'
        _, _, log = self.run_hook('Bash', API + "projects/42/issues/7/notes -f 'body=%s'" % secret, CONFIG)
        self.assertIn('ALLOW', log)
        self.assertNotIn(secret, log)

    def test_non_gitlab_command_is_not_audited(self):
        code, _, log = self.run_hook('Bash', 'ls -la', CONFIG)
        self.assertEqual(0, code)
        self.assertEqual('', log)

    def test_missing_config_blocks(self):
        code, err, _ = self.run_hook('Bash', API + 'projects/42/issues', None)
        self.assertEqual(2, code)
        self.assertIn('gl-setup', err)

    def test_unreadable_config_blocks(self):
        code, err, _ = self.run_hook('Bash', API + 'projects/42/issues', None, raw_config='{ not json')
        self.assertEqual(2, code)
        self.assertIn('could not be read', err)

    def test_garbage_stdin_fails_open(self):
        proc = subprocess.run([sys.executable, GUARD], input=b'not json', capture_output=True)
        self.assertEqual(0, proc.returncode)


if __name__ == '__main__':
    unittest.main()
