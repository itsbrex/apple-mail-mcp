# docs/plans/

Interactive, self-contained HTML plan/decision pages — one file each,
offline-ready, approve/reject/edit-able, numbered per repo.

## Browse

```bash
bun run plans            # interactive picker (fzf if installed, else numbered)
bun run plans latest     # open the newest plan (highest #seq), or an app page edited after it
bun run plans <substr>   # open first plan whose filename matches <substr>
open docs/plans/index.html   # dashboard (auto-regenerated each session; also https://<appName>.localhost/plans/)
```

(No `package.json`? Use `bun scripts/plans.mjs …` — or `node scripts/plans.mjs …`
if bun isn't installed — or the global `claude-plans` command — same behavior.)

## Create

```bash
bun run plans new <slug> --title "Title" --source "where this came from"
```

Stamps `YYYY-MM-DD-NNN-<slug>.html` from `.plan-template.html` with the next
sequence number and this repo's accent color, then rebuilds the dashboard.
Fill in the thesis paragraph and `PLAN_ITEMS` (see `DESIGN.md`).
Both stock and Mono use the mobile review flow: section cards, one decision at
a time, Hold / Change / Approve, full source text, local progress and retryable
Send. Exporting a copy does not claim delivery. Only a valid inbox receipt does.

Since v16 stamping is context-aware (a title or source containing quotes or
tags can neither break nor inject into the page), `plans new` takes a sequence
lock so two sessions never mint the same `#NNN`, and every page carries a
random submission token the decision listener must see (see `DESIGN.md`,
"Receiving decisions"). Tests: `node --test ~/.claude/templates/plans/tests/*.test.mjs`.

Plan pages carry a 14-entry theme system (v39). New viewers start on
**Mono**, and a theme saved under `plan-ui` always wins. **Auto** stays in the
list and resolves to Cresa goldenrod on dark systems, paper on light. **Cresa
dark** uses the Cresa skills' dark tokens (`#0A0A0A` page, `#161616` cards,
Goldenrod `#FFB600`). **Repo accent** restores the stamped per-repo color.
A persisted Motion toggle sits beside the theme button. Both live on the
toolbar and are shared across the browser origin via the `plan-ui`
localStorage key; repos on the shared hub hostname share these UI preferences.
Stock plans honor the OS reduced-motion preference as of v29.

## Mobile review and device testing (v45)

Stock and Mono share safe-area layouts, touch-sized controls, readable phone
inputs, reduced motion, and modal focus loops. Closing a dialog restores focus
without moving the page. Completed-decision confirmation returns to Send when
auto-advance has replaced the original approval button. Existing authored pages
and saved decisions are preserved by the normal provenance upgrade guards.

```bash
bun run plans mobile-test --url http://MAC_LAN_IP:5173 --out ./artifacts/mobile
```

This delegates to AppKit's reusable physical Safari harness. Keep the phone
connected and unlocked; use a phone-reachable URL and an isolated test fixture.
The harness saves device evidence and closes its own session. It needs no Xcode
project or signed runner app. See
`~/.claude/templates/appkit/docs/MOBILE-DEVICE-TESTING.md` for custom flows,
one-time Safari prerequisites, and separate VoiceOver/software-keyboard checks.

## App skeletons — owned by appkit, not by this folder

```bash
bun run plans app <slug> [--title "Title"] [--badge "TAG"] [--dest dir] [--recipe workspace|records|qa-review|review|changes]
appkit new <slug> --recipe workspace          # the same thing, direct
```

`plans app` forwards to **appkit** (`~/.claude/templates/appkit`), the canonical
source for single-file HTML apps. appkit composes the app from named parts
instead of copying one giant template, and records provenance in
`<repo>/.appkit/lock.json` so the app can be upgraded later:

```bash
appkit recipes                    # what each recipe ships
appkit status                     # is an upgrade available for this repo's apps?
appkit diff apps/<slug>.html      # preview it — writes nothing
appkit migrate apps/<slug>.html   # apply it via 3-way merge, keeping your edits
appkit doctor                     # integrity, drift, and context-hygiene checks
```

Five recipes are available:

- **`workspace`** (default): file, drag and paste intake; one scroll region;
  source sheet; copy, download and offline ZIP export.
- **`records`**: searchable and sortable records, grouped board, phone cards,
  record details and CSV export. Empty fields follow the current data policy.
- **`review`**: evidence cards/table, source details, filters and JSON/CSV export.
  Read-only report with System, Light and Dark themes.
- **`qa-review`**: screenshot intake, carousel, annotations, saved notes and
  verdicts, portable HTML and JSON exports.
- **`changes`**: contribution charts, commit cards, branches, local decisions
  and JSON export. No listener or remote writes.

AppKit keeps Geist, Cresa goldenrod and paper palettes; phone controls use the
system font. Sheets respect safe areas, controls support touch and keyboard,
and OS reduced motion takes priority. See `appkit recipes` for exact
capabilities. The Records and Changes fallback files are generated from the
same recipes with `node ~/.claude/templates/appkit/tools/build-plans-mirrors.mjs`.

`--template <name>` still uses the old copy-a-file path for named variants that
have not been ported to a recipe yet. `--template changes` forwards to the
Changes recipe. As of hook v9
this folder no longer receives `.app-template*.html` copies; if your repo still
has them, they are leftovers — `appkit doctor` lists them.

## Where pages open (v17 plans hub)

Every registered repo is served at `https://<appName>.localhost/plans/` by one
always-on Bun process (`~/.claude/plans-hub/hub.ts`, launchd agent
`sh.claude.plans-hub`, ~35 MB total for any number of repos) behind the
portless proxy. `bun run plans latest` opens that URL when the hub answers and
falls back to `file://` otherwise. Decisions submitted from a page land in
`~/.claude/plans-hub/inbox/<appName>/<slug>-<seq>.json`; Claude waits for them
with `bun run plans wait <slug>` (no per-session listener).

```bash
bun run plans hub status        # hub, agent, portless, this repo's route
bun run plans hub install       # once per machine (launchd user agent, no sudo)
bun run plans hub register      # done silently by the SessionStart hook each session
bun run plans wait <slug>       # block until the reader submits; prints the inbox path
```

The hook registers the repo (`portless alias <appName> <hubPort>`, a static
route with no process) and suffixes `appName` with `-2` if another repo already
owns it. Without portless or the agent, pages simply keep opening from
`file://` with the JSON download fallback.

## From your phone (v19 remote + notify)

Turn remote access on once per machine and the hub answers a tunnel host with
a keyed, path-prefixed mirror of every repo: `/` lists what is waiting on you,
`/<appName>/plans/<file>` (no `.html`; the old `.html` form redirects) is the
page itself, and Submit posts back to the same origin. `bun run plans wait <slug>` then texts you the link.

```bash
bun run plans hub remote on --provider cloudflare --tunnel-name plans-hub --hostname plans.cresa.dev
# Existing permanent hostname on this machine. Keep its current tunnel and key.
# Optional new setup: --provider tailscale is private; funnel/ngrok/Cloudflare are public.
bun run plans hub notify set --channel imessage --to <your iMessage handle>
bun run plans notify --test                           # get the link on your phone now
bun run plans hub status                              # remote + notify lines at the bottom
```

Details, security model and the per-page ENDPOINT rewrite: `DESIGN.md`
("Reviewing from your phone").

## Publish to cresa.one (v31)

With a publish Site set, `bun run plans wait <slug>` first copies the plan to
that Site. It then checks the link card and texts you the Site link, for
example `https://plans.cresa.one/<appName>/003-<slug>` (links never end in
`.html`; the `.html` URL still opens the same page). If the publish
fails, `wait` exits with code 3 and texts nothing.

```bash
bun run plans hub publish set --site plans --allow you@example.com   # once per machine
bun run plans publish <slug> [--notify]   # publish one plan now (no wait)
bun run plans hub publish status          # config, live access mode, submit route
```

The Site is restricted to the allowed emails. Link cards stay public. Submit on
the Site copy reaches Claude through the Site's `/_hub` proxy route. The
checklist and rules are in `DESIGN.md`, under "Done means published, checked,
and texted" and "Publishing to a cresa.one Site".

## Serving apps (portless — REQUIRED, no raw ports)

```bash
bun run plans serve <command…>            # e.g. bun run plans serve bun web/server.ts
bun run plans serve --name api <command…> # rare: extra name for a second server
```

Any server that backs an HTML page/app in this repo MUST be started through
`plans serve`, which wraps [portless](https://www.npmjs.com/package/portless):

- **One name per repo, created once.** `plans.config.json` carries `appName`
  (auto-derived from the repo folder on first use; edit it once to taste, then
  commit). Every HTML page/app in the repo reuses the SAME name — pages are
  distinguished by *route*, never by port.
- **Stable URL, zero port conflicts.** The app is always at
  `https://<appName>.localhost`. portless injects a free `PORT` (plus `HOST`
  and `PORTLESS_URL`) into the child, so two repos — or a crashed old
  process — can never collide with `EADDRINUSE` again.
- **Server contract:** listen on `Number(process.env.PORT || 0)` (0 = ephemeral
  fallback for direct runs), bind `process.env.HOST` when set, and when
  auto-opening a browser prefer `process.env.PORTLESS_URL`. NEVER hardcode a
  port number in code, scripts, or docs.
- **Safe replacement:** re-running replaces only the exact app hostname under
  the active proxy's TLD. `--keep` refuses replacement. If the previous owner
  cannot shut down gracefully within five seconds, the wrapper exits without
  starting another server; it never force-kills an owner and leaves its detached
  server behind.
- **package.json:** wire app scripts through the wrapper, e.g.
  `"web": "bun scripts/plans.mjs serve bun web/server.ts"`.
- Cross-service refs: `portless get <name>`. No portless installed? The wrapper
  warns and falls back to a direct run on an ephemeral port.

## Convention

- One plan = one `*.html` file: `YYYY-MM-DD-NNN-short-title.html`. `NNN` is the
  repo-monotonic sequence — highest number is always the latest plan.
- `plans.config.json` holds the repo's randomized accent color, `nextSeq`, and
  the portless `appName`. Commit it; it keeps every machine's plans cohesive
  and every machine's app URL identical.
- Every page is interactive: ✓ approve / ✗ reject / double-click-edit each
  decision, then **Submit to Claude** (localhost listener, JSON download
  fallback). Decisions persist in `localStorage`.
- `DESIGN.md` holds the visual system + the decision-item contract.
- Pages are fully self-contained (inline CSS/JS, system fonts): they open from
  `file://` with no server and no build step.

This folder + `scripts/plans.mjs` are auto-scaffolded and version-upgraded from
`~/.claude/templates/plans/` by a SessionStart hook. Hook-owned files:
`plans.mjs`, `.plan-template.html`, `DESIGN.md`, `README.md`, `index.html`.
Plan pages themselves are never touched. Opt a repo out with an empty
`.no-claude-plans` file at its root.

Since v15 the hook also records provenance in `.plans-template.json` (commit
it), backs up any file it replaces to `~/.claude/backups/plans/`, and never
overwrites a copy that has been customized — either because that manifest no
longer matches the files, or because an empty `.no-claude-plans-upgrade` sits
at the repo root. Inspect or drive that explicitly when you want to:

```bash
node ~/.claude/templates/plans/manage-plans.mjs status "$PWD"     # current / upgrade-available / diverged
node ~/.claude/templates/plans/manage-plans.mjs upgrade "$PWD" --expect-source <sha256 from status>
```

`adopt` (record provenance for an exact-match copy) and `install` (absent files
only) exist too; the manager refuses Git WIP, symlinks, and custom forks.

App skeletons are **not** hook-owned — see `~/.claude/templates/appkit/` and its
`docs/ARCHITECTURE.md` for why that split exists.

## QA screenshot reviewer

`bun run plans app qa-review --recipe qa-review --title "QA Reviews"` creates one
offline app for every review run. Add captures with
`appkit qa add apps/qa-review.html --manifest receipts.json --id <unique-run-id>`.
Carousel, notes, pass/issue status, run progress, and portable exports are included.
Details: `~/.claude/templates/appkit/docs/QA-REVIEW.md`. Existing startup-hook
delegation discovers this recipe without copying template internals into projects.

## v30 guarded maintenance

Startup reads the version from canonical `plans.mjs`; managed copies and their
provenance now report the same version. Missing/incomplete provenance, symlinks,
customized files, and `.no-claude-plans-upgrade` prevent automatic replacement.
The default app recipe remains `workspace`; `review` is opt-in (AppKit 1.2.0).

For an uncommitted but unchanged managed installation, explicit upgrades may
use `--expect-installed <installedSourceHash>` alongside `--expect-source` after
reviewing both snapshots. This only permits files still matching their manifest;
custom edits remain blocked. The manager backs up original bytes and provenance.

Existing authored pages are a separate operation: run
`node ~/.claude/templates/plans/migrate-pages.mjs <repo>` to inspect recognized
storage blocks, then `--expect <snapshotHash>` to apply exactly that preview.
Only storage plumbing changes; authored content and submission tokens survive.
Unrecognized/custom blocks require manual review. Old browser saves are kept;
shared-origin legacy decisions require explicit recovery in the page.
