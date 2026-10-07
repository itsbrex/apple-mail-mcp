# #001 Upstream sync + next features (2026-10-07)

Paired summary of `2026-10-07-001-upstream-sync-roadmap.html`. The HTML page
is the decision surface; this file is the plain-text record.

## Findings (verified 2026-10-07)

- Upstream `imdinu/apple-mail-mcp` released **v0.5.0** on 2026-09-14 (PyPI
  0.5.0). Fork `main` already contains it (fork PR #3) plus the post-release CI
  fix `0398b86`.
- Maintainer comments on our open PRs (2026-09-30):
  - **#118** (ty gate) and **#117** (perf): CI approved, "reviewing for the next
    release", both need a rebase onto 0.5.0. `git merge-tree` shows both merge
    cleanly with `upstream/main`.
  - **#116** (write tools): held behind **#107**. Reason 1: `move_email` must
    use the new `resolve_for_identity` mailbox resolver. Reason 2: index
    eviction after a move only happens in the writer instance, so docs must say
    eventual consistency.
- **#107** (morquis, nested mailbox paths + resolver) is a draft with one commit
  (2026-07-17). The design was agreed on 2026-07-31 and 2026-08-16. NFD
  normalization (#120) was folded in on 2026-09-30. No push since July.
- **#112** (iret77): a second fork offers ~20 units. The maintainer accepted
  them. Overlaps: C3 `set_flag`/`set_read_status` vs our `update_email_status`;
  C1 schema v6 vs #107 schema v6; A1/A5 vs #125.
- Unclaimed issues: **#127** (Envelope Index path outside `V10/`), #125 (one
  bad `.emlx` aborts sync; iret77 has a fix). Maintainer owns #122 and the FDA
  family (#123/#124).
- Open PR **#121** (singhgm): tolerate JXA account-lookup failure on index
  reads; no maintainer response yet.
- Versions: fastmcp **4.0.11** GA (we pin `<4`; 3.4.8 patch out 2026-10-04);
  mcp SDK 2.3.0 (we resolve 1.26.0). Upstream CI tests Python 3.11–3.13;
  reporters run 3.14. Our suite: **712 passed on Python 3.14** (temp worktree,
  this session).

## Local state

- WIP committed on `feat/outgoing-mail-compose`: `8aeb0ee` (plans
  `package.json` + dashboard) and `44342a4` (plans scaffold v14 to v32 with
  `.plans-template.json` provenance).
- Local-only branches: `feat/outgoing-mail-compose` (+5 vs main) and
  `codex/mail-ingestion-pages` (+1, Codex worktree).
- `stash@{0}` (pre-PR #3 WIP) is superseded by HEAD.

## Decisions (all pre-selected "approved")

| id | decision | pick | next-best alternative |
|----|----------|------|-----------------------|
| d01 | Back up local-only branches | push both to fork | private git bundle |
| d02 | Stale stash | export patch, drop | keep |
| d03 | Compose onto fork main | fork PR + CI + FF merge | direct FF push |
| d04 | Export branch | rebase, check, review, fork PR | park |
| d05 | #118/#117 | rebase both now | serial rebase |
| d06 | #116 | reply + eventual-consistency docs commit | also carve out `send_email` |
| d07 | Python 3.14 | tiny upstream CI PR | fold into #118 |
| d08 | #107 | offer to co-build resolver | wait 2 weeks |
| d09 | iret77 overlap | comment on #112 | ask maintainer |
| d10 | #121 | tested review | skip |
| d11 | Compose upstream | PR-A now, PR-B/C after #116 | one PR after #116 |
| d12 | Next upstream fix | claim #127 | #125 (collides with iret77) |
| d13 | fastmcp 4 | spike on fork branch | patch to 3.4.8 |
