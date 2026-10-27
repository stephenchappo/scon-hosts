#!/usr/bin/env python3
"""On-demand GitHub sync for an Obsidian vault, triggered from the phone.

Usage: vault-sync-on-demand.py [VAULT_DIR]   (default: ~/work/obsidian-kink-rag)


Sync.md at the vault root carries a "- [ ] Sync now" checkbox. Syncthing brings
the page to Deepthought; vault-sync-on-demand.timer runs this every minute. If
the box is ticked: commit everything, rebase onto GitHub, push, confirm with
ls-remote, write the result into the page and untick the box. Syncthing then
carries the page back to the phone. Sync.md itself is in .git/info/exclude.
"""
import datetime
import fcntl
import os
import re
import subprocess
import sys
from pathlib import Path

VAULT = Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / "work/obsidian-kink-rag").expanduser()
PAGE = VAULT / "Sync.md"
TICKED = re.compile(r"^- \[[xX]\] Sync now", re.M)
UNTICKED = "- [ ] Sync now"
MAX_FILES = 30
HISTORY = 5

HEADER = f"""# Sync

{UNTICKED}

Tick this; Deepthought commits your phone edits, pushes to GitHub and unticks it when it's live. It checks every minute.

<!-- Everything below is rewritten by Deepthought (~/bin/vault-sync-on-demand.py). -->
"""


def git(*args, check=True):
    r = subprocess.run(["git", *args], cwd=VAULT, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise GitError(f"git {' '.join(args)}", r.stdout + r.stderr)
    return r.stdout.strip()


def repo_url():
    """git@github.com:owner/repo.git -> https://github.com/owner/repo"""
    url = git("remote", "get-url", "origin")
    url = re.sub(r"^git@([^:]+):", r"https://\1/", url)
    return re.sub(r"\.git$", "", url)


class GitError(Exception):
    def __init__(self, cmd, output):
        super().__init__(cmd)
        self.cmd, self.output = cmd, output


def sync():
    """Returns (ok, summary line, detail lines)."""
    lines = []
    git("add", "-A")
    staged = git("diff", "--cached", "--name-status").splitlines()
    if staged:
        stamp = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
        git("commit", "-q", "-m", f"phone sync: {stamp}")
        lines.append(f"- committed {len(staged)} file(s):")
        lines += [f"    - `{s}`" for s in staged[:MAX_FILES]]
        if len(staged) > MAX_FILES:
            lines.append(f"    - … and {len(staged) - MAX_FILES} more")
    git("fetch", "-q", "origin", "main")
    incoming = int(git("rev-list", "--count", "HEAD..origin/main"))
    r = subprocess.run(["git", "rebase", "-q", "--autostash", "origin/main"],
                       cwd=VAULT, capture_output=True, text=True)
    if r.returncode != 0:
        git("rebase", "--abort", check=False)
        raise GitError("git rebase origin/main (aborted, nothing forced — "
                       "a phone edit conflicts with GitHub; needs a hand merge on Deepthought)",
                       r.stdout + r.stderr)
    lines.append(f"- {incoming} commit(s) came in from GitHub")
    git("push", "-q", "origin", "HEAD:main")
    head = git("rev-parse", "HEAD")
    remote = git("ls-remote", "origin", "refs/heads/main").split()[0]
    if remote != head:
        raise GitError("ls-remote check", f"GitHub main is {remote}, local HEAD is {head}")
    link = f"[`{head[:7]}`]({repo_url()}/commit/{head})"
    if staged:
        return True, f"✅ live on GitHub at {link}", lines
    return True, f"✅ nothing to commit, up to date with GitHub at {link}", lines


def write_page(summary, detail, old_text):
    now = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    history = []
    m = re.search(r"^## Last sync\n\*\*(.+?)\*\*", old_text, re.M)
    if m:
        history.append(f"- {m.group(1)}")
    h = re.search(r"^## History\n(.*)", old_text, re.M | re.S)
    if h:
        history += [l for l in h.group(1).splitlines() if l.startswith("- ")]
    body = HEADER + f"\n## Last sync\n**{now} · {summary}**\n\n" + "\n".join(detail) + "\n"
    if history:
        body += "\n## History\n" + "\n".join(history[:HISTORY]) + "\n"
    tmp = PAGE.with_name(".Sync.md.tmp")
    tmp.write_text(body)
    os.replace(tmp, PAGE)


def main():
    if not PAGE.exists():
        PAGE.write_text(HEADER)
        return
    text = PAGE.read_text()
    if not TICKED.search(text):
        return
    lock = open(VAULT / ".git/vault-sync-on-demand.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    if (VAULT / ".git/index.lock").exists():
        return  # lecturn (or someone) mid-git-op; next minute
    try:
        ok, summary, detail = sync()
    except GitError as e:
        ok = False
        tail = "\n".join(e.output.strip().splitlines()[-15:])
        summary = f"❌ failed at {e.cmd}"
        detail = ["- Nothing was forced. Tick again to retry; if it keeps failing, ask Claude on Deepthought.",
                  "", "```", tail, "```"]
    write_page(summary, detail, text)
    print(summary)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
