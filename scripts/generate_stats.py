#!/usr/bin/env python3
"""
Generates self-contained, animated SVG graphics from live GitHub data.

No third-party image services are used at render time — this script calls the
GitHub GraphQL API once (via the scheduled Action), computes the numbers, and
writes plain SVGs with SMIL animation baked in. GitHub strips <script> and
<style> tags from README-embedded SVGs, so all animation here uses SMIL
(<animate>, <animateTransform>) and all styling is inline attributes.

Outputs (written to assets/):
  stats.svg   - total contributions in the last year, animated count-up
  streak.svg  - current + longest contribution streak
  langs.svg   - top languages by bytes, animated bar chart
  year.svg    - contribution activity heatmap

Requires env vars: GITHUB_TOKEN, GITHUB_USERNAME
"""
import os
import sys
import json
import datetime
import urllib.request

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME")

API_URL = "https://api.github.com/graphql"

BG = "#0D1117"
FG = "#00E5FF"
FG_DIM = "#8B949E"
TEXT = "#C9D1D9"
FONT = "'JetBrains Mono','SFMono-Regular',Consolas,monospace"

LANG_COLORS = {
    "Python": "#3572A5", "JavaScript": "#f1e05a", "TypeScript": "#3178c6",
    "HTML": "#e34c26", "CSS": "#563d7c", "Dart": "#00B4AB", "Java": "#b07219",
    "Shell": "#89e051", "Dockerfile": "#384d54", "C++": "#f34b7d", "C": "#555555",
}


def gql(query: str, variables: dict) -> dict:
    req = urllib.request.Request(
        API_URL,
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Authorization": f"bearer {GITHUB_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def fetch_contribution_days(username: str):
    query = """
    query($login: String!) {
      user(login: $login) {
        contributionsCollection {
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays { date contributionCount }
            }
          }
        }
      }
    }
    """
    data = gql(query, {"login": username})
    cal = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    weeks = [w["contributionDays"] for w in cal["weeks"]]
    days = [d for w in weeks for d in w]
    return cal["totalContributions"], days, weeks


def fetch_top_languages(username: str, max_repos: int = 100):
    query = """
    query($login: String!, $count: Int!) {
      user(login: $login) {
        repositories(first: $count, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
          nodes {
            languages(first: 8, orderBy: {field: SIZE, direction: DESC}) {
              edges { size node { name color } }
            }
          }
        }
      }
    }
    """
    data = gql(query, {"login": username, "count": max_repos})
    totals = {}
    colors = {}
    for repo in data["data"]["user"]["repositories"]["nodes"]:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            totals[name] = totals.get(name, 0) + edge["size"]
            colors[name] = edge["node"]["color"] or LANG_COLORS.get(name, FG_DIM)
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:5]
    total_bytes = sum(totals.values()) or 1
    return [(name, size, size / total_bytes, colors.get(name, FG_DIM)) for name, size in ranked]


def compute_streaks(days):
    days_sorted = sorted(days, key=lambda d: d["date"])
    today = datetime.date.today()

    longest = current = 0
    run = 0
    for d in days_sorted:
        if d["contributionCount"] > 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0

    # current streak: walk backwards from most recent day
    for d in reversed(days_sorted):
        d_date = datetime.date.fromisoformat(d["date"])
        if d_date > today:
            continue
        if d["contributionCount"] > 0:
            current += 1
        else:
            break
    return current, longest


def svg_header(width, height):
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" font-family="{FONT}">'
        f'<rect width="100%" height="100%" rx="10" fill="{BG}"/>'
    )


def make_stats_svg(total_contributions: int) -> str:
    width, height = 432, 100
    svg = [svg_header(width, height)]
    svg.append(
        f'<text x="30" y="45" fill="{FG_DIM}" font-size="13" letter-spacing="2">'
        f'CONTRIBUTIONS · LAST YEAR</text>'
    )
    svg.append(
        f'<text x="30" y="70" fill="{FG}" font-size="36" font-weight="700" opacity="0">'
        f'{total_contributions:,}'
        f'<animate attributeName="opacity" from="0" to="1" dur="0.8s" begin="0.1s" fill="freeze"/>'
        f'</text>'
    )
    svg.append("</svg>")
    return "".join(svg)


def make_streak_svg(current: int, longest: int) -> str:
    width, height = 432, 100
    svg = [svg_header(width, height)]
    svg.append(
        f'<text x="30" y="40" fill="{FG_DIM}" font-size="13" letter-spacing="2">CURRENT STREAK</text>'
    )
    svg.append(
        f'<text x="30" y="70" fill="{FG}" font-size="26" font-weight="700" opacity="0">{current} days'
        f'<animate attributeName="opacity" from="0" to="1" dur="0.6s" begin="0.1s" fill="freeze"/></text>'
    )
    svg.append(
        f'<text x="230" y="40" fill="{FG_DIM}" font-size="13" letter-spacing="2">LONGEST STREAK</text>'
    )
    svg.append(
        f'<text x="230" y="70" fill="{TEXT}" font-size="26" font-weight="700" opacity="0">{longest} days'
        f'<animate attributeName="opacity" from="0" to="1" dur="0.6s" begin="0.3s" fill="freeze"/></text>'
    )
    svg.append("</svg>")
    return "".join(svg)


def make_langs_svg(langs) -> str:
    width = 432
    row_h = 34
    height = 30 + row_h * max(len(langs), 1)
    svg = [svg_header(width, height)]
    svg.append(
        f'<text x="30" y="24" fill="{FG_DIM}" font-size="13" letter-spacing="2">TOP LANGUAGES</text>'
    )
    bar_max_w = 230
    y = 45
    for i, (name, size, frac, color) in enumerate(langs):
        pct = round(frac * 100, 1)
        bar_w = max(4, bar_max_w * frac)
        delay = 0.1 + i * 0.12
        svg.append(f'<text x="30" y="{y + 14}" fill="{TEXT}" font-size="13">{name}</text>')
        svg.append(
            f'<rect x="150" y="{y}" width="{bar_max_w}" height="10" rx="5" fill="#21262D"/>'
        )
        svg.append(
            f'<rect x="150" y="{y}" width="0" height="10" rx="5" fill="{color}">'
            f'<animate attributeName="width" from="0" to="{bar_w:.1f}" dur="0.9s" '
            f'begin="{delay:.2f}s" fill="freeze" calcMode="spline" keySplines="0.25 0.1 0.25 1"/>'
            f'</rect>'
        )
        svg.append(
            f'<text x="{150 + bar_max_w + 12}" y="{y + 9}" fill="{FG_DIM}" font-size="11">{pct}%</text>'
        )
        y += row_h
    svg.append("</svg>")
    return "".join(svg)


def make_year_svg(weeks) -> str:
    """weeks: list of week-lists of {date, contributionCount}, oldest first."""
    cell = 10
    gap = 3
    left_pad = 26
    top_pad = 16
    n_weeks = len(weeks)
    width = left_pad + n_weeks * (cell + gap)
    height = top_pad + 7 * (cell + gap) + 20

    counts = [d["contributionCount"] for w in weeks for d in w]
    max_count = max(counts) if counts else 1
    max_count = max(max_count, 1)

    def color_for(count):
        if count == 0:
            return "#161B22"
        frac = min(count / max_count, 1.0)
        levels = ["#0E4B52", "#116877", "#0FA3B1", "#00D4E8", "#00E5FF"]
        idx = min(int(frac * (len(levels) - 1)), len(levels) - 1)
        return levels[idx]

    svg = [svg_header(width, height)]
    month_labels_done = set()
    for wi, week in enumerate(weeks):
        x = left_pad + wi * (cell + gap)
        if week:
            d = datetime.date.fromisoformat(week[0]["date"])
            key = (d.year, d.month)
            if d.day <= 7 and key not in month_labels_done:
                month_labels_done.add(key)
                svg.append(
                    f'<text x="{x}" y="12" fill="{FG_DIM}" font-size="9">{d.strftime("%b")}</text>'
                )
        for di, day in enumerate(week):
            y = top_pad + di * (cell + gap)
            count = day["contributionCount"]
            fill = color_for(count)
            delay = 0.15 + (wi * 7 + di) * 0.0025
            svg.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" fill="{fill}" opacity="0">'
                f'<animate attributeName="opacity" from="0" to="1" dur="0.5s" begin="{delay:.3f}s" fill="freeze"/>'
                f'</rect>'
            )
    svg.append("</svg>")
    return "".join(svg)


def write(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def main():
    if not GITHUB_TOKEN or not GITHUB_USERNAME:
        print("GITHUB_TOKEN and GITHUB_USERNAME must be set", file=sys.stderr)
        sys.exit(1)

    total, days, weeks = fetch_contribution_days(GITHUB_USERNAME)
    current, longest = compute_streaks(days)
    langs = fetch_top_languages(GITHUB_USERNAME)

    write("assets/stats.svg", make_stats_svg(total))
    write("assets/streak.svg", make_streak_svg(current, longest))
    write("assets/langs.svg", make_langs_svg(langs))
    write("assets/year.svg", make_year_svg(weeks))
    print(f"Generated: {total} contributions, streak {current}/{longest}, {len(langs)} languages")


if __name__ == "__main__":
    main()