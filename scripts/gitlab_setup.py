#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gitlab-kit setup helper: the file-writing half of /gl-setup.

The wizard's QUESTIONS are asked by Claude (skills/gl-setup/SKILL.md). The wizard's WRITES go
through this script, because two of them must never be destructive and a model editing a file by
hand is exactly how they become destructive:

  write-config <workspace> <answers.json>   merge answers into <workspace>/.claude/gitlab.json,
                                            keeping keys the answers do not mention
  disable <workspace>                       write {"enabled": false} and keep the rest
  render-claude-md <workspace>              write or replace the gitlab-kit section of CLAUDE.md
                                            between two marker comments; everything outside the
                                            markers is kept byte for byte: text, line endings
                                            and a UTF-8 byte-order mark if the file has one
  validate <workspace>                      check the config and print a one-screen summary

Exit 0 on success, 1 with a message on stderr otherwise. No network: this script never talks
to GitLab. Discovery is Claude's job through `glab api`, behind the scope guard.
"""
import json
import os
import re
import sys
from urllib.parse import urlparse

CONFIG_PATH = os.path.join('.claude', 'gitlab.json')
CLAUDE_MD = 'CLAUDE.md'
MARK_START = '<!-- gitlab-kit:start -->'
MARK_END = '<!-- gitlab-kit:end -->'
PROJECT_PATH = re.compile(r'^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)+$')
ASCII_LABEL = re.compile(r'^[\x21-\x7e]([\x20-\x7e]*[\x21-\x7e])?$')

# `phase`: the parent issue of a roadmap phase (Community Edition has no epics). A config that
# still stores such a label as `other` keeps working; it is only not found by role.
TYPE_ROLES = ('bug', 'feature', 'task', 'idea', 'debt', 'phase', 'other')
STATUS_ROLES = ('todo', 'doing', 'review', 'blocked', 'other')

DEFAULTS = {
    'enabled': True,
    'host': '',
    'projectId': None,
    'projectPath': '',
    'projectName': '',
    'defaultBranch': '',
    'agentLabel': 'gitlab-kit',
    'enforceAgentLabelOnCreate': True,
    'ciRead': False,
    'ticketLanguage': '',
    'instance': {
        'version': '',
        'enterprise': False,
        'epics': False,
        'blockingLinks': False,
        'nativeStatus': False,
    },
    'issueTypes': [],
    'workflow': {
        'statuses': [],
        'initialStatusId': None,
        'activeStatusIds': [],
        'initialStatus': '',
        'activeStatuses': [],
        'requiresApprovalForClose': True,
        'closeKeyword': 'Relates to',
    },
    'conventions': {
        'milestones': False,
        'parentIssues': True,
    },
    'triageTriggers': ['feature-start', 'bugfix-start', 'release-planning', 'manual'],
    'ticketCreationPolicy': {
        'allowRoutineCreation': True,
        'approvalRequiredForBulkOrAmbiguousCreation': True,
    },
    'labels': {
        'agentCreated': 'gitlab-kit',
        'agentAnalysis': 'source::agent-analysis',
        'userRequest': 'source::user-request',
        'appFeedback': 'source::app-feedback',
        'externalBugReport': 'source::external-bug-report',
    },
    'guard': {
        'mcpServers': [],
        'auditLog': '.claude/gitlab-guard.log',
    },
}


def fail(message):
    sys.stderr.write('gl-setup: %s\n' % message)
    return 1


# ── config ──────────────────────────────────────────────────────────────────────────────────────

def read_json(path):
    with open(path, 'r', encoding='utf-8-sig') as handle:
        return json.load(handle)


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write('\n')


def deep_merge(base, overlay):
    """overlay wins; dicts merge recursively; lists and scalars replace."""
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(workspace):
    path = os.path.join(workspace, CONFIG_PATH)
    return read_json(path) if os.path.isfile(path) else None


def normalise_answers(answers):
    """Shape what a person types into what the guard reads. Returns an error text or None."""
    if 'host' in answers:
        host = str(answers['host'] or '').strip().rstrip('/')
        if host and '://' not in host:
            host = 'https://' + host
        parsed = urlparse(host)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.path not in ('', '/'):
            return 'host %r is not an https GitLab address like https://gitlab.example.com' % answers['host']
        answers['host'] = 'https://' + parsed.netloc.lower()
    if 'projectId' in answers:
        value = str(answers['projectId']).strip()
        if not value.isdigit() or int(value) <= 0:
            return 'projectId %r is not a numeric GitLab project id' % answers['projectId']
        answers['projectId'] = int(value)
    if 'projectPath' in answers:
        path = str(answers['projectPath'] or '').strip()
        if '://' in path:
            path = urlparse(path).path
        path = path.strip('/')
        if path.endswith('.git'):
            path = path[:-4]
        if '/-/' in '/' + path + '/':
            path = ('/' + path + '/').split('/-/', 1)[0].strip('/')
        if not PROJECT_PATH.match(path):
            return 'projectPath %r is not a GitLab path with namespace like group/project' % answers['projectPath']
        answers['projectPath'] = path
    return None


def derive_workflow(config):
    """GitLab CE has two native states, opened and closed. Everything between is a scoped label
    (workflow::doing). Labels can be renamed, so the label ID is the identity; the names are
    recomputed from the ids on every write, so a rerun with fresh labels refreshes stale names.
    Closed is the only terminal state, and closing always asks first."""
    workflow = config.get('workflow') or {}
    statuses = workflow.get('statuses') or []
    for status in statuses:
        role = str(status.get('role') or 'other').lower()
        status['role'] = role if role in STATUS_ROLES else 'other'
    name_of = {s['id']: s.get('name') for s in statuses if s.get('id') is not None}
    if workflow.get('initialStatusId') not in name_of:
        todo = [s['id'] for s in statuses if s['role'] == 'todo' and s.get('id') is not None]
        workflow['initialStatusId'] = todo[0] if todo else None
    active = [i for i in (workflow.get('activeStatusIds') or []) if i in name_of]
    if not active:
        active = [s['id'] for s in statuses if s['role'] in ('doing', 'review') and s.get('id') is not None]
    workflow['activeStatusIds'] = active
    workflow['initialStatus'] = name_of.get(workflow['initialStatusId'], '') or ''
    workflow['activeStatuses'] = [name_of[i] for i in active]
    config['workflow'] = workflow
    return config


def derive_issue_types(config):
    """`issueTypes` joins the project's type labels (type::bug) with a ROLE the person confirms.
    Skills ask for 'the bug label' and get whatever this project calls it, by id."""
    for entry in config.get('issueTypes') or []:
        role = str(entry.get('role') or 'other').lower()
        entry['role'] = role if role in TYPE_ROLES else 'other'
    return config


def problems(config):
    out = []
    if not isinstance(config, dict):
        return ['config is not an object']
    if not config.get('enabled', False):
        return []  # a disabled workspace needs nothing else
    parsed = urlparse(str(config.get('host') or ''))
    if parsed.scheme != 'https' or not parsed.hostname:
        out.append('host is empty or not https; it is the GitLab address, e.g. https://gitlab.example.com')
    if not str(config.get('projectId') or '').isdigit():
        out.append('projectId is empty; it is the number on the project page ("Project ID")')
    if not PROJECT_PATH.match(str(config.get('projectPath') or '')):
        out.append('projectPath is empty or invalid; it is group/project from the project URL')
    label = config.get('agentLabel') or (config.get('labels') or {}).get('agentCreated')
    if not label:
        out.append('agentLabel is empty; every agent-created issue must carry one')
    labels = dict(config.get('labels') or {}, agentLabel=label or '')
    for key, value in labels.items():
        if value and not ASCII_LABEL.match(str(value)):
            out.append('label %s=%r is not ASCII; labels are never translated' % (key, value))
    roles = {t.get('role') for t in (config.get('issueTypes') or [])}
    for role in ('bug', 'task'):
        if role not in roles:
            out.append('no type label has role "%s"; /gl-create needs one (issueTypes[].role)' % role)
    for entry in (config.get('issueTypes') or []) + ((config.get('workflow') or {}).get('statuses') or []):
        if entry.get('id') is None:
            out.append('label %r has no id yet; create it, then rerun /gl-setup' % entry.get('name'))
    if not (config.get('workflow') or {}).get('activeStatusIds'):
        out.append('no workflow label has role "doing"; /gl-work cannot mark an issue as started')
    if not isinstance(config.get('ciRead', False), bool):
        out.append('ciRead must be true or false; anything else counts as false in the guard')
    if not config.get('ticketLanguage'):
        out.append('ticketLanguage is empty; sample recent titles and set the language issues are written in')
    return out


def cmd_write_config(workspace, answers_path):
    try:
        answers = read_json(answers_path)
    except (OSError, ValueError) as error:
        return fail('cannot read answers %s: %s' % (answers_path, error))
    if not isinstance(answers, dict):
        return fail('answers must be a JSON object')
    error = normalise_answers(answers)
    if error:
        return fail(error)
    existing = load_config(workspace) or {}
    merged = deep_merge(deep_merge(DEFAULTS, existing), answers)
    merged = derive_workflow(derive_issue_types(merged))
    write_json(os.path.join(workspace, CONFIG_PATH), merged)
    print('wrote %s' % os.path.join(workspace, CONFIG_PATH))
    for line in problems(merged):
        print('  still missing: ' + line)
    return 0


def cmd_disable(workspace):
    existing = load_config(workspace) or {}
    merged = deep_merge(deep_merge(DEFAULTS, existing), {'enabled': False})
    write_json(os.path.join(workspace, CONFIG_PATH), merged)
    print('GitLab disabled in %s' % os.path.join(workspace, CONFIG_PATH))
    return 0


def cmd_validate(workspace):
    config = load_config(workspace)
    if config is None:
        return fail('no %s; run /gl-setup' % CONFIG_PATH)
    issues = problems(config)
    print(summary(config))
    for line in issues:
        print('PROBLEM: ' + line)
    return 1 if issues else 0


def summary(config):
    workflow = config.get('workflow') or {}
    instance = config.get('instance') or {}
    labels = config.get('labels') or {}
    return '\n'.join([
        'enabled:           %s' % config.get('enabled'),
        'project:           %s  #%s  %s' % (config.get('projectPath') or '-', config.get('projectId') or '-',
                                            config.get('projectName') or ''),
        'host:              %s  (GitLab %s, %s)' % (
            config.get('host') or '-', instance.get('version') or '?',
            'Enterprise' if instance.get('enterprise') else 'Community Edition'),
        'agent label:       %s' % (config.get('agentLabel') or labels.get('agentCreated')),
        'origin labels:     %s' % ', '.join(labels[k] for k in
                                            ('agentAnalysis', 'userRequest', 'appFeedback', 'externalBugReport')
                                            if labels.get(k)),
        'ticket language:   %s' % (config.get('ticketLanguage') or '-'),
        'type labels:       %s' % (', '.join('%s=%s' % (t.get('role'), t.get('name'))
                                             for t in (config.get('issueTypes') or [])) or '-'),
        'initial status:    %s' % (workflow.get('initialStatus') or '- (opened, no label)'),
        'active statuses:   %s' % (', '.join(workflow.get('activeStatuses') or []) or '-'),
        'closing:           closed state only  (approval required: %s; MR keyword: %s #n)' % (
            workflow.get('requiresApprovalForClose', True), workflow.get('closeKeyword') or 'Relates to'),
        'CI reads:          %s' % ('on: pipelines, jobs, job logs, ci/lint' if config.get('ciRead') is True
                                       else 'off'),
        'triage triggers:   %s' % ', '.join(config.get('triageTriggers') or []),
    ])


# ── CLAUDE.md ───────────────────────────────────────────────────────────────────────────────────

def render_section(config):
    path = config.get('projectPath')
    pid = config.get('projectId')
    name = config.get('projectName')
    host = urlparse(str(config.get('host') or '')).hostname or '<host>'
    label = config.get('agentLabel') or (config.get('labels') or {}).get('agentCreated') or 'gitlab-kit'
    labels = config.get('labels') or {}
    origin = [labels[k] for k in ('agentAnalysis', 'userRequest', 'appFeedback', 'externalBugReport')
              if labels.get(k)]
    triggers = config.get('triageTriggers') or []
    policy = config.get('ticketCreationPolicy') or {}
    workflow = config.get('workflow') or {}

    if not config.get('enabled', False):
        return '\n'.join([
            MARK_START,
            '## GitLab',
            '',
            'GitLab integration is **disabled** in this workspace (`.claude/gitlab.json`). Do not call',
            'GitLab here. Run `/gl-setup` to enable it.',
            MARK_END,
        ])

    lines = [
        MARK_START,
        '## GitLab scope and operating rules (gitlab-kit)',
        '',
        'This workspace is authorised to use GitLab issues **only for project `%s`** (id `%s`%s).' % (
            path, pid, ', named *%s*' % name if name else ''),
        'A hook refuses every GitLab call it cannot prove is inside that project; these rules are what',
        'the hook cannot see.',
        '',
        '- Reach GitLab only as one plain command: `glab api --hostname %s projects/%s/...`.' % (host, pid),
        '  No `;`, `&&`, pipes, redirections or `$( )`. Long text goes in a JSON file passed with `--input`.',
        '- Never read, create, edit, comment on, link or close issues outside project `%s`.' % pid,
        '- Never delete anything, and never merge, approve or rebase a merge request: the operator does.',
        '  Never touch groups, users, members, settings, CI/CD variables, tokens or deploy keys.',
        '- Never write a line that starts with `/` in an issue or note outside a code block: GitLab runs',
        '  it as a quick action (`/move`, `/close`, `/relate`).',
        '- Apply the `%s` label to every issue you create.' % label,
    ]
    if origin:
        lines.append('- Add one origin label when the source is known:')
        lines.append('  %s.' % ', '.join('`%s`' % o for o in origin))
    lines += [
        '- Search project `%s` for likely duplicates before creating an issue.' % pid,
        '- **Ask for explicit approval before closing any issue.** Merged code and green tests do not',
        '  authorise closure; the person does. Only `/gl-signoff` closes.',
        '- In merge requests and commits write `%s #n`, never `Closes #n` or `Fixes #n`: those close the'
        % (workflow.get('closeKeyword') or 'Relates to'),
        '  issue when the merge request reaches the default branch. Commits carry the trailer `Refs #n`;',
        '  a spec names its issue in its header as `Issue: #n`.',
    ]
    if policy.get('allowRoutineCreation', True):
        lines.append('- You may create a clearly necessary issue after a one-line rationale; report it at once.')
    else:
        lines.append('- Ask before creating any issue.')
    if policy.get('approvalRequiredForBulkOrAmbiguousCreation', True):
        lines.append('- Ask before creating batches, parent issues, hierarchies or anything ambiguous.')
    lines += [
        '- Report every GitLab write: `#n`, link, what changed, why.',
        '- Do not comment on routine steps. Do not change an issue because code changed locally.',
        '- Link dependent issues so the backlog reads in order: propose the links, create them after',
        '  approval.',
        '- Labels can be renamed: match type and workflow labels on the ids in `.claude/gitlab.json`.',
        '  Labels are ASCII and never translated.',
    ]
    if config.get('ciRead') is True:
        lines += [
            '- CI reads are on: you may read the pipelines and job logs of this project and lint a',
            '  `.gitlab-ci.yml` (`GET pipelines`, `pipelines/<id>`, its `jobs` and `test_report`, `jobs/<id>`,',
            '  `jobs/<id>/trace`; `POST ci/lint`). Never run, retry, cancel or delete a pipeline or a job;',
            '  never read CI/CD variables or download artifacts.',
        ]
    if config.get('ticketLanguage'):
        lines.append('- Write issue titles, descriptions and notes in **%s**, the language the project'
                     % config['ticketLanguage'])
        lines.append('  uses. Talk to the person in whatever language they use.')
    if triggers:
        lines.append('- Offer a project-scoped GitLab check at: %s.' % ', '.join(triggers))
    lines.append('- Skills: `/gl-status` shows this configuration; `/gl-triage`, `/gl-create`, `/gl-work`,')
    lines.append('  `/gl-signoff` and `/gl-plan` do the work inside project `%s`.' % pid)
    lines.append(MARK_END)
    return '\n'.join(lines)


def cmd_render_claude_md(workspace):
    config = load_config(workspace)
    if config is None:
        return fail('no %s; run write-config first' % CONFIG_PATH)
    path = os.path.join(workspace, CLAUDE_MD)
    section = render_section(config)

    if os.path.isfile(path):
        with open(path, 'rb') as handle:
            raw = handle.read()
        # Keep the file's byte-order mark exactly as found. Some editors and tools on Windows
        # write CLAUDE.md with one and show a diff on every line when it disappears.
        bom = raw.startswith(b'\xef\xbb\xbf')
        text = raw.decode('utf-8-sig')
        eol = '\r\n' if '\r\n' in text else '\n'
        section_eol = section.replace('\n', eol)
        start, end = text.find(MARK_START), text.find(MARK_END)
        if start != -1 and end != -1 and end > start:
            new_text = text[:start] + section_eol + text[end + len(MARK_END):]
            action = 'replaced the gitlab-kit section in'
        elif start != -1 or end != -1:
            return fail('%s has one gitlab-kit marker but not the other; fix the file by hand' % path)
        else:
            sep = eol if text.endswith(eol) else eol * 2
            new_text = text + sep + section_eol + eol
            action = 'appended the gitlab-kit section to'
        with open(path, 'wb') as handle:
            handle.write((b'\xef\xbb\xbf' if bom else b'') + new_text.encode('utf-8'))
    else:
        new_text = '# CLAUDE.md\n\n' + section + '\n'
        with open(path, 'wb') as handle:
            handle.write(new_text.encode('utf-8'))
        action = 'created'
    print('%s %s' % (action, path))
    return 0


# ── entry ───────────────────────────────────────────────────────────────────────────────────────

def main(argv):
    # A Windows console is cp1252 by default and cannot print a Czech project name.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    if len(argv) < 3:
        return fail('usage: gitlab_setup.py write-config <workspace> <answers.json> | disable <workspace> | '
                    'render-claude-md <workspace> | validate <workspace>')
    command, workspace = argv[1], argv[2]
    if not os.path.isdir(workspace):
        return fail('workspace %s is not a directory' % workspace)
    if command == 'write-config':
        if len(argv) < 4:
            return fail('write-config needs <answers.json>')
        return cmd_write_config(workspace, argv[3])
    if command == 'disable':
        return cmd_disable(workspace)
    if command == 'render-claude-md':
        return cmd_render_claude_md(workspace)
    if command == 'validate':
        return cmd_validate(workspace)
    return fail('unknown command %r' % command)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
