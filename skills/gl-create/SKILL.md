---
name: gl-create
description: >
  Create one GitLab issue in this workspace's project, after a duplicate check, with the agent
  label, a type label and an origin label, in the project's own language. Use when the user says
  /gl-create, "make an issue", "make a ticket", "file a bug", "capture this as an issue", "add this
  to GitLab", or when the user reports a defect, idea or request that should be tracked and is not
  just thinking aloud.
---

# /gl-create

Read `${CLAUDE_PLUGIN_ROOT}/docs/skill-conventions.md` first.

## Steps

1. **Load the config** (conventions §1). Note `ticketCreationPolicy`, `issueTypes`, `labels`,
   `ticketLanguage`, `conventions`.

2. **Gather.** From the user's words and the current context, settle: role (`bug`, `feature`,
   `task`, `idea`, `debt`), title, description, acceptance criteria, origin, and optionally a
   milestone or a parent issue. Do not ask for what you can infer. Ask for what you cannot.

   | Situation | Role |
   |---|---|
   | possibility worth considering, not planned | `idea` |
   | specific unit of work | `task` |
   | defect or regression | `bug` |
   | user-facing capability | `feature` |
   | knowingly taken shortcut to pay back | `debt` |
   | large multi-issue initiative | a parent issue, and only with approval (step 4) |

   Map the role to an `issueTypes` entry, then to its **current** name by id (conventions §3). No
   entry with that role: say so, offer the closest role that exists. Never invent a label.

3. **Duplicate check.** Pick the two or three most specific words of the title:

   ```bash
   glab api -X GET --hostname HOST projects/ID/issues -f state=opened -f 'search=word1 word2' -f in=title,description -f per_page=10
   ```

   Show up to five hits with `#n`, labels and title. If one plausibly is the same work, ask:
   *use it, or create anyway?* Default to using it.

4. **Approval gate.** Ask before writing when any of these hold: the policy says
   `allowRoutineCreation: false`; it is a parent issue; more than one issue would be created; the
   scope is ambiguous; step 3 found a plausible duplicate. Otherwise state the plan in one line and
   create.

5. **Create.** Write the body to a JSON file in the scratchpad with the Write tool:

   ```json
   {
     "title": "<in ticketLanguage>",
     "description": "<in ticketLanguage>\n\n## Acceptance criteria\n- [ ] ...",
     "labels": "AGENT_LABEL,<current type label name>,<origin label>"
   }
   ```

   ```bash
   glab api -X POST --hostname HOST projects/ID/issues --input <file>
   ```

   - The agent label is mandatory; the guard refuses a create without it.
   - Origin label: `agentAnalysis` when you found the need yourself, `userRequest` when the person
     asked, `appFeedback` or `externalBugReport` when they say that is where it came from.
   - `milestone_id` only when `conventions.milestones` is true and the user named one.
   - No workflow label: a new issue is simply *opened*. Do not add `workflow::doing` here.
   - No line in the description starts with `/` outside a code block (conventions §7).
   - Never `Closes #n` in the description of anything.

6. **If GitLab rejects the create**, the error names the field. Fix from the message, say what you
   changed, and retry once. Do not guess a value the message did not offer.

7. **Report.** `#n  <web_url>  created <role> "<title>"  because <reason>`.
   Use the `iid` and `web_url` from the response; never build the URL.

8. **Link dependencies** (conventions §8). If the new issue depends on an existing one, or an
   existing one depends on it, or step 3 found related work, propose the links in one table:
   first, then, why. Create them only after the person approves, and report each one. No
   dependency, no link: do not link for decoration.
