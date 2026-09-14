#!/usr/bin/env python3
"""
update_weekly_repos.py

Analyzes weekly GitHub contributions to identify top contributed repositories
in the past 7 days and renders a stacked-bar card (assets/cards/weekly-repos.svg)
showing the language breakdown for each repository.
"""

import os
import sys
import json
import re
import datetime
import urllib.request
import urllib.error
import subprocess

# Language Colors (consistent with profile widgets)
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
    "LaTeX": "#3D6117",
    "TeX": "#3D6117",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "SCSS": "#c6538c",
    "Dockerfile": "#384d54",
    "SQL": "#e38c00",
    "Swift": "#F05138",
    "Cython": "#fed10a",
    "CMake": "#064F8C",
    "Makefile": "#427819",
    "PowerShell": "#012456",
    "Sage": "#4F88C0",
    "Other": "#8b949e",
}

LANGUAGE_ALIASES = {
    "TeX": "LaTeX",
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


def get_weekly_repos(token, days=7, limit=4):
    """Fetch top contributed repositories in the past N days and their language distributions."""
    now = datetime.datetime.now(datetime.timezone.utc)
    since_date = now - datetime.timedelta(days=days)
    since_iso = since_date.isoformat()
    now_iso = now.isoformat()

    query = f"""
    query {{
      viewer {{
        login
        contributionsCollection(from: "{since_iso}", to: "{now_iso}") {{
          commitContributionsByRepository(maxRepositories: 15) {{
            repository {{
              name
              nameWithOwner
              isPrivate
              description
              url
              primaryLanguage {{
                name
                color
              }}
              languages(first: 8, orderBy: {{field: SIZE, direction: DESC}}) {{
                totalSize
                edges {{
                  size
                  node {{
                    name
                    color
                  }}
                }}
              }}
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
    if not res or "data" not in res or not res["data"].get("viewer"):
        print("Failed to fetch weekly repository contributions.", file=sys.stderr)
        return []

    viewer_login = res["data"]["viewer"].get("login", "02loveslollipop")
    contribs = res["data"]["viewer"]["contributionsCollection"].get(
        "commitContributionsByRepository", []
    )

    results = []
    meta_repo = f"{viewer_login}/{viewer_login}".lower()

    for item in contribs:
        repo = item.get("repository")
        if not repo or not repo.get("nameWithOwner"):
            continue
        commits = item.get("contributions", {}).get("totalCount", 0)
        if commits == 0:
            continue

        # Filter out meta profile repo unless there are very few active repos
        if repo["nameWithOwner"].lower() == meta_repo and len(contribs) > 3:
            continue

        raw_edges = repo.get("languages", {}).get("edges", []) or []
        langs = []
        total_size = 0
        for edge in raw_edges:
            name = edge["node"]["name"]
            size = edge.get("size", 0)
            name = LANGUAGE_ALIASES.get(name, name)
            langs.append({"name": name, "size": size})
            total_size += size

        total_size = total_size or 1

        # Calculate percentages
        lang_percentages = []
        for l in langs:
            pct = (l["size"] / total_size) * 100.0
            if pct >= 0.5:  # filter negligible <0.5%
                lang_percentages.append(
                    {
                        "name": l["name"],
                        "size": l["size"],
                        "percentage": pct,
                        "color": LANGUAGE_COLORS.get(l["name"], "#8b949e"),
                    }
                )

        results.append(
            {
                "name": repo["name"],
                "nameWithOwner": repo["nameWithOwner"],
                "isPrivate": repo.get("isPrivate", False),
                "url": repo.get("url", f"https://github.com/{repo['nameWithOwner']}"),
                "commits": commits,
                "languages": lang_percentages,
            }
        )

        if len(results) >= limit:
            break

    return results


def render_weekly_repos_card(repos, output_path):
    """Render a standalone dark SVG card showing top contributed repos with stacked bars."""
    today_str = datetime.date.today().strftime("%B %d, %Y")

    num_repos = len(repos)
    # Calculate height dynamically based on number of repos
    row_height = 76
    card_height = max(240, 68 + num_repos * row_height + 18)
    card_width = 820

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {card_width} {card_height}" width="{card_width}" height="{card_height}" fill="none">
  <style>
    * {{
      font-family: 'Segoe UI', Ubuntu, "Helvetica Neue", Sans-Serif;
    }}
    .header {{
      font-weight: 700;
      font-size: 18px;
      fill: #fe428e;
    }}
    .footer {{
      font-weight: 400;
      font-size: 12px;
      fill: #a9fef7;
      opacity: 0.75;
    }}
    .repo-name {{
      font-weight: 700;
      font-size: 14px;
      fill: #fe428e;
    }}
    .commit-count {{
      font-weight: 600;
      font-size: 12px;
      fill: #a9fef7;
    }}
    .lang-legend {{
      font-weight: 500;
      font-size: 11px;
      fill: #ffffff;
    }}
    .private-badge {{
      font-weight: 600;
      font-size: 10px;
      fill: #f8d847;
    }}
  </style>

  <!-- Background Card -->
  <rect x="1" y="1" width="{card_width - 2}" height="{card_height - 2}" rx="6" fill="#141321" stroke="#7F3FBF" stroke-width="1.5"/>

  <!-- Title Banner -->
  <!-- Material Symbols: Mode Heat (Fire) Icon -->
  <svg x="25" y="18" width="18" height="18" viewBox="0 -960 960 960" fill="#fe428e">
    <path d="M160-400q0-116 71.5-225T428-811q17-11 34.5-.5T480-780v72q0 34 23.5 57t57.5 23q18 0 33.5-7.5T622-658q8-9 18-12.5t19 2.5q66 45 103.5 116T800-400q0 95-49 171.5T622-113q23-26 35.5-58t12.5-67q0-38-14-71.5T615-370L480-502 346-370q-28 27-42 60.5T290-238q0 35 12.5 67t35.5 58q-80-39-129-115.5T160-400Zm320-18 92 90q18 18 28 41t10 49q0 53-38 90.5T480-110q-54 0-92-37.5T350-238q0-26 9.5-49t28.5-41l92-90Z"/>
  </svg>
  <text x="49" y="33" class="header">Top Contributed Repositories (This Week)</text>
  <text x="795" y="33" text-anchor="end" class="footer">Past 7 Days · Updated: {today_str}</text>
  <line x1="25" y1="46" x2="795" y2="46" stroke="#7F3FBF" stroke-opacity="0.3" stroke-width="1"/>
"""

    bar_width = 770
    bar_height = 9
    start_x = 25

    y_offset = 72

    if not repos:
        svg += """
  <text x="410" y="140" text-anchor="middle" class="footer">No public or private commit activity recorded this week.</text>
"""
    else:
        for idx, repo in enumerate(repos):
            repo_name = repo["nameWithOwner"]
            commits = repo["commits"]
            commit_label = f"+{commits} {'commit' if commits == 1 else 'commits'} this week"
            langs = repo["languages"]

            # Repo Title Row
            svg += f"""
  <!-- Repo {idx+1}: {repo_name} -->
  <g transform="translate(0, {y_offset})">
    <!-- Folder Icon -->
    <svg x="25" y="-12" width="15" height="15" viewBox="0 -960 960 960" fill="#f8d847">
      <path d="M160-160q-33 0-56.5-23.5T80-240v-480q0-33 23.5-56.5T160-800h240l80 80h320q33 0 56.5 23.5T880-640v400q0 33-23.5 56.5T800-160H160Z"/>
    </svg>
    <text x="46" y="0" class="repo-name">{repo_name}</text>
"""
            if repo["isPrivate"]:
                svg += """
    <rect x="220" y="-12" width="52" height="16" rx="4" fill="#222036" stroke="#7F3FBF" stroke-width="1"/>
    <text x="246" y="0" text-anchor="middle" class="private-badge">Private</text>
"""

            svg += f"""    <text x="795" y="0" text-anchor="end" class="commit-count">{commit_label}</text>

    <!-- Stacked Bar -->
    <mask id="bar-mask-{idx}">
      <rect x="{start_x}" y="9" width="{bar_width}" height="{bar_height}" rx="4.5" fill="white"/>
    </mask>
    <rect x="{start_x}" y="9" width="{bar_width}" height="{bar_height}" rx="4.5" fill="#222036"/>
"""

            # Stacked bar segments
            seg_x = start_x
            for l in langs:
                seg_w = (l["percentage"] / 100.0) * bar_width
                if seg_w > 0:
                    svg += f'    <rect x="{seg_x:.2f}" y="9" width="{seg_w:.2f}" height="{bar_height}" fill="{l["color"]}" mask="url(#bar-mask-{idx})"/>\n'
                    seg_x += seg_w

            # Language Legend underneath
            legend_y = 32
            cur_leg_x = start_x
            for l in langs:
                lang_label = f"{l['name']} {l['percentage']:.1f}%"
                approx_width = len(lang_label) * 7.2 + 18
                svg += f"""    <circle cx="{cur_leg_x + 4}" cy="{legend_y - 4}" r="3.5" fill="{l['color']}"/>
    <text x="{cur_leg_x + 12}" y="{legend_y}" class="lang-legend">{lang_label}</text>
"""
                cur_leg_x += approx_width

            svg += "  </g>\n"

            # Divider line between repos
            if idx < len(repos) - 1:
                div_y = y_offset + 52
                svg += f'  <line x1="25" y1="{div_y}" x2="795" y2="{div_y}" stroke="#7F3FBF" stroke-opacity="0.2" stroke-dasharray="3 3" stroke-width="1"/>\n'

            y_offset += row_height

    svg += "</svg>"

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"Generated weekly repos SVG card at: {output_path}")


def render_markdown_section(repos):
    """Render markdown section for README.md with card and crawler comments."""
    md = []
    md.append("<!-- START_SECTION:weekly_repos -->")
    md.append('<p align="center">')
    md.append(
        '  <img src="./assets/cards/weekly-repos.svg" alt="Top Contributed Repositories (This Week)" width="100%"/>'
    )
    md.append("</p>\n")

    # Hidden crawler data
    md.append("<!--")
    md.append("Weekly Contributed Repositories Data:")
    md.append("| Repository | Commits This Week | Primary Languages |")
    md.append("| :--- | :--- | :--- |")
    for r in repos:
        lang_str = ", ".join([f"{l['name']} ({l['percentage']:.1f}%)" for l in r["languages"]])
        md.append(f"| {r['nameWithOwner']} | {r['commits']} commits | {lang_str} |")
    md.append("-->")
    md.append("<!-- END_SECTION:weekly_repos -->")
    return "\n".join(md)


def update_readme(template_path, readme_path, section_md):
    """Update README.md with weekly repos section without erasing other sections."""
    target_file = readme_path if os.path.exists(readme_path) else template_path
    with open(target_file, "r", encoding="utf-8") as f:
        content = f.read()

    placeholder_pattern = re.compile(
        r"(\{weekly[\s_]+repos\}|\{weekly[\s_]+contributions\}|<!--\s*WEEKLY_REPOS\s*-->)",
        re.IGNORECASE,
    )
    start_delim = "<!-- START_SECTION:weekly_repos -->"
    end_delim = "<!-- END_SECTION:weekly_repos -->"
    section_pattern = re.compile(
        rf"{re.escape(start_delim)}.*?{re.escape(end_delim)}", re.DOTALL
    )

    if placeholder_pattern.search(content):
        new_content = placeholder_pattern.sub(section_md, content)
    elif section_pattern.search(content):
        new_content = section_pattern.sub(section_md, content)
    else:
        end_use_to_code = "<!-- END_SECTION:use_to_code -->"
        if end_use_to_code in content:
            new_content = content.replace(
                end_use_to_code, f"{end_use_to_code}\n\n{section_md}"
            )
        else:
            new_content = content + f"\n\n{section_md}\n"

    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"Updated {readme_path} with weekly repos section.")
    return True

    return False


def main():
    token = get_token()
    print("1. Fetching top contributed repositories for the past 7 days...")
    repos = get_weekly_repos(token, days=7, limit=4)
    print(f"   Found {len(repos)} active repositories this week.")
    for r in repos:
        print(f"   - {r['nameWithOwner']}: {r['commits']} commits")

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    template_path = os.path.join(base_dir, "TEMPLATE_README.md")
    readme_path = os.path.join(base_dir, "README.md")
    svg_path = os.path.join(base_dir, "assets", "cards", "weekly-repos.svg")

    print("2. Generating SVG card with stacked bars...")
    render_weekly_repos_card(repos, svg_path)

    print("3. Updating README section...")
    section_md = render_markdown_section(repos)
    update_readme(template_path, readme_path, section_md)

    print("Done!")


if __name__ == "__main__":
    main()
