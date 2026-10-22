# Proposal: let agentic-kit call gitlab-kit at the same moments as jira-kit

Status: **proposal, not applied.** Written against agentic-kit 1.60.1 (commit `c8ca25e`). The kit owner approves each change separately.

## The idea in one paragraph

Today the workflow's ticket hooks name Jira: they act when `.claude/jira.json` is enabled and call
`/jira-*`. The proposal makes them name **the issue tracker**: whichever of `.claude/jira.json` or
`.claude/gitlab.json` is present and enabled (a workspace binds at most one; if both are enabled,
stop and ask). The moments stay exactly the same. Only the file, the skill prefix and the shape of a
reference change:

| | Jira on | GitLab on |
|---|---|---|
| config | `.claude/jira.json` | `.claude/gitlab.json` |
| skills | `/jira-plan`, `/jira-work`, `/jira-create`, `/jira-signoff`, `/jira-triage`, `/jira-status`, `/jira-setup` | `/gl-plan`, `/gl-work`, `/gl-create`, `/gl-signoff`, `/gl-triage`, `/gl-status`, `/gl-setup` |
| a reference | `KEY-n` | `#n` |
| where the spec names it | the `**Feature Branch**` line | a header line `Issue: #n` |
| commits | carry `KEY-n` | carry the trailer `Refs #n`; never `Closes #n` or `Fixes #n` |
| a phase | an epic `KEY-epic` | a parent issue `#n` (CE has no epics), or a milestone if the project uses them |
| an unscheduled idea | a Jira Idea | an issue with the idea-role label (`type::idea`) |
| priority | Jira priority | the project's own convention; none by default |
| the one-time sweep | `docs/jira-sweep.md` | the same document, read with this table |

Everywhere below, *the tracker* means that pair, and *on* means its config is present and enabled.

## Changes

### 1. `project-skills/speckit-flow/SKILL.md`

Lines 160–170. Replace:

> with Jira **on**, its ticket **and every related ticket** (same epic, same area labels, linked or
> named in it), `ROADMAP.md` only for its phase; with Jira **off**, its roadmap entry …
>
> **Jira — only if `.claude/jira.json` is enabled and its `triageTriggers` list `feature-start`;
> otherwise skip and say nothing.** Run `/jira-plan`, write the key it finds or creates on
> `spec.md`'s `**Feature Branch**` line, and from then on every commit message of the feature
> carries it. The ticket moves to active only through `/jira-work` when the operator says so;
> nothing else in the flow touches Jira.

with:

> with the tracker **on**, its ticket **and every related ticket** (same epic or parent issue, same
> area labels, linked or named in it), `ROADMAP.md` only for its phase; with the tracker **off**,
> its roadmap entry …
>
> **Tracker — only if `.claude/jira.json` or `.claude/gitlab.json` is enabled and its
> `triageTriggers` list `feature-start`; otherwise skip and say nothing.** Run `/jira-plan` or
> `/gl-plan`. Write the reference it finds or creates into `spec.md`: Jira, the key on the
> `**Feature Branch**` line; GitLab, a header line `Issue: #n`. From then on every commit message of
> the feature carries it (GitLab: the trailer `Refs #n`, never `Closes #n`). The ticket moves to
> active only through `/jira-work` or `/gl-work` when the operator says so; nothing else in the flow
> touches the tracker.

Line 299. Replace *"(with Jira on, a ticket created as it comes)"* with *"(with the tracker on, a
ticket created as it comes, through `/jira-create` or `/gl-create`)"*.

### 2. `project-skills/manage-roadmap/SKILL.md`

Lines 13–19. Replace the Jira paragraph with:

> **Where the detail lives depends on one fact — is an issue tracker bound
> (`.claude/jira.json` or `.claude/gitlab.json` present and enabled)?** With the tracker **on**,
> `ROADMAP.md` is a **map** (template Shape A) and the tracker is the backlog: every planned
> feature, idea and debt item is a ticket carrying **everything needed to start it**, condensed, so
> a feature starts from the ticket alone; the roadmap line is `F-id — title · KEY-n · effort ·
> status` with Jira and `F-id — title · #n · effort · status` with GitLab. Titles and area labels
> must let an agent understand a ticket without opening it. With the tracker **off**, the roadmap
> carries the detail itself (Shape B) with a Parking Lot. A project moving from off to on runs the
> one-time sweep in the kit's `docs/jira-sweep.md` (for GitLab, read it with the mapping table in
> that document's header).

Line 43: *"with Jira on, create the tickets first (an epic per phase, a ticket per feature; …)"* →
*"with the tracker on, create the tickets first (an epic per phase with Jira, a parent issue per
phase with GitLab; a ticket per feature; …)"*.

Line 52: *"With Jira on, a scope or priority change is made **in the ticket**"* → *"With the tracker
on, …"*.

Lines 59–61: *"With Jira on, then read the open tickets under that phase's epic, and anything
`priority = High`"* → *"With the tracker on, then read the open tickets under that phase's epic or
parent issue, and anything the project marks as high priority"*.

Lines 74–82: *"**Jira on** … becomes a ticket through `/jira-create` … type by role (Idea for
parked), the phase epic as parent …"* → *"**Tracker on** … becomes a ticket through `/jira-create`
or `/gl-create` … type by role (Idea for parked; GitLab: the idea-role label), the phase epic or
parent issue as parent …"*. *"**Jira off:**"* → *"**Tracker off:**"*.

### 3. `project-skills/manage-roadmap/references/roadmap-template.md`

Line 4: *"is `.claude/jira.json` present and enabled?"* → *"is an issue tracker bound
(`.claude/jira.json` or `.claude/gitlab.json` present and enabled)?"*

Shape A heading: *"Jira on"* → *"Tracker on"*. In the template body:

```markdown
## Phase N: <name> · `KEY-epic` (Jira) / `#n` parent issue (GitLab) — <n>% (<done>/<total>)
- **FN.2 — <title> · `KEY-n` or `#n` · <S/M/L> · <Not started | In progress (`specs/NNN-slug/`)>**
```

Shape A rules: *"an unscheduled idea is a Jira Idea"* → *"an unscheduled idea is a Jira Idea, or a
GitLab issue with the idea-role label"*. Shape B heading: *"Jira off"* → *"Tracker off"*.

### 4. `project-skills/post-implement/SKILL.md`

Lines 79–82: *"**With Jira on**, new debt is a ticket first … (`/jira-create`; severity →
priority) … debt paid down goes to `/jira-signoff`"* → *"**With the tracker on**, … (`/jira-create`
or `/gl-create`; severity → priority where the project uses priorities) … debt paid down goes to
`/jira-signoff` or `/gl-signoff`"*.

Lines 97–100: *"**With Jira on the roadmap is a map**"* → *"**With the tracker on the roadmap is a
map**"*; *"With Jira off"* → *"With the tracker off"*.

Lines 112–114. Replace:

> 5. **Jira — only if `.claude/jira.json` is enabled and `spec.md` names a ticket; otherwise skip
>    and say nothing.** Run `/jira-signoff` for it, last.

with:

> 5. **Tracker — only if `.claude/jira.json` or `.claude/gitlab.json` is enabled and `spec.md` names
>    a ticket (`KEY-n` on the Feature Branch line, or `Issue: #n`); otherwise skip and say nothing.**
>    Run `/jira-signoff` or `/gl-signoff` for it, last. It asks the operator before any terminal
>    status; never close a ticket because the feature merged or the suite is green. With GitLab,
>    check that no merge request of the feature says `Closes #n`, which would close it on merge.

### 5. `bootstrap/SKILL.md`

Step 1c (lines 123–130). Replace with:

> 1c. **Offer an issue tracker, never impose one.** If `/jira-setup` (the `jira-kit` plugin) or
>    `/gl-setup` (the `gitlab-kit` plugin) is available, ask once: *bind this repository to one Jira
>    project, one GitLab project, or neither?* Offer only what is installed. On a choice, run its
>    setup skill — it writes `.claude/jira.json` or `.claude/gitlab.json`, a marked `CLAUDE.md`
>    section, and the scope guard comes with the plugin. On no, or with no plugin, do nothing: the
>    tracker lines in `speckit-flow`, `manage-roadmap` and `post-implement` act only when one of those
>    files exists, so they stay inert until someone binds the project later. **Bound from day one,
>    the roadmap takes Shape A** (a map; the backlog and every feature's detail live in the tracker)
>    and the project settles its area labels in `CLAUDE.md`. A project bound later, with a markdown
>    backlog, runs the one-time sweep in `docs/jira-sweep.md`.

Line 165 (the final checklist): *"Jira: bound (`/jira-status` …), declined, or no plugin — say
which."* → *"Issue tracker: Jira bound (`/jira-status` answers with one narrow read), GitLab bound
(`/gl-status` likewise), declined, or no plugin — say which."*

### 6. `docs/jira-sweep.md`

No rewrite. Add one paragraph after the title:

> **GitLab.** The same sweep works with gitlab-kit. Read it with the mapping table in
> `docs/agentic-kit-proposal.md` of gitlab-kit (or its copy here): `/gl-*` for `/jira-*`, `#n` for
> `KEY-n`, a parent issue per phase for an epic, the idea-role label for a Jira Idea. Check the
> project's labels with `/gl-status` before the batch, not the config. The kit writes `#n` back into
> each live source row.

A later, separate step could rename the file to `tracker-sweep.md`; not proposed now, because the
roadmap and two skills link the current name.

## What this does not change

- No moment is added or removed; a workspace with no tracker runs the workflow unchanged.
- jira-kit and its config are untouched; a Jira workspace reads the same as before.
- Merge, approve and rebase stay with the operator in both trackers.

## How to check after applying

`grep -rn "jira" project-skills bootstrap docs` in agentic-kit should show only lines that name Jira
next to GitLab, the jira-kit skill names, and `docs/jira-sweep.md`.
