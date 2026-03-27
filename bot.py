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
# CONFIGURAÇÃO DE LOGS
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
LOGGER = logging.getLogger("IntelTechBot")

# ==========================================
# VARIÁVEIS DE AMBIENTE (REQUERIDAS)
# ==========================================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")

# Canal para alertas automáticos (Destaques Críticos)
AUTO_POST_CHANNEL_ID = int(os.getenv("AUTO_POST_CHANNEL_ID", "0"))

# Fontes RSS
RSS_SOURCES = {
    "The Hacker News": "https://thehackernews.com/feeds/posts/default",
    "BleepingComputer": "https://www.bleepingcomputer.com/feed/",
    "Reddit Linux": "https://www.reddit.com/r/linux/.rss",
    "Reddit Windows": "https://www.reddit.com/r/windows/.rss",
    "Reddit NetSec": "https://www.reddit.com/r/netsec/.rss",
    "Reddit Cybersecurity": "https://www.reddit.com/r/cybersecurity/.rss"
}

# ==========================================
# CAMADA DE BANCO DE DADOS (MYSQL - AIOMYSQL)
# ==========================================
class DatabaseManager:
    """Gerencia conexões, tabelas e persistência no MySQL de forma assíncrona."""
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
                    # processed_news table (AI Summaries)
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS processed_news (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            news_id INT NOT NULL,
                            summary TEXT NOT NULL,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (news_id) REFERENCES news(id) ON DELETE CASCADE
                        )
                    """)
                    # user search history table
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS user_search_history (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            user_id BIGINT NOT NULL,
                            query VARCHAR(255) NOT NULL,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    # user monitors table
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS user_monitors (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            user_id BIGINT NOT NULL,
                            topic VARCHAR(255) NOT NULL,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(user_id, topic)
                        )
                    """)
            LOGGER.info("MySQL Connection pool initialized and tables verified.")
        except Exception as e:
            LOGGER.error(f"Failed to initialize MySQL Database: {e}")
            raise

    async def save_news(self, title: str, link: str, source: str, category: str, summary_raw: str) -> Tuple[Optional[int], bool]:
        """Salva uma notícia e retorna seu ID e se ela foi inserida agora (True) ou já existia (False)."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # Tenta inserir
                    await cur.execute(
                        "INSERT IGNORE INTO news (title, link, source, category, summary_raw) VALUES (%s, %s, %s, %s, %s)",
                        (title[:512], link, source, category, summary_raw)
                    )
                    was_inserted = cur.rowcount > 0

                    if was_inserted:
                        return cur.lastrowid, True

                    # Se já existe, buscamos o ID
                    await cur.execute("SELECT id FROM news WHERE link = %s", (link,))
                    res = await cur.fetchone()
                    return (res[0], False) if res else (None, False)
        except Exception as e:
            LOGGER.error(f"Error saving news to DB: {e}")
            return None, False

    async def get_cached_summary(self, news_id: int) -> Optional[str]:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT summary FROM processed_news WHERE news_id = %s", (news_id,))
                    res = await cur.fetchone()
                    return res[0] if res else None
        except Exception as e:
            LOGGER.error(f"Error getting cached summary: {e}")
            return None

    async def save_processed_summary(self, news_id: int, summary: str):
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("INSERT IGNORE INTO processed_news (news_id, summary) VALUES (%s, %s)", (news_id, summary))
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
            LOGGER.error(f"Error searching news in DB: {e}")
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
            LOGGER.error(f"Error getting news by category from DB: {e}")
            return []

    async def log_user_search(self, user_id: int, query: str):
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
                    await cur.execute("INSERT IGNORE INTO user_monitors (user_id, topic) VALUES (%s, %s)", (user_id, topic))
        except Exception as e:
            LOGGER.error(f"Error adding monitor: {e}")

# ==========================================
# CAMADA DE IA (OPENAI)
# ==========================================
class AIService:
    """Utiliza a OpenAI para traduzir, resumir e destacar pontos-chave em Português."""
    def __init__(self, api_key: str):
        self.client = AsyncOpenAI(api_key=api_key)

    async def process_with_ai(self, text: str) -> str:
        if not OPENAI_API_KEY:
            return "AI Error: Chave da OpenAI não configurada."

        prompt = (
            "Você é um analista sênior em inteligência de ameaças e tecnologia. "
            "Traduza o seguinte conteúdo para o Português (Brasil), resuma-o e destaque "
            "os pontos mais importantes com bullets. Mantenha um tom profissional e informativo.\n\n"
            f"Texto: {text}"
        )

        max_retries = 1
        for attempt in range(max_retries + 1):
            try:
                response = await asyncio.wait_for(
                    self.client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=600,
                        temperature=0.3
                    ),
                    timeout=25.0
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                LOGGER.warning(f"AI Attempt {attempt+1} failed: {e}")
                if attempt < max_retries:
                    await asyncio.sleep(2)
                    continue
                return f"Falha no processamento por IA: {str(e)}"

# ==========================================
# CAMADA DO BOT DO DISCORD
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
        LOGGER.info("IntelBot setup complete. Commands synced.")

    async def close(self):
        if self.session:
            await self.session.close()
        if self.db.pool:
            self.db.pool.close()
            await self.db.pool.wait_closed()
        await super().close()

    def classify_category(self, text: str) -> str:
        text = text.lower()
        security_kws = ["security", "vulnerability", "exploit", "cve", "breach", "ransomware", "hacking", "zero-day", "malware"]
        if any(kw in text for kw in security_kws):
            return "security"
        if "windows" in text or "microsoft" in text:
            return "windows"
        if "linux" in text or "kernel" in text or "ubuntu" in text:
            return "linux"
        return "general"

    def is_critical(self, text: str) -> bool:
        text = text.lower()
        critical_kws = ["critical", "zero-day", "ransomware", "data breach", "vulnerabilidade crítica", "vazamento"]
        return any(kw in text for kw in critical_kws)

    @tasks.loop(minutes=30)
    async def rss_sync_task(self):
        LOGGER.info("Starting background RSS Ingestion...")
        for source_name, url in RSS_SOURCES.items():
            try:
                async with self.session.get(url, timeout=20) as resp:
                    if resp.status != 200:
                        continue
                    content = await resp.text()
                    feed = await asyncio.to_thread(feedparser.parse, content)
                    for entry in feed.entries:
                        title = entry.get("title", "No Title")
                        link = entry.get("link", "")
                        summary_raw = entry.get("summary", "") or entry.get("description", "")

                        category = self.classify_category(f"{title} {summary_raw}")

                        news_id, is_new = await self.db.save_news(title, link, source_name, category, summary_raw)

                        # Alertas Automáticos (Destaques Críticos) - Apenas para notícias NOVAS
                        if is_new and news_id and self.is_critical(f"{title} {summary_raw}"):
                            await self.handle_auto_alert(news_id, title, summary_raw, source_name, link, category)
            except Exception as e:
                LOGGER.error(f"Sync error for {source_name}: {e}")

    async def handle_auto_alert(self, news_id, title, summary_raw, source, link, category):
        if not AUTO_POST_CHANNEL_ID:
            return

        channel = self.get_channel(AUTO_POST_CHANNEL_ID)
        if not channel:
            return

        # Check cache (Don't reprocess AI)
        summary_ai = await self.db.get_cached_summary(news_id)
        if not summary_ai:
            summary_ai = await self.ai.process_with_ai(f"{title}\n{summary_raw}")
            await self.db.save_processed_summary(news_id, summary_ai)

        embed = self.create_news_embed(title, summary_ai, source, link, category)
        try:
            await channel.send(content="🚨 **ALERTA CRÍTICO DETECTADO**", embed=embed)
        except Exception as e:
            LOGGER.error(f"Error sending auto alert: {e}")

    def create_news_embed(self, title: str, summary: str, source: str, link: str, category: str) -> discord.Embed:
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
# SLASH COMMANDS (EPHEMERAL)
# ==========================================

@bot.tree.command(name="buscar", description="Pesquisa notícias relevantes no banco de dados e gera resumo com IA.")
@app_commands.describe(query="Termo de busca")
async def buscar(interaction: discord.Interaction, query: str):
    await interaction.response.defer(ephemeral=True)
    await bot.db.log_user_search(interaction.user.id, query)

    results = await bot.db.search_news(query, limit=5)
    if not results:
        return await interaction.followup.send("Nenhum resultado encontrado para sua busca.", ephemeral=True)

    embeds = []
    for news in results:
        # Check cache
        summary_ai = await bot.db.get_cached_summary(news['id'])
        if not summary_ai:
            summary_ai = await bot.ai.process_with_ai(f"{news['title']}\n{news['summary_raw']}")
            await bot.db.save_processed_summary(news['id'], summary_ai)

        embeds.append(bot.create_news_embed(news['title'], summary_ai, news['source'], news['link'], news['category']))

    await interaction.followup.send(embeds=embeds[:5], ephemeral=True)

@bot.tree.command(name="categoria", description="Exibe as últimas notícias armazenadas de uma categoria específica.")
@app_commands.choices(categoria=[
    app_commands.Choice(name="Segurança", value="security"),
    app_commands.Choice(name="Windows", value="windows"),
    app_commands.Choice(name="Linux", value="linux"),
])
async def categoria(interaction: discord.Interaction, categoria: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True)

    results = await bot.db.get_latest_by_category(categoria.value, limit=5)
    if not results:
        return await interaction.followup.send(f"Nenhuma notícia encontrada para a categoria {categoria.name}.", ephemeral=True)

    embeds = []
    for news in results:
        # Check cache
        summary_ai = await bot.db.get_cached_summary(news['id'])
        if not summary_ai:
            summary_ai = await bot.ai.process_with_ai(f"{news['title']}\n{news['summary_raw']}")
            await bot.db.save_processed_summary(news['id'], summary_ai)

        embeds.append(bot.create_news_embed(news['title'], summary_ai, news['source'], news['link'], news['category']))

    await interaction.followup.send(embeds=embeds[:5], ephemeral=True)

@bot.tree.command(name="monitor", description="Adiciona um tópico para monitoramento automático futuro.")
@app_commands.describe(topico="Tópico de interesse (ex: Linux, exploit)")
async def monitor(interaction: discord.Interaction, topico: str):
    await bot.db.add_monitor(interaction.user.id, topico)
    await interaction.response.send_message(f"Monitoramento registrado para o tópico: **{topico}**.", ephemeral=True)

# ==========================================
# INICIALIZAÇÃO
# ==========================================
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("ERRO: DISCORD_TOKEN não configurado nas variáveis de ambiente.")
    else:
        bot.run(DISCORD_TOKEN)
