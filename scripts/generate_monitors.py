import json
import os
from collections import Counter
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.request import Request, urlopen


def github(query, **variables):
    request = Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "Content-Type": "application/json",
            "User-Agent": "profile-monitor-generator",
        },
    )
    with urlopen(request, timeout=30) as response:
        result = json.load(response)
    if result.get("errors"):
        raise RuntimeError(result["errors"])
    return result["data"]["user"]


def contribution_stats(login):
    user = github(
        """
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
        """,
        login=login,
    )
    calendar = user["contributionsCollection"]["contributionCalendar"]
    today = datetime.now(timezone.utc).date().isoformat()
    current = longest = 0

    for week in calendar["weeks"]:
        for day in week["contributionDays"]:
            if day["date"] > today:
                continue
            if day["contributionCount"]:
                current += 1
                longest = max(longest, current)
            elif day["date"] < today:
                # Today is still open, so yesterday's streak can continue.
                current = 0

    return calendar["totalContributions"], current, longest


def language_totals(login):
    totals = Counter()
    cursor = None
    while True:
        user = github(
            """
            query($login: String!, $cursor: String) {
              user(login: $login) {
                repositories(first: 25, after: $cursor, privacy: PUBLIC,
                             ownerAffiliations: [OWNER], isFork: false) {
                  nodes {
                    languages(first: 100, orderBy: {field: SIZE, direction: DESC}) {
                      edges { size node { name } }
                    }
                  }
                  pageInfo { hasNextPage endCursor }
                }
              }
            }
            """,
            login=login,
            cursor=cursor,
        )
        repos = user["repositories"]
        for repo in repos["nodes"]:
            for edge in repo["languages"]["edges"]:
                totals[edge["node"]["name"]] += edge["size"]
        if not repos["pageInfo"]["hasNextPage"]:
            return totals
        cursor = repos["pageInfo"]["endCursor"]


def draw_monitors(total, current, longest, languages):
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 920 410" '
        'role="img" aria-labelledby="title desc">',
        '<title id="title">Mohamad’s GitHub workstation</title>',
        f'<desc id="desc">{total:,} contributions in the last 12 months. '
        f'Current streak {current} days. Longest streak {longest} days. '
        'The second monitor shows languages by bytes of public code.</desc>',
        '<g font-family="ui-monospace, monospace">',
    ]
    copper, cream, muted = "#ff9955", "#fff1df", "#adc0ce"

    def rect(x, y, w, h, color, radius=0, stroke="none"):
        parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" '
            f'fill="{color}" stroke="{stroke}"/>'
        )

    def text(x, y, value, size, color=cream, anchor="start"):
        parts.append(
            f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" '
            f'text-anchor="{anchor}">{escape(str(value))}</text>'
        )

    def monitor(x, y, w, h):
        center = x + w / 2
        rect(center - 12, y + h - 2, 24, 375 - (y + h) + 2, "#344151")
        rect(center - 58, 374, 116, 8, "#596775", 4)
        rect(x, y, w, h, "#202936", 12, "#637080")
        rect(x + 8, y + 8, w - 16, h - 25, "#07131e", 6, "#865638")
        rect(x + w - 30, y + h - 10, 12, 3, copper, 1)

    monitor(12, 77, 575, 260)
    monitor(605, 12, 300, 325)

    text(40, 121, "> contribution history", 23, copper)
    text(40, 191, f"{total:,}", 62)
    text(43, 221, "Contributions · last 12 months", 18, muted)
    rect(42, 243, 513, 1, "#344151")
    text(42, 271, "CURRENT STREAK", 14, muted)
    text(300, 271, "LONGEST IN PERIOD", 14, muted)
    for x, days in [(42, current), (300, longest)]:
        text(x, 301, f"{days} {'day' if days == 1 else 'days'}", 22)

    text(627, 52, "> languages", 23, copper)
    text(627, 76, "Public repos · by bytes", 15, muted)
    byte_count = sum(languages.values())
    for index, (name, count) in enumerate(languages.most_common(6)):
        y = 111 + 36 * index
        share = count / byte_count
        label = name if len(name) <= 17 else name[:16] + "…"
        text(627, y, label, 16)
        text(881, y, f"{share:.1%}", 15, muted, "end")
        rect(627, y + 7, 254, 4, "#263542", 2)
        rect(627, y + 7, round(254 * share, 2), 4, copper, 2)
    if not byte_count:
        text(627, 115, "No language data yet", 16, muted)

    parts.append("</g></svg>")
    return "\n".join(parts)


if __name__ == "__main__":
    login = os.environ.get("GITHUB_REPOSITORY_OWNER", "theArnaout")
    stats = contribution_stats(login)
    svg = draw_monitors(*stats, language_totals(login))
    output = Path(__file__).resolve().parents[1] / "assets" / "github-monitors.svg"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(svg, encoding="utf-8")
