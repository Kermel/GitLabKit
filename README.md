# gitlab-kit

Project-scoped GitLab issues for Claude Code. **One workspace, one GitLab project, enforced by a
hook.**

A Claude Code plugin, modelled on jira-kit. It works in any repository, with or without
agentic-kit. Nothing in it depends on a particular method or stack. It reaches GitLab only through
the official `glab` CLI and a project access token.

## What is here

| Piece | Where | State |
|---|---|---|
| Deny-by-default scope guard (`PreToolUse` hook on Bash, PowerShell and MCP tools) | `hooks/gitlab-scope-guard.py` | done |
| Workspace config schema | `config/gitlab.example.json` | done, example values |
| Plugin manifest and marketplace | `.claude-plugin/` | done |
| `/gl-setup` wizard | `skills/gl-setup/SKILL.md` | done, run live on a real project |
| File writer behind the wizard (merge config, marked `CLAUDE.md` section) | `scripts/gitlab_setup.py` | done |
| `/gl-status`, `/gl-triage`, `/gl-create`, `/gl-work`, `/gl-signoff`, `/gl-plan` | `skills/*/SKILL.md` | written; status, triage and create driven live, the rest not yet |
| Conventions every skill follows (one plain command, label ids, links, closing) | `docs/skill-conventions.md` | done |
| Documentation | `docs/gitlab-integration.md`, `docs/integrating-with-a-workflow.md` | done |
| Proposed changes to agentic-kit | `docs/agentic-kit-proposal.md` | proposal, not applied |
| Tests | `tests/` | 130, all green |

**Next:** drive `/gl-work` and `/gl-signoff` on a real issue, and the CI reads against a live
pipeline.

## How the guard decides

`glab` runs from the shell, so the guard reads every Bash command the way a shell would. It ignores
commands that do not run `glab`. For those that do, it reads `<workspace>/.claude/gitlab.json` and
refuses anything it cannot **prove** stays inside the configured project.

- **No config, or `enabled: false`:** every GitLab call is refused.
- **`glab` as an argument is data.** `grep glab ...`, a commit message quoting `glab api -X DELETE`,
  a quoted heredoc: not checked. `glab` in command position anywhere (after `&&`, in `$( )`, behind
  `xargs` or `bash -c`) is.
- **One plain command.** No `;`, `&&`, pipes, redirections, `$( )`, `$VAR`, environment prefixes
  or wrappers in a GitLab call.
- **`glab api` only**, with `--hostname <configured host>` and an endpoint under
  `projects/<id>` or the URL-encoded path. Other `glab` commands are refused.
- **A route allowlist.** Issues, notes, links, labels, milestones and merge-request reads. No
  `DELETE`, ever; no settings, members, variables, tokens, hooks, moves or clones; no merge,
  approve or rebase.
- **Parameters** from `-f`, `-F`, the query string and an `--input` file are checked together. A
  project key must be this project; epic, group, namespace, token, `sudo` and `_method` keys are
  refused; a create needs the agent label; a link needs this project as its target.
- **Quick actions.** A description or note line starting with `/` (`/move`, `/relate`, `/close`)
  is run by GitLab as a command, so it is refused outside a code block. Other free text is not
  scanned.
- **No side doors.** `glab` in PowerShell, an HTTP client that names the GitLab host, and every
  GitLab MCP tool are refused.

Every decision on a GitLab call is appended to `.claude/gitlab-guard.log` as
`time, tool, ALLOW|DENY, project, reason`. No issue text and no credentials are logged.

## What the guard is not

It is defense in depth, not a security boundary. The **project access token** is the real wall: a
bot user that is a member of one project, with role Reporter and scope `read_api` (read only) or
`api` (create and edit). The hook can be switched off by anyone who can edit the workspace.

The token is set by the person: `GITLAB_TOKEN` as a user environment variable, or
`glab auth login --hostname <host> --use-keyring` (Windows Credential Manager). Never in chat, never
in a file. A blocked API or permission is a decision of the administrators; ask the AI platform team,
do not work around it.

## Try it

```bash
python -m unittest discover -s tests -v
```

By hand, the way Claude Code calls the hook:

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"glab api --hostname gitlab.example.com projects/43/issues"},"cwd":"."}' | CLAUDE_PROJECT_DIR=. python hooks/gitlab-scope-guard.py; echo "exit $?"
```

## Install

Needs Python 3 and `glab`:

```bash
winget install glab.glab
```

Then, from this folder, on one machine:

```bash
claude plugin marketplace add <path to this repository>
```

```bash
claude plugin install gitlab-kit@gitlab-kit
```

Then run `/gl-setup` in the workspace. It writes `<workspace>/.claude/gitlab.json` and one marked
section in `CLAUDE.md`, creates the labels you approve, and nothing else. Details in
[docs/gitlab-integration.md](docs/gitlab-integration.md).

What the first live run taught, now built in: CE 19 has no epics, no native status and only
`relates_to` links, so type and workflow are scoped labels matched by id; GitLab 19 links issues as
`/-/work_items/n`, so report lines use the `web_url` GitLab returns; and bash decodes `$'...'`, so the
guard decodes it too before looking for quick actions.

**Releasing a change:** raise `version` in `.claude-plugin/plugin.json` and add a `CHANGELOG.md`
entry in the same commit. `claude plugin update` compares that number only.

**Installing at user scope activates the guard in every workspace.** A workspace without
`.claude/gitlab.json` then refuses every `glab` call. That is the intended deny-by-default; enable
GitLab per workspace by running `/gl-setup`.
