import datetime
import io
import unittest
from unittest.mock import patch

from scripts import github_activity as activity
from scripts.update_weekly_repos import get_weekly_repos
from scripts.update_use_to_code import get_recent_activity


NOW = datetime.datetime(2026, 10, 25, 12, tzinfo=datetime.timezone.utc)
REPO = {"name": "project", "full_name": "02loveslollipop/project",
        "html_url": "https://github.com/02loveslollipop/project",
        "private": False, "pushed_at": NOW.isoformat(), "default_branch": "main"}


def push(identifier, timestamp, before="base", after="new", ref="refs/heads/feature/work"):
    return {"id": identifier, "activity_type": "push", "timestamp": timestamp,
            "before": before, "after": after, "ref": ref}


def commit(sha="new", parents=None):
    return {"sha": sha, "parents": parents if parents is not None else [{"sha": "base"}],
            "commit": {"author": {"date": "2020-01-01T00:00:00Z"}},
            "files": [{"filename": "work.py", "additions": 10}]}


class ActivityTests(unittest.TestCase):
    def collect(self, pushes, comparison=None, events=None, creation=None):
        calls = []

        def fake_pages(path, token, **params):
            calls.append((path, params))
            if path.startswith("users/") and path.endswith("/repos"):
                yield [REPO]
            elif path.endswith("/events/public"):
                yield events or []
            elif path.endswith("/activity"):
                yield pushes
            elif "/compare/" in path:
                yield {"commits": comparison if comparison is not None else [{"sha": "new"}]}
            elif path.endswith("/commits"):
                yield creation or [{"sha": "new"}]
            elif "/commits/" in path:
                # Simulate paginated commit files.
                yield commit(path.rsplit("/", 1)[-1])
                yield {"files": [{"filename": "other.go", "additions": 5}]}
            else:
                raise AssertionError(path)

        with patch.object(activity, "pages", side_effect=fake_pages), patch("sys.stdout", io.StringIO()):
            result = activity.get_recent_repositories("token", now=NOW)
        return result, calls

    def test_exact_rolling_window_and_old_commits_pushed_to_branches(self):
        result, calls = self.collect([
            push(1, "2026-10-18T12:00:00Z"),  # Exact seven-day boundary.
            push(2, "2026-10-18T11:59:59Z", after="old"),
            push(3, "2026-10-25T12:00:01Z", after="future"),
        ])
        self.assertEqual(result[0]["pushes"], 1)
        self.assertEqual([c["sha"] for c in result[0]["commits"]], ["new"])
        self.assertEqual(len(result[0]["commits"][0]["files"]), 2)
        self.assertTrue(any("compare/base...new" in path for path, _ in calls))
        self.assertFalse(any("since" in params for _, params in calls))

    def test_commits_shared_by_branches_are_counted_once(self):
        result, _ = self.collect([
            push(1, NOW.isoformat()),
            push(2, NOW.isoformat(), ref="refs/heads/main"),
        ])
        self.assertEqual(result[0]["pushes"], 2)
        self.assertEqual(len(result[0]["commits"]), 1)

    def test_new_branch_uses_default_branch_baseline(self):
        result, calls = self.collect([push(1, NOW.isoformat(), before="0" * 40)])
        self.assertEqual(len(result[0]["commits"]), 1)
        self.assertTrue(any("compare/main...new" in path for path, _ in calls))

    def test_initial_push_includes_root_commit(self):
        result, calls = self.collect([push(1, NOW.isoformat(), before="0" * 40,
                                          ref="refs/heads/main")])
        self.assertTrue(any(path.endswith("/commits") for path, _ in calls))
        self.assertEqual(len(result[0]["commits"]), 1)

    def test_event_and_repository_activity_deduplicate_same_push(self):
        event = {"created_at": NOW.isoformat(), "type": "PushEvent",
                 "repo": {"name": REPO["full_name"]},
                 "payload": {"push_id": 1, "before": "base", "head": "new",
                             "ref": "refs/heads/feature/work"}}
        result, _ = self.collect([push(1, NOW.isoformat())], events=[event])
        self.assertEqual(result[0]["pushes"], 1)

    def test_zero_addition_push_still_appears_and_no_private_projects(self):
        item = {"repository": REPO, "commits": [], "pushes": 1}
        private = {"repository": {**REPO, "private": True}, "commits": [], "pushes": 1}
        repos = get_weekly_repos("token", activity=[item, private])
        self.assertEqual(len(repos), 1)
        self.assertEqual(repos[0]["insertions"], 0)
        self.assertEqual(repos[0]["pushes"], 1)

    def test_project_and_language_rankings_share_branch_additions(self):
        result, _ = self.collect([push(1, NOW.isoformat())])
        repos = get_weekly_repos("token", activity=result)
        languages = get_recent_activity("token", activity=result)
        self.assertEqual(repos[0]["insertions"], 15)
        self.assertEqual(languages, {"Python": 10, "Go": 5})
        self.assertEqual(repos[0]["languages"][0]["name"], "Python")

    def test_collection_errors_propagate(self):
        with patch.object(activity, "pages", side_effect=RuntimeError("API unavailable")):
            with self.assertRaisesRegex(RuntimeError, "API unavailable"):
                activity.get_recent_repositories("token", now=NOW)

    def test_link_pagination(self):
        responses = [([1], "https://api.github.com/next"), ([2], None)]
        with patch.object(activity, "request", side_effect=responses) as request:
            self.assertEqual(list(activity.pages("example", "token")), [[1], [2]])
        self.assertEqual(request.call_args.args[0], "https://api.github.com/next")


if __name__ == "__main__":
    unittest.main()
