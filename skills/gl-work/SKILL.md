---
name: gl-work
description: >
  Trace implementation work against its GitLab issue: find the active issue from the branch, the
  commits or the user's words, summarise its acceptance criteria and blockers, mark it as started
  when the user starts on it, and keep it current with the few facts that matter. Use when the
  user says /gl-work, "which issue is this", "start on #12", "update the issue", "what does the
  issue say", or names an issue number while working.
---

# /gl-work

Read `${CLAUDE_PLUGIN_ROOT}/docs/skill-conventions.md` first. This skill never closes an issue;
that is `/gl-signoff`.

## Steps

1. **Load the config** (conventions §1). Note `workflow.activeStatusIds`, `workflow.initialStatusId`
   and `closeKeyword`.

2. **Find the issue.** In this order:
   - a number the user named (`#12`, `12`, or a URL of **this** project ending in
     `/-/issues/12` or `/-/work_items/12`);
   - the current branch: `git branch --show-current`. GitLab's own branch names start with the
     iid (`12-login-timeout`); a `feature/NNN-slug` branch carries a spec number, not an iid, so
     read the spec's `Issue: #n` header instead;
   - the last few commits: `git log -5 --format=%B`, looking for a `Refs #n` trailer;
   - merge requests of the branch:
     `glab api -X GET --hostname HOST projects/ID/merge_requests -f source_branch=<branch> -f state=opened`,
     then `projects/ID/merge_requests/<iid>/closes_issues` and `related_issues`;
   - a scoped search on the feature's words (conventions §4).

   If several fit, list them and ask. If none fit, offer `/gl-create`. A URL or reference to
   another project (`group/other#3`) is outside this workspace: say so and stop.

3. **Read it.** `projects/ID/issues/<iid>`, and its notes when `user_notes_count` is above zero
   (`'projects/ID/issues/<iid>/notes?sort=asc&per_page=100'`), and its links. Summarise in the
   user's language: acceptance criteria (the task list in the description), state, current
   workflow label, blockers named in notes, linked issues, `Depends on` lines, assignee, milestone.

4. **Mark as started, only when asked.** If the user's instruction means "I am starting this" and
   the issue carries no active workflow label:
   - read the current names of every label in `workflow.statuses` by id
     (`projects/ID/labels/<id>`, one call each);
   - one PUT that adds the first of `workflow.activeStatusIds` and removes all the others
     (conventions §3; Community Edition keeps both otherwise):
     `glab api -X PUT --hostname HOST projects/ID/issues/<iid> -f 'add_labels=<doing name>' -f 'remove_labels=<every other status name, comma-separated>'`;
   - report the labels the response says the issue now carries. More than one workflow label
     left: say so, it means a name was stale.

   A move between two steps (doing to review, or back to todo) follows the same path when the
   user asks: add the target, remove every other status label. A change of type (bug to task) is
   the same with `issueTypes`, and only when the user asks. Closing is refused here: point to
   `/gl-signoff`. An issue that is *closed* is not reopened without the user saying so
   (`-f state_event=reopen`, reported).

5. **Keep it current, sparingly.** Update the issue when a material fact changed: scope narrowed or
   widened, an acceptance criterion turned out wrong, a blocker appeared or cleared. One note per
   material change, in `ticketLanguage`, with the fact and its consequence:

   ```bash
   glab api -X POST --hostname HOST projects/ID/issues/<iid>/notes --input <file with {"body": "..."}>
   ```

   Description edits (`-X PUT ... --input` with `description`) only for corrections the user
   agreed to. No progress notes for routine steps, builds or commits.

6. **Link commits and merge requests** only by text:
   - commit messages end with the trailer `Refs #n`;
   - a merge-request description says `closeKeyword #n` (default `Relates to #n`), **never**
     `Closes #n` or `Fixes #n`, which close the issue on merge without asking (conventions §6);
   - the spec header carries `Issue: #n`.

   The kit never creates, merges, approves or rebases a merge request; the operator does.

7. **Report** every write in one line (conventions §6).
