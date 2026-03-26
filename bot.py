import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Union

import discord
import feedparser
import aiohttp
import aiomysql
from discord import app_commands
from discord.ext import commands, tasks
from openai import AsyncOpenAI

# ==========================================
# CONFIGURATION & LOGGING
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
LOGGER = logging.getLogger("TechIntelBot")

# Environment Variables
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")

# ID dos canais para envios automáticos (críticos)
# Podem ser configurados individualmente ou usar um padrão
CHANNEL_ID_SECURITY = int(os.getenv("CHANNEL_ID_SECURITY", "0"))
CHANNEL_ID_WINDOWS = int(os.getenv("CHANNEL_ID_WINDOWS", "0"))
CHANNEL_ID_LINUX = int(os.getenv("CHANNEL_ID_LINUX", "0"))
# Fallback para o canal geral se os outros não estiverem definidos
AUTO_POST_CHANNEL_ID = int(os.getenv("AUTO_POST_CHANNEL_ID", "0"))

# Sources
RSS_SOURCES = {
    "The Hacker News": "https://thehackernews.com/feeds/posts/default",
    "BleepingComputer": "https://www.bleepingcomputer.com/feed/",
    "Reddit Linux": "https://www.reddit.com/r/linux/.rss",
    "Reddit Windows": "https://www.reddit.com/r/windows/.rss",
    "Reddit NetSec": "https://www.reddit.com/r/netsec/.rss",
    "Reddit CyberSecurity": "https://www.reddit.com/r/cybersecurity/.rss"
}

# ==========================================
# DATA LAYER (DATABASE)
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
                    # news table
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS news (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            title VARCHAR(512) NOT NULL,
                            link VARCHAR(512) UNIQUE NOT NULL,
                            source VARCHAR(100),
                            category VARCHAR(50),
                            summary_raw TEXT,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    # processed_news table
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS processed_news (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            news_id INT NOT NULL,
                            summary TEXT NOT NULL,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (news_id) REFERENCES news(id) ON DELETE CASCADE
                        )
                    """)
                    # search history table
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS user_search_history (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            user_id BIGINT NOT NULL,
                            query VARCHAR(255) NOT NULL,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    # user monitors
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS user_monitors (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            user_id BIGINT NOT NULL,
                            topic VARCHAR(255) NOT NULL,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
            LOGGER.info("MySQL Connection established and tables verified.")
        except Exception as e:
            LOGGER.error(f"Critical Database Error: {e}")
            raise

    async def save_news(self, title: str, link: str, source: str, category: str, summary_raw: str) -> Optional[int]:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "INSERT IGNORE INTO news (title, link, source, category, summary_raw) VALUES (%s, %s, %s, %s, %s)",
                        (title[:512], link, source, category, summary_raw)
                    )
                    if cur.rowcount > 0:
                        return cur.lastrowid
                    # Se já existir, pegamos o ID existente
                    await cur.execute("SELECT id FROM news WHERE link = %s", (link,))
                    res = await cur.fetchone()
                    return res[0] if res else None
        except Exception as e:
            LOGGER.error(f"DB Error saving news: {e}")
            return None

    async def get_cached_summary(self, news_id: int) -> Optional[str]:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT summary FROM processed_news WHERE news_id = %s", (news_id,))
                    res = await cur.fetchone()
                    return res[0] if res else None
        except Exception as e:
            LOGGER.error(f"DB Error getting cache: {e}")
            return None

    async def save_cached_summary(self, news_id: int, summary: str):
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("INSERT IGNORE INTO processed_news (news_id, summary) VALUES (%s, %s)", (news_id, summary))
        except Exception as e:
            LOGGER.error(f"DB Error saving cache: {e}")

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
            LOGGER.error(f"DB Error searching: {e}")
            return []

    async def get_by_category(self, category: str, limit: int = 5) -> List[Dict[str, Any]]:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute(
                        "SELECT * FROM news WHERE category = %s ORDER BY created_at DESC LIMIT %s",
                        (category, limit)
                    )
                    return await cur.fetchall()
        except Exception as e:
            LOGGER.error(f"DB Error fetching category: {e}")
            return []

    async def log_search(self, user_id: int, query: str):
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("INSERT INTO user_search_history (user_id, query) VALUES (%s, %s)", (user_id, query))
        except Exception as e:
            LOGGER.error(f"DB Error logging search: {e}")

    async def add_monitor(self, user_id: int, topic: str):
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("INSERT INTO user_monitors (user_id, topic) VALUES (%s, %s)", (user_id, topic))
        except Exception as e:
            LOGGER.error(f"DB Error adding monitor: {e}")

# ==========================================
# AI PROCESSING LAYER
# ==========================================
class AIService:
    def __init__(self, api_key: str):
        self.client = AsyncOpenAI(api_key=api_key)

    async def process_with_ai(self, text: str) -> str:
        """
        Calls OpenAI to translate to Portuguese, summarize, and highlight points.
        Includes retry logic and timeout.
        """
        if not OPENAI_API_KEY:
            return "AI Error: API Key missing."

        prompt = (
            "Você é um analista sênior de inteligência cibernética e tecnologia. "
            "Traduza o seguinte conteúdo para o Português (Brasil), resuma-o de forma clara "
            "e destaque os pontos principais com bullets. Utilize um tom profissional e informativo.\n\n"
            f"Texto: {text}"
        )

        max_retries = 1
        for attempt in range(max_retries + 1):
            try:
                response = await asyncio.wait_for(
                    self.client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=700,
                        temperature=0.3
                    ),
                    timeout=30.0
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                LOGGER.warning(f"AI Attempt {attempt+1} failed: {e}")
                if attempt < max_retries:
                    await asyncio.sleep(2)
                    continue
                return f"Falha no processamento por IA: {str(e)}"

# ==========================================
# BOT LAYER
# ==========================================
class IntelBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.db = DatabaseManager()
        self.ai = AIService(OPENAI_API_KEY)
        self.session: Optional[aiohttp.ClientSession] = None

    async def setup_hook(self):
        self.session = aiohttp.ClientSession()
        await self.db.initialize()
        self.rss_sync_task.start()
        await self.tree.sync()
        LOGGER.info("Bot logic and Slash commands synced.")

    async def close(self):
        if self.session:
            await self.session.close()
        if self.db.pool:
            self.db.pool.close()
            await self.db.pool.wait_closed()
        await super().close()

    def classify_news(self, text: str) -> str:
        text = text.lower()
        # Security Keywords (Priority 1)
        security_kws = ["vulnerability", "exploit", "cve", "breach", "ransomware", "security", "zero-day", "hacking", "malware", "cyberattack", "ataque", "vulnerabilidade"]
        if any(kw in text for kw in security_kws):
            return "security"
        # Windows (Priority 2)
        if "windows" in text or "microsoft" in text or "azure" in text:
            return "windows"
        # Linux (Priority 3)
        if "linux" in text or "kernel" in text or "ubuntu" in text or "debian" in text or "fedora" in text:
            return "linux"
        return "general"

    def detect_critical(self, text: str) -> bool:
        text = text.lower()
        critical_kws = ["critical", "zero-day", "data breach", "ransomware", "crítico", "vazamento"]
        if any(kw in text for kw in critical_kws):
            return True
        # CVSS check (CVSS 9.0+)
        cvss_match = re.search(r"cvss\s*(?:score)?\s*:?\s*([0-9.]+)", text)
        if cvss_match:
            try:
                score = float(cvss_match.group(1))
                if score >= 9.0:
                    return True
            except ValueError:
                pass
        return False

    async def process_rss_sync(self):
        """Perform the actual RSS synchronization."""
        LOGGER.info("Initiating RSS Sync...")
        new_news_count = 0
        for source_name, url in RSS_SOURCES.items():
            try:
                async with self.session.get(url, timeout=20) as resp:
                    if resp.status != 200:
                        continue
                    content = await resp.text()
                    # Use asyncio.to_thread for the blocking feedparser.parse call
                    feed = await asyncio.to_thread(feedparser.parse, content)
                    for entry in feed.entries:
                        title = entry.get("title", "No Title")
                        link = entry.get("link", "")
                        summary_raw = entry.get("summary", "") or entry.get("description", "")

                        category = self.classify_news(f"{title} {summary_raw}")

                        news_id = await self.db.save_news(title, link, source_name, category, summary_raw)

                        # Auto-send logic (Critical Alerts)
                        if news_id and self.detect_critical(f"{title} {summary_raw}"):
                            new_news_count += 1
                            await self.handle_auto_post(news_id, title, summary_raw, source_name, link, category)
            except Exception as e:
                LOGGER.error(f"Sync error for {source_name}: {e}")
        return new_news_count

    @tasks.loop(minutes=30)
    async def rss_sync_task(self):
        await self.process_rss_sync()

    async def handle_auto_post(self, news_id, title, summary_raw, source, link, category):
        # Determine the target channel based on category
        channel_id = AUTO_POST_CHANNEL_ID
        if category == "security" and CHANNEL_ID_SECURITY:
            channel_id = CHANNEL_ID_SECURITY
        elif category == "windows" and CHANNEL_ID_WINDOWS:
            channel_id = CHANNEL_ID_WINDOWS
        elif category == "linux" and CHANNEL_ID_LINUX:
            channel_id = CHANNEL_ID_LINUX

        if not channel_id:
            return

        channel = self.get_channel(channel_id)
        if not channel:
            return

        # Use cache if available
        summary_ai = await self.db.get_cached_summary(news_id)
        if not summary_ai:
            summary_ai = await self.ai.process_with_ai(f"{title}\n{summary_raw}")
            await self.db.save_cached_summary(news_id, summary_ai)

        embed = self.create_intel_embed(title, summary_ai, source, link, category)
        try:
            await channel.send(content="🚨 **ALERTA CRÍTICO DETECTADO**", embed=embed)
        except Exception as e:
            LOGGER.error(f"Error sending auto post to channel {channel_id}: {e}")

    def create_intel_embed(self, title, summary, source, link, category) -> discord.Embed:
        colors = {
            "security": discord.Color.red(),
            "windows": discord.Color.blue(),
            "linux": discord.Color.green(),
            "general": discord.Color.light_grey()
        }
        embed = discord.Embed(
            title=title[:250],
            url=link,
            description=summary[:4000],
            color=colors.get(category, discord.Color.light_grey()),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_author(name=f"Fonte: {source}")
        embed.set_footer(text=f"Categoria: {category.capitalize()}")
        return embed

bot = IntelBot()

# ==========================================
# COMMANDS & SLASH COMMANDS
# ==========================================

@bot.command(name="check")
@commands.has_permissions(administrator=True)
async def check_command(ctx):
    """Force an immediate RSS update (Manual Update)."""
    await ctx.send("🔄 Iniciando atualização manual das notícias... Aguarde.")
    count = await bot.process_rss_sync()
    await ctx.send(f"✅ Atualização concluída! {count} alertas críticos processados.")

@bot.tree.command(name="buscar", description="Busca notícias relevantes e gera resumo via IA.")
@app_commands.describe(query="Termo para pesquisa")
async def buscar(interaction: discord.Interaction, query: str):
    await interaction.response.defer(ephemeral=True)
    await bot.db.log_search(interaction.user.id, query)

    results = await bot.db.search_news(query, limit=5)
    if not results:
        return await interaction.followup.send("Nenhum resultado encontrado para sua busca.", ephemeral=True)

    embeds = []
    for news in results:
        summary_ai = await bot.db.get_cached_summary(news['id'])
        if not summary_ai:
            summary_ai = await bot.ai.process_with_ai(f"{news['title']}\n{news['summary_raw']}")
            await bot.db.save_cached_summary(news['id'], summary_ai)

        embeds.append(bot.create_intel_embed(news['title'], summary_ai, news['source'], news['link'], news['category']))

    await interaction.followup.send(embeds=embeds[:5], ephemeral=True)

@bot.tree.command(name="categoria", description="Exibe as 5 últimas notícias de uma categoria específica.")
@app_commands.choices(categoria=[
    app_commands.Choice(name="Segurança", value="security"),
    app_commands.Choice(name="Windows", value="windows"),
    app_commands.Choice(name="Linux", value="linux"),
])
async def categoria(interaction: discord.Interaction, categoria: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True)

    results = await bot.db.get_by_category(categoria.value, limit=5)
    if not results:
        return await interaction.followup.send(f"Sem notícias recentes para a categoria {categoria.name}.", ephemeral=True)

    embeds = []
    for news in results:
        summary_ai = await bot.db.get_cached_summary(news['id'])
        if not summary_ai:
            summary_ai = await bot.ai.process_with_ai(f"{news['title']}\n{news['summary_raw']}")
            await bot.db.save_cached_summary(news['id'], summary_ai)

        embeds.append(bot.create_intel_embed(news['title'], summary_ai, news['source'], news['link'], news['category']))

    await interaction.followup.send(embeds=embeds[:5], ephemeral=True)

@bot.tree.command(name="monitor", description="Salva um tópico de interesse para monitoramento.")
@app_commands.describe(topico="Tópico de interesse")
async def monitor(interaction: discord.Interaction, topico: str):
    await bot.db.add_monitor(interaction.user.id, topico)
    await interaction.response.send_message(f"✅ Monitoramento registrado para: **{topico}**", ephemeral=True)

# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("Error: DISCORD_TOKEN environment variable is not set.")
    else:
        bot.run(DISCORD_TOKEN)
