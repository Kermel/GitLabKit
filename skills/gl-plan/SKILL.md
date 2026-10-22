---
name: gl-plan
description: >
  Plan a piece of work against this workspace's GitLab project: find related issues, duplicates,
  dependencies and open bugs, propose an implementation plan and, if useful, a small issue
  hierarchy, and create it only after the person approves. Use when the user says /gl-plan, "plan
  this in GitLab", "break this down into issues", "what's already in GitLab about X", or at the
  start of a feature when the config's triageTriggers include feature-start or
  implementation-planning.
---

# /gl-plan

Read `${CLAUDE_PLUGIN_ROOT}/docs/skill-conventions.md` first. Planning is read-only until step 6.

## Steps

1. **Load the config** (conventions §1). Note `conventions` (milestones, parentIssues),
   `instance.blockingLinks` and the `issueTypes` roles.

2. **What exists.** Two or three scoped reads on the feature's words, never more:

   ```bash
   glab api -X GET --hostname HOST projects/ID/issues -f state=opened -f 'search=words' -f in=title,description -f per_page=20
   glab api -X GET --hostname HOST projects/ID/issues -f state=opened -f 'labels=<bug label>' -f 'search=words'
   glab api -X GET --hostname HOST projects/ID/issues -f state=closed -f 'search=words' -f order_by=updated_at -f per_page=10
   ```

   The third finds work already done under a similar name. Use the bug label's current name; if
   the project has no bug role, drop that read.

3. **Read the relevant ones** (`projects/ID/issues/<iid>`, `.../links`, `.../notes` when needed):
   acceptance criteria, links, parent, labels, state. Note dependencies and blockers. Everything
   referenced must be inside the project; a `group/other#n` reference is noted, never followed.

4. **Propose the plan.** In the user's language: goal, what existing issues cover, what is new,
   order of work, risks, and which existing issue the work should attach to if any.

5. **Propose the issues, if any.** Only what the plan needs:

   | Project uses | Shape |
   |---|---|
   | parent issues (CE) | one parent issue (only for multi-issue work; a roadmap phase's parent carries the `phase`-role label) whose description is an ordered task list of its children; each child relates to the parent |
   | milestones | the children share the milestone the person names |
   | neither | flat issues |

   Whatever the shape, the **order of work is carried by links plus one `Depends on #a.` line**
   (conventions §8). Show the proposed list as a table: role, title (in `ticketLanguage`), parent,
   depends on, one-line rationale. Use the configured labels only. Do not invent a taxonomy.

6. **Ask, then create.** Any of these needs approval before the first write: more than one issue,
   any parent issue, any change to an existing issue's links or description, any relabelling of
   existing issues (a relabel adds the new label and removes the old ones in one PUT,
   conventions §3). On approval, create each issue through the `/gl-create` steps (duplicate check,
   agent label, origin label `agentAnalysis` or `userRequest`), one write at a time, one report
   line each. Create the parent first; after the children exist, update the parent's description
   with the ordered task list of their `#n` (one `PUT` with `--input`, reported).

   Then link (conventions §8). Every "depends on" in the approved table becomes one link plus the
   `Depends on #a.` line in the waiting issue, created after all the issues exist, both ends inside
   the project. Each child also relates to its parent. Report each link.

7. **Hand the number back.** When the plan came from a spec flow, give the issue `#n` the work
   attaches to, so the spec header can carry `Issue: #n` and the commits `Refs #n`.

8. **Stop at the plan** if the person does not approve. The plan itself is the deliverable; the
   issues are optional.
