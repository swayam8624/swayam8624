#!/usr/bin/env python3
"""Generate repository-owned SVG telemetry for the GitHub profile README."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


GRAPHQL_ENDPOINT = "https://api.github.com/graphql"
OUTPUT_DIR = Path("assets/profile")


@dataclass(frozen=True)
class Theme:
    name: str
    background: str
    panel: str
    border: str
    text: str
    muted: str
    accent: str
    blue: str
    green: str
    grid: str


THEMES = {
    "light": Theme(
        "light", "#ffffff", "#f6f8fa", "#d0d7de", "#1f2328", "#656d76",
        "#7c3aed", "#0969da", "#1a7f37", "#d8dee4"
    ),
    "dark": Theme(
        "dark", "#0d1117", "#161b22", "#30363d", "#f0f6fc", "#8b949e",
        "#a78bfa", "#58a6ff", "#3fb950", "#21262d"
    ),
}


QUERY = """
query ProfileTelemetry($login: String!) {
  user(login: $login) {
    name
    login
    followers { totalCount }
    repositories(
      first: 100
      ownerAffiliations: OWNER
      privacy: PUBLIC
      isFork: false
      orderBy: {field: STARGAZERS, direction: DESC}
    ) {
      totalCount
      nodes {
        name
        url
        stargazerCount
        forkCount
        primaryLanguage { name color }
      }
    }
    contributionsCollection {
      totalCommitContributions
      totalIssueContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
"""


def fetch_profile(username: str, token: str) -> dict[str, Any]:
    payload = json.dumps({"query": QUERY, "variables": {"login": username}}).encode()
    request = urllib.request.Request(
        GRAPHQL_ENDPOINT,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "swayam8624-profile-assets",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub GraphQL request failed ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub GraphQL request failed: {exc.reason}") from exc

    if result.get("errors"):
        raise RuntimeError(f"GitHub GraphQL returned errors: {result['errors']}")
    user = result.get("data", {}).get("user")
    if not user:
        raise RuntimeError(f"GitHub user {username!r} was not found")
    return user


def contribution_days(user: dict[str, Any]) -> list[tuple[date, int]]:
    weeks = user["contributionsCollection"]["contributionCalendar"]["weeks"]
    days: list[tuple[date, int]] = []
    for week in weeks:
        for item in week["contributionDays"]:
            days.append((date.fromisoformat(item["date"]), int(item["contributionCount"])))
    return sorted(days)


def calculate_streaks(days: list[tuple[date, int]]) -> dict[str, Any]:
    by_date = dict(days)
    today = date.today()
    cursor = today
    if by_date.get(cursor, 0) == 0:
        cursor -= timedelta(days=1)

    current_end = cursor
    current = 0
    while by_date.get(cursor, 0) > 0:
        current += 1
        cursor -= timedelta(days=1)
    current_start = cursor + timedelta(days=1) if current else None

    longest = 0
    longest_start = None
    longest_end = None
    run = 0
    run_start = None
    for day, count in days:
        if count > 0:
            if run == 0:
                run_start = day
            run += 1
            if run > longest:
                longest = run
                longest_start = run_start
                longest_end = day
        else:
            run = 0
            run_start = None

    return {
        "current": current,
        "current_start": current_start,
        "current_end": current_end if current else None,
        "longest": longest,
        "longest_start": longest_start,
        "longest_end": longest_end,
        "active_days": sum(1 for _, count in days if count > 0),
        "max_day": max((count for _, count in days), default=0),
    }


def compact(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def fmt_period(start: date | None, end: date | None) -> str:
    if not start or not end:
        return "No active run"
    if start == end:
        return start.strftime("%d %b %Y")
    return f"{start.strftime('%d %b')} – {end.strftime('%d %b %Y')}"


def svg_open(width: int, height: int, theme: Theme, title: str, description: str) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(title)}</title>',
        f'<desc id="desc">{escape(description)}</desc>',
        "<style>",
        "text{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Inter,Arial,sans-serif}",
        ".mono{font-family:'SFMono-Regular',Consolas,'Liberation Mono',monospace}",
        "</style>",
        f'<rect width="{width}" height="{height}" rx="16" fill="{theme.background}"/>',
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="15.5" fill="none" stroke="{theme.border}"/>',
    ]


def text(x: float, y: float, value: str, *, size: int, fill: str, weight: int = 400,
         anchor: str = "start", cls: str = "") -> str:
    class_attr = f' class="{cls}"' if cls else ""
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" '
        f'fill="{fill}" text-anchor="{anchor}"{class_attr}>{escape(value)}</text>'
    )


def metric_card(lines: list[str], x: int, y: int, width: int, height: int,
                label: str, value: str, note: str, theme: Theme, accent: str) -> None:
    lines.append(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="12" fill="{theme.panel}" stroke="{theme.border}"/>')
    lines.append(f'<rect x="{x}" y="{y}" width="4" height="{height}" rx="2" fill="{accent}"/>')
    lines.append(text(x + 18, y + 28, label.upper(), size=11, fill=theme.muted, weight=700, cls="mono"))
    lines.append(text(x + 18, y + 68, value, size=30, fill=theme.text, weight=750))
    lines.append(text(x + 18, y + 91, note, size=12, fill=theme.muted))


def render_stats(user: dict[str, Any], theme: Theme) -> str:
    contributions = user["contributionsCollection"]
    calendar = contributions["contributionCalendar"]
    repos = user["repositories"]
    nodes = repos["nodes"]
    stars = sum(int(repo["stargazerCount"]) for repo in nodes)
    forks = sum(int(repo["forkCount"]) for repo in nodes)
    followers = int(user["followers"]["totalCount"])
    top = nodes[:4]

    lines = svg_open(
        1000, 330, theme,
        "GitHub engineering telemetry",
        "Repository-owned GitHub statistics and leading public repositories.",
    )
    lines.append(text(30, 42, "GITHUB // ENGINEERING TELEMETRY", size=15, fill=theme.accent, weight=800, cls="mono"))
    lines.append(text(30, 67, "Generated from GitHub's GraphQL API — no public card service.", size=13, fill=theme.muted))

    card_width = 220
    gap = 20
    labels = [
        ("YEAR CONTRIBUTIONS", compact(int(calendar["totalContributions"])), "rolling contribution calendar", theme.accent),
        ("PUBLIC REPOSITORIES", compact(int(repos["totalCount"])), "owned, non-fork repositories", theme.blue),
        ("STARS / FORKS", f"{compact(stars)} / {compact(forks)}", "across public repositories", theme.green),
        ("FOLLOWERS", compact(followers), "GitHub audience", theme.accent),
    ]
    for index, item in enumerate(labels):
        metric_card(lines, 30 + index * (card_width + gap), 88, card_width, 105, item[0], item[1], item[2], theme, item[3])

    lines.append(text(30, 225, "TOP PUBLIC REPOSITORIES", size=12, fill=theme.muted, weight=800, cls="mono"))
    if not top:
        lines.append(text(30, 260, "No public repositories returned.", size=14, fill=theme.text))
    else:
        col_width = 235
        for index, repo in enumerate(top):
            x = 30 + index * col_width
            language = (repo.get("primaryLanguage") or {}).get("name") or "Mixed"
            name = repo["name"][:24]
            lines.append(text(x, 258, name, size=15, fill=theme.text, weight=700))
            lines.append(text(x, 282, f"stars {repo['stargazerCount']}   forks {repo['forkCount']}   {language}", size=12, fill=theme.muted))
            if index < len(top) - 1:
                lines.append(f'<line x1="{x + 215}" y1="238" x2="{x + 215}" y2="292" stroke="{theme.border}"/>')

    lines.append(text(970, 315, date.today().isoformat(), size=10, fill=theme.muted, anchor="end", cls="mono"))
    lines.append("</svg>")
    return "\n".join(lines)


def render_streak(user: dict[str, Any], days: list[tuple[date, int]], theme: Theme) -> str:
    streak = calculate_streaks(days)
    total_days = max(len(days), 1)
    activity_rate = round(streak["active_days"] / total_days * 100)
    lines = svg_open(
        1000, 220, theme,
        "GitHub contribution streak",
        "Current and longest contribution streaks calculated from the GitHub contribution calendar.",
    )
    lines.append(text(30, 42, "CONTRIBUTION // STREAK CORE", size=15, fill=theme.accent, weight=800, cls="mono"))
    lines.append(text(30, 66, "Calculated in-repository from contribution-calendar dates.", size=13, fill=theme.muted))

    metric_card(lines, 30, 88, 290, 105, "CURRENT STREAK", f"{streak['current']} days",
                fmt_period(streak["current_start"], streak["current_end"]), theme, theme.green)
    metric_card(lines, 355, 88, 290, 105, "LONGEST STREAK", f"{streak['longest']} days",
                fmt_period(streak["longest_start"], streak["longest_end"]), theme, theme.accent)
    metric_card(lines, 680, 88, 290, 105, "ACTIVE DAYS", f"{streak['active_days']} · {activity_rate}%",
                f"peak day: {streak['max_day']} contributions", theme, theme.blue)
    lines.append("</svg>")
    return "\n".join(lines)


def weekly_series(days: list[tuple[date, int]]) -> list[tuple[date, int]]:
    result: list[tuple[date, int]] = []
    for index in range(0, len(days), 7):
        chunk = days[index:index + 7]
        if chunk:
            result.append((chunk[0][0], sum(count for _, count in chunk)))
    return result


def render_wave(days: list[tuple[date, int]], theme: Theme) -> str:
    series = weekly_series(days)
    width, height = 1000, 300
    left, right, top, bottom = 52, 28, 76, 48
    chart_w = width - left - right
    chart_h = height - top - bottom
    max_value = max((value for _, value in series), default=1)
    max_value = max(max_value, 1)

    points: list[tuple[float, float, date, int]] = []
    denominator = max(len(series) - 1, 1)
    for index, (week_date, value) in enumerate(series):
        x = left + index / denominator * chart_w
        y = top + chart_h - (value / max_value) * chart_h
        points.append((x, y, week_date, value))

    lines = svg_open(
        width, height, theme,
        "Weekly contribution signal",
        "A waveform-style view of weekly GitHub contributions across the rolling calendar year.",
    )
    lines.append(text(30, 40, "CONTRIBUTION // WEEKLY SIGNAL", size=15, fill=theme.accent, weight=800, cls="mono"))
    lines.append(text(30, 64, "Weekly totals instead of the standard square heatmap.", size=13, fill=theme.muted))

    for grid_index in range(5):
        y = top + grid_index / 4 * chart_h
        value = round(max_value * (1 - grid_index / 4))
        lines.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="{theme.grid}" stroke-dasharray="4 6"/>')
        lines.append(text(left - 10, y + 4, str(value), size=10, fill=theme.muted, anchor="end", cls="mono"))

    if points:
        path = " ".join(("M" if index == 0 else "L") + f" {x:.1f} {y:.1f}" for index, (x, y, _, _) in enumerate(points))
        area = path + f" L {points[-1][0]:.1f} {top + chart_h:.1f} L {points[0][0]:.1f} {top + chart_h:.1f} Z"
        gradient_id = f"wave-{theme.name}"
        lines.insert(-1, f'<defs><linearGradient id="{gradient_id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="{theme.accent}" stop-opacity="0.38"/><stop offset="100%" stop-color="{theme.accent}" stop-opacity="0.02"/></linearGradient></defs>')
        lines.append(f'<path d="{area}" fill="url(#{gradient_id})"/>')
        lines.append(f'<path d="{path}" fill="none" stroke="{theme.accent}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"><animate attributeName="stroke-dashoffset" from="1" to="0" dur="1.8s" fill="freeze"/></path>')

        marker_step = max(1, len(points) // 12)
        for index, (x, y, _, value) in enumerate(points):
            if index % marker_step == 0 or index == len(points) - 1:
                radius = 3.5 if value else 2.5
                lines.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}" fill="{theme.background}" stroke="{theme.blue}" stroke-width="2"/>')

        month_positions: dict[tuple[int, int], float] = {}
        for x, _, week_date, _ in points:
            month_positions.setdefault((week_date.year, week_date.month), x)
        for (_, month), x in list(month_positions.items())[::2]:
            label = date(2000, month, 1).strftime("%b")
            lines.append(text(x, height - 20, label, size=10, fill=theme.muted, anchor="middle", cls="mono"))

    lines.append("</svg>")
    return "\n".join(lines)


def write_assets(user: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    days = contribution_days(user)
    if not days:
        raise RuntimeError("No contribution calendar days were returned")

    for name, theme in THEMES.items():
        (OUTPUT_DIR / f"github-stats-{name}.svg").write_text(render_stats(user, theme), encoding="utf-8")
        (OUTPUT_DIR / f"github-streak-{name}.svg").write_text(render_streak(user, days, theme), encoding="utf-8")
        (OUTPUT_DIR / f"contribution-wave-{name}.svg").write_text(render_wave(days, theme), encoding="utf-8")


def main() -> int:
    username = os.environ.get("GITHUB_USERNAME", "swayam8624")
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is required", file=sys.stderr)
        return 2

    try:
        user = fetch_profile(username, token)
        write_assets(user)
    except Exception as exc:
        print(f"Profile asset generation failed: {exc}", file=sys.stderr)
        return 1

    print(f"Generated profile assets for {username} in {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
