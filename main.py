"""Discord bot entrypoint for cybersecurity and tech intelligence automation."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

from ai import AISummarizer, short_summary
from config import CATEGORY_KEYWORDS, load_settings
from cve import fetch_latest_cves
from db import Database
from feeds import extract_trend_keywords, fetch_critical_alerts, fetch_news

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
LOGGER = logging.getLogger("cyber-intel-bot")

settings = load_settings()
db = Database(settings.db_path)
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


def make_news_embed(title: str, summary: str, source: str, link: str, critical: bool) -> discord.Embed:
    marker = emoji_for_item(title, summary, critical)
    embed = discord.Embed(
        title=f"{marker} {title}",
        description=short_summary(summary),
        color=discord.Color.red() if critical else discord.Color.blurple(),
    )
    embed.add_field(name="Source", value=source, inline=True)
    embed.add_field(name="Link", value=f"[Read more]({link})", inline=True)
    embed.set_footer(text="Cybersecurity & Tech Intelligence Hub")
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
        embed = make_news_embed(item.title, summary, item.source, item.link, item.critical)
        await ctx.send(embed=embed)


@bot.command(name="alerts")
async def alerts_cmd(ctx: commands.Context) -> None:
    await ctx.trigger_typing()
    alerts = fetch_critical_alerts(limit=5)
    if not alerts:
        await ctx.send("No critical alerts available at this moment.")
        return

    for item in alerts:
        summary = ai.summarize(item.title, item.description, item.source)
        embed = make_news_embed(item.title, summary, item.source, item.link, critical=True)
        await ctx.send(embed=embed)


@bot.command(name="cve")
async def cve_cmd(ctx: commands.Context) -> None:
    await ctx.trigger_typing()
    cves = fetch_latest_cves(limit=8)
    if not cves:
        await ctx.send("Unable to fetch CVE data right now.")
        return

    for cve in cves:
        if db.has_shown_cve(cve.cve_id):
            continue

        icon = "🚨" if cve.severity == "critical" else "🔐"
        embed = discord.Embed(
            title=f"{icon} {cve.cve_id}",
            description=short_summary(cve.summary, limit=500),
            color=discord.Color.red() if cve.severity == "critical" else discord.Color.orange(),
        )
        embed.add_field(name="Severity", value=f"{cve.severity.upper()} (CVSS: {cve.cvss:.1f})", inline=True)
        embed.add_field(name="Source", value="CIRCL CVE API", inline=True)
        embed.set_footer(text="Use this for defensive prioritization.")
        await ctx.send(embed=embed)
        db.mark_cve_shown(cve.cve_id, cve.severity)


@bot.command(name="trend")
async def trend_cmd(ctx: commands.Context) -> None:
    trends = db.top_trends(limit=10)
    if not trends:
        await ctx.send("No trend data yet. Run `!news` commands first.")
        return

    lines = [f"• **{kw}**: {count}" for kw, count in trends]
    embed = discord.Embed(
        title="📈 Threat Keyword Trends",
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
        embed = make_news_embed(item.title, summary, item.source, item.link, item.critical)
        try:
            await channel.send(embed=embed)
            db.mark_link_posted(item.link, item.title, item.source, "security")
        except Exception as exc:
            LOGGER.error("Failed to auto-post item %s: %s", item.link, exc)


@auto_post_news.before_loop
async def before_auto_post_news() -> None:
    await bot.wait_until_ready()


if __name__ == "__main__":
    bot.run(settings.discord_token)
