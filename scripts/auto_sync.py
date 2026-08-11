"""
Auto-sync HaGeZi DNS blocklists from GitLab mirror into this repo.
- Only re-downloads / rewrites files whose GitLab blob SHA changed since
  the last successful run (tracked in .sync_state.json), keeping runs
  fast and commits small.
- Rewrites hagezi -> adv247 links in every changed blocklist file and in
  all existing description files (README.md, sources.md, index.html...).
- Records a SHA-256 hash for every synced file in .sync_state.json AND in
  MANIFEST.sha256.txt at repo root, so every update leaves a verifiable
  integrity record.
Run by .github/workflows/auto-sync.yml on a daily schedule.
"""
import hashlib
import json
import os
import sys
import requests

GITLAB_PROJECT = "hagezi%2Fmirror"  # hagezi/mirror, URL-encoded
GITLAB_API = "https://gitlab.com/api/v4"
GITLAB_RAW_BASE = "https://gitlab.com/hagezi/mirror/-/raw/main/dns-blocklists"
DNS_PATH = "dns-blocklists"
STATE_FILE = ".sync_state.json"
MANIFEST_FILE = "MANIFEST.sha256.txt"

FORMAT_DIRS = [
    "adblock", "controld", "dnsmasq", "domains",
    "hosts", "ips", "pac", "rpz", "share", "wildcard",
]

OLD_RAW = "https://raw.githubusercontent.com/hagezi/dns-blocklists/main"
NEW_RAW = "https://raw.githubusercontent.com/adv247/dns-blocklists/main"
OLD_GH = "https://github.com/hagezi/dns-blocklists"
NEW_GH = "https://github.com/adv247/dns-blocklists"


def fix_links(text: str) -> str:
    text = text.replace(OLD_RAW, NEW_RAW)
    text = text.replace(OLD_GH, NEW_GH)
    return text


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")


def list_gitlab_dir(path: str):
    url = f"{GITLAB_API}/projects/{GITLAB_PROJECT}/repository/tree"
    items = []
    page = 1
    while True:
        r = requests.get(
            url,
            params={"path": path, "ref": "main", "per_page": 100, "page": page},
            timeout=30,
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        items.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return items


def download_raw(file_path: str) -> str:
    rel = file_path[len(DNS_PATH) + 1:]
    url = f"{GITLAB_RAW_BASE}/{rel}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def sync_format_dir(fmt: str, state: dict, changed_files: list) -> tuple:
    remote_path = f"{DNS_PATH}/{fmt}"
    items = list_gitlab_dir(remote_path)
    os.makedirs(fmt, exist_ok=True)
    checked = 0
    changed = 0
    new_entries = {}
    seen_names = set()
    for item in items:
        if item.get("type") != "blob":
            continue
        name = item["name"]
        seen_names.add(name)
        state_key = f"{fmt}/{name}"
        blob_sha = item.get("id")
        checked += 1
        local_path = os.path.join(fmt, name)
        prev = state.get(state_key)
        prev_blob = prev.get("blob_sha") if isinstance(prev, dict) else prev
        if prev_blob == blob_sha and os.path.exists(local_path):
            new_entries[state_key] = prev if isinstance(prev, dict) else {"blob_sha": blob_sha}
            continue
        try:
            content = download_raw(item["path"])
        except requests.HTTPError as e:
            print(f"[warn] failed to download {item['path']}: {e}", file=sys.stderr)
            continue
        content = fix_links(content)
        with open(local_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        new_entries[state_key] = {"blob_sha": blob_sha, "sha256": sha256_of(content)}
        changed += 1
        changed_files.append(local_path)
    if os.path.isdir(fmt):
        for existing in os.listdir(fmt):
            if existing not in seen_names:
                stale_path = os.path.join(fmt, existing)
                if os.path.isfile(stale_path):
                    os.remove(stale_path)
                    state.pop(f"{fmt}/{existing}", None)
                    changed_files.append(f"{stale_path} (removed)")
                    changed += 1
    print(f"[sync] {fmt}: {checked} checked, {changed} changed")
    return checked, changed, new_entries


def fix_description_files(changed_files: list):
    exts = (".md", ".txt", ".html")
    skip_dirs = {".git", ".github"}
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        rel_root = os.path.relpath(root, ".")
        top = rel_root.split(os.sep)[0]
        if top in FORMAT_DIRS:
            continue
        for fname in files:
            if not fname.endswith(exts) or fname == MANIFEST_FILE:
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
            except (UnicodeDecodeError, OSError):
                continue
            new_content = fix_links(content)
            if new_content != content:
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(new_content)
                changed_files.append(fpath)
                print(f"[fix-links] {fpath}")


def write_manifest(state: dict):
    lines = []
    for key in sorted(state.keys()):
        entry = state[key]
        digest = entry.get("sha256", "") if isinstance(entry, dict) else ""
        if digest:
            lines.append(f"{digest}  {key}")
    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    state = load_state()
    new_state = dict(state)
    changed_files = []
    total_checked = 0
    for fmt in FORMAT_DIRS:
        try:
            checked, changed, entries = sync_format_dir(fmt, new_state, changed_files)
            total_checked += checked
            new_state.update(entries)
        except Exception as e:
            print(f"[error] syncing {fmt}: {e}", file=sys.stderr)

    fix_description_files(changed_files)
    save_state(new_state)
    write_manifest(new_state)

    print(f"[done] checked={total_checked} changed={len(changed_files)}")

    summary_path = os.path.join(os.environ.get("RUNNER_TEMP", "/tmp"), "_sync_summary.txt")
    summary = "\n".join(f"- {p}" for p in changed_files[:50])
    if len(changed_files) > 50:
        summary += f"\n- ...and {len(changed_files) - 50} more"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary if summary else "(no changes)")

    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as f:
            f.write(f"changed_count={len(changed_files)}\n")
            f.write(f"summary_path={summary_path}\n")


if __name__ == "__main__":
    main()
