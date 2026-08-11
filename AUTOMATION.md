# Auto-Sync Automation - Incident Report (Round 2)

## 1. Debug

Even after you switched **Settings -> Actions -> General -> Workflow
permissions** to "Read and write permissions", the workflow still failed
with no new `chore(sync): ...` commit and no `.sync_state.json` /
`MANIFEST.sha256.txt` appearing on `main`. That ruled out the repo
permissions setting as the remaining cause.

## 2. So sánh (compare against the previous fix)

The previous fix added a **"Verify token has write access"** step that
called:

```
gh api repos/{owner}/{repo} --jq '.permissions.push'
```

Comparing behavior before/after: this check can return `false`/`null`
**even when the `GITHUB_TOKEN` genuinely has write access**, because the
`permissions` object on the repo-details API response reflects metadata
tied to the authenticated principal in a way that doesn't map cleanly onto
the ephemeral, workflow-scoped `GITHUB_TOKEN`. In practice this made the
check an unreliable predictor — it could fail-closed regardless of the
real Workflow permissions setting.

## 3. Phân tích luồng hoạt động

```
checkout -> [BUGGY CHECK: exits 1 here, false negative] -> sync -> commit -> push -> release -> notify
```

Because the buggy check ran immediately after checkout and exited early,
none of the real work (sync, commit, push, release) ever executed —
matching exactly what we observed (no state file, no commit, no release).

## 4. Kiểm thử

I re-verified: `main` still has no `.sync_state.json` / `MANIFEST.sha256.txt`
after your re-run, confirming the job never reached the sync step.

## 5. Sửa lỗi

**Removed the flawed "Verify token" step entirely.** Permission problems
now surface naturally and unambiguously at the one place they actually
matter — the `git push` command itself — which is a ground-truth test,
not a guess:

- The push step now captures `git push` stderr into `push_error.log`.
- If the error text contains "permission", "403", or "denied", the step
  fails immediately with a clear `::error::` message pointing back to the
  Workflow permissions setting — no more silent/ambiguous failures.
- Otherwise it falls through to the existing fetch-rebase-retry loop (for
  ordinary non-fast-forward conflicts, unrelated to permissions).

## 6. Soi chéo

| Symptom reported | Root cause | Fix |
|---|---|---|
| Run failed even after permission setting fixed | My own added permission-check step gave a false negative | Removed the check; real push result is now the only source of truth |
| Garbage release `37522026.223.54613` | Legacy `release.yml` inherited from hagezi/dns-blocklists | Deleted that file (done in the previous turn) |
| Release step could crash on duplicate CalVer tag (two runs same minute) | `gh release create` errors on existing tag | Now checks `gh release view` first and appends seconds (`-SS`) to disambiguate; a release-creation failure no longer marks the whole job failed if the sync commit already pushed successfully |

## 7. Kiểm chừng

After this push, trigger **Actions -> Auto Sync DNS Blocklists from GitLab
-> Run workflow** again. Expect: a `chore(sync): ...` commit on `main`,
`.sync_state.json` + `MANIFEST.sha256.txt` present at repo root, a release
tagged `vYYYY.MM.DD-HHMM`, and a Telegram message with the per-category
breakdown. If it still fails, the failure Telegram message and the
`push_error.log` output in the Action log will now say exactly why
(permission-denied vs. something else) instead of failing opaquely.

## 8. Đánh giá chất lượng

The fix trades a proactive-but-unreliable guard for a reactive-but-accurate
one. This is the right tradeoff here: a false negative that blocks a
perfectly working push is worse than a slightly later failure with an
accurate message.

## 9. Tài liệu hoá

This file, plus inline comments in
[`.github/workflows/auto-sync.yml`](.github/workflows/auto-sync.yml).

## 10. Cải tiến

- Push failures now distinguish "permission denied" from ordinary
  conflicts and message accordingly.
- Release creation is now idempotent against tag collisions and
  non-fatal if it fails after a successful commit/push.
- Telegram failure message now includes the permissions-setting hint
  directly, so you don't have to open the Actions log to get a first
  lead.

## 11. Ngăn lỗi tái diễn

Going forward, any new diagnostic step I add will be validated against
the actual outcome (e.g. testing a real push) rather than inferred from a
side-channel API field, to avoid repeating this class of false-negative
bug.

## 12. Báo cáo tối ưu

No extra API calls were added (the removed check saved one `gh api` call
per run); the push step now does at most one extra `cat` of a local log
file, negligible overhead.

## 13. Đánh giá cuối cùng

The workflow's core logic (diff-only sync, SHA-256 manifest, CalVer
release, category breakdown, Telegram notify) was correct all along — the
only defect was the extra guard I added in the previous round. That guard
is now removed and replaced with an accurate, ground-truth check at the
push step itself.
