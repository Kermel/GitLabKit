---
name: gl-status
description: >
  Show this workspace's GitLab binding and prove it works with narrow reads. Use when the user
  says /gl-status, "is GitLab connected", "which GitLab project is this", "show the GitLab
  config", or before any other GitLab work when you are unsure the workspace is set up.
---

# /gl-status

Read `${CLAUDE_PLUGIN_ROOT}/docs/skill-conventions.md` first. Read-only: this skill writes nothing
to GitLab.

## Steps

1. **Config.** Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/gitlab_setup.py" validate "$CLAUDE_PROJECT_DIR"`.
   Show its summary. If it exits 1, show the problems and suggest `/gl-setup`.
   If there is no config, say so and stop.

2. **Connectivity, narrowly.** `glab api --hostname HOST projects/ID`.
   Success proves the host, the token's access to the project, and the guard letting a scoped
   call through. Check that `path_with_namespace` equals `projectPath`; a different path means the
   project was moved or renamed: one line, *"rerun /gl-setup"*. An error is reported verbatim with
   the likely cause: `401` no usable token, `404` wrong id or the token cannot see the project,
   `403` the role is too low.

3. **Token.** `glab api --hostname HOST personal_access_tokens/self`. Report `name`, `scopes` and
   `expires_at`, nothing else. `read_api` only: say writes will fail. Expiry within 30 days: say so.

4. **Instance.** `glab api --hostname HOST metadata`. A `version` or `enterprise` different from
   `instance` in the config is one line: *"GitLab is now X; rerun /gl-setup to detect features"*.

5. **Drift.** `glab api --hostname HOST 'projects/ID/labels?per_page=100'`. **Compare by id**
   with `issueTypes` and `workflow.statuses`. A configured id the project no longer has is drift,
   one line each: *"label 2023 (workflow::doing) is gone; rerun /gl-setup"*. The same id under a
   different name is a **rename**: one line, *"labels renamed, for example workflow::doing is now
   workflow::in-progress; the config still works, /gl-setup refreshes the names"*. Do not list every
   renamed label.

6. **Guard log.** If `.claude/gitlab-guard.log` exists, show the last ten lines and the count of
   `DENY` lines. A run of denies is worth a sentence about why.

7. **Breadth.** The token's reach cannot be read without listing projects, and this skill never
   lists projects. If `name` or the person says it is a personal token, one line: the token reaches
   more than this workspace needs, and the hook is the only per-workspace fence; a project access
   token is the least privilege.

## Output

One screen: the summary, one line each for connectivity, token and instance, drift lines if any,
the log tail. No issue reads.
