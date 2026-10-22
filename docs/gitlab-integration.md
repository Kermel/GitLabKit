# GitLab integration with gitlab-kit

One Claude Code workspace, one GitLab project. A hook enforces it. Skills make it useful.

## Enable, disable, rerun

| Want | Do |
|---|---|
| Enable in a workspace | run `/gl-setup`, answer the wizard, commit `.claude/gitlab.json` and `CLAUDE.md` |
| Disable in a workspace | run `/gl-setup` and answer **No**, or set `"enabled": false` in `.claude/gitlab.json` |
| Change the project or a policy | run `/gl-setup` again; it keeps every answer you do not change |
| Check what is configured | `python <plugin>/scripts/gitlab_setup.py validate <workspace>` or `/gl-status` |

The wizard writes two files in the workspace, and nothing else there:

- `<workspace>/.claude/gitlab.json`: the configuration. Commit it. It has no secrets.
- `<workspace>/CLAUDE.md`: one section between `<!-- gitlab-kit:start -->` and
  `<!-- gitlab-kit:end -->`. Everything outside the markers is kept byte for byte: the text, the
  line endings, and a UTF-8 byte-order mark if the file starts with one.

In GitLab it creates only the labels you approve (type, workflow, agent and origin labels).

Add `.claude/gitlab-guard.log` to `.gitignore` (or `.claude/*.log`). It is the audit trail, local
only.

## Install

The plugin needs Python 3 and the official `glab` CLI on the machine:

```bash
winget install glab.glab
```

Then, from a clone of this repository, on one machine:

```bash
claude plugin marketplace add <path to this repository>
```

```bash
claude plugin install gitlab-kit@gitlab-kit
```

Installing at user scope activates the guard in **every** workspace on that machine. A workspace
without `.claude/gitlab.json` then refuses every `glab` call. That is deny-by-default working as
intended. Run `/gl-setup` in each workspace that should have GitLab.

## Access: official and auditable only

- **Interface:** the official `glab` CLI, calling GitLab's REST API v4 through `glab api`. No
  browser automation, no cookies or session reuse, no scraping, no direct `curl` (the guard refuses
  an HTTP client that names the GitLab host). GitLab's MCP server is not used; the guard refuses
  every GitLab MCP tool until one is approved.
- **Token:** a **project access token** of the bound project. It is a bot user that is a member of
  that one project only, so it is the real wall. Role **Reporter**; scope `read_api` for read-only
  use, `api` when the kit should create and edit issues. Delete needs Owner, and the kit never asks
  for it.
- **Where the token lives:** the person sets `GITLAB_TOKEN` as a user environment variable
  (*System Properties → Environment Variables*), or stores it in Windows Credential Manager with
  `glab auth login --hostname <host> --use-keyring`. Never in chat, never in a file of the
  repository, never in the command history. A plain `glab auth login` without `--use-keyring`
  writes the token in clear text to glab's config file; do not use that.
- **If a scope or permission is missing**, GitLab answers `401` or `403`. The skills stop and say
  which. A blocked API is a decision of the GitLab administrators: ask the AI platform team for an
  approved path, never work around it.

## How the scope guard works

`hooks/gitlab-scope-guard.py` is registered as a `PreToolUse` hook on `Bash`, `PowerShell` and
every `mcp__*` tool. It reads `.claude/gitlab.json` and lets a GitLab call through only when it can
prove the call stays in the configured project. Otherwise it exits 2 with a message the model sees,
and the call never runs.

### Which commands are GitLab calls

`glab` runs from the shell, so the guard reads a Bash command the way a shell would: quotes,
`$( )`, backticks, heredocs, redirections. A command is a GitLab call when `glab` stands in
**command position** anywhere in it: first word, after `;`, `&&`, `|`, inside `$( )` or backticks,
behind `env`, `xargs`, `timeout`, `bash -c` and similar wrappers.

`glab` as an **argument** is data and is not checked: `grep glab hooks/...`, a commit message that
quotes `glab api -X DELETE ...`, a quoted heredoc (`<<'EOF'`). An unquoted heredoc still runs its
`$( )`, and the guard reads those.

### What a GitLab call must be

| Rule | Why |
|---|---|
| One plain command: no `;`, `&&`, pipes, redirections, heredocs, `$( )`, backticks, `$VAR`, unquoted globs, `NAME=value` prefixes or wrappers | only then does the guard know exactly what runs |
| `glab api`, `glab auth status` (without `--show-token`), `glab version`, help; nothing else | one surface, the REST API, checked properly; `glab issue`, `glab mr` and the rest are refused |
| `--hostname <configured host>` on every `glab api` | without it glab picks a default host the guard cannot see |
| endpoint `projects/<id>` or `projects/<URL-encoded path>`, then a route on the allowlist | one project; no `..`, `//`, encoded dots, URLs or glab placeholders (`:id`, `:fullpath`), which glab fills from the current directory |
| no `DELETE`, no `PATCH`, no headers | deletes are a person's job; a `Sudo:` header impersonates; a token header swaps identity |
| parameters from `-f`, `-F`, the query string and an `--input` file are checked together | a parameter smuggled into the query string counts |
| a key with `project` in it (`target_project_id`, `to_project_id`) must be this project | moves, clones and cross-project links are refused |
| keys with `epic`, `group`, `namespace`, `token`, `sudo`, `_method` are refused | outside one project, change who acts, or turn a POST into a DELETE |
| creating an issue needs the agent label | every agent-made issue is traceable |
| a link needs `target_project_id` = this project and a numeric `target_issue_iid` | both ends inside |
| no line starting with `/` in a description or note, outside a fenced code block | GitLab runs it as a quick action (`/move`, `/relate`, `/close`) |
| PowerShell `glab` is refused with a pointer to Bash | the guard reads Bash syntax only |

Outside the project, three GET reads with no parameters are allowed: `version`, `metadata` (version
and edition, for `/gl-setup`) and `personal_access_tokens/self` (the token's name, scopes and
expiry, never its value).

### Allowed routes

| Method | Routes under `projects/<id>` |
|---|---|
| GET | the project itself; `issues`, `issues/<iid>`, its `notes`, `links`, `related_merge_requests`, `closed_by`, `resource_label_events`; `issues_statistics`; `labels`, `labels/<id>`; `milestones`, `milestones/<id>`, its `issues`; `merge_requests`, `merge_requests/<iid>`, its `closes_issues`, `related_issues`; `search` |
| POST | `issues`, `issues/<iid>/notes`, `issues/<iid>/links`, `labels` |
| PUT | `issues/<iid>` (edit, labels, `state_event` close or reopen), `issues/<iid>/notes/<id>` |
| GET, only with `"ciRead": true` | `pipelines`, `pipelines/<id>`, `pipelines/<id>/jobs`, `pipelines/<id>/test_report`, `jobs/<id>`, `jobs/<id>/trace` |
| POST, only with `"ciRead": true` | `ci/lint` (validate a `.gitlab-ci.yml`; `dry_run` simulates, runs nothing) |

Everything else is refused: settings, members, variables, tokens, deploy keys, hooks, repository
files, moves and clones, merge, approve and rebase; and for CI, running, retrying, cancelling or
deleting a pipeline or a job, CI/CD variables, artifact downloads, runners, schedules and triggers,
even with `ciRead` on.

### CI reads: opt-in per workspace

`ciRead` is `false` by default, so a workspace reads no pipeline data unless `/gl-setup` turned it
on. Only the JSON value `true` counts; `"true"` or `1` is off. Turn it on only in a workspace that
builds in this project's CI and needs to check its own pipelines. Job logs hold whatever a job
printed, so a careless job can leak a secret into them; mask variables in the project's CI settings.
`ci/lint` may need a role above Reporter on some versions; a `403` is reported, never worked around.

Every decision on a GitLab call appends one line to `.claude/gitlab-guard.log`:
`time  tool  ALLOW|DENY  project path  reason`. No issue text, no credentials. Commands that are not
GitLab calls are not logged.

### Why free text is not scanned for references

A description that says "same root cause as other/project#9" acts on nothing in that project.
Refusing it would make the agent unable to write honest issues. Structural fields are different: a
`target_project_id` of another project changes that project, so those are checked. GitLab does add
a "mentioned in" note to an issue the **token can read**; with a project access token that is only
the bound project.

Quick actions are the exception: they look like text and act like commands, so they are checked.

## Test the guard

```bash
python -m unittest discover -s tests -v
```

Or by hand, the way Claude Code calls it:

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"glab api --hostname gitlab.example.com projects/43/issues"},"cwd":"."}' | CLAUDE_PROJECT_DIR=. python hooks/gitlab-scope-guard.py; echo "exit $?"
```

Exit 2 and a message on stderr is a refusal. Exit 0 is an allow.

## Known limitations

- **The hook is not a security boundary.** Anyone who can edit the workspace can edit
  `.claude/gitlab.json` or uninstall the plugin. The project access token is the real wall.
- **The guard reads the shell, not every program.** A Python or Node script that calls GitLab with
  its own HTTP code is not seen. The rules in `CLAUDE.md` forbid it; the token limits it.
- **PowerShell is read coarsely.** A `glab` in command position is refused; text in double quotes
  that only mentions glab is allowed.
- **The route allowlist is fixed in the guard.** A route a new skill needs is added there, with a
  must-allow and a must-block test.
- **Community Edition** has no epics, no native status and only `relates_to` links. The kit uses
  scoped labels (a `phase` type role marks a roadmap phase's parent issue), parent issues and a
  `Depends on #a.` line instead. On CE scoped labels are not exclusive: a status or type change
  adds the new label and removes the old ones in one call. `/gl-setup` detects the edition
  from `GET metadata`; on an Enterprise instance it asks for the tier rather than guess.
- **Token expiry.** Project access tokens expire. `/gl-status` warns 30 days ahead.

## Language

What the agent writes into issues follows `ticketLanguage`, which the wizard proposes from the
project's recent titles and the user confirms. Labels stay ASCII and untranslated. The agent speaks
to the person in the person's language.

## Skills

All skills read [skill-conventions.md](skill-conventions.md) first.

| Command | Does | Writes to GitLab |
|---|---|---|
| `/gl-setup` | the wizard above | the labels you approve |
| `/gl-status` | config summary, narrow reads for connectivity, token and edition, label drift by id, guard log tail | no |
| `/gl-triage` | recent non-agent issues grouped by likely action, missing labels, text that names `#n` with no link, numbered proposals | no |
| `/gl-create` | duplicate search, approval gate, create with agent, type and origin labels, links after approval | one issue, its links |
| `/gl-work` | find the issue from branch, `Refs #n` or merge request; summarise; workflow label on request; sparse notes | a workflow label, rare notes |
| `/gl-signoff` | criteria review, direct yes/no question, close | close, after a yes |
| `/gl-plan` | related work, duplicates, dependencies, plan, optional parent issue, order carried by links | issues and links, after approval |

## Closing needs a direct yes

Closing an issue needs a direct yes from the person, every time. Merged code and green tests are not
a yes. `Closes #n`, `Fixes #n` and `Resolves #n` in a merge request or commit close the issue on
merge without asking, so the kit writes `Relates to #n` and the commit trailer `Refs #n`; `Closes`
is written only after `/gl-signoff` received a yes. If a user sets `requiresApprovalForClose` to
`false` by hand, the skills honour it and say so.

## Wiring into your workflow

[integrating-with-a-workflow.md](integrating-with-a-workflow.md) maps the moments (feature start,
bug-fix start, implementation, release planning, a reported defect, feature end) to skills, with the
condition that keeps a GitLab-disabled workspace unchanged. gitlab-kit names no method; the method
names gitlab-kit.

## Adopting in an existing project

Nothing changes until `/gl-setup` runs. Existing `CLAUDE.md` content is kept; the section is
appended once and replaced on rerun. Existing hooks in `.claude/settings.json` are untouched,
because the guard is registered by the plugin, not by the workspace. Declining or disabling leaves
the project as it was, apart from a `.claude/gitlab.json` that says `"enabled": false`.
