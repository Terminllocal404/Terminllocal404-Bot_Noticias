"""Entrypoint for Cyber Intelligence Hub Discord bot."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

from ai import AISummarizer, short_summary
from config import CATEGORY_KEYWORDS, load_settings
from cve import CVEItem, fetch_latest_cves
from db import Database
from feeds import NewsItem, extract_trend_keywords, fetch_critical_alerts, fetch_news

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
LOGGER = logging.getLogger("cyber-intelligence-hub")

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


def emoji_for_news(item: NewsItem) -> str:
    if item.severity_level == "CRITICAL":
        return "🚨"
    if item.severity_level == "HIGH":
        return "⚠️"
    if item.category == "linux":
        return "🐧"
    if item.category == "windows":
        return "🪟"
    return "🔐"


def make_news_embed(item: NewsItem, ai_summary: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"{emoji_for_news(item)} {item.title}",
        description=short_summary(ai_summary),
        color=discord.Color.red() if item.severity_level == "CRITICAL" else discord.Color.orange(),
    )
    embed.add_field(name="Source", value=item.source, inline=True)
    embed.add_field(name="Category", value=item.category.upper(), inline=True)
    embed.add_field(name="Severity", value=f"{item.severity_level} ({item.severity_score})", inline=True)
    embed.add_field(name="Link", value=f"[Read article]({item.link})", inline=False)
    embed.set_footer(text="Cyber Intelligence Hub")
    return embed


def make_cve_embed(item: CVEItem) -> discord.Embed:
    icon = "🚨" if item.severity == "CRITICAL" else ("⚠️" if item.severity == "HIGH" else "🔐")
    embed = discord.Embed(
        title=f"{icon} {item.cve_id}",
        description=short_summary(item.summary, limit=550),
        color=discord.Color.red() if item.severity == "CRITICAL" else discord.Color.orange(),
    )
    embed.add_field(name="Severity", value=item.severity, inline=True)
    embed.add_field(name="CVSS", value=f"{item.cvss:.1f}", inline=True)
    embed.add_field(name="Source", value="CIRCL CVE API", inline=True)
    return embed


@bot.event
async def on_ready() -> None:
    LOGGER.info("Cyber Intelligence Hub logged in as %s", bot.user)
    if not auto_post_news.is_running():
        auto_post_news.start()


@bot.command(name="news")
async def news_cmd(ctx: commands.Context, category: str) -> None:
    normalized = category.lower().strip()
    if normalized not in CATEGORY_KEYWORDS:
        await ctx.send("Usage: `!news linux`, `!news windows`, `!news security`")
        return

    await ctx.trigger_typing()
    items = fetch_news(category=normalized, limit=8)
    if not items:
        await ctx.send("No matching intelligence right now.")
        return

    db.update_keyword_hits([kw for item in items for kw in item.matched_keywords])
    for item in items:
        summary = ai.summarize(item.title, item.description, item.source)
        await ctx.send(embed=make_news_embed(item, summary))


@bot.command(name="alerts")
async def alerts_cmd(ctx: commands.Context) -> None:
    await ctx.trigger_typing()
    alerts = fetch_critical_alerts(limit=8)
    if not alerts:
        await ctx.send("No HIGH/CRITICAL alerts currently available.")
        return

    for item in alerts:
        summary = ai.summarize(item.title, item.description, item.source)
        await ctx.send(embed=make_news_embed(item, summary))


@bot.command(name="cve")
async def cve_cmd(ctx: commands.Context) -> None:
    await ctx.trigger_typing()
    items = fetch_latest_cves(limit=10)
    if not items:
        await ctx.send("Unable to fetch CVEs right now.")
        return

    posted = 0
    for item in items:
        if db.has_cve(item.cve_id):
            continue
        db.store_cve(item.cve_id, item.summary, item.severity)
        await ctx.send(embed=make_cve_embed(item))
        posted += 1

    if posted == 0:
        await ctx.send("No new CVEs since the last check.")


@bot.command(name="trend")
async def trend_cmd(ctx: commands.Context) -> None:
    trends = db.top_trends(limit=10)
    if not trends:
        await ctx.send("No trend data yet.")
        return

    description = "\n".join([f"• **{kw}**: {count}" for kw, count in trends])
    embed = discord.Embed(title="📈 Top Threat Trends", description=description, color=discord.Color.green())
    await ctx.send(embed=embed)


@tasks.loop(minutes=settings.post_interval_minutes)
async def auto_post_news() -> None:
    channel = bot.get_channel(settings.post_channel_id)
    if channel is None:
        LOGGER.warning("Configured channel %s not found", settings.post_channel_id)
        return

    items = fetch_news(category=None, limit=25)
    filtered = [item for item in items if item.severity_level in {"HIGH", "CRITICAL"}]
    if not filtered:
        return

    db.update_keyword_hits(extract_trend_keywords(filtered).keys())

    for item in filtered:
        if db.has_posted_link(item.link):
            continue

        summary = ai.summarize(item.title, item.description, item.source)
        await channel.send(embed=make_news_embed(item, summary))
        db.mark_link_posted(item.title, item.link, item.source, item.category, item.severity_score)


@auto_post_news.before_loop
async def before_auto_post_news() -> None:
    await bot.wait_until_ready()


if __name__ == "__main__":
    bot.run(settings.discord_token)
