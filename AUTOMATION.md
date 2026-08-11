# Auto-Sync Automation

This document describes the automated pipeline that keeps this repository
(`adv247/dns-blocklists`) in sync with the upstream
[HaGeZi DNS blocklists](https://gitlab.com/hagezi/mirror/-/tree/main/dns-blocklists)
mirror on GitLab, while rewriting every internal link to point back to this
repo instead of the original `hagezi/dns-blocklists`.

## ⚠️ Important: why the first run failed

Run [`31495768519`](https://github.com/adv247/dns-blocklists/actions/runs/31495768519)
failed because **something outside this workflow is force-resetting the
`main` branch to an exact copy of `hagezi/dns-blocklists`** (same commit
SHAs, same author `hagezi <hagezi@outlook.de>`, same commit message
`release`). Evidence:

- The commit we pushed (`7ea3239...`) still exists in the repo's object
  database, but `main` now points to `f37b844...`, an upstream commit with
  an **earlier** timestamp — that's only possible via a hard reset / mirror
  push (`git push --mirror` or `git push --force`), never a normal merge or
  GitHub's built-in "sync fork" (which only fast-forwards and would refuse
  to run if it could drop a commit).
- All the files we added (`.github/workflows/auto-sync.yml`,
  `scripts/auto_sync.py`, `AUTOMATION.md`) disappeared from `main` after
  that reset, so any scheduled run after the reset fails immediately with
  "file not found" because the workflow file and script it depends on no
  longer exist on the branch GitHub Actions reads from.

**You need to find and stop (or adjust) whatever process is mirroring
`hagezi/dns-blocklists` wholesale into `adv247/dns-blocklists`** — this is
most likely a cron job, personal script, or third-party mirroring tool
running outside GitHub (it is **not** one of the workflow files currently
in this repo; those are just HaGeZi's own issue-triage workflows, copied in
when the repo was created). Common patterns to check for:

```bash
git clone --mirror https://github.com/hagezi/dns-blocklists
cd dns-blocklists.git
git push --mirror https://github.com/adv247/dns-blocklists   # <- wipes everything
```

If you find such a job (e.g. on a VPS, GitHub App, Zapier/Make scenario, or
another CI system), either:

1. **Disable it entirely** — our `auto-sync.yml` workflow already pulls the
   list data straight from the same ultimate source (HaGeZi's GitLab
   mirror), so the two processes are redundant and directly conflict. This
   is the recommended fix.
2. **Or change it from a mirror-push to a merge/rebase**, and exclude
   `.github/workflows/auto-sync.yml`, `scripts/`, `AUTOMATION.md`, and
   `.sync_state.json` from being overwritten.

Until that external process stops force-resetting `main`, this repo's own
workflow will keep getting wiped no matter how it's written.

## What the workflow does now

Workflow file: [`.github/workflows/auto-sync.yml`](.github/workflows/auto-sync.yml)
Script: [`scripts/auto_sync.py`](scripts/auto_sync.py)

1. **Runs daily** via cron (`0 18 * * *`, 18:00 UTC = 01:00 Asia/Singapore),
   plus on manual trigger (`workflow_dispatch`). A `concurrency` group
   prevents two runs from overlapping and racing on the same push.
2. **Only touches changed files** — the script keeps a small state file
   (`.sync_state.json`) mapping each blocklist file to the GitLab blob SHA
   it last saw. On every run it lists each format directory
   (`adblock`, `controld`, `dnsmasq`, `domains`, `hosts`, `ips`, `pac`,
   `rpz`, `share`, `wildcard`) via the GitLab API and **compares blob SHAs
   before downloading anything** — unchanged files are skipped entirely
   (no download, no write, no commit noise). Files removed upstream are
   deleted locally too, so the repo never accumulates stale lists. This
   keeps runs fast and commits small even though the upstream list set is
   large.
3. **Rewrites links** in every changed blocklist file, and in existing
   description files (README.md, sources.md, index.html, etc.):
   - `https://raw.githubusercontent.com/hagezi/dns-blocklists/main/...`
     → `https://raw.githubusercontent.com/adv247/dns-blocklists/main/...`
   - `https://github.com/hagezi/dns-blocklists/...`
     → `https://github.com/adv247/dns-blocklists/...`
4. **Commits and pushes** any changes to `main` as `github-actions[bot]`,
   with an automatic fetch-rebase-retry loop (up to 5 attempts) if the push
   is rejected because `main` moved in the meantime.
5. **Creates a GitHub Release** (only when something actually changed)
   tagged with a CalVer-style version — see next section.
6. **Sends a Telegram notification** reporting success (with file count and
   release tag) or failure (with a direct link to the failed run's logs).

## Release versioning scheme

Releases are tagged with **CalVer** (calendar versioning):

```
v<YEAR>.<MONTH>.<DAY>-<HOUR><MINUTE>   (UTC)
e.g. v2026.08.11-1830
```

This is more useful than arbitrary `v1.2.3` semver bumps for a data-only
repo like this one, because:

- The tag itself tells you exactly **when** that snapshot of the blocklists
  was pulled from upstream, with no need to open the release notes.
- Tags sort correctly both chronologically and lexicographically.
- A release is only created when files actually changed, so the release
  list doubles as a changelog of "when did the blocklists actually update"
  instead of one noisy release per day regardless of content.
- Each release's notes list exactly which files changed (up to 50, with a
  count if more), taken straight from the sync script's diff.

## Setting up the Telegram notification

You need two GitHub Actions secrets on this repository:
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

1. **Create a bot and get the token**
   - Open Telegram, message [@BotFather](https://t.me/BotFather).
   - Send `/newbot`, follow the prompts to name it.
   - BotFather replies with a token like `123456789:ABCDefGhIJKlmNoPQRstuVWxyZ`.
     This is your `TELEGRAM_BOT_TOKEN`.

2. **Get your chat ID**
   - Start a chat with your new bot (send it any message, e.g. `hi`).
   - Visit `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates` in a
     browser, replacing `<YOUR_BOT_TOKEN>` with the token from step 1.
   - Find `"chat":{"id":<NUMBER>, ...}` in the JSON response — that number
     is your `TELEGRAM_CHAT_ID`. (For a group, add the bot to the group
     first, send a message there, then look for the group's — negative —
     chat ID.)

3. **Add the secrets to GitHub**
   - Go to `Settings` → `Secrets and variables` → `Actions` on
     `adv247/dns-blocklists`.
   - **New repository secret** → name `TELEGRAM_BOT_TOKEN`, value from
     step 1. Save.
   - **New repository secret** → name `TELEGRAM_CHAT_ID`, value from
     step 2. Save.

4. **Test it**
   - Go to **Actions** → **Auto Sync DNS Blocklists from GitLab** →
     **Run workflow** to trigger it manually and confirm you receive a
     Telegram message and (if anything changed) a new entry under
     **Releases**.

## Making this run forever without manual intervention

- `permissions: contents: write` is already set, so the workflow's
  auto-provided `GITHUB_TOKEN` (which never expires and needs no manual
  renewal) is enough to push commits and create releases — no personal
  access token to babysit.
- The `concurrency` group plus fetch-rebase-retry loop makes pushes
  self-healing against transient races (e.g. two triggers firing close
  together, or a manual `workflow_dispatch` overlapping the scheduled run).
- Because the script only re-downloads/rewrites files whose GitLab blob SHA
  changed, runs stay fast even as the upstream list set grows, so there is
  no need to ever manually prune or resync from scratch.
- The **one manual thing left** is stopping the external process described
  above that force-resets `main`. Once that's disabled, this workflow is
  fully self-sufficient: schedule → diff-only sync → link fix → commit →
  release → Telegram notification, indefinitely.
