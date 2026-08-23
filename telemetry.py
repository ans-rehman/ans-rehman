#!/usr/bin/env python3
"""
telemetry.py -- rebuild the profile downlink card from live GitHub data.

Reads svg/dark_mode.svg and svg/light_mode.svg as templates, substitutes
{{TOKEN}} placeholders with current account statistics, and writes the
results back in place. Intended to run unattended from GitHub Actions.

Environment:
    ACCESS_TOKEN   personal access token, scopes: repo, read:user
    GITHUB_ACTOR   account to report on (Actions sets this automatically)

Line-of-code totals are the expensive part: they need per-repository
contributor statistics, so results are cached in cache/loc.json and keyed on
each repository's pushedAt timestamp. A repository is only re-counted after
it has actually been pushed to.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import sys
import time

import requests

# ── configuration ────────────────────────────────────────────────────────
# Edit these three: they are yours to write, not derived from the API.
ROLE = "MS ECE @ KAUST -- Communication Theory Lab"
FOCUS = "wireless comms · LEO satellite PHM · IoT"
LOCATION = "Thuwal, SA"

GRAPHQL = "https://api.github.com/graphql"
REST = "https://api.github.com"
ROOT = pathlib.Path(__file__).parent
CACHE = ROOT / "cache" / "loc.json"

TOKEN = os.environ.get("ACCESS_TOKEN", "")
USER = os.environ.get("GITHUB_ACTOR", "")

if not TOKEN or not USER:
    sys.exit("ACCESS_TOKEN and GITHUB_ACTOR must both be set")

HEADERS = {
    "Authorization": f"bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
}


# ── api helpers ──────────────────────────────────────────────────────────
def graphql(query: str, variables: dict) -> dict:
    """POST a GraphQL query, raising on transport or query-level errors."""
    r = requests.post(
        GRAPHQL,
        json={"query": query, "variables": variables},
        headers=HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    payload = r.json()
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]


def rest(path: str, retries: int = 3) -> object | None:
    """GET a REST endpoint. Returns None if the resource never materialises.

    The contributor-statistics endpoint answers 202 while GitHub computes the
    numbers in the background, so a 202 means 'ask again shortly', not
    'failed'.
    """
    for attempt in range(retries):
        r = requests.get(f"{REST}{path}", headers=HEADERS, timeout=30)
        if r.status_code == 202:
            time.sleep(2 + 2 * attempt)
            continue
        if r.status_code == 204:  # empty repository
            return []
        if r.status_code == 403:  # rate limited
            time.sleep(5)
            continue
        if not r.ok:
            return None
        return r.json()
    return None


# ── data collection ──────────────────────────────────────────────────────
PROFILE_QUERY = """
query($login: String!) {
  user(login: $login) {
    name
    login
    createdAt
    followers { totalCount }
    repositories(ownerAffiliations: OWNER) { totalCount }
    contributionsCollection { totalCommitContributions }
  }
}
"""

REPOS_QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    repositories(first: 100, after: $cursor, ownerAffiliations: OWNER,
                 orderBy: {field: PUSHED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        nameWithOwner
        isFork
        pushedAt
        stargazerCount
        primaryLanguage { name }
        languages(first: 8, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
  }
}
"""


def fetch_profile() -> dict:
    return graphql(PROFILE_QUERY, {"login": USER})["user"]


def fetch_repos() -> list[dict]:
    repos, cursor = [], None
    while True:
        page = graphql(REPOS_QUERY, {"login": USER, "cursor": cursor})
        block = page["user"]["repositories"]
        repos.extend(block["nodes"])
        if not block["pageInfo"]["hasNextPage"]:
            return repos
        cursor = block["pageInfo"]["endCursor"]


def load_cache() -> dict:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def save_cache(cache: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True))


def count_loc(repos: list[dict]) -> tuple[int, int]:
    """Return (added, deleted) across every owned repository.

    Only counts commits authored by USER, so contributions from collaborators
    and merged pull requests from others do not inflate the totals.
    """
    cache = load_cache()
    added = deleted = 0

    for repo in repos:
        if repo["isFork"]:
            continue
        # Key on pushedAt: unchanged repositories are served from cache.
        key = hashlib.sha256(repo["nameWithOwner"].encode()).hexdigest()[:16]
        stamp = repo["pushedAt"] or ""
        entry = cache.get(key)

        if entry and entry.get("pushedAt") == stamp:
            added += entry["added"]
            deleted += entry["deleted"]
            continue

        stats = rest(f"/repos/{repo['nameWithOwner']}/stats/contributors")
        r_add = r_del = 0
        if isinstance(stats, list):
            for contributor in stats:
                author = (contributor.get("author") or {}).get("login", "")
                if author.lower() != USER.lower():
                    continue
                for week in contributor.get("weeks", []):
                    r_add += week.get("a", 0)
                    r_del += week.get("d", 0)

        cache[key] = {
            "repo": repo["nameWithOwner"],
            "pushedAt": stamp,
            "added": r_add,
            "deleted": r_del,
        }
        added += r_add
        deleted += r_del

    save_cache(cache)
    return added, deleted


def top_languages(repos: list[dict], limit: int = 6) -> str:
    totals: dict[str, int] = {}
    for repo in repos:
        if repo["isFork"]:
            continue
        for edge in repo["languages"]["edges"]:
            totals[edge["node"]["name"]] = (
                totals.get(edge["node"]["name"], 0) + edge["size"]
            )
    ranked = sorted(totals, key=totals.get, reverse=True)[:limit]
    return " · ".join(ranked) if ranked else "--"


def uptime_since(created: str) -> str:
    start = dt.datetime.fromisoformat(created.replace("Z", "+00:00"))
    now = dt.datetime.now(dt.timezone.utc)
    years = now.year - start.year
    months = now.month - start.month
    days = now.day - start.day
    if days < 0:
        months -= 1
    if months < 0:
        years -= 1
        months += 12
    return f"{years}y {months}mo"


def link_margin(commits: int, stars: int, followers: int) -> tuple[int, int]:
    """A cosmetic 0-300px bar and its dB label.

    This is a visual flourish, not a real signal measurement -- it maps
    account activity onto a bounded scale so the bar always renders sensibly.
    """
    score = min(1.0, (commits / 2000) * 0.6 + (stars / 100) * 0.2 + (followers / 100) * 0.2)
    return int(300 * max(0.08, score)), round(3 + 17 * score, 1)


# ── rendering ────────────────────────────────────────────────────────────
def render(tokens: dict[str, str]) -> None:
    """Fill templates and write the rendered copies alongside them.

    Templates in svg/templates/ keep their {{TOKEN}} placeholders and are
    never written to -- rendering into the same file would consume the
    placeholders on the first run and leave nothing to substitute on the
    second.
    """
    for template, output in (("dark.svg", "dark_mode.svg"),
                             ("light.svg", "light_mode.svg")):
        svg = (ROOT / "svg" / "templates" / template).read_text(encoding="utf-8")
        for key, value in tokens.items():
            svg = svg.replace(f"{{{{{key}}}}}", str(value))
        leftover = [k for k in tokens if f"{{{{{k}}}}}" in svg]
        if leftover:
            raise RuntimeError(f"{template}: unsubstituted tokens {leftover}")
        (ROOT / "svg" / output).write_text(svg, encoding="utf-8")
        print(f"wrote svg/{output}")


def main() -> None:
    print(f"collecting telemetry for {USER}")
    profile = fetch_profile()
    repos = fetch_repos()

    stars = sum(r["stargazerCount"] for r in repos if not r["isFork"])
    commits = profile["contributionsCollection"]["totalCommitContributions"]
    followers = profile["followers"]["totalCount"]

    added, deleted = count_loc(repos)
    bar, snr = link_margin(commits, stars, followers)
    now = dt.datetime.now(dt.timezone.utc)

    tokens = {
        "NAME": profile["name"] or profile["login"],
        "ROLE": ROLE,
        "FOCUS": FOCUS,
        "LOCATION": LOCATION,
        "UPTIME": uptime_since(profile["createdAt"]),
        "REPOS": f"{profile['repositories']['totalCount']:,}",
        "STARS": f"{stars:,}",
        "COMMITS": f"{commits:,}",
        "FOLLOWERS": f"{followers:,}",
        "LOC_ADD": f"{added:,}",
        "LOC_DEL": f"{deleted:,}",
        "LOC_NET": f"{added - deleted:,}",
        "LANGS": top_languages(repos),
        "SNR": snr,
        "SNR_BAR": bar,
        "AOS": now.strftime("%H:%M:%S"),
        "UPDATED": now.strftime("%Y-%m-%d %H:%M"),
        "FRAME": now.strftime("%j%H%M"),
    }

    for key, value in tokens.items():
        print(f"  {key:<10} {value}")
    render(tokens)


if __name__ == "__main__":
    main()
