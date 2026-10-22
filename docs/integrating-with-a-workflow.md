# Integrating gitlab-kit with a development workflow

gitlab-kit does not know your method. It knows a few moments where a GitLab check helps, and it
has a skill for each. If your workflow, whatever it is called, has named phases, call the skill at
the matching phase. Only when `.claude/gitlab.json` exists in the workspace and says
`"enabled": true`; otherwise do nothing and say nothing.

## Moments and skills

| Moment in your workflow | Config trigger name | Skill | It is |
|---|---|---|---|
| a feature is about to be specified or planned | `feature-start`, `implementation-planning` | `/gl-plan` | read-only until the person approves issues |
| a bug-fix session begins | `bugfix-start` | `/gl-triage`, then `/gl-work` on the matching bug | read-only, then one workflow label on request |
| implementation of an issue starts | (any) | `/gl-work` | adds the doing label if the person says so |
| a release or deployment is being planned | `release-planning` | `/gl-triage` | read-only; lists open and in-review work, never closes anything |
| the person reports a defect, idea or request | (any) | `/gl-create` | one issue, after a duplicate check and, when in doubt, a question |
| a feature is finished | (any) | `/gl-signoff` | asks before closing |
| a session starts | `session-start` | offer `/gl-triage` in one line | nothing unless accepted |
| the person asks | `manual` | any | as the skill says |

`triageTriggers` in `.claude/gitlab.json` lists which of these the person wants offered. Respect
it. A trigger that is not listed is not offered.

## How to wire it

In the file that describes your workflow to the agent (a `CLAUDE.md`, a skill, a phase checklist),
add one line at each phase:

```markdown
Before writing the spec: if `.claude/gitlab.json` is enabled and lists `feature-start`, run `/gl-plan`.
After the feature is complete: if `.claude/gitlab.json` is enabled, run `/gl-signoff`.
```

That is the whole integration. The skills read the config themselves, refuse to leave the project
themselves, and ask before closing anything themselves. Your workflow only says *when*.

## The links an issue carries

| Where | Writes |
|---|---|
| the spec header | `Issue: #n` |
| every commit of the feature | the trailer `Refs #n` |
| the merge-request description | `Relates to #n` (the configured `closeKeyword`) and the spec directory |
| the branch | your workflow's own name; GitLab's `n-slug` form lets `/gl-work` find the issue by itself |

Never `Closes #n` or `Fixes #n` in a commit or merge request by habit: GitLab closes the issue when
it reaches the default branch, and nobody was asked.

## What not to wire

- Do not make GitLab a hard step. A workspace with GitLab disabled must run your workflow unchanged.
- Do not run `/gl-triage` on every session start unless the person chose `session-start`; it is a
  search, and a search every session is noise.
- Do not call `/gl-signoff` automatically at the end of a phase. Call it, and let it ask.
- Do not add your own `glab` calls beside the skills. The skills carry the conventions
  ([skill-conventions.md](skill-conventions.md)); a bare call in a workflow file does not.
- Do not merge, approve or rebase merge requests from the workflow. That stays with the operator.

## Example: a spec-driven flow

A flow with the phases *specify, plan, implement, review, wrap up* would read:

| Phase | Add |
|---|---|
| specify | `/gl-plan` first; write `Issue: #n` into the spec header |
| plan | nothing new; `/gl-work` if the person wants the doing label set |
| implement | commit messages carry `Refs #n` |
| review | nothing |
| wrap up | `/gl-signoff` |

Any other flow maps the same way: find the moment, name the skill, keep the condition.

## A roadmap that lives in GitLab

When the backlog lives in GitLab, a roadmap file becomes a **map**: one line per planned feature,
pointing at its issue, and the detail lives in the issue.

```markdown
- F-12 — Approval step for activities · #34 · M · in progress
```

`F-id — title · #n · effort · status`. Status follows the issue: *opened* with no workflow label
is planned, the doing or review label is in progress, *closed* is done.
