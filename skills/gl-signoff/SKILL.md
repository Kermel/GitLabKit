---
name: gl-signoff
description: >
  Close out work on a GitLab issue: summarise what was built, tested and left open against the
  issue's acceptance criteria, then ask the person directly before closing it. The only gitlab-kit
  skill allowed to close an issue or to write a closing keyword. Use when the user says
  /gl-signoff, "close the issue", "mark #12 done", "we're finished with #12", or when a feature
  ends and its issue is still open.
---

# /gl-signoff

Read `${CLAUDE_PLUGIN_ROOT}/docs/skill-conventions.md` first.

## The rule

Closing needs a direct **yes** from the person, in this conversation, for the specific issue.
Merged code is not a yes. Green tests are not a yes. A ticked task list is not a yes. If
`workflow.requiresApprovalForClose` is `false` in the config, you still say what you are about to
close before doing it.

## Steps

1. **Load the config** (conventions §1).

2. **Identify the issue(s).** As in `/gl-work` step 2. Every issue must be in this project.

3. **Read and compare.** `projects/ID/issues/<iid>`, its notes and its links. List each acceptance
   criterion with one of: met (how you know), not met (what is missing), not verifiable here (why).
   Add: what was implemented, what was tested and how, remaining risks, open linked issues, and any
   merge request (`.../related_merge_requests`) still open.

   **Watch for the auto-close trap.** If an open merge request or a commit on its way to the
   default branch says `Closes #n`, `Fixes #n` or `Resolves #n`, the issue will close itself on
   merge. Say so; the person decides whether that is wanted.

4. **Ask.** One question per issue, with `AskUserQuestion`, in the user's language, shaped like:

   > #11 *Login times out* appears ready to close. Criteria met: 3 of 3. Tests: 86 passing, guard
   > run by hand. Open risk: none recorded. Open merge request: none. Close it?

   Options: yes; no; *yes with a closing note* if that is the project's habit. Wait.

5. **On yes.** If the person asked for a closing note, add it first, in `ticketLanguage`, three
   lines at most (`POST .../notes --input`). Then:

   ```bash
   glab api -X PUT --hostname HOST projects/ID/issues/<iid> -f state_event=close
   ```

   The closed state replaces the workflow label's meaning; leave the label as it is.

   If the person wants the **merge** to close the issue instead, this is the one place where
   `Closes #n` may be written into the merge-request description, and only the person edits or
   merges the merge request.

6. **On no or on silence.** Do nothing to the issue. Offer to record the remaining items as a note,
   and only do that if told.

7. **Report.** `#n  <web_url>  closed  approved by the user in this session`.
   If the response's `state` is not `closed`, say so.
