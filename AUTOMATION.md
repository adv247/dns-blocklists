# Auto-Sync Automation

Pipeline that keeps `adv247/dns-blocklists` (branch `main`) in sync with
[HaGeZi's blocklists on GitLab](https://gitlab.com/hagezi/mirror/-/tree/main/dns-blocklists),
rewrites internal links, tracks integrity hashes, and tags releases with a
CalVer scheme.

## What it does

Workflow: [`.github/workflows/auto-sync.yml`](.github/workflows/auto-sync.yml)
Script: [`scripts/auto_sync.py`](scripts/auto_sync.py)

1. **Runs daily** via cron (`0 18 * * *`, 18:00 UTC = 01:00 Asia/Singapore),
   or on demand via `workflow_dispatch`. A `concurrency` group
   (`dns-blocklists-auto-sync`) makes sure two runs never race on the same
   push.
2. **Only updates changed files.** `scripts/auto_sync.py` keeps a small
   state file, `.sync_state.json`, mapping every blocklist file to the
   GitLab blob SHA it last saw. Each run lists the format directories
   (`adblock`, `controld`, `dnsmasq`, `domains`, `hosts`, `ips`, `pac`,
   `rpz`, `share`, `wildcard`) via the GitLab API and compares blob SHAs
   **before downloading anything** — unchanged files are skipped entirely.
   Files removed upstream are deleted locally too.
3. **Rewrites links** hagezi → adv247 in every changed blocklist file and
   in existing description files (README.md, sources.md, index.html...):
   - `https://raw.githubusercontent.com/hagezi/dns-blocklists/main/...`
     → `https://raw.githubusercontent.com/adv247/dns-blocklists/main/...`
   - `https://github.com/hagezi/dns-blocklists/...`
     → `https://github.com/adv247/dns-blocklists/...`
4. **Records a SHA-256 hash** for every synced file — both inside
   `.sync_state.json` and in a plain-text `MANIFEST.sha256.txt` at the repo
   root, regenerated every run, so every update leaves a verifiable
   integrity record you (or anyone) can check independently of Git's own
   hashing.
5. **Commits and pushes** to `main` as `github-actions[bot]`, with an
   automatic **fetch → rebase → retry** loop (up to 5 attempts, backing off
   5s/10s/15s/20s/25s) if the push is rejected because `main` moved in the
   meantime.
6. **Creates a GitHub Release only when something actually changed**,
   tagged with CalVer — see below — with release notes listing exactly
   which files changed (or a count if more than 50).
7. **Sends a Telegram notification** on both success (file count + release
   tag, or "no changes") and failure (with a direct link to the failed
   run's logs).

## Release versioning: CalVer

Releases are tagged:

```
v<YEAR>.<MONTH>.<DAY>-<HOUR><MINUTE>   (UTC)
e.g. v2026.08.11-1830
```

Why this instead of semver (`v1.2.3`):

- The tag itself tells you **when** that snapshot was pulled, with no need
  to open the release notes.
- Tags sort correctly both chronologically and lexicographically.
- A release only exists when files actually changed — the release list is
  effectively a changelog of "when did the blocklists really update",
  instead of one noisy release per day regardless of content.

## Running forever without manual intervention

- `permissions: contents: write` lets the workflow use the built-in
  `GITHUB_TOKEN` — it never expires and needs no manual renewal, unlike a
  personal access token.
- `concurrency` + the fetch-rebase-retry loop make pushes self-healing
  against transient races (e.g. a manual `workflow_dispatch` firing close
  to the scheduled run).
- Since the script only re-downloads/rewrites files whose GitLab blob SHA
  changed, runs stay fast and cheap even as the upstream list set grows —
  no need to ever manually prune or resync from scratch.
- With this in place, the loop is: schedule → diff-only sync → link fix →
  hash → commit (retry-safe) → release (only if changed) → Telegram
  notification, indefinitely, with zero manual steps required under normal
  operation.

## Setting up the Telegram notification

You need two GitHub Actions secrets: `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_CHAT_ID`.

1. Message [@BotFather](https://t.me/BotFather) on Telegram, send
   `/newbot`, follow the prompts — you get a token like
   `123456789:ABCDefGhIJKlmNoPQRstuVWxyZ` (`TELEGRAM_BOT_TOKEN`).
2. Message your new bot once (e.g. `hi`), then open
   `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates` in a browser
   and read `"chat":{"id":<NUMBER>}` (`TELEGRAM_CHAT_ID`).
3. Repo → **Settings → Secrets and variables → Actions** → add both as
   **New repository secret**.
4. Test via **Actions → Auto Sync DNS Blocklists from GitLab → Run
   workflow**.
