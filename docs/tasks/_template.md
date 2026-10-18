# Task: <short name>

<!-- The lead writes one of these per delegated task, commits it (e.g. docs/tasks/<date>-<name>.md) and points the
     builder at it. A tight spec is the single biggest factor in how fast a builder finishes: exact files,
     exact cases, exact done-criteria. Vague specs produce 25 minutes of exploring before any code. -->

**Assigned to:** agy  **Lead / reviewer:** claude  **Second review:** codex (read-only)
**Branch:** `feat/<name>`  **Worktree:** `../<repo>-wt-agy`

## Goal
One or two sentences: what the user can do afterwards that they can't today.

## Files you may touch (nothing else)
- `src/...`
- `tests/...`

## Runtime boundary
Where each piece runs (server / browser / build time / CLI) and which config it may read. Missed boundaries are a
spec gap, not an agent gap.

## Test cases (write these first, make them fail, then implement)
1. ...
2. ...
3. Edge: ...

## Seams
Leave `// HOOK: <what> (wired by lead)` at <place> instead of editing <file the lead owns>.

## Done when
- [ ] All cases above pass; full suite passes 3 runs in a row; typecheck clean.
- [ ] Commit on `feat/<name>` (no push).
- [ ] `scripts/collab.sh handoff agy claude "feat/<name> · <done> · <test result> · <anything unsure>"`
- [ ] `scripts/collab.sh release agy`

## Don'ts
- No new dependencies. No changes outside the file list. No background commands. One command per call.
