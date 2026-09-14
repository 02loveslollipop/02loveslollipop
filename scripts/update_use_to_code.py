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
    """Fetch all non-fork repos (public and private) across all pages and aggregate language byte counts."""
    query = """
    query ($after: String) {
      viewer {
        login
        repositories(first: 100, after: $after, ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER], orderBy: {field: PUSHED_AT, direction: DESC}) {
          pageInfo {
            hasNextPage
            endCursor
          }
          nodes {
            nameWithOwner
            isFork
            isPrivate
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
    has_next_page = True
    after_cursor = None
    lang_bytes = {}
    username = "02loveslollipop"
    public_count = 0
    private_count = 0

    while has_next_page:
        res = fetch_graphql(query, token, variables={"after": after_cursor})
        if not res or "data" not in res or not res["data"].get("viewer"):
            break

        viewer = res["data"]["viewer"]
        username = viewer.get("login", username)
        repos_data = viewer.get("repositories", {})

        for repo in repos_data.get("nodes", []):
            if not repo or repo.get("isFork"):
                continue
            if repo.get("isPrivate"):
                private_count += 1
            else:
                public_count += 1

            for edge in repo.get("languages", {}).get("edges", []) or []:
                if not edge or not edge.get("node"):
                    continue
                name = edge["node"]["name"]
                size = edge.get("size", 0)
                # Exclude pure markup / non-code documentation from programming language metrics
                if name in ["HTML", "TeX", "Markdown"]:
                    continue
                lang_bytes[name] = lang_bytes.get(name, 0) + size

        page_info = repos_data.get("pageInfo", {})
        has_next_page = page_info.get("hasNextPage", False)
        after_cursor = page_info.get("endCursor")

    print(f"   Analyzed {public_count} public and {private_count} private repositories across all pages.")
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
        if not item or not item.get("repository") or not item["repository"].get("nameWithOwner"):
            continue
        repo_name = item["repository"]["nameWithOwner"]
        count = item.get("contributions", {}).get("totalCount", 0)
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
    """Render the section for README.md with only the card visible and data for crawlers."""
    total_all_time = sum(all_time.values()) or 1
    total_recent = sum(recent.values()) or 1

    sorted_all_time = sorted(
        all_time.items(), key=lambda x: x[1], reverse=True
    )[:10]
    sorted_recent = sorted(recent.items(), key=lambda x: x[1], reverse=True)[:10]

    md = []
    md.append("<!-- START_SECTION:use_to_code -->")
    md.append('<p align="center">')
    md.append(
        '  <img src="./assets/cards/code-ranking.svg" alt="Languages &amp; Tools Ranking: All-Time vs Currently Coding" width="100%"/>'
    )
    md.append("</p>\n")

    # Data for search engines, web crawlers, and accessibility (hidden from visual rendering)
    md.append("<!--")
    md.append("Data for search engine crawlers and screen readers:")
    md.append("| Rank | All-Time Language | Codebase Share | Currently Coding (Last 30 Days) | Recent Share |")
    md.append("| :--- | :--- | :--- | :--- | :--- |")

    max_rows = max(len(sorted_all_time), len(sorted_recent))
    for i in range(max_rows):
        rank = f"{i+1}"
        col_a = (
            f"{sorted_all_time[i][0]} ({format_bytes(sorted_all_time[i][1])})"
            if i < len(sorted_all_time)
            else "-"
        )
        col_a_share = (
            f"{(sorted_all_time[i][1] / total_all_time) * 100:.1f}%"
            if i < len(sorted_all_time)
            else "-"
        )
        col_r = (
            f"{sorted_recent[i][0]} (+{sorted_recent[i][1]:,} lines)"
            if i < len(sorted_recent)
            else "-"
        )
        col_r_share = (
            f"{(sorted_recent[i][1] / total_recent) * 100:.1f}%"
            if i < len(sorted_recent)
            else "-"
        )
        md.append(f"| {rank} | {col_a} | {col_a_share} | {col_r} | {col_r_share} |")

    md.append("-->")
    md.append("<!-- END_SECTION:use_to_code -->")
    return "\n".join(md)


def render_svg_card(all_time, recent, output_path):
    """Render a standalone dark SVG card showing All-Time vs Now rankings (Top 10)."""
    total_all_time = sum(all_time.values()) or 1
    total_recent = sum(recent.values()) or 1

    sorted_all_time = sorted(
        all_time.items(), key=lambda x: x[1], reverse=True
    )[:10]
    sorted_recent = sorted(recent.items(), key=lambda x: x[1], reverse=True)[:10]

    today_str = datetime.date.today().strftime("%B %d, %Y")

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 820 440" width="820" height="440" fill="none">
  <style>
    * {{
      font-family: 'Segoe UI', Ubuntu, "Helvetica Neue", Sans-Serif;
    }}
    .header {{
      font-weight: 700;
      font-size: 18px;
      fill: #fe428e;
    }}
    .subhead-trophy {{
      font-weight: 600;
      font-size: 14px;
      fill: #f8d847;
    }}
    .subhead-fire {{
      font-weight: 600;
      font-size: 14px;
      fill: #fe428e;
    }}
    .label {{
      font-weight: 500;
      font-size: 13px;
      fill: #a9fef7;
    }}
    .value {{
      font-weight: 400;
      font-size: 12px;
      fill: #ffffff;
    }}
    .footer {{
      font-weight: 400;
      font-size: 12px;
      fill: #a9fef7;
      opacity: 0.75;
    }}
  </style>

  <!-- Background Card -->
  <rect x="1" y="1" width="818" height="438" rx="6" fill="#141321" stroke="#7F3FBF" stroke-width="1.5"/>

  <!-- Title Banner -->
  <text x="25" y="33" class="header">Languages &amp; Tools Ranking</text>
  <text x="795" y="33" text-anchor="end" class="footer">Updated: {today_str}</text>
  <line x1="25" y1="46" x2="795" y2="46" stroke="#7F3FBF" stroke-opacity="0.3" stroke-width="1"/>

  <!-- Divider Line Between Columns -->
  <line x1="410" y1="56" x2="410" y2="420" stroke="#7F3FBF" stroke-opacity="0.25" stroke-dasharray="3 3" stroke-width="1"/>

  <!-- Column 1: All-Time Ranking (Top 10) -->
  <g transform="translate(25, 70)">
    <!-- Material Symbols: Trophy (Rounded Filled) -->
    <svg x="0" y="-15" width="18" height="18" viewBox="0 -960 960 960" fill="#f8d847">
      <path d="M284-526v-166H180v44q0 45 29.5 78.5T284-526Zm392 0q45-10 74.5-43.5T780-648v-44H676v166ZM450-180v-148q-54-11-96-46.5T296-463q-74-8-125-60t-51-125v-44q0-24.75 17.63-42.38Q155.25-752 180-752h104v-28q0-24.75 17.63-42.38Q319.25-840 344-840h272q24.75 0 42.38 17.62Q676-804.75 676-780v28h104q24.75 0 42.38 17.62Q840-716.75 840-692v44q0 73-51 125t-125 60q-16 53-58 88.5T510-328v148h122q12.75 0 21.38 8.68 8.62 8.67 8.62 21.5 0 12.82-8.62 21.32-8.63 8.5-21.38 8.5H328q-12.75 0-21.37-8.68-8.63-8.67-8.63-21.5 0-12.82 8.63-21.32 8.62-8.5 21.37-8.5h122Z"/>
    </svg>
    <text x="24" y="0" class="subhead-trophy">All-Time Codebase</text>
"""

    # Add left column items (Top 10)
    y_offset = 26
    for i, (lang, size) in enumerate(sorted_all_time):
        color = LANGUAGE_COLORS.get(lang, "#8b949e")
        pct = (size / total_all_time) * 100
        bar_width = max(5, int((pct / 100.0) * 344))
        formatted_size = format_bytes(size)

        svg += f"""
    <!-- Item {i+1}: {lang} -->
    <circle cx="5" cy="{y_offset - 4}" r="4" fill="{color}"/>
    <text x="16" y="{y_offset}" class="label">{lang}</text>
    <text x="360" y="{y_offset}" text-anchor="end" class="value">{formatted_size} ({pct:.1f}%)</text>
    <rect x="16" y="{y_offset + 6}" width="344" height="5" rx="2.5" fill="#222036"/>
    <rect x="16" y="{y_offset + 6}" width="{bar_width}" height="5" rx="2.5" fill="{color}"/>
"""
        y_offset += 34

    svg += """  </g>

  <!-- Column 2: Currently Coding (Past 30 Days - Top 10) -->
  <g transform="translate(435, 70)">
    <!-- Material Symbols: Mode Heat (Rounded Filled) -->
    <svg x="0" y="-15" width="18" height="18" viewBox="0 -960 960 960" fill="#fe428e">
      <path d="M160-400q0-116 71.5-225T428-811q17-11 34.5-.5T480-780v72q0 34 23.5 57t57.5 23q18 0 33.5-7.5T622-658q8-9 18-12.5t19 2.5q66 45 103.5 116T800-400q0 95-49 171.5T622-113q23-26 35.5-58t12.5-67q0-38-14-71.5T615-370L480-502 346-370q-28 27-42 60.5T290-238q0 35 12.5 67t35.5 58q-80-39-129-115.5T160-400Zm320-18 92 90q18 18 28 41t10 49q0 53-38 90.5T480-110q-54 0-92-37.5T350-238q0-26 9.5-49t28.5-41l92-90Z"/>
    </svg>
    <text x="24" y="0" class="subhead-fire">Currently Coding (Past 30 Days)</text>
"""

    # Add right column items (Top 10)
    y_offset = 26
    for i, (lang, lines) in enumerate(sorted_recent):
        color = LANGUAGE_COLORS.get(lang, "#8b949e")
        pct = (lines / total_recent) * 100
        bar_width = max(5, int((pct / 100.0) * 344))

        svg += f"""
    <!-- Item {i+1}: {lang} -->
    <circle cx="5" cy="{y_offset - 4}" r="4" fill="{color}"/>
    <text x="16" y="{y_offset}" class="label">{lang}</text>
    <text x="360" y="{y_offset}" text-anchor="end" class="value">+{lines:,} lines ({pct:.1f}%)</text>
    <rect x="16" y="{y_offset + 6}" width="344" height="5" rx="2.5" fill="#222036"/>
    <rect x="16" y="{y_offset + 6}" width="{bar_width}" height="5" rx="2.5" fill="{color}"/>
"""
        y_offset += 34

    svg += """  </g>
</svg>"""

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"Generated SVG card at: {output_path}")


def update_readme(template_path, readme_path, rendered_section):
    """Render README.md from TEMPLATE_README.md by replacing {use to code}."""
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            template_content = f.read()

        placeholder_pattern = re.compile(
            r"(\{use[\s_]+to[\s_]+code\}|<!--\s*USE_TO_CODE\s*-->)", re.IGNORECASE
        )
        if placeholder_pattern.search(template_content):
            new_content = placeholder_pattern.sub(rendered_section, template_content)
        else:
            heading = "## Use To Code"
            if heading in template_content:
                new_content = template_content.replace(
                    heading, f"{heading}\n\n{rendered_section}"
                )
            else:
                new_content = template_content + f"\n\n{heading}\n\n{rendered_section}\n"

        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"Successfully rendered {readme_path} from {template_path}.")
        return True

    # Fallback to editing README.md directly if template does not exist
    if not os.path.exists(readme_path):
        print(f"Neither {template_path} nor {readme_path} found.", file=sys.stderr)
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
    template_path = os.path.join(base_dir, "TEMPLATE_README.md")
    readme_path = os.path.join(base_dir, "README.md")
    svg_path = os.path.join(base_dir, "assets", "cards", "code-ranking.svg")

    print("3. Generating SVG card...")
    render_svg_card(all_time, recent, svg_path)

    print("4. Rendering README.md from template...")
    section_md = render_markdown_section(all_time, recent)
    update_readme(template_path, readme_path, section_md)

    print("Done!")


if __name__ == "__main__":
    main()
