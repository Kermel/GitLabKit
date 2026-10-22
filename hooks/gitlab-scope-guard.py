#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gitlab-kit scope guard: a Claude Code PreToolUse hook.

One workspace, one GitLab project. Every GitLab call is inspected BEFORE it runs, and it runs only
when it can be PROVEN to stay inside the configured project. Anything ambiguous is refused with a
message that says how to phrase the request safely.

What this is:   a defense-in-depth layer. It stops an agent that has been told "only project
                group/app" from drifting into another project because an issue mentioned it.
What this is not: a security boundary. The access token's own scope is the real wall: a project
                access token reaches one project and nothing else. A hook can be bypassed by a
                person who edits the config or disables the plugin.

GitLab is reached through the official `glab` CLI, so the calls arrive as shell commands (Bash or
PowerShell tool), not as MCP tool calls. The guard reads the command the way a shell would.

Decision rules (deny-by-default):
  * A Bash command is a GitLab call when `glab` stands in COMMAND position in any part of it:
    after `;`, `&&`, `|`, inside `$( )` or backticks, behind `env`, `xargs`, `bash -c` and the
    like. `glab` as an ARGUMENT is data: `grep glab file`, a commit message quoting `glab api`,
    a quoted heredoc. Any other command is not our business -> allow.
  * No config, or `enabled: false`                            -> deny every GitLab call.
  * A GitLab call must be ONE plain command: no `;`, `&&`, pipes, redirections, heredocs,
    `$( )`, backticks, `$VAR`, unquoted globs, environment prefixes or wrappers. Only then does
    the guard know exactly what runs.
  * Allowed: `glab api`, `glab auth status` (without --show-token), `glab version`, help.
    Outside the project only three GET reads with no project data: `version`, `metadata` (edition)
    and `personal_access_tokens/self` (the token's scopes and expiry, never its value).
    Every other glab command is refused: one surface, the REST API, is checked properly.
  * `glab api` must name `--hostname <configured host>` (without it glab picks a default host the
    guard cannot see), a path `projects/<id or URL-encoded path>/...` of THIS project, and a
    method + route on the allowlist below. No DELETE, ever. No headers (`Sudo:` impersonates).
    No placeholders (`:id`, `:fullpath`), which glab fills from the current directory.
  * Only when the config says `"ciRead": true`: GET pipelines, pipelines/<id>, its jobs and
    test_report, jobs/<id> and its trace, and POST ci/lint. Never run, retry, cancel or delete.
  * Parameters from `-f`/`-F`, the query string and an `--input` JSON file are checked together.
    A key naming a project (`project_id`, `target_project_id`, `to_project_id`) must be this
    project. Keys naming an epic, group or namespace, and `sudo` or token keys, are refused.
  * Creating an issue needs the configured agent label in `labels`.
  * A link (`POST .../issues/<iid>/links`) must name `target_project_id` = this project and a
    numeric `target_issue_iid`.
  * Free text is not scanned for references: a description that mentions `other/app#3` acts on
    nothing. EXCEPT GitLab quick actions: a description or note line that starts with `/`
    (`/move`, `/clone`, `/relate other#3`, `/close`) is a command GitLab runs. Refused outside
    a fenced code block.
  * PowerShell: a `glab` call is refused with a pointer to the Bash tool, where it can be read.
  * Any command that runs an HTTP client (curl, wget, Invoke-RestMethod, ...) and names the
    configured host is refused: GitLab is reached through glab only.
  * MCP tools on a server whose name contains `gitlab`: refused. No GitLab MCP server is approved.

Exit code 2 + a stderr message is the refusal; Claude Code shows the message to the model.
A hook that cannot even parse its stdin exits 0, because it then cannot know the call was GitLab.
"""
import datetime
import json
import os
import re
import sys
from urllib.parse import parse_qsl, unquote, urlparse

CONFIG_RELATIVE_PATH = os.path.join('.claude', 'gitlab.json')
NOT_GITLAB = 'not a GitLab call'

GLAB = re.compile(r'^glab(\.exe)?$', re.IGNORECASE)
GLAB_ANYWHERE = re.compile(r'(?<![\w.-])glab(\.exe)?(?![\w-])', re.IGNORECASE)
ASSIGNMENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*=')
PROJECT_PATH = re.compile(r'^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)+$')

# Words that run the NEXT word (or a string) as a command. A GitLab call behind one of them is
# never plain, and the guard refuses it rather than unwrap every option they take.
WRAPPERS = {'env', 'sudo', 'exec', 'command', 'builtin', 'nohup', 'time', 'nice', 'timeout',
            'xargs', 'stdbuf', 'winpty', 'start', 'call', 'watch', 'parallel',
            '{', '}', '!', 'if', 'then', 'else', 'elif', 'while', 'until', 'do'}
SHELLS = {'bash', 'sh', 'zsh', 'dash', 'ksh', 'fish', 'pwsh', 'powershell', 'cmd', 'wsl', 'eval',
          'source', '.'}
HTTP_CLIENTS = {'curl', 'wget', 'http', 'https', 'xh', 'httpie', 'aria2c', 'invoke-webrequest',
                'iwr', 'invoke-restmethod', 'irm', 'start-bitstransfer'}

# Method -> routes below `projects/<project>`. Deny-by-default: what is not here is refused.
API_ROUTES = {
    'GET': [
        r'', r'/issues', r'/issues/\d+', r'/issues/\d+/notes', r'/issues/\d+/notes/\d+',
        r'/issues/\d+/links', r'/issues/\d+/related_merge_requests', r'/issues/\d+/closed_by',
        r'/issues/\d+/resource_label_events', r'/issues_statistics',
        r'/labels', r'/labels/[^/]+', r'/milestones', r'/milestones/\d+', r'/milestones/\d+/issues',
        r'/merge_requests', r'/merge_requests/\d+', r'/merge_requests/\d+/closes_issues',
        r'/merge_requests/\d+/related_issues', r'/search',
    ],
    'POST': [r'/issues', r'/issues/\d+/notes', r'/issues/\d+/links', r'/labels'],
    'PUT': [r'/issues/\d+', r'/issues/\d+/notes/\d+'],
}
API_ROUTES['HEAD'] = API_ROUTES['GET']

# Opt-in per workspace (`"ciRead": true`): read the project's own pipelines and job logs, and lint a
# .gitlab-ci.yml. Nothing that runs, retries, cancels or deletes a pipeline or a job; no variables,
# no artifact downloads, no runners.
CI_ROUTES = {
    'GET': [r'/pipelines', r'/pipelines/\d+', r'/pipelines/\d+/jobs', r'/pipelines/\d+/test_report',
            r'/jobs/\d+', r'/jobs/\d+/trace'],
    'POST': [r'/ci/lint'],
}
CI_ROUTES['HEAD'] = CI_ROUTES['GET']

# Instance reads that carry no project data, needed to prove a binding: the version and edition
# (`metadata`), and the token's own name, scopes and expiry (never its value). GET, no parameters.
META_ROUTES = {'version', 'metadata', 'personal_access_tokens/self'}

# glab api flags. Value flags take the next word (or `=value`); switches take none.
API_VALUE_FLAGS = {'-X': 'method', '--method': 'method', '-f': 'raw-field', '--raw-field': 'raw-field',
                   '-F': 'field', '--field': 'field', '--hostname': 'hostname', '--input': 'input',
                   '-H': 'header', '--header': 'header', '--output': 'output'}
API_SWITCHES = {'--paginate', '-i', '--include', '--silent'}

# `_method` turns a POST into a DELETE in Rails; sudo and token keys change who is acting.
FORBIDDEN_KEY = re.compile(r'epic|group|namespace|^sudo$|token|^_method$', re.IGNORECASE)
PROJECT_KEY = re.compile(r'project', re.IGNORECASE)
FREE_TEXT_KEY = re.compile(r'^(description|body|note)$', re.IGNORECASE)
QUICK_ACTION = re.compile(r'^\s*/[A-Za-z]')
FENCE = re.compile(r'^\s*(```|~~~)')


class Deny(Exception):
    pass


class ShellSyntax(Exception):
    pass


# ── config ──────────────────────────────────────────────────────────────────────────────────────

def project_dir(payload):
    return os.environ.get('CLAUDE_PROJECT_DIR') or payload.get('cwd') or os.getcwd()


def load_config(directory):
    path = os.path.join(directory, CONFIG_RELATIVE_PATH)
    if not os.path.isfile(path):
        return None
    with open(path, 'r', encoding='utf-8-sig') as handle:
        return json.load(handle)


class Binding(object):
    """The one project this workspace may touch, read from the config or refused."""

    def __init__(self, config):
        if config is None:
            raise Deny('This workspace has no .claude/gitlab.json. GitLab is off until /gl-setup has '
                       'bound the workspace to one project.')
        if not isinstance(config, dict) or not config.get('enabled', False):
            raise Deny('GitLab integration is disabled in this workspace (.claude/gitlab.json: '
                       '"enabled": false). Do not call GitLab here.')
        host = str(config.get('host') or '').strip()
        parsed = urlparse(host)
        if parsed.scheme != 'https' or not parsed.hostname:
            raise Deny('.claude/gitlab.json has no valid https `host`; rerun /gl-setup.')
        self.host = parsed.hostname.lower()
        self.project_id = str(config.get('projectId') or '').strip()
        if not self.project_id.isdigit():
            raise Deny('.claude/gitlab.json has no numeric `projectId`; rerun /gl-setup.')
        self.path = str(config.get('projectPath') or '').strip().strip('/')
        if not PROJECT_PATH.match(self.path):
            raise Deny('.claude/gitlab.json has no valid `projectPath`; rerun /gl-setup.')
        self.agent_label = config.get('agentLabel') or 'gitlab-kit'
        self.enforce_label = config.get('enforceAgentLabelOnCreate', True)
        self.ci_read = config.get('ciRead') is True

    def is_project(self, value):
        text = str(value).strip()
        if text.isdigit():
            return text == self.project_id
        return unquote(text).strip('/').lower() == self.path.lower()


def host_of(config):
    """The configured host name, or None. Used by the HTTP-client rule, which needs no binding."""
    try:
        return (urlparse(str((config or {}).get('host') or '')).hostname or '').lower() or None
    except ValueError:
        return None


# ── reading a Bash command ──────────────────────────────────────────────────────────────────────

class Word(object):
    __slots__ = ('parts', 'quoted', 'dynamic', 'brace')

    def __init__(self):
        self.parts, self.quoted, self.dynamic, self.brace = [], False, False, False

    def add(self, text):
        self.parts.append(text)

    @property
    def text(self):
        return ''.join(self.parts)


class Lexed(object):
    def __init__(self):
        self.segments = []       # simple commands, each a list of Words
        self.operators = 0       # ; & | && || ( ) and newlines between commands
        self.substitutions = 0   # $( ), backticks, <( ), >( )
        self.redirects = 0
        self.heredocs = 0


class Lexer(object):
    """Enough of POSIX shell syntax to say which words stand in command position.

    It does not run anything and does not need to be complete: any construct it cannot read
    raises ShellSyntax, and a command it cannot read is refused when it mentions glab at all."""

    def __init__(self, src, out=None, depth=0):
        self.src, self.i = src, 0
        self.out = out if out is not None else Lexed()
        self.depth = depth

    def run(self):
        self.commands(None)
        return self.out

    def peek(self, k=0):
        j = self.i + k
        return self.src[j] if j < len(self.src) else ''

    def nested(self, text):
        if self.depth > 16:
            raise ShellSyntax('the command nests too deeply to read')
        Lexer(text, self.out, self.depth + 1).run()

    def commands(self, closer):
        self.depth += 1
        if self.depth > 16:
            raise ShellSyntax('the command nests too deeply to read')
        src, out = self.src, self.out
        state = {'seg': [], 'word': None, 'target': False}
        heredocs = []   # [delimiter or None, strip tabs, expand]

        def cur():
            if state['word'] is None:
                state['word'] = Word()
            return state['word']

        def end_word():
            word = state['word']
            if word is None:
                return
            state['word'] = None
            if word.brace and word.text not in ('{', '}'):
                word.dynamic = True
            if state['target']:
                state['target'] = False
                if heredocs and heredocs[-1][0] is None:
                    heredocs[-1][0] = word.text
                    heredocs[-1][2] = not word.quoted
                return
            state['seg'].append(word)

        def end_segment():
            end_word()
            if state['target']:
                raise ShellSyntax('a redirection has no target')
            if state['seg']:
                out.segments.append(state['seg'])
            state['seg'] = []

        while self.i < len(src):
            ch = src[self.i]
            if closer and ch == closer:
                self.i += 1
                end_segment()
                self.depth -= 1
                return
            if ch == '\\':
                if self.peek(1) == '\n':
                    self.i += 2
                    continue
                word = cur()
                word.add(self.peek(1))
                word.quoted = True
                self.i += 2
                continue
            if ch == "'":
                end = src.find("'", self.i + 1)
                if end == -1:
                    raise ShellSyntax('unterminated single quote')
                word = cur()
                word.add(src[self.i + 1:end])
                word.quoted = True
                self.i = end + 1
                continue
            if ch == '"':
                self.double_quoted(cur())
                continue
            if ch == '`':
                self.backtick(cur())
                continue
            if ch == '$':
                self.dollar(cur(), in_double=False)
                continue
            if ch in ' \t\r':
                end_word()
                self.i += 1
                continue
            if ch == '\n':
                end_segment()
                out.operators += 1
                self.i += 1
                for doc in heredocs:
                    self.heredoc_body(doc)
                del heredocs[:]
                continue
            if ch == '#' and state['word'] is None:
                newline = src.find('\n', self.i)
                self.i = len(src) if newline == -1 else newline
                continue
            if ch in '<>':
                word = state['word']
                if word is not None and word.text.isdigit() and not word.quoted:
                    state['word'] = None          # `2>`: the digit is a descriptor, not a word
                else:
                    end_word()
                if self.peek(1) == '(':
                    self.i += 2
                    out.substitutions += 1
                    self.commands(')')
                    cur().dynamic = True
                    continue
                if src.startswith('<<<', self.i):
                    self.i += 3
                elif src.startswith('<<', self.i):
                    self.i += 2
                    strip = self.peek() == '-'
                    if strip:
                        self.i += 1
                    heredocs.append([None, strip, True])
                    out.heredocs += 1
                else:
                    self.i += 1
                    while self.peek() in ('>', '&', '|') and self.peek():
                        self.i += 1
                out.redirects += 1
                state['target'] = True
                continue
            if ch == '&' and self.peek(1) == '>':
                end_word()
                self.i += 2
                if self.peek() == '>':
                    self.i += 1
                out.redirects += 1
                state['target'] = True
                continue
            if ch in ';&|()':
                end_segment()
                out.operators += 1
                self.i += 1
                if ch == '(':
                    self.commands(')')
                elif ch == ')':
                    raise ShellSyntax('unbalanced parenthesis')
                continue
            word = cur()
            if ch in '*?[':
                word.dynamic = True
            elif ch in '{}':
                word.brace = True
            elif ch == '~' and not word.parts:
                word.dynamic = True
            word.add(ch)
            self.i += 1
        if closer:
            raise ShellSyntax('unbalanced parenthesis or substitution')
        end_segment()
        for doc in heredocs:
            if doc[0] is None:
                raise ShellSyntax('a heredoc has no delimiter')
        self.depth -= 1

    def double_quoted(self, word):
        src = self.src
        word.quoted = True
        self.i += 1
        while self.i < len(src):
            ch = src[self.i]
            if ch == '"':
                self.i += 1
                return
            if ch == '\\' and self.peek(1) in ('$', '`', '"', '\\', '\n'):
                if self.peek(1) != '\n':
                    word.add(self.peek(1))
                self.i += 2
                continue
            if ch == '`':
                self.backtick(word)
                continue
            if ch == '$':
                self.dollar(word, in_double=True)
                continue
            word.add(ch)
            self.i += 1
        raise ShellSyntax('unterminated double quote')

    def backtick(self, word):
        src, j, buf = self.src, self.i + 1, []
        while j < len(src):
            ch = src[j]
            if ch == '\\' and j + 1 < len(src):
                buf.append(src[j + 1])
                j += 2
                continue
            if ch == '`':
                break
            buf.append(ch)
            j += 1
        else:
            raise ShellSyntax('unterminated backtick')
        self.i = j + 1
        self.out.substitutions += 1
        word.dynamic = True
        self.nested(''.join(buf))

    def dollar(self, word, in_double):
        src, nxt = self.src, self.peek(1)
        if nxt == '(':
            self.i += 2
            self.out.substitutions += 1
            self.commands(')')
            word.dynamic = True
            return
        if nxt == '{':
            end = src.find('}', self.i + 2)
            if end == -1:
                raise ShellSyntax('unterminated ${')
            inner = src[self.i + 2:end]
            if '$(' in inner or '`' in inner:
                self.out.substitutions += 1
                self.nested(inner)
            word.dynamic = True
            self.i = end + 1
            return
        if nxt == "'" and not in_double:
            j = self.i + 2
            while j < len(src) and src[j] != "'":
                j += 2 if src[j] == '\\' else 1
            if j >= len(src):
                raise ShellSyntax("unterminated $'")
            # bash decodes these escapes, so `$'a\n/move x'` holds a real second line.
            word.add(ansi_c(src[self.i + 2:j]))
            word.quoted = True
            self.i = j + 1
            return
        if nxt == '"' and not in_double:
            self.i += 1
            self.double_quoted(word)
            return
        match = re.match(r'[A-Za-z_][A-Za-z0-9_]*|[0-9@*#?$!-]', src[self.i + 1:])
        if match:
            word.add('$' + match.group(0))
            word.dynamic = True
            self.i += 1 + len(match.group(0))
            return
        word.add('$')
        self.i += 1

    def heredoc_body(self, doc):
        delimiter, strip, expand = doc
        if delimiter is None:
            raise ShellSyntax('a heredoc has no delimiter')
        src, lines = self.src, []
        while self.i < len(src):
            newline = src.find('\n', self.i)
            stop = len(src) if newline == -1 else newline
            line = src[self.i:stop]
            self.i = stop + 1 if newline != -1 else len(src)
            if (line.lstrip('\t') if strip else line).rstrip('\r') == delimiter:
                return self.expand_body(lines, expand)
            lines.append(line)
        self.expand_body(lines, expand)

    def expand_body(self, lines, expand):
        """A quoted delimiter (<<'EOF') makes the body data. An unquoted one still runs $( )."""
        if not expand:
            return
        body = '\n'.join(lines)
        if '$(' not in body and '`' not in body:
            return
        scanner = Lexer(body, self.out, self.depth + 1)
        while scanner.i < len(body):
            ch = body[scanner.i]
            if ch == '\\':
                scanner.i += 2
            elif ch == '`':
                scanner.backtick(Word())
            elif ch == '$':
                scanner.dollar(Word(), in_double=True)
            else:
                scanner.i += 1


ANSI_C_ESCAPES = {'n': '\n', 't': '\t', 'r': '\r', 'a': '\a', 'b': '\b', 'e': '\x1b', 'E': '\x1b',
                  'f': '\f', 'v': '\v', '\\': '\\', "'": "'", '"': '"', '?': '?'}


def ansi_c(raw):
    """The value bash gives $'...': escapes decoded, as bash would pass it to the program."""
    def one(match):
        body = match.group(1)
        if body in ANSI_C_ESCAPES:
            return ANSI_C_ESCAPES[body]
        if body[0] in 'xuU':
            return chr(int(body[1:], 16))
        if body[0] == 'c':
            return chr(ord(body[1]) & 0x1f)
        return chr(int(body, 8) & 0xff)
    return re.sub(r'\\(x[0-9A-Fa-f]{1,2}|u[0-9A-Fa-f]{1,4}|U[0-9A-Fa-f]{1,8}|[0-7]{1,3}|c.|.)',
                  one, raw, flags=re.S)


def basename(word_text):
    return word_text.replace('\\', '/').rsplit('/', 1)[-1].lower()


def command_position(segment):
    """Index of the word that runs, after leading NAME=value assignments; None if there is none."""
    for index, word in enumerate(segment):
        if not (ASSIGNMENT.match(word.text) and not word.text.startswith('=')):
            return index
    return None


def strip_exe(name):
    return name[:-4] if name.endswith('.exe') else name


def segment_kind(segment):
    """'glab' when glab runs here, 'wrapped' when it may run behind a wrapper or shell, 'http'
    for an HTTP client, None otherwise."""
    index = command_position(segment)
    if index is None:
        return None
    command = strip_exe(basename(segment[index].text))
    if GLAB.match(command):
        return 'glab'
    if command in WRAPPERS or command in SHELLS:
        rest = [w.text for w in segment[index + 1:]]
        if any(GLAB_ANYWHERE.search(text) for text in rest):
            return 'wrapped'
        if any(strip_exe(basename(text)) in HTTP_CLIENTS for text in rest):
            return 'http'
        if any(re.search(r'\b(curl|wget|invoke-webrequest|invoke-restmethod)\b', t, re.IGNORECASE)
               for t in rest):
            return 'http'
        return None
    if command in HTTP_CLIENTS:
        return 'http'
    return None


# ── Bash decision ───────────────────────────────────────────────────────────────────────────────

def decide_bash(command, config, base_dir, config_error):
    if not isinstance(command, str):
        return 'allow', NOT_GITLAB
    host = host_of(config)
    try:
        lexed = Lexer(command).run()
    except ShellSyntax as problem:
        if GLAB_ANYWHERE.search(command):
            return 'deny', ('The command mentions glab and the guard cannot read it (%s). Run glab '
                            'as one plain command.' % problem)
        if host and host in command.lower() and re.search(
                r'\b(curl|wget|invoke-webrequest|invoke-restmethod|iwr|irm)\b', command, re.IGNORECASE):
            return 'deny', 'An HTTP client names the GitLab host; GitLab is reached through glab only.'
        return 'allow', NOT_GITLAB

    kinds = [segment_kind(segment) for segment in lexed.segments]
    if 'http' in kinds and host and host in command.lower():
        return 'deny', ('An HTTP client names %s. GitLab is reached through glab only, so every call '
                        'is visible to this guard and to GitLab\'s audit.' % host)
    if 'glab' not in kinds and 'wrapped' not in kinds:
        return 'allow', NOT_GITLAB
    try:
        if config_error is not None:
            raise Deny('.claude/gitlab.json could not be read (%s). GitLab is refused until the file '
                       'parses.' % config_error)
        binding = Binding(config)
        plain_glab(lexed, kinds)
        segment = lexed.segments[0]
        reason = check_glab([w.text for w in segment[1:]], binding, base_dir)
    except Deny as refusal:
        return 'deny', str(refusal)
    return 'allow', reason


def plain_glab(lexed, kinds):
    how = ('Run glab as ONE plain command: no ;, &&, pipes, redirections, heredocs, $( ), '
           'backticks, $VARIABLES, environment prefixes or wrappers. Quote every argument that '
           'holds * ? [ { or $.')
    if 'wrapped' in kinds:
        raise Deny('glab runs behind a wrapper or a nested shell (env, xargs, bash -c, ...). ' + how)
    if lexed.substitutions:
        raise Deny('The command uses command substitution. ' + how)
    if len(lexed.segments) != 1 or lexed.operators:
        raise Deny('glab is part of a compound command. ' + how)
    if lexed.redirects or lexed.heredocs:
        raise Deny('The command redirects input or output. ' + how)
    segment = lexed.segments[0]
    if command_position(segment) != 0:
        raise Deny('glab has an environment prefix (NAME=value glab ...). ' + how)
    for word in segment:
        if word.dynamic:
            raise Deny('The argument %r is expanded by the shell, so the guard cannot know its '
                       'value. %s' % (word.text, how))


def check_glab(args, binding, base_dir):
    """args: the words after `glab`, quotes removed. Returns the allow reason or raises Deny."""
    if not args or args[0] in ('version', '--version', 'help'):
        return 'glab help or version'
    if args[-1] in ('--help', '-h') and len(args) <= 3 and not any(a.startswith('-') for a in args[:-1]):
        return 'glab help'
    if args[0] == 'auth':
        if args[1:2] != ['status']:
            raise Deny('glab auth %s is the operator\'s job. Only `glab auth status` is allowed; the '
                       'token is set by the person, never by the agent.' % ' '.join(args[1:2]))
        rest = args[2:]
        if any(a in ('-t', '--show-token') or a.startswith('--show-token') for a in rest):
            raise Deny('glab auth status --show-token would print the token. Refused.')
        check_hostname_flags(rest, binding, required=False)
        return 'glab auth status'
    if args[0] != 'api':
        raise Deny('glab %s is not allowed. gitlab-kit talks to GitLab through `glab api --hostname '
                   '%s projects/%s/...` only, so one surface is checked properly. Delete, merge, '
                   'approve and rebase stay with the operator.' % (args[0], binding.host, binding.project_id))
    return check_api(args[1:], binding, base_dir)


def check_hostname_flags(rest, binding, required):
    seen = None
    for index, arg in enumerate(rest):
        value = None
        if arg == '--hostname':
            value = rest[index + 1] if index + 1 < len(rest) else ''
        elif arg.startswith('--hostname='):
            value = arg.split('=', 1)[1]
        if value is not None:
            parsed = (urlparse(value).hostname if '://' in value else value) or ''
            if parsed.lower() != binding.host:
                raise Deny('--hostname %s is not this workspace\'s GitLab host %s.' % (value, binding.host))
            seen = parsed
    if required and not seen:
        raise Deny('glab api needs `--hostname %s`. Without it glab uses a default host the guard '
                   'cannot see.' % binding.host)


def parse_api_args(args):
    opts = {'method': None, 'fields': [], 'input': None, 'hostname': None, 'path': None}
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if arg in API_SWITCHES:
            continue
        name, value = arg, None
        if arg.startswith('--') and '=' in arg:
            name, value = arg.split('=', 1)
        elif arg.startswith('-') and not arg.startswith('--') and len(arg) > 2 and arg[:2] in API_VALUE_FLAGS:
            name, value = arg[:2], arg[2:]
        if name in API_VALUE_FLAGS:
            if value is None:
                if index >= len(args):
                    raise Deny('glab api %s has no value.' % name)
                value = args[index]
                index += 1
            kind = API_VALUE_FLAGS[name]
            if kind == 'header':
                raise Deny('glab api headers are refused (a `Sudo:` header impersonates another user, '
                           'a token header swaps the identity).')
            if kind in ('raw-field', 'field'):
                if '=' not in value:
                    raise Deny('glab api %s %r is not key=value.' % (name, value))
                key, val = value.split('=', 1)
                opts['fields'].append((key, val, kind == 'field'))
            elif kind in ('method', 'hostname', 'input'):
                if opts[kind] is not None:
                    raise Deny('glab api names %s twice.' % name)
                opts[kind] = value
            continue
        if arg.startswith('-') and arg != '-':
            raise Deny('glab api option %r is not on gitlab-kit\'s list (-X, -f, -F, --input, '
                       '--hostname, --paginate, --include, --silent, --output).' % arg)
        if opts['path'] is not None:
            raise Deny('glab api names two endpoints (%r and %r).' % (opts['path'], arg))
        opts['path'] = arg
    return opts


def read_text(path, base_dir, what):
    if path in ('-', ''):
        raise Deny('%s reads standard input, which the guard cannot see. Write the body to a file.' % what)
    full = path if os.path.isabs(path) else os.path.join(base_dir, path)
    try:
        with open(full, 'r', encoding='utf-8-sig') as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError) as error:
        raise Deny('%s %s cannot be read by the guard (%s), so its contents cannot be checked.'
                   % (what, path, error))


def flatten(node, key=''):
    """(key, leaf) pairs of a JSON body. A list repeats its key; a nested key is its own name."""
    if isinstance(node, dict):
        for name, value in node.items():
            for pair in flatten(value, str(name)):
                yield pair
    elif isinstance(node, list):
        for value in node:
            for pair in flatten(value, key):
                yield pair
    else:
        yield key, node


def base_key(key):
    """`labels[]` -> labels, `issue[title]` -> title: the innermost name is what GitLab reads."""
    names = [part for part in re.split(r'[\[\]]+', key) if part]
    return names[-1] if names else key


def check_api(args, binding, base_dir):
    opts = parse_api_args(args)
    check_hostname_flags(args, binding, required=True)
    path = opts['path']
    if not path:
        raise Deny('glab api names no endpoint.')

    params = []
    for key, value, typed in opts['fields']:
        if typed and value.startswith('@'):
            value = read_text(value[1:], base_dir, '-F %s=@' % key)
        params.append((base_key(key), value))
    if opts['input'] is not None:
        try:
            body = json.loads(read_text(opts['input'], base_dir, '--input'))
        except ValueError as error:
            raise Deny('--input %s is not JSON (%s).' % (opts['input'], error))
        if not isinstance(body, dict):
            raise Deny('--input %s must hold one JSON object.' % opts['input'])
        params.extend(flatten(body))

    method = (opts['method'] or ('POST' if params else 'GET')).upper()
    if path.strip('/') in META_ROUTES:
        if method != 'GET' or params:
            raise Deny('glab api %s is an instance read: GET, no parameters.' % path)
        return 'glab api GET %s (instance metadata)' % path.strip('/')
    route, query = route_of(path, binding)
    params.extend((base_key(k), v) for k, v in parse_qsl(query, keep_blank_values=True))

    if method in ('DELETE', 'PATCH'):
        raise Deny('glab api %s is never allowed through gitlab-kit. Deleting issues, notes, labels, '
                   'branches or merge requests is a person\'s job.' % method)
    def listed(table):
        return any(re.match('^%s$' % pattern, route) for pattern in table.get(method, []))

    if listed(CI_ROUTES) and not binding.ci_read:
        raise Deny('glab api %s projects/%s%s is a CI read, and CI reads are off in this workspace. '
                   'Set "ciRead": true through /gl-setup to read pipelines and job logs and to lint '
                   '.gitlab-ci.yml.' % (method, binding.project_id, route))
    if not listed(API_ROUTES) and not listed(CI_ROUTES):
        raise Deny('glab api %s projects/%s%s is not on gitlab-kit\'s allowlist. Issues, their notes '
                   'and links, labels, milestones and merge-request reads are, and pipeline and job '
                   'reads when ciRead is on; running, retrying, cancelling, settings, members, '
                   'variables, tokens, hooks, artifacts and moves are not.%s'
                   % (method, binding.project_id, route,
                      ' (No -X given and fields present, so glab sends POST; add -X GET for a read.)'
                      if not opts['method'] and params else ''))

    check_params(params, binding)
    if method == 'POST' and route == '/issues' and binding.enforce_label:
        labels = []
        for key, value in params:
            if key == 'labels':
                labels.extend(part.strip() for part in str(value).split(','))
        if binding.agent_label not in labels:
            raise Deny('Creating an issue must carry the agent label %r in `labels`, so the issue is '
                       'traceable to the agent.' % binding.agent_label)
    if method == 'POST' and re.match(r'^/issues/\d+/links$', route):
        targets = [v for k, v in params if k == 'target_project_id']
        iids = [v for k, v in params if k == 'target_issue_iid']
        if len(targets) != 1 or len(iids) != 1 or not str(iids[0]).strip().isdigit():
            raise Deny('A link names exactly one target_project_id (this project, %s) and one numeric '
                       'target_issue_iid.' % binding.project_id)
    return 'glab api %s projects/%s%s' % (method, binding.project_id, route)


def route_of(path, binding):
    """`projects/<this project>/<route>[?query]` -> (route, query), or Deny."""
    if '://' in path:
        raise Deny('glab api takes an endpoint like projects/%s/issues, not a URL.' % binding.project_id)
    path = path.lstrip('/')
    route_part, _, query = path.partition('?')
    lowered = route_part.lower()
    if '..' in route_part or '//' in route_part or '\\' in route_part or '%2e' in lowered \
            or '%5c' in lowered or '#' in route_part or re.search(r'\s', route_part):
        raise Deny('The endpoint %r has path tricks (.., //, encoded dots or slashes); refused.' % path)
    if ':' in route_part:
        raise Deny('The endpoint %r uses a glab placeholder (:id, :fullpath, ...). glab fills it from '
                   'the current directory, which the guard cannot prove; name projects/%s.'
                   % (path, binding.project_id))
    match = re.match(r'^projects/([^/]+)(/.*)?$', route_part)
    if not match:
        raise Deny('The endpoint %r is outside projects/%s. Groups, users, runners, admin, search '
                   'across projects and GraphQL are never allowed.' % (path, binding.project_id))
    if not binding.is_project(match.group(1)):
        raise Deny('The endpoint names project %s; this workspace may only use project %s (%s).'
                   % (unquote(match.group(1)), binding.project_id, binding.path))
    return (match.group(2) or '').rstrip('/'), query


def check_params(params, binding):
    for key, value in params:
        if FORBIDDEN_KEY.search(key):
            raise Deny('The parameter %r is refused: epics, groups and namespaces are outside one '
                       'project, sudo or token parameters change who is acting, and _method turns '
                       'a write into a delete.' % key)
        if PROJECT_KEY.search(key):
            if not binding.is_project(value):
                raise Deny('The parameter %s=%s names another project; this workspace may only use '
                           'project %s (%s).' % (key, value, binding.project_id, binding.path))
        if FREE_TEXT_KEY.match(key) and isinstance(value, str):
            check_quick_actions(key, value)


def check_quick_actions(key, text):
    fenced = False
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced and QUICK_ACTION.match(line):
            raise Deny('The %s has a line starting with "/" (%r). GitLab runs such a line as a quick '
                       'action (/move, /clone, /relate, /close) and it can act outside the project. '
                       'Put it in a fenced code block or reword it.' % (key, line.strip()[:40]))


# ── PowerShell, MCP ─────────────────────────────────────────────────────────────────────────────

def decide_powershell(command, config):
    if not isinstance(command, str):
        return 'allow', NOT_GITLAB
    # Single-quoted strings and here-strings are literal in PowerShell: data, never commands.
    text = re.sub(r"@'.*?\n'@", "''", command, flags=re.S)
    text = re.sub(r"'(?:[^']|'')*'", "''", text)
    host = host_of(config)
    pieces = re.split(r'[;|\n{}()]|&&|\|\||\$\(', text)
    glab_runs, http_runs = False, False
    for piece in pieces:
        words = piece.strip().lstrip('&.').split()
        if not words:
            continue
        first = strip_exe(basename(words[0].strip('"')))
        if GLAB.match(first):
            glab_runs = True
        if first in HTTP_CLIENTS:
            http_runs = True
    if re.search(r'(?<![\w-])(iex|invoke-expression|start-process|saps|cmd|-command|-c)(?![\w-])',
                 text, re.IGNORECASE) and GLAB_ANYWHERE.search(text):
        glab_runs = True
    if http_runs and host and host in command.lower():
        return 'deny', 'An HTTP client names %s. GitLab is reached through glab only.' % host
    if glab_runs:
        return 'deny', ('glab through PowerShell is refused: the guard reads Bash syntax only. Run the '
                        'same `glab api --hostname ... projects/<id>/...` command with the Bash tool.')
    return 'allow', NOT_GITLAB


def split_tool_name(tool_name):
    """'mcp__gitlab__get_issue' -> ('gitlab', 'get_issue'); non-MCP -> (None, None)."""
    if not isinstance(tool_name, str) or not tool_name.startswith('mcp__'):
        return None, None
    parts = tool_name.split('__')
    if len(parts) < 3:
        return None, None
    return parts[1], '__'.join(parts[2:])


def decide(tool_name, tool_input, config, base_dir='.', config_error=None):
    """Return (decision, reason). decision is 'allow' or 'deny'; reason NOT_GITLAB means the call
    is none of this guard's business and is not audited. No network, no writes."""
    if tool_name in ('Bash', 'PowerShell'):
        command = tool_input.get('command') if isinstance(tool_input, dict) else None
        if tool_name == 'Bash':
            return decide_bash(command, config, base_dir, config_error)
        return decide_powershell(command, config)
    server, _ = split_tool_name(tool_name)
    extra = ((config or {}).get('guard') or {}).get('mcpServers') or [] if isinstance(config, dict) else []
    if server is not None and (re.search(r'gitlab', server, re.IGNORECASE) or server in extra):
        return 'deny', ('No GitLab MCP server is approved for gitlab-kit; it uses the glab CLI. Run '
                        '`glab api --hostname ... projects/<id>/...` with the Bash tool.')
    return 'allow', NOT_GITLAB


# ── audit ───────────────────────────────────────────────────────────────────────────────────────

def audit(directory, config, tool_name, decision, reason):
    """One line per GitLab decision. Tool name and verdict only: no issue text, no credentials."""
    guard = ((config or {}).get('guard') or {}) if isinstance(config, dict) else {}
    rel = guard.get('auditLog') or os.path.join('.claude', 'gitlab-guard.log')
    try:
        path = rel if os.path.isabs(rel) else os.path.join(directory, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        project = (config or {}).get('projectPath') if isinstance(config, dict) else None
        with open(path, 'a', encoding='utf-8') as handle:
            handle.write('%s\t%s\t%s\t%s\t%s\n' % (stamp, tool_name, decision.upper(), project or '-',
                                                   reason.replace('\n', ' ')[:200]))
    except OSError:
        pass


# ── entry ───────────────────────────────────────────────────────────────────────────────────────

def main():
    # Refusal messages quote the offending value; a cp1252 console must not turn the refusal
    # itself into a crash.
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # cannot even tell which tool this is; nothing to enforce.
    if not isinstance(payload, dict):
        return 0
    tool_name = payload.get('tool_name')
    if tool_name not in ('Bash', 'PowerShell') and split_tool_name(tool_name)[0] is None:
        return 0
    directory = project_dir(payload)
    config, config_error = None, None
    try:
        config = load_config(directory)
    except (OSError, ValueError) as error:
        config_error = error
    tool_input = payload.get('tool_input')
    try:
        decision, reason = decide(tool_name, tool_input, config,
                                  base_dir=payload.get('cwd') or directory, config_error=config_error)
    except Exception as error:  # a guard bug must not open the door, nor block every ls
        if GLAB_ANYWHERE.search(json.dumps(tool_input)):
            decision, reason = 'deny', 'the guard failed on this glab call (%s); refused.' % error
        else:
            return 0
    if reason == NOT_GITLAB:
        return 0
    audit(directory, config, tool_name, decision, reason)
    if decision == 'allow':
        return 0
    sys.stderr.write('gitlab-kit BLOCKED %s: %s\n' % (tool_name, reason))
    return 2


if __name__ == '__main__':
    sys.exit(main())
