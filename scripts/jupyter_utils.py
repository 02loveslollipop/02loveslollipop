#!/usr/bin/env python3
"""
jupyter_utils.py

Advanced parser and analyzer for Jupyter Notebooks (.ipynb) to ensure
only executable code lines in code blocks are counted, strictly ignoring:
- Binary blobs, base64 images, PNGs, SVGs, plots, and MIME bundles in cell outputs.
- Markdown documentation cells and raw text cells.
- Blank lines and comment-only lines within code cells.
"""

import os
import sys
import json
import urllib.request
import urllib.error
import difflib

CACHE_FILE = os.path.join(os.path.dirname(__file__), ".cache", "jupyter_cache.json")


def parse_notebook_code(content):
    """
    Parse a Jupyter notebook and extract only executable code lines and code bytes.
    
    Returns:
        tuple (exec_lines, code_bytes):
            exec_lines (list[str]): Stripped executable code lines from code blocks.
            code_bytes (int): Total byte length of code lines in code blocks.
    """
    if isinstance(content, (bytes, bytearray)):
        content = content.decode("utf-8", errors="replace")
    if isinstance(content, str):
        try:
            data = json.loads(content)
        except Exception:
            return [], 0
    elif isinstance(content, dict):
        data = content
    else:
        return [], 0

    cells = data.get("cells", [])
    if not isinstance(cells, list):
        return [], 0

    exec_lines = []
    code_bytes = 0

    for cell in cells:
        # Strictly code cells: ignore markdown documentation and raw cells
        if cell.get("cell_type") != "code":
            continue

        # Cell outputs (blobs, images, base64 data, stdout) are strictly ignored
        source = cell.get("source", [])
        if isinstance(source, str):
            source = source.splitlines(True)
        elif not isinstance(source, list):
            continue

        for line in source:
            stripped = line.strip()
            # Only count executable code lines: skip empty lines and comment-only lines
            if stripped and not stripped.startswith("#"):
                exec_lines.append(stripped)
                code_bytes += len(line.encode("utf-8"))

    return exec_lines, code_bytes


def calculate_notebook_diff(old_content, new_content):
    """
    Calculate the exact number of executable code lines added between two notebook versions.
    """
    old_lines, _ = parse_notebook_code(old_content) if old_content else ([], 0)
    new_lines, _ = parse_notebook_code(new_content) if new_content else ([], 0)

    if not old_lines:
        return len(new_lines)
    if not new_lines:
        return 0

    diff = difflib.ndiff(old_lines, new_lines)
    additions = sum(1 for d in diff if d.startswith("+ "))
    return additions


def fetch_file_content(url, token):
    """Fetch raw file content from GitHub using token authentication."""
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "02loveslollipop-jupyter-analyzer",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def get_notebook_commit_additions(repo_name, commit_sha, parent_sha, file_path, token):
    """
    Compute the executable code additions for a notebook changed in a commit.
    """
    new_url = f"https://raw.githubusercontent.com/{repo_name}/{commit_sha}/{file_path}"
    new_content = fetch_file_content(new_url, token)
    if not new_content:
        return 0

    old_content = None
    if parent_sha:
        old_url = f"https://raw.githubusercontent.com/{repo_name}/{parent_sha}/{file_path}"
        old_content = fetch_file_content(old_url, token)

    return calculate_notebook_diff(old_content, new_content)


def load_cache(cache_path=CACHE_FILE):
    """Load persistent blob SHA cache."""
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_cache(cache, cache_path=CACHE_FILE):
    """Save persistent blob SHA cache."""
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"Warning: Failed to save jupyter cache: {e}", file=sys.stderr)


def analyze_repository_notebooks(repo_name, branch, token, cache, github_request_fn):
    """
    Analyze all Jupyter notebooks in a repository using Git tree blobs.
    
    Returns:
        dict with keys 'lines', 'bytes', 'files'
    """
    tree_data = github_request_fn(
        f"https://api.github.com/repos/{repo_name}/git/trees/{branch}?recursive=1",
        token,
    )
    if not tree_data or "tree" not in tree_data:
        fallback_branch = "master" if branch == "main" else "main"
        tree_data = github_request_fn(
            f"https://api.github.com/repos/{repo_name}/git/trees/{fallback_branch}?recursive=1",
            token,
        )

    if not tree_data or "tree" not in tree_data:
        return {"lines": 0, "bytes": 0, "files": 0}

    nb_items = [x for x in tree_data["tree"] if x["path"].endswith(".ipynb")]
    if not nb_items:
        return {"lines": 0, "bytes": 0, "files": 0}

    total_lines = 0
    total_bytes = 0

    for item in nb_items:
        sha = item.get("sha")
        path = item.get("path")
        if sha and sha in cache:
            total_lines += cache[sha]["lines"]
            total_bytes += cache[sha]["bytes"]
            continue

        raw_url = f"https://raw.githubusercontent.com/{repo_name}/{branch}/{path}"
        content = fetch_file_content(raw_url, token)
        if not content:
            alt_branch = "master" if branch == "main" else "main"
            raw_url_alt = f"https://raw.githubusercontent.com/{repo_name}/{alt_branch}/{path}"
            content = fetch_file_content(raw_url_alt, token)

        if content:
            lines, cbytes = parse_notebook_code(content)
            if sha:
                cache[sha] = {"lines": len(lines), "bytes": cbytes}
            total_lines += len(lines)
            total_bytes += cbytes

    return {"lines": total_lines, "bytes": total_bytes, "files": len(nb_items)}


def get_all_jupyter_stats(token, repos_with_jupyter, github_request_fn):
    """
    Analyze Jupyter notebooks across all specified repositories.
    
    Args:
        token (str): GitHub token.
        repos_with_jupyter (list[dict]): List of dicts with 'nameWithOwner' and 'defaultBranch'.
        github_request_fn (callable): GitHub request helper.
        
    Returns:
        tuple (total_lines, total_bytes, per_repo_stats)
    """
    cache = load_cache()
    per_repo_stats = {}
    total_lines = 0
    total_bytes = 0

    for repo in repos_with_jupyter:
        name = repo["nameWithOwner"]
        branch = repo.get("defaultBranch") or "main"
        stats = analyze_repository_notebooks(name, branch, token, cache, github_request_fn)
        per_repo_stats[name] = stats
        total_lines += stats["lines"]
        total_bytes += stats["bytes"]

    save_cache(cache)
    return total_lines, total_bytes, per_repo_stats
