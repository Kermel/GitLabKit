# Changelog

Every release raises `version` in `.claude-plugin/plugin.json`. `claude plugin update` compares
that number only, so a change pushed under the old number is never installed.

## 0.3.0 — scoped labels on Community Edition, a phase role, a closing note by default

Three fixes found while using 0.2.0 on a real Community Edition 19.1 project.

- **Scoped labels are not exclusive on Community Edition.** Measured: after
  `add_labels=workflow::review` the issue carried both `workflow::doing` and `workflow::review`.
  Only a paid tier makes a scoped label replace its sibling, and the conventions said otherwise.
  Now every status or type change is **one PUT that adds the new label and removes every other
  configured label of the same kind** (`add_labels=…` with `remove_labels=…`). Always, on every
  edition, not only when `instance.enterprise` is false: removing a label an issue does not carry
  changes nothing, so one path is right everywhere, and an edition check could be wrong (an
  Enterprise build without a licence behaves like Community Edition). `/gl-work` does it;
  `/gl-plan` relabels the same way; `/gl-triage` lists issues that carry two labels of one kind.
- **`phase` type role**, for the parent issue of a roadmap phase (Community Edition has no epics).
  `/gl-setup` offers `type::phase`; tools find phase parents by role. A config that stores such a
  label as `other` keeps working and validates; a rerun proposes `phase`.
- **`/gl-signoff` writes a closing note by default.** The first answer is *yes, with this closing
  note*: at most three lines, drafted and shown before the question: what was done against the
  issue's acceptance criteria (*Done when*), where the evidence is (pipeline, summary file, merge
  request), any debt left. *Yes, without a note* stays possible.

New `tests/test_skill_texts.py` tests the rules that live only in skill text; 8 of its 9 tests
fail on the 0.2.0 files. 130 tests.

## 0.2.0 — opt-in CI reads

**A workspace can read its own pipelines and lint its `.gitlab-ci.yml`, and only when it says so.**

- **Config:** `"ciRead"`, `false` by default. Only the JSON value `true` turns it on; `validate`
  names anything else as a problem. A rerun keeps it.
- **Guard:** with `ciRead` on, `GET` `pipelines`, `pipelines/<id>`, `pipelines/<id>/jobs`,
  `pipelines/<id>/test_report`, `jobs/<id>`, `jobs/<id>/trace`, and `POST ci/lint`. With it off or
  missing, the same routes are refused with a message naming `ciRead`. Never allowed, on or off:
  creating, retrying, cancelling, playing, erasing or deleting a pipeline or a job, CI/CD variables,
  artifact downloads, runners, schedules and triggers.
- **Setup:** `/gl-setup` asks for it on the policy screen; the rendered `CLAUDE.md` section lists the
  CI routes when it is on, and the `validate` summary shows `CI reads: on|off`.

117 tests. Not yet tried against a live pipeline.

## 0.1.0

First release: the jira-kit pattern, ported to GitLab issues on a Community Edition instance.

- **Scope guard** (`hooks/gitlab-scope-guard.py`), a `PreToolUse` hook on Bash, PowerShell and MCP
  tools. GitLab is reached through the official `glab` CLI, so the guard reads shell commands: `glab`
  in command position is checked, `glab` as an argument (grep, commit messages, quoted heredocs) is
  data. A GitLab call must be one plain `glab api --hostname <host> projects/<id>/...` command on a
  method and route allowlist. Refused: DELETE, headers, placeholders, path tricks, other `glab`
  commands, PowerShell `glab`, HTTP clients naming the host, every GitLab MCP tool, foreign project
  keys, epic/group/namespace/token/sudo/`_method` keys, creates without the agent label, links out of
  the project, and quick-action lines in descriptions and notes.
- **`/gl-setup`** with `scripts/gitlab_setup.py`: two facts must agree (project id and URL path),
  edition detected from `GET metadata`, type and workflow as scoped labels matched by id, labels
  created only after approval, a marked `CLAUDE.md` section that keeps everything else byte for byte.
- **Work skills:** `/gl-status`, `/gl-triage`, `/gl-create`, `/gl-plan`, `/gl-work`, `/gl-signoff`,
  sharing `docs/skill-conventions.md`. Closing needs a direct yes; `Relates to #n` and `Refs #n` by
  default, because `Closes #n` closes on merge without asking.
- **Docs**, and a proposal for agentic-kit's GitLab hooks (`docs/agentic-kit-proposal.md`, not
  applied).

Probed live on a real Community Edition 19.1 project before release: 13 labels created through the
guard, `/gl-status` and `/gl-triage` reads pass, `/gl-create` made the first issue, and a call to
another project was refused. Two things the live
run taught are built in: GitLab 19 answers `/-/work_items/n` links, and bash decodes `$'...'`, which
had let a hidden quick-action line past an early guard.

106 tests.
