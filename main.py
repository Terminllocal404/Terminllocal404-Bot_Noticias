"""Discord bot entrypoint for Cyber Intelligence Bot."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

from ai import AISummarizer, short_summary
from config import CATEGORY_KEYWORDS, load_settings
from cve import CVEItem, fetch_latest_cves
from db import Database
from feeds import NewsItem, extract_trend_keywords, fetch_critical_alerts, fetch_news

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
LOGGER = logging.getLogger("cyber-intelligence-bot")

settings = load_settings()
db = Database(
    host=settings.mysql_host,
    port=settings.mysql_port,
    user=settings.mysql_user,
    password=settings.mysql_password,
    database=settings.mysql_database,
)
ai = AISummarizer(api_key=settings.openai_api_key, model=settings.openai_model)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


def emoji_for_item(title: str, summary: str, critical: bool) -> str:
    text = f"{title} {summary}".lower()
    if critical:
        return "🚨"
    if "linux" in text:
        return "🐧"
    if "windows" in text or "microsoft" in text:
        return "🪟"
    return "🔐"


def make_news_embed(item: NewsItem, summary: str) -> discord.Embed:
    marker = emoji_for_item(item.title, summary, item.critical)
    embed = discord.Embed(
        title=f"{marker} {item.title}",
        description=short_summary(summary),
        color=discord.Color.red() if item.critical else discord.Color.blurple(),
    )
    embed.add_field(name="Source", value=item.source, inline=True)
    embed.add_field(name="URL", value=f"[Open article]({item.link})", inline=True)
    embed.set_footer(text="Cyber Intelligence Bot")
    return embed


def make_cve_embed(cve: CVEItem) -> discord.Embed:
    icon = "🚨" if cve.severity == "critical" else "🔐"
    embed = discord.Embed(
        title=f"{icon} {cve.cve_id}",
        description=short_summary(cve.summary, limit=500),
        color=discord.Color.red() if cve.severity == "critical" else discord.Color.orange(),
    )
    embed.add_field(name="Severity", value=f"{cve.severity.upper()} (CVSS {cve.cvss:.1f})", inline=True)
    embed.add_field(name="Source", value="cve.circl.lu", inline=True)
    embed.set_footer(text="Use this intelligence for defensive prioritization")
    return embed


@bot.event
async def on_ready() -> None:
    LOGGER.info("Logged in as %s", bot.user)
    if not auto_post_news.is_running():
        auto_post_news.start()


@bot.command(name="news")
async def news_cmd(ctx: commands.Context, category: str) -> None:
    category = category.lower().strip()
    if category not in CATEGORY_KEYWORDS:
        await ctx.send("Usage: `!news linux`, `!news windows`, or `!news security`")
        return

    await ctx.trigger_typing()
    items = fetch_news(category=category, limit=5)
    if not items:
        await ctx.send("No relevant news found right now.")
        return

    db.update_keyword_hits([kw for item in items for kw in item.matched_keywords])
    for item in items:
        summary = ai.summarize(item.title, item.description, item.source)
        await ctx.send(embed=make_news_embed(item, summary))


@bot.command(name="alerts")
async def alerts_cmd(ctx: commands.Context) -> None:
    await ctx.trigger_typing()
    alerts = fetch_critical_alerts(limit=5)
    if not alerts:
        await ctx.send("No critical alerts available at this moment.")
        return

    for item in alerts:
        summary = ai.summarize(item.title, item.description, item.source)
        await ctx.send(embed=make_news_embed(item, summary))


@bot.command(name="cve")
async def cve_cmd(ctx: commands.Context) -> None:
    await ctx.trigger_typing()
    cves = fetch_latest_cves(limit=8)
    if not cves:
        await ctx.send("Unable to fetch CVE data right now.")
        return

    posted = 0
    for cve in cves:
        if db.has_cve(cve.cve_id):
            continue
        db.store_cve(cve.cve_id, cve.summary, cve.severity, cve.cvss)
        await ctx.send(embed=make_cve_embed(cve))
        posted += 1

    if posted == 0:
        await ctx.send("No new CVEs since the last sync.")


@bot.command(name="trend")
async def trend_cmd(ctx: commands.Context) -> None:
    trends = db.top_trends(limit=10)
    if not trends:
        await ctx.send("No trend data yet. Run `!news` commands first.")
        return

    lines = [f"• **{keyword}**: {count}" for keyword, count in trends]
    embed = discord.Embed(
        title="📈 Top Threat Trends",
        description="\n".join(lines),
        color=discord.Color.green(),
    )
    await ctx.send(embed=embed)


@tasks.loop(minutes=settings.post_interval_minutes)
async def auto_post_news() -> None:
    channel = bot.get_channel(settings.post_channel_id)
    if channel is None:
        LOGGER.warning("Configured channel %s not found.", settings.post_channel_id)
        return

    items = fetch_news(category="security", limit=10)
    if not items:
        return

    trend_counts = extract_trend_keywords(items)
    db.update_keyword_hits(trend_counts.keys())

    for item in items:
        if db.has_posted_link(item.link):
            continue

        summary = ai.summarize(item.title, item.description, item.source)
        await channel.send(embed=make_news_embed(item, summary))
        db.mark_link_posted(item.title, item.link, "security", item.source)


@auto_post_news.before_loop
async def before_auto_post_news() -> None:
    await bot.wait_until_ready()


if __name__ == "__main__":
    bot.run(settings.discord_token)
