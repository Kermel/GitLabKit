# Conventions every gitlab-kit skill follows

Read this before running any `/gl-*` skill. It is short on purpose.

## 1. Load the config, or stop

Read `$CLAUDE_PROJECT_DIR/.claude/gitlab.json`.

- Missing: tell the user to run `/gl-setup`. Stop.
- `"enabled": false`: say GitLab is disabled in this workspace. Stop.

Take from it: `host` (its host name is HOST below), `projectId` (ID), `projectPath`,
`agentLabel`, `labels`, `issueTypes` (id + name + role), `workflow` (`initialStatusId`,
`activeStatusIds`, their names, `requiresApprovalForClose`, `closeKeyword`), `ticketLanguage`,
`ticketCreationPolicy`, `conventions`, `instance`.

## 2. One plain command per call

Every GitLab call is one `glab api` command, run with the **Bash** tool:

```bash
glab api --hostname HOST projects/ID/issues/12
```

- No `;`, `&&`, pipes, redirections, heredocs or `$( )`. The guard refuses them, and you read the
  JSON yourself anyway.
- Quote every argument that holds `?`, `&`, `[`, `{`, `*` or `$`: `'projects/ID/issues?state=opened'`.
- With `-f` fields and no `-X`, glab sends **POST**. A read with fields says `-X GET`.
- **Long or multi-line text goes in a JSON file.** Write it with the Write tool to the scratchpad,
  then pass it: `glab api -X POST --hostname HOST projects/ID/issues --input <file>`. A file needs
  no shell quoting, so `$`, backticks and quotes in the text are safe. The guard reads the file.
- Never PowerShell for glab, never `curl`, never a GitLab MCP tool. The guard refuses all three.
- `iid` is what people see as `#12`; it is per project and is what every route uses. The global
  `id` is never used in a route.

## 3. Ids are the identity; label names can change

Type and workflow steps are **scoped labels** (`type::bug`, `workflow::doing`). A label can be
renamed in the UI; its id stays. So:

- **Never type a label name from memory**, and do not trust a stored name for a write. The
  config's names are for showing; its **ids** are what you match on.
- **Before a write that sets a label, read its current name by id:**
  `glab api --hostname HOST projects/ID/labels/<id>`. Use the `name` that comes back.
- **A stored name that no longer matches** its id is a rename, not a broken config. Use the
  current name, and say once that `/gl-setup` refreshes the stored names.
- **Changing a status or a type is one PUT that adds the new label and removes the old ones.**
  On Community Edition a scoped label does **not** replace its sibling: measured on a CE 19.1
  project, `add_labels=workflow::review` left the issue with both `workflow::doing` and
  `workflow::review`. Only a paid tier makes scoped labels exclusive. So always send both:

  ```bash
  glab api -X PUT --hostname HOST projects/ID/issues/12 -f 'add_labels=workflow::review' -f 'remove_labels=workflow::todo,workflow::doing'
  ```

  `remove_labels` lists the **current names** of every other configured label of the same kind
  (the other `workflow.statuses` for a status, the other `issueTypes` for a type), whether or not
  the issue carries them. Removing a label an issue does not carry changes nothing, so the same
  call is right on every edition, and it needs no edition check that could be wrong (an Enterprise
  build without a licence behaves like Community Edition). Never touch labels outside that kind.
- **An issue that already carries two labels of one kind** (left by an older version or by hand)
  is fixed the same way the next time its status or type changes; `/gl-triage` lists it.
- Read issues by label with the labels' current names; compare an issue's `labels` with the
  current names of the configured ids.

## 4. Every call names the project

Every route starts with `projects/ID/`. Useful reads, all allowed by the guard:

| Want | Call |
|---|---|
| open issues | `'projects/ID/issues?state=opened&per_page=50'` |
| not created by the agent | `-X GET ... projects/ID/issues -f state=opened -f 'not[labels]=AGENT_LABEL'` |
| created by the agent | `-X GET ... projects/ID/issues -f state=opened -f labels=AGENT_LABEL` |
| recent | `-f updated_after=2026-09-21T00:00:00Z` (compute the date; no relative dates) |
| likely duplicates | `-X GET ... projects/ID/issues -f 'search=word1 word2' -f in=title,description` |
| one issue | `projects/ID/issues/12` |
| its notes | `'projects/ID/issues/12/notes?sort=asc&per_page=100'` |
| its links | `projects/ID/issues/12/links` |
| merge requests that mention it | `projects/ID/issues/12/related_merge_requests` |

`not[labels]` keeps issues with no labels at all, unlike Jira's `labels not in`. Cap at 50 issues
per skill run unless the user asks for more; `--paginate` only when the user wants everything.

## 5. Language of what you write

- Issue titles, descriptions and notes: `ticketLanguage` from the config.
- Labels: as configured, ASCII, never translated.
- Talking to the person: their language, whatever it is.

## 6. Writes are reported, closures are asked

After every create, edit, note, label change, link or close, print one line:
`#n  <web_url>  <what changed>  <why>`. Take `web_url` from GitLab's response; do not build it.
GitLab 19 answers `.../-/work_items/n`, older versions `.../-/issues/n`.

Before closing any issue (`state_event=close`), ask a direct yes/no question and wait. Merged
code, green tests and a finished checklist are not a yes. Only `/gl-signoff` closes.

**The auto-close trap.** `Closes #n`, `Fixes #n` or `Resolves #n` in a merge request or a commit
closes the issue when it reaches the default branch, with no question asked. So:

- merge-request descriptions and commits write `closeKeyword` (default `Relates to #n`);
- commits carry the trailer `Refs #n`;
- a spec names its issue in its header: `Issue: #n`;
- `Closes #n` is written only after `/gl-signoff` received a yes, and only when the person wants
  the merge to do the closing.

## 7. GitLab quick actions are commands

A line in a description or note that starts with `/` (`/close`, `/move other/project`,
`/relate other#3`, `/label`) is run by GitLab as a **quick action**. The guard refuses such a line
outside a fenced code block. Put paths and commands in a code block; never use a quick action
instead of the API call.

## 8. Dependent issues are linked

A backlog must read in order, so an issue that depends on another is linked to it.

- **Link type.** On Community Edition (`instance.blockingLinks: false`) the only type is
  `relates_to`, which has no direction. The order goes into the waiting issue's description, one
  line: `Depends on #a.` With `blockingLinks: true`, use `blocks` / `is_blocked_by` instead.
- **Both ends in the project.** `target_project_id` is ID, always. The guard refuses anything else.
- **Check before linking.** `GET projects/ID/issues/<iid>/links` lists existing links. Do not create
  one that exists in either direction.
- **After approval, one at a time.** Propose links in a table (first, then, why). Create them only
  after the person approves, and report each one: `#a  relates to  #b  <why>`.

```bash
glab api --hostname HOST projects/ID/issues/<b>/links -f target_project_id=ID -f target_issue_iid=<a> -f link_type=relates_to
```

- **A roadmap phase's parent carries the `phase`-role label** (`issueTypes[].role: "phase"`); find
  phase parents by that role, never by a label name. A project without a `phase` role has no phase
  parents to find; say so rather than guess.
- **A parent is a regular issue** (`conventions.parentIssues`); CE has no epics. Its description
  holds the children as an ordered task list (`- [ ] #a`, `- [ ] #b`), and each child relates to it.

## 9. What not to do

- No issue for every small observation. No notes on routine steps.
- No label change because code changed locally.
- No labels or milestones applied on a guess. `conventions` says what the project uses.
- No touching issues that look owned by another workflow unless the user says so.
- Never delete, never merge, approve or rebase a merge request, never move or clone an issue.
  Those are a person's job, and the guard refuses them.
