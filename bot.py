import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Dict, Any

import discord
import feedparser
import aiohttp
import aiomysql
from discord import app_commands
from discord.ext import commands, tasks
from openai import AsyncOpenAI

# ==========================================
# LOGGING CONFIGURATION
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
LOGGER = logging.getLogger("TechNewsBot")

# ==========================================
# ENVIRONMENT VARIABLES
# ==========================================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")

# Required IDs (can be configured via env or logic)
AUTO_POST_CHANNEL_ID = int(os.getenv("AUTO_POST_CHANNEL_ID", "0"))

# ==========================================
# DATA LAYER (RSS & SOURCES)
# ==========================================
RSS_SOURCES = [
    "https://thehackernews.com/feeds/posts/default",
    "https://www.bleepingcomputer.com/feed/",
    "https://www.reddit.com/r/linux/.rss",
    "https://www.reddit.com/r/windows/.rss",
    "https://www.reddit.com/r/netsec/.rss",
    "https://www.reddit.com/r/cybersecurity/.rss"
]

# ==========================================
# DATABASE LAYER (MYSQL)
# ==========================================
class DatabaseManager:
    def __init__(self):
        self.pool: Optional[aiomysql.Pool] = None

    async def initialize(self):
        try:
            self.pool = await aiomysql.create_pool(
                host=MYSQL_HOST,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                db=MYSQL_DATABASE,
                autocommit=True
            )
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS news (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            title VARCHAR(255) NOT NULL,
                            link VARCHAR(512) UNIQUE NOT NULL,
                            source VARCHAR(100),
                            category VARCHAR(50),
                            summary_raw TEXT,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS processed_news (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            news_id INT NOT NULL,
                            summary TEXT NOT NULL,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (news_id) REFERENCES news(id) ON DELETE CASCADE
                        )
                    """)
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS user_search_history (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            user_id BIGINT NOT NULL,
                            query VARCHAR(255) NOT NULL,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS user_monitors (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            user_id BIGINT NOT NULL,
                            topic VARCHAR(255) NOT NULL,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
            LOGGER.info("MySQL Database initialized successfully.")
        except Exception as e:
            LOGGER.error(f"Failed to initialize database: {e}")
            raise

    async def save_news(self, title: str, link: str, source: str, category: str, summary_raw: str) -> Optional[int]:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "INSERT IGNORE INTO news (title, link, source, category, summary_raw) VALUES (%s, %s, %s, %s, %s)",
                        (title[:255], link, source, category, summary_raw)
                    )
                    if cur.rowcount > 0:
                        return cur.lastrowid
            return None
        except Exception as e:
            LOGGER.error(f"Error saving news: {e}")
            return None

    async def get_processed_summary(self, news_id: int) -> Optional[str]:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT summary FROM processed_news WHERE news_id = %s", (news_id,))
                    result = await cur.fetchone()
                    return result[0] if result else None
        except Exception as e:
            LOGGER.error(f"Error getting processed summary: {e}")
            return None

    async def save_processed_summary(self, news_id: int, summary: str):
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("INSERT INTO processed_news (news_id, summary) VALUES (%s, %s)", (news_id, summary))
        except Exception as e:
            LOGGER.error(f"Error saving processed summary: {e}")

    async def search_news(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute(
                        "SELECT * FROM news WHERE title LIKE %s OR summary_raw LIKE %s ORDER BY created_at DESC LIMIT %s",
                        (f"%{query}%", f"%{query}%", limit)
                    )
                    return await cur.fetchall()
        except Exception as e:
            LOGGER.error(f"Error searching news: {e}")
            return []

    async def get_latest_by_category(self, category: str, limit: int = 5) -> List[Dict[str, Any]]:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute(
                        "SELECT * FROM news WHERE category = %s ORDER BY created_at DESC LIMIT %s",
                        (category, limit)
                    )
                    return await cur.fetchall()
        except Exception as e:
            LOGGER.error(f"Error fetching news by category: {e}")
            return []

    async def log_search(self, user_id: int, query: str):
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("INSERT INTO user_search_history (user_id, query) VALUES (%s, %s)", (user_id, query))
        except Exception as e:
            LOGGER.error(f"Error logging search: {e}")

    async def add_monitor(self, user_id: int, topic: str):
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("INSERT INTO user_monitors (user_id, topic) VALUES (%s, %s)", (user_id, topic))
        except Exception as e:
            LOGGER.error(f"Error adding monitor: {e}")

# ==========================================
# AI PROCESSING LAYER (OPENAI)
# ==========================================
class AIService:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    async def process_with_ai(self, text: str) -> str:
        """Translates to Portuguese, summarizes and highlights key points."""
        if not OPENAI_API_KEY:
            return "AI Key not configured."

        prompt = (
            "Você é um analista de segurança e tecnologia sênior. "
            "Traduza o seguinte texto para o Português do Brasil, resuma-o e destaque os pontos principais. "
            "O resumo deve ser objetivo e profissional.\n\n"
            f"Texto: {text}"
        )

        retries = 1
        for attempt in range(retries + 1):
            try:
                response = await asyncio.wait_for(
                    self.client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=500,
                        temperature=0.4
                    ),
                    timeout=20.0
                )
                return response.choices[0].message.content.strip()
            except (asyncio.TimeoutError, Exception) as e:
                if attempt < retries:
                    LOGGER.warning(f"AI call failed (attempt {attempt+1}), retrying... Error: {e}")
                    await asyncio.sleep(2)
                    continue
                LOGGER.error(f"Final AI call failed after {retries+1} attempts: {e}")
                return f"Erro ao processar com IA: {str(e)}"

# ==========================================
# BOT LAYER (DISCORD)
# ==========================================
class TechNewsBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.db = DatabaseManager()
        self.ai = AIService()
        self.session: Optional[aiohttp.ClientSession] = None

    async def setup_hook(self):
        self.session = aiohttp.ClientSession()
        await self.db.initialize()
        self.rss_loop.start()
        await self.tree.sync()
        LOGGER.info("TechNewsBot is ready and commands are synced.")

    async def on_resigned(self):
        if self.session:
            await self.session.close()
        if self.db.pool:
            self.db.pool.close()
            await self.db.pool.wait_closed()

    def classify_category(self, text: str) -> str:
        text = text.lower()
        security_keywords = ["vulnerability", "exploit", "cve", "breach", "ransomware", "hack", "security", "zero-day"]
        windows_keywords = ["windows", "microsoft", "azure", "defender", "outlook"]
        linux_keywords = ["linux", "kernel", "ubuntu", "debian", "red hat", "fedora", "distro"]

        if any(kw in text for kw in security_keywords):
            return "security"
        if any(kw in text for kw in windows_keywords):
            return "windows"
        if any(kw in text for kw in linux_keywords):
            return "linux"
        return "general"

    def is_critical(self, text: str) -> bool:
        text = text.lower()
        critical_keywords = ["critical", "zero-day", "data breach", "ransomware"]
        # Basic CVSS detection in text
        cvss_match = re.search(r"cvss\s*(?:score)?\s*:?\s*([0-9.]+)", text)
        if cvss_match:
            try:
                score = float(cvss_match.group(1))
                if score >= 9.0:
                    return True
            except ValueError:
                pass
        return any(kw in text for kw in critical_keywords)

    @tasks.loop(minutes=30)
    async def rss_loop(self):
        LOGGER.info("Starting RSS ingestion cycle...")
        for url in RSS_SOURCES:
            try:
                async with self.session.get(url, timeout=15) as response:
                    if response.status == 200:
                        content = await response.text()
                        feed = feedparser.parse(content)
                        for entry in feed.entries:
                            title = entry.get("title", "")
                            link = entry.get("link", "")
                            summary_raw = entry.get("summary", "") or entry.get("description", "")
                            source_name = feed.feed.get("title", "RSS Feed")

                            category = self.classify_category(f"{title} {summary_raw}")

                            news_id = await self.db.save_news(title, link, source_name, category, summary_raw)

                            # Handle Auto-Send for Critical Items
                            if news_id and self.is_critical(f"{title} {summary_raw}"):
                                if AUTO_POST_CHANNEL_ID:
                                    channel = self.get_channel(AUTO_POST_CHANNEL_ID)
                                    if channel:
                                        # Process with AI for critical alert
                                        summary_ai = await self.ai.process_with_ai(f"{title}\n{summary_raw}")
                                        await self.db.save_processed_summary(news_id, summary_ai)

                                        embed = self.create_news_embed(title, summary_ai, source_name, link, category)
                                        await channel.send(content="🚨 **ALERTA CRÍTICO DETECTADO**", embed=embed)
            except Exception as e:
                LOGGER.error(f"Error in RSS loop for {url}: {e}")

    def create_news_embed(self, title: str, summary: str, source: str, link: str, category: str) -> discord.Embed:
        colors = {
            "security": discord.Color.red(),
            "windows": discord.Color.blue(),
            "linux": discord.Color.green(),
            "general": discord.Color.greyple()
        }
        embed = discord.Embed(
            title=title[:250],
            url=link,
            description=summary[:4000],
            color=colors.get(category, discord.Color.greyple()),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Fonte", value=source, inline=True)
        embed.add_field(name="Categoria", value=category.capitalize(), inline=True)
        embed.set_footer(text="Inteligência de Notícias Tech")
        return embed

bot = TechNewsBot()

# ==========================================
# COMMANDS
# ==========================================

@bot.tree.command(name="buscar", description="Pesquisa notícias recentes e gera resumo com IA.")
@app_commands.describe(query="Termo de pesquisa")
async def buscar(interaction: discord.Interaction, query: str):
    await interaction.response.defer(ephemeral=True)
    await bot.db.log_search(interaction.user.id, query)

    results = await bot.db.search_news(query, limit=5)
    if not results:
        return await interaction.followup.send("Nenhuma notícia relevante encontrada.", ephemeral=True)

    embeds = []
    for news in results:
        # Check cache
        summary_ai = await bot.db.get_processed_summary(news['id'])
        if not summary_ai:
            summary_ai = await bot.ai.process_with_ai(f"{news['title']}\n{news['summary_raw']}")
            await bot.db.save_processed_summary(news['id'], summary_ai)

        embeds.append(bot.create_news_embed(news['title'], summary_ai, news['source'], news['link'], news['category']))

    await interaction.followup.send(embeds=embeds[:5], ephemeral=True)

@bot.tree.command(name="categoria", description="Mostra as 5 notícias mais recentes de uma categoria.")
@app_commands.choices(category=[
    app_commands.Choice(name="Linux", value="linux"),
    app_commands.Choice(name="Windows", value="windows"),
    app_commands.Choice(name="Segurança", value="security"),
])
async def categoria(interaction: discord.Interaction, category: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True)

    results = await bot.db.get_latest_by_category(category.value, limit=5)
    if not results:
        return await interaction.followup.send(f"Nenhuma notícia encontrada para a categoria {category.name}.", ephemeral=True)

    embeds = []
    for news in results:
        # Check cache
        summary_ai = await bot.db.get_processed_summary(news['id'])
        if not summary_ai:
            summary_ai = await bot.ai.process_with_ai(f"{news['title']}\n{news['summary_raw']}")
            await bot.db.save_processed_summary(news['id'], summary_ai)

        embeds.append(bot.create_news_embed(news['title'], summary_ai, news['source'], news['link'], news['category']))

    await interaction.followup.send(embeds=embeds[:5], ephemeral=True)

@bot.tree.command(name="monitor", description="Adiciona um tópico para monitoramento.")
@app_commands.describe(topic="Tópico de interesse")
async def monitor(interaction: discord.Interaction, topic: str):
    await bot.db.add_monitor(interaction.user.id, topic)
    await interaction.response.send_message(f"Monitoramento ativado para: **{topic}**.", ephemeral=True)

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("Error: DISCORD_TOKEN environment variable is not set.")
    else:
        bot.run(DISCORD_TOKEN)
