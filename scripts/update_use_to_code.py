#!/usr/bin/env python3
"""
update_use_to_code.py

Analyzes GitHub activity using GitHub GraphQL and REST APIs to calculate:
1. All-Time Language Ranking (bytes and percentage across user's repositories)
2. Current / "Now" Language Ranking (exact lines of code added in the past 30 days)

Updates README.md between:
<!-- START_SECTION:use_to_code -->
...
<!-- END_SECTION:use_to_code -->

And renders an SVG card to assets/cards/code-ranking.svg.
"""

import os
import sys
import json
import re
import datetime
import urllib.request
import urllib.error
import subprocess

# Extension to Language mapping
EXTENSION_TO_LANGUAGE = {
    # Python & Data
    ".py": "Python",
    ".pyw": "Python",
    ".ipynb": "Jupyter Notebook",
    # Go
    ".go": "Go",
    # C & C++
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cxx": "C++",
    ".cc": "C++",
    ".hpp": "C++",
    ".hxx": "C++",
    # Dart / Flutter
    ".dart": "Dart",
    # Kotlin & Android
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    # Java
    ".java": "Java",
    # JavaScript & TypeScript
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    # Web & UI
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sass": "Sass",
    ".svelte": "Svelte",
    ".vue": "Vue",
    ".astro": "Astro",
    # Systems
    ".rs": "Rust",
    ".cs": "C#",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".dockerfile": "Dockerfile",
    "dockerfile": "Dockerfile",
    ".sql": "SQL",
    ".tex": "TeX",
    ".latex": "TeX",
    ".swift": "Swift",
    ".rb": "Ruby",
    ".php": "PHP",
    ".lua": "Lua",
}

# Ignored path patterns (generated / lock / minified files)
IGNORED_PATTERNS = [
    r"package-lock\.json$",
    r"yarn\.lock$",
    r"pnpm-lock\.yaml$",
    r"go\.sum$",
    r"Cargo\.lock$",
    r"composer\.lock$",
    r"Gemfile\.lock$",
    r"\.min\.(js|css)$",
    r"(^|/)(node_modules|dist|build|\.next|\.git|vendor|Pods)/",
    r"\.(json|yaml|yml|md|txt|csv|svg|png|jpg|jpeg|gif|ico|webp|woff|woff2|ttf|eot)$",
]

LANGUAGE_COLORS = {
    "Python": "#3572A5",
    "Jupyter Notebook": "#DA5B0B",
    "TypeScript": "#3178c6",
    "JavaScript": "#f1e05a",
    "Dart": "#00B4AB",
    "Kotlin": "#A97BFF",
    "Go": "#00ADD8",
    "C": "#555555",
    "C++": "#f34b7d",
    "Rust": "#dea584",
    "C#": "#178600",
    "Java": "#b07219",
    "Shell": "#89e051",
    "Svelte": "#ff3e00",
    "Astro": "#ff5a03",
    "TeX": "#3D6117",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "SCSS": "#c6538c",
    "Dockerfile": "#384d54",
    "SQL": "#e38c00",
    "Swift": "#F05138",
    "Cython": "#fed10a",
    "Other": "#8b949e",
}


def get_token():
    """Retrieve GitHub token from environment or local gh cli."""
    token = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN")
    if not token:
        try:
            token = subprocess.check_output(
                ["gh", "auth", "token"], text=True
            ).strip()
        except Exception:
            pass
    if not token:
        print("Error: No GitHub token found (set GH_PAT or GITHUB_TOKEN).")
        sys.exit(1)
    return token


def github_request(url, token, method="GET", data=None):
    """Execute authenticated HTTP request to GitHub API."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "02loveslollipop-stats-agent",
    }
    req_data = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(
        url, data=req_data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code} for {url}: {body}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Request error for {url}: {e}", file=sys.stderr)
        return None


def fetch_graphql(query, token, variables=None):
    """Execute GraphQL query."""
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    return github_request(
        "https://api.github.com/graphql", token, method="POST", data=payload
    )


def get_all_time_languages(token):
    """Fetch all non-fork repos and aggregate language byte counts."""
    query = """
    query {
      viewer {
        login
        repositories(first: 100, ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER], orderBy: {field: PUSHED_AT, direction: DESC}) {
          nodes {
            nameWithOwner
            isFork
            languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
              edges {
                size
                node {
                  name
                  color
                }
              }
            }
          }
        }
      }
    }
    """
    res = fetch_graphql(query, token)
    if not res or "data" not in res:
        print("Failed to fetch all-time languages.", file=sys.stderr)
        return {}, "02loveslollipop"

    username = res["data"]["viewer"]["login"]
    lang_bytes = {}
    for repo in res["data"]["viewer"]["repositories"]["nodes"]:
        if repo.get("isFork"):
            continue
        for edge in repo.get("languages", {}).get("edges", []):
            name = edge["node"]["name"]
            size = edge["size"]
            # Exclude markup / documentation languages from programming language counts if desired
            if name in ["HTML", "TeX", "Markdown"]:
                continue
            lang_bytes[name] = lang_bytes.get(name, 0) + size

    return lang_bytes, username


def get_recent_activity(token, days=30):
    """Fetch lines of code added in the past N days per language."""
    now = datetime.datetime.now(datetime.timezone.utc)
    since_date = now - datetime.timedelta(days=days)
    since_iso = since_date.isoformat()
    now_iso = now.isoformat()

    query = f"""
    query {{
      viewer {{
        contributionsCollection(from: "{since_iso}", to: "{now_iso}") {{
          commitContributionsByRepository(maxRepositories: 30) {{
            repository {{
              nameWithOwner
            }}
            contributions {{
              totalCount
            }}
          }}
        }}
      }}
    }}
    """
    res = fetch_graphql(query, token)
    if not res or "data" not in res:
        print("Failed to fetch recent contributions.", file=sys.stderr)
        return {}

    repos = res["data"]["viewer"]["contributionsCollection"][
        "commitContributionsByRepository"
    ]
    lang_lines = {}

    for item in repos:
        repo_name = item["repository"]["nameWithOwner"]
        count = item["contributions"]["totalCount"]
        if count == 0:
            continue

        # Fetch commits since date
        commits_url = f"https://api.github.com/repos/{repo_name}/commits?since={since_iso}&per_page=100"
        commits = github_request(commits_url, token)
        if not commits or not isinstance(commits, list) or len(commits) == 0:
            continue

        if len(commits) == 1:
            # Single commit: fetch single commit file diff
            commit_sha = commits[0]["sha"]
            c_url = f"https://api.github.com/repos/{repo_name}/commits/{commit_sha}"
            c_data = github_request(c_url, token)
            if c_data and "files" in c_data:
                for f in c_data["files"]:
                    add_file_additions(f, lang_lines)
        else:
            # Multiple commits: compare parent of earliest commit to latest commit
            earliest_commit = commits[-1]
            latest_sha = commits[0]["sha"]
            parents = earliest_commit.get("parents", [])
            base_sha = parents[0]["sha"] if parents else earliest_commit["sha"]

            comp_url = f"https://api.github.com/repos/{repo_name}/compare/{base_sha}...{latest_sha}"
            comp_data = github_request(comp_url, token)
            if comp_data and "files" in comp_data:
                for f in comp_data["files"]:
                    add_file_additions(f, lang_lines)
                # If earliest commit had no parent (initial commit), also add its own files
                if not parents:
                    c_url = f"https://api.github.com/repos/{repo_name}/commits/{earliest_commit['sha']}"
                    c_data = github_request(c_url, token)
                    if c_data and "files" in c_data:
                        for f in c_data["files"]:
                            add_file_additions(f, lang_lines)
            else:
                # Fallback: iterate commits if compare fails
                for c in commits[:15]:
                    c_url = f"https://api.github.com/repos/{repo_name}/commits/{c['sha']}"
                    c_data = github_request(c_url, token)
                    if c_data and "files" in c_data:
                        for f in c_data["files"]:
                            add_file_additions(f, lang_lines)

    return lang_lines


def add_file_additions(file_obj, lang_lines):
    """Classify file by extension and accumulate addition count."""
    filename = file_obj.get("filename", "")
    additions = file_obj.get("additions", 0)

    # Check ignored patterns
    for pat in IGNORED_PATTERNS:
        if re.search(pat, filename, re.IGNORECASE):
            return

    # Determine extension
    basename = os.path.basename(filename)
    lower_base = basename.lower()
    _, ext = os.path.splitext(lower_base)

    lang = EXTENSION_TO_LANGUAGE.get(ext) or EXTENSION_TO_LANGUAGE.get(
        lower_base
    )
    if not lang:
        return

    # Exclude HTML/TeX from primary coding stats if desired
    if lang in ["HTML", "TeX"]:
        return

    lang_lines[lang] = lang_lines.get(lang, 0) + additions


def format_progress_bar(percentage, length=18):
    """Create a unicode progress bar."""
    filled = int(round((percentage / 100.0) * length))
    filled = max(0, min(length, filled))
    return "█" * filled + "░" * (length - filled)


def format_bytes(size_bytes):
    """Format bytes to human readable string."""
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.0f} KB"
    return f"{size_bytes} B"


def render_markdown_section(all_time, recent):
    """Render the markdown table comparing All-Time and Currently Coding."""
    total_all_time = sum(all_time.values()) or 1
    total_recent = sum(recent.values()) or 1

    sorted_all_time = sorted(
        all_time.items(), key=lambda x: x[1], reverse=True
    )[:6]
    sorted_recent = sorted(recent.items(), key=lambda x: x[1], reverse=True)[:6]

    md = []
    md.append("<!-- START_SECTION:use_to_code -->")
    md.append('<p align="center">')
    md.append(
        '  <img src="./assets/cards/code-ranking.svg" alt="Languages Ranking: All-Time vs Now" width="100%"/>'
    )
    md.append("</p>\n")

    md.append("<details open>")
    md.append("<summary><b>📊 Detailed Breakdown & Activity Metrics</b></summary>")
    md.append("\n")

    md.append(
        "| Rank | 🏆 All-Time Language | Codebase Share | 🔥 Currently Coding (Last 30 Days) | Recent Share |"
    )
    md.append(
        "| :---: | :--- | :--- | :--- | :--- |"
    )

    max_rows = max(len(sorted_all_time), len(sorted_recent))
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣"]

    for i in range(max_rows):
        rank = medals[i] if i < len(medals) else f"{i+1}."

        # All-Time column
        if i < len(sorted_all_time):
            lang_a, size_a = sorted_all_time[i]
            pct_a = (size_a / total_all_time) * 100
            bar_a = format_progress_bar(pct_a, length=12)
            col_a = f"**{lang_a}** ({format_bytes(size_a)})"
            col_a_share = f"`{bar_a}` {pct_a:.1f}%"
        else:
            col_a = "-"
            col_a_share = "-"

        # Recent column
        if i < len(sorted_recent):
            lang_r, lines_r = sorted_recent[i]
            pct_r = (lines_r / total_recent) * 100
            bar_r = format_progress_bar(pct_r, length=12)
            col_r = f"**{lang_r}** (+{lines_r:,} lines)"
            col_r_share = f"`{bar_r}` {pct_r:.1f}%"
        else:
            col_r = "-"
            col_r_share = "-"

        md.append(f"| {rank} | {col_a} | {col_a_share} | {col_r} | {col_r_share} |")

    md.append("\n</details>")
    md.append("<!-- END_SECTION:use_to_code -->")
    return "\n".join(md)


def render_svg_card(all_time, recent, output_path):
    """Render a standalone dark SVG card showing All-Time vs Now rankings."""
    total_all_time = sum(all_time.values()) or 1
    total_recent = sum(recent.values()) or 1

    sorted_all_time = sorted(
        all_time.items(), key=lambda x: x[1], reverse=True
    )[:5]
    sorted_recent = sorted(recent.items(), key=lambda x: x[1], reverse=True)[:5]

    today_str = datetime.date.today().strftime("%B %d, %Y")

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 820 330" width="820" height="330" fill="none">
  <defs>
    <style>
      .header {{ font: 600 17px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; fill: #F85D7F; }}
      .subhead {{ font: 600 14px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; fill: #F8D866; }}
      .label {{ font: 500 13px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; fill: #e6edf3; }}
      .value {{ font: 400 12px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; fill: #8b949e; }}
      .footer {{ font: 400 11px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; fill: #6e7681; }}
    </style>
    <linearGradient id="cardGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0D1117" />
      <stop offset="100%" stop-color="#161b22" />
    </linearGradient>
  </defs>

  <!-- Background Card -->
  <rect x="1.5" y="1.5" width="817" height="327" rx="12" fill="url(#cardGrad)" stroke="#7F3FBF" stroke-width="2"/>

  <!-- Title Banner -->
  <text x="30" y="38" class="header">⚡ Languages &amp; Tools Ranking</text>
  <text x="790" y="38" text-anchor="end" class="footer">Updated: {today_str}</text>
  <line x1="30" y1="52" x2="790" y2="52" stroke="#30363d" stroke-width="1"/>

  <!-- Column 1: All-Time Ranking -->
  <g transform="translate(30, 72)">
    <text x="0" y="0" class="subhead">🏆 All-Time Codebase</text>
"""

    # Add left column items
    y_offset = 24
    for i, (lang, size) in enumerate(sorted_all_time):
        color = LANGUAGE_COLORS.get(lang, "#8b949e")
        pct = (size / total_all_time) * 100
        bar_width = int((pct / 100.0) * 230)
        bar_width = max(6, min(230, bar_width))
        formatted_size = format_bytes(size)

        svg += f"""
    <!-- Item {i+1}: {lang} -->
    <circle cx="6" cy="{y_offset - 4}" r="5" fill="{color}"/>
    <text x="20" y="{y_offset}" class="label">{lang}</text>
    <text x="350" y="{y_offset}" text-anchor="end" class="value">{formatted_size} ({pct:.1f}%)</text>
    <!-- Progress Bar Track & Fill -->
    <rect x="20" y="{y_offset + 8}" width="330" height="7" rx="3.5" fill="#21262d"/>
    <rect x="20" y="{y_offset + 8}" width="{bar_width * 330 // 230}" height="7" rx="3.5" fill="{color}"/>
"""
        y_offset += 42

    svg += """  </g>

  <!-- Divider Line -->
  <line x1="410" y1="65" x2="410" y2="280" stroke="#30363d" stroke-dasharray="4 4" stroke-width="1"/>

  <!-- Column 2: Currently Coding (Past 30 Days) -->
  <g transform="translate(435, 72)">
    <text x="0" y="0" class="subhead">🔥 Currently Coding (Past 30 Days)</text>
"""

    # Add right column items
    y_offset = 24
    for i, (lang, lines) in enumerate(sorted_recent):
        color = LANGUAGE_COLORS.get(lang, "#8b949e")
        pct = (lines / total_recent) * 100
        bar_width = int((pct / 100.0) * 230)
        bar_width = max(6, min(230, bar_width))

        svg += f"""
    <!-- Item {i+1}: {lang} -->
    <circle cx="6" cy="{y_offset - 4}" r="5" fill="{color}"/>
    <text x="20" y="{y_offset}" class="label">{lang}</text>
    <text x="350" y="{y_offset}" text-anchor="end" class="value">+{lines:,} lines ({pct:.1f}%)</text>
    <!-- Progress Bar Track & Fill -->
    <rect x="20" y="{y_offset + 8}" width="330" height="7" rx="3.5" fill="#21262d"/>
    <rect x="20" y="{y_offset + 8}" width="{bar_width * 330 // 230}" height="7" rx="3.5" fill="{color}"/>
"""
        y_offset += 42

    svg += """  </g>

  <!-- Footer Info -->
  <line x1="30" y1="298" x2="790" y2="298" stroke="#30363d" stroke-width="1"/>
  <text x="30" y="315" class="footer">✨ Dynamic statistics computed weekly from commits &amp; language distributions</text>
</svg>"""

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"Generated SVG card at: {output_path}")


def update_readme(readme_path, rendered_section):
    """Update README.md between comment delimiters."""
    if not os.path.exists(readme_path):
        print(f"File {readme_path} not found.", file=sys.stderr)
        return False

    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()

    start_delim = "<!-- START_SECTION:use_to_code -->"
    end_delim = "<!-- END_SECTION:use_to_code -->"

    pattern = re.compile(
        rf"{re.escape(start_delim)}.*?{re.escape(end_delim)}", re.DOTALL
    )

    if pattern.search(content):
        new_content = pattern.sub(rendered_section, content)
    else:
        # If delimiters don't exist yet, insert after '## Use To Code'
        heading = "## Use To Code"
        if heading in content:
            new_content = content.replace(
                heading, f"{heading}\n\n{rendered_section}"
            )
        else:
            new_content = content + f"\n\n{heading}\n\n{rendered_section}\n"

    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"Updated {readme_path} with dynamic ranking section.")
    return True


def main():
    token = get_token()
    print("1. Fetching all-time language stats...")
    all_time, username = get_all_time_languages(token)
    print(f"   Found {len(all_time)} languages across {username}'s repositories.")

    print("2. Fetching recent 30-day activity & line additions...")
    recent = get_recent_activity(token, days=30)
    print(f"   Found {len(recent)} languages active in the last 30 days.")

    # Paths
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    readme_path = os.path.join(base_dir, "README.md")
    svg_path = os.path.join(base_dir, "assets", "cards", "code-ranking.svg")

    print("3. Generating SVG card...")
    render_svg_card(all_time, recent, svg_path)

    print("4. Updating README.md...")
    section_md = render_markdown_section(all_time, recent)
    update_readme(readme_path, section_md)

    print("Done!")


if __name__ == "__main__":
    main()
