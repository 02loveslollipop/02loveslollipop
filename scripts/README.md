# Profile activity cards

`python3 scripts/update_use_to_code.py` updates both rankings and the project card.
`python3 scripts/update_weekly_repos.py` updates only the project card.
Use `GH_PAT` or `GITHUB_TOKEN`; local runs can also use `gh auth token`.
`PROFILE_USERNAME` defaults to `02loveslollipop`, independently of the token owner.

The rankings workflow runs daily at 06:17 UTC, on pushes to this profile's `main`,
and on manual dispatch. Each run recomputes the preceding 168 hours ending at
collection time in UTC. Pushes to other projects are picked up by the next daily
run; they do not directly trigger this profile repository's workflow.

Public repositories are discovered from profile repository memberships and public
push events. Repository activity includes default branches, feature branches,
force pushes, and new branches. Push time determines eligibility, including older
commits pushed during the window. A commit SHA counts once per repository across
branches and pushes. Merge diffs are excluded to avoid counting merged code twice.
For a new feature branch, the current default branch provides the baseline;
initial pushes to a new default branch include its full history.

Projects are ranked by cumulative insertions, with push count breaking ties, and
limited to seven projects. Deletion-only pushes can appear with zero insertions.
The profile repository is excluded. Language shares come from code added in the
window, including branch code; generated files and documentation are excluded from
language shares. Notebook additions count executable code, excluding outputs.

GitHub's public event feed is delayed and limited to 300 events. Repository
activity supplies push history for discovered repositories, but an external
repository outside the profile's memberships may be missed if its events have
fallen out of the feed. Collection failures stop the workflow rather than publish
partial rankings. Private projects are excluded from recent cards; all-time
language totals retain the existing visibility allowed by the configured token.

Run regression checks with `python3 -m unittest discover -s tests -v`.
