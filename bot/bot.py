"""Discord bot for Cyber Intelligence Platform."""

from __future__ import annotations

import os

import discord
import requests
from discord.ext import commands

API_BASE = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


def _emoji(severity: str, category: str) -> str:
    sev = (severity or "").upper()
    cat = (category or "").lower()
    if sev == "CRITICAL":
        return "🚨"
    if sev == "HIGH":
        return "⚠️"
    if cat == "linux":
        return "🐧"
    if cat == "windows":
        return "🪟"
    return "🔐"


def _embed(item: dict) -> discord.Embed:
    severity = item.get("severity", "MEDIUM")
    category = item.get("category", "security")
    color = discord.Color.red() if severity == "CRITICAL" else discord.Color.orange()
    embed = discord.Embed(
        title=f"{_emoji(severity, category)} {item.get('title', 'Untitled')}",
        description=item.get("summary") or "No summary available.",
        color=color,
    )
    embed.add_field(name="Severity", value=severity, inline=True)
    embed.add_field(name="Source", value=item.get("source", "Unknown"), inline=True)
    link = item.get("link", "")
    embed.add_field(name="Link", value=f"[Open]({link})" if link else "N/A", inline=False)
    return embed


def _api_get(path: str, params: dict | None = None) -> list[dict]:
    response = requests.get(f"{API_BASE}{path}", params=params, timeout=25)
    response.raise_for_status()
    return response.json().get("items", [])


@bot.event
async def on_ready() -> None:
    print(f"Cyber Intelligence Platform bot ready: {bot.user}")


@bot.command(name="news")
async def news_cmd(ctx: commands.Context, category: str) -> None:
    category = category.lower().strip()
    if category not in {"linux", "windows", "security"}:
        await ctx.send("Usage: `!news linux`, `!news windows`, `!news security`")
        return

    items = _api_get(f"/news/{category}", {"limit": 5})
    if not items:
        await ctx.send("No intelligence available right now.")
        return
    for item in items:
        await ctx.send(embed=_embed(item))


@bot.command(name="alerts")
async def alerts_cmd(ctx: commands.Context) -> None:
    items = _api_get("/alerts", {"limit": 5})
    if not items:
        await ctx.send("No alerts available right now.")
        return
    for item in items:
        await ctx.send(embed=_embed(item))


@bot.command(name="cve")
async def cve_cmd(ctx: commands.Context) -> None:
    items = _api_get("/cves", {"limit": 8})
    if not items:
        await ctx.send("No CVE entries available right now.")
        return

    for item in items:
        embed = discord.Embed(
            title=f"{_emoji(item.get('severity', 'MEDIUM'), 'security')} {item.get('cve_id', 'UNKNOWN-CVE')}",
            description=item.get("summary", "No summary available."),
            color=discord.Color.red() if item.get("severity") == "CRITICAL" else discord.Color.orange(),
        )
        embed.add_field(name="Severity", value=item.get("severity", "MEDIUM"), inline=True)
        await ctx.send(embed=embed)


if __name__ == "__main__":
    bot.run(TOKEN)
