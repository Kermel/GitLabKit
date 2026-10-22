---
name: gl-triage
description: >
  Read-only review of recent issues in this workspace's GitLab project that the agent did not
  create: new bugs, ideas, requests, and issues missing labels, grouped by likely next action.
  Use when the user says /gl-triage, "what's new in GitLab", "triage the backlog", "anything
  reported", at the start of a feature or bug-fix session, or before release planning when the
  config's triageTriggers include that moment.
---

# /gl-triage

Read `${CLAUDE_PLUGIN_ROOT}/docs/skill-conventions.md` first. **This skill changes nothing by
default.** It reads, groups, proposes. Any change goes through `/gl-create`, `/gl-work` or the
user's explicit instruction, one at a time.

## Steps

1. **Load the config** (conventions §1). Note `agentLabel`, the origin labels and the current
   names of the configured type and workflow label ids (conventions §3; one labels read).

2. **Not ours, recent, open.** Compute the date 30 days ago, then:

   ```bash
   glab api -X GET --hostname HOST projects/ID/issues -f state=opened -f 'not[labels]=AGENT_LABEL' -f updated_after=<date>T00:00:00Z -f order_by=updated_at -f per_page=50
   ```

   Widen to 90 days only if that returns nothing and the user wants history.

3. **Ours, still open.** A second, smaller read so the report can separate them:

   ```bash
   glab api -X GET --hostname HOST projects/ID/issues -f state=opened -f labels=AGENT_LABEL -f order_by=updated_at -f per_page=50
   ```

4. **Read what you need, not everything.** The list already carries each issue's `description`,
   `labels`, `assignees`, `milestone` and `user_notes_count`. Read notes
   (`projects/ID/issues/<iid>/notes`) only when the grouping depends on them.

5. **Group by likely action.** Each issue appears once:

   | Group | Typical signal |
   |---|---|
   | needs clarification | one-line title, no description, no steps |
   | likely duplicate | same words as another open issue; name the pair |
   | candidate for roadmap | idea or feature request, no assignee |
   | ready for implementation | acceptance criteria present, unblocked, no workflow label or the todo label. **No criteria means not ready**, however clear the scope reads: put it under *needs clarification* and say criteria are missing |
   | likely bug needing investigation | carries the bug-role label, or the text describes a failure |
   | no action needed now | done elsewhere, waiting on a person, or informational |

   Issues with an origin label (`source::user-request`, `source::app-feedback`,
   `source::external-bug-report`) are called out by origin.

6. **Missing metadata**, one line per issue: no type label, no labels at all, open for more than 30
   days with no workflow label, an active workflow label but no assignee, **two labels of one kind**
   (two configured workflow labels, or two configured type labels; Community Edition does not stop
   it, conventions §3). Propose the fix as one PUT that keeps the right one and removes the other.

   **Missing links** (conventions §8). For an issue whose description names another `#n`, read its
   links (`projects/ID/issues/<iid>/links`). A named `#n` with no link is one line:
   `#a  names #b in its text but is not linked to it`. A reference to another project
   (`group/project#n`) is only noted, never proposed for a link. Read at most ten issues' links;
   say so if there were more.

7. **Propose, then wait.** End with a numbered action list: *"1. #9 and #8 look like one piece of
   work; link them or close one? 2. #10 has been in workflow::review 14 days; ask the reviewer?
   3. #6 names #7 but is not linked; link them?"* Ask which to do. Do nothing until told. A "yes to
   all" still runs each change as a separate, reported write.

## Output

Groups as short lists: `#n  labels  title (trimmed)  reason`. Then the metadata lines. Then the
numbered proposals. Write the report in the user's language; quote issue titles verbatim. An empty
project gets one line, not a report.
