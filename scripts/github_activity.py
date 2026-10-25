"""Collect public push activity across branches in an exact rolling UTC window."""

import datetime
import json
import os
import re
import sys
import urllib.parse
import urllib.request

API = "https://api.github.com"


def request(url, token):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "02loveslollipop-stats-agent",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    # Propagate errors so Actions cannot publish an empty or partial success card.
    with urllib.request.urlopen(req, timeout=60) as response:
        data = json.load(response)
        link = response.headers.get("Link", "")
    match = re.search(r'<([^>]+)>; rel="next"', link)
    return data, match.group(1) if match else None


def pages(path, token, **params):
    url = f"{API}/{path}?{urllib.parse.urlencode({'per_page': 100, **params})}"
    while url:
        data, url = request(url, token)
        yield data


def parse_date(value):
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def get_recent_repositories(token, days=7, now=None):
    """Return public repositories, pushes and unique commits added by those pushes.

    Push timestamps determine eligibility, including commits authored before the
    window. All branch refs are included. A commit shared by branches counts once
    per repository. Repository activity avoids the user event feed's 300-event cap;
    that feed also discovers pushes to repositories outside the user's membership.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    since = now - datetime.timedelta(days=days)
    username = os.environ.get("PROFILE_USERNAME", "02loveslollipop")
    candidates = {}
    event_pushes = {}

    # This endpoint works with the Actions installation token as well as a PAT;
    # the profile identity must never be inferred from the token's bot identity.
    for batch in pages(f"users/{username}/repos", token,
                       type="all", sort="pushed", direction="desc"):
        for repo in batch:
            if repo.get("pushed_at") and parse_date(repo["pushed_at"]) >= since:
                candidates[repo["full_name"]] = repo
        if batch and all(not r.get("pushed_at") or
                         parse_date(r["pushed_at"]) < since for r in batch):
            break

    events_seen = 0
    oldest_event = now
    # Do not stop at the first old event: GitHub's event feed can be unordered.
    for batch in pages(f"users/{username}/events/public", token):
        events_seen += len(batch)
        for event in batch:
            timestamp = parse_date(event["created_at"])
            oldest_event = min(oldest_event, timestamp)
            if not since <= timestamp <= now or event["type"] != "PushEvent":
                continue
            name = event["repo"]["name"]
            payload = event["payload"]
            event_pushes.setdefault(name, {})[str(payload["push_id"])] = {
                "id": payload["push_id"], "before": payload.get("before"),
                "after": payload.get("head"), "ref": payload.get("ref", ""),
                "timestamp": event["created_at"],
            }
            if name not in candidates:
                candidates[name] = request(f"{API}/repos/{name}", token)[0]
    if events_seen >= 300 and oldest_event > since:
        print("Warning: public event feed does not cover the full window; "
              "external repositories outside your memberships may be missing.", file=sys.stderr)

    results = []
    for name, repo in sorted(candidates.items()):
        if repo.get("private"):
            continue
        pushes = dict(event_pushes.get(name, {}))
        # Fetch a superset and apply exact timestamps locally. This endpoint uses
        # cursor pagination, followed through Link headers rather than page numbers.
        period = "month" if days <= 28 else "year"
        for batch in pages(f"repos/{name}/activity", token,
                           actor=username, time_period=period, direction="desc"):
            for activity in batch:
                if (activity["activity_type"] in
                        {"push", "force_push", "branch_creation", "pr_merge"}
                        and since <= parse_date(activity["timestamp"]) <= now):
                    pushes[str(activity["id"])] = activity
        pushes = [p for p in pushes.values() if p.get("ref", "").startswith("refs/heads/")]
        if not pushes:
            continue

        commits = {}
        for push in pushes:
            before, after = push.get("before"), push.get("after")
            if not after or not after.strip("0"):
                continue  # Branch deletion contains no new code.
            if before and before.strip("0"):
                # Enumerate commits rather than compare.files (which has a 300-file
                # cap and reports a net diff instead of cumulative insertions).
                for comparison in pages(f"repos/{name}/compare/{before}...{after}", token):
                    for commit in comparison["commits"]:
                        commits[commit["sha"]] = commit
            else:
                # Branch creation has no before SHA. Compare with the default
                # branch to exclude inherited history, without filtering commit
                # dates: old commits pushed today still belong to this window.
                default_branch = repo.get("default_branch")
                if default_branch and push["ref"] != f"refs/heads/{default_branch}":
                    base = urllib.parse.quote(default_branch, safe="")
                    for comparison in pages(f"repos/{name}/compare/{base}...{after}", token):
                        for commit in comparison["commits"]:
                            commits[commit["sha"]] = commit
                else:
                    # Initial push to the repository's default branch.
                    for batch in pages(f"repos/{name}/commits", token, sha=after):
                        for commit in batch:
                            commits[commit["sha"]] = commit

        details = []
        for sha in sorted(commits):
            commit_data = None
            files = []
            for batch in pages(f"repos/{name}/commits/{sha}", token):
                commit_data = commit_data or batch
                files.extend(batch.get("files", []))
            commit_data["files"] = files
            # Merge diffs repeat code already counted in the individual commits.
            if len(commit_data.get("parents", [])) > 1:
                commit_data["files"] = []
            details.append(commit_data)
        print(f"   {name}: {len(pushes)} pushes, {len(details)} unique commits")
        results.append({"repository": repo, "commits": details, "pushes": len(pushes)})
    return results
