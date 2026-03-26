import asyncio
import logging
import sqlite3
import os
import aiohttp
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Dict

import discord
from discord import app_commands
from discord.ext import commands, tasks
import feedparser
from openai import AsyncOpenAI

# ==========================================
# INSTRUÇÕES DE CONFIGURAÇÃO E PERMISSÕES
# ==========================================
# 1. Acesse https://discord.com/developers/applications
# 2. No menu 'OAuth2' -> 'URL Generator':
#    - Marque os Escopos: 'bot', 'applications.commands'
#    - Marque as Permissões do Bot: 'Send Messages', 'Embed Links', 'Read Message History', 'Use Slash Commands'
# 3. Use a URL gerada para convidar o bot para o seu servidor.
# 4. Certifique-se de que 'Message Content Intent' esteja ATIVADO em 'Bot' -> 'Privileged Gateway Intents'.

# ==========================================
# CONFIGURAÇÃO DO BOT (INSIRA SEUS DADOS AQUI)
# ==========================================
DISCORD_TOKEN = "SEU_TOKEN_AQUI"
OPENAI_API_KEY = "SUA_CHAVE_OPENAI_AQUI"

# ID do canal para notícias críticas automáticas (Destaques)
CHANNEL_ID_HIGHLIGHTS = 123456789012345678

# Configurações Gerais
CHECK_INTERVAL_MINUTES = 30
DATABASE_NAME = "tech_intel_bot.db"
OPENAI_MODEL = "gpt-4o-mini"

# Fontes RSS (Incluindo Reddit via RSS)
RSS_FEEDS = {
    "security": [
        "https://www.bleepingcomputer.com/feed/",
        "https://feeds.feedburner.com/TheHackersNews",
        "https://www.reddit.com/r/netsec/.rss",
        "https://www.reddit.com/r/cybersecurity/.rss"
    ],
    "windows": [
        "https://news.microsoft.com/feed/",
        "https://www.reddit.com/r/windows/.rss",
        "https://www.windowslatest.com/feed/"
    ],
    "linux": [
        "https://www.phoronix.com/rss.php",
        "https://linuxmagazine.com/rss/feed/lmi_news",
        "https://www.reddit.com/r/linux/.rss"
    ]
}

# API de CVEs (Vulnerabilidades)
CVE_API_URL = "https://cve.circl.lu/api/last"

# Configuração de Logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
LOGGER = logging.getLogger("TechIntelBot")

# ==========================================
# BANCO DE DADOS (SQLite)
# ==========================================
class Database:
    """Gerencia a persistência de notícias e preferências dos usuários."""
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS news_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    link TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    summary_raw TEXT,
                    summary_ai TEXT,
                    category TEXT,
                    source TEXT,
                    is_critical INTEGER DEFAULT 0,
                    collected_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_monitors (
                    user_id INTEGER NOT NULL,
                    keyword TEXT NOT NULL,
                    PRIMARY KEY (user_id, keyword)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sent_notifications (
                    user_id INTEGER,
                    news_link TEXT,
                    sent_at TEXT,
                    PRIMARY KEY (user_id, news_link)
                )
            """)
            conn.commit()

    def save_news(self, news_data: dict):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO news_cache (link, title, summary_raw, category, source, is_critical, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                news_data['link'], news_data['title'], news_data['summary_raw'],
                news_data['category'], news_data['source'], news_data['is_critical'],
                datetime.now(timezone.utc).isoformat()
            ))
            conn.commit()

    def update_ai_summary(self, link: str, summary_ai: str):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE news_cache SET summary_ai = ? WHERE link = ?", (summary_ai, link))
            conn.commit()

    def get_news_by_category(self, category: str, limit: int = 5) -> List[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM news_cache WHERE category = ? ORDER BY collected_at DESC LIMIT ?", (category, limit))
            return [dict(row) for row in cursor.fetchall()]

    def search_news(self, query: str, limit: int = 5) -> List[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM news_cache
                WHERE title LIKE ? OR summary_raw LIKE ?
                ORDER BY collected_at DESC LIMIT ?
            """, (f'%{query}%', f'%{query}%', limit))
            return [dict(row) for row in cursor.fetchall()]

    def add_monitor(self, user_id: int, keyword: str):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO user_monitors (user_id, keyword) VALUES (?, ?)", (user_id, keyword.lower()))
            conn.commit()

    def get_user_monitors(self) -> List[Tuple[int, str]]:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, keyword FROM user_monitors")
            return cursor.fetchall()

    def mark_as_sent_to_user(self, user_id: int, link: str):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO sent_notifications (user_id, news_link, sent_at) VALUES (?, ?, ?)",
                           (user_id, link, datetime.now(timezone.utc).isoformat()))
            conn.commit()

    def was_sent_to_user(self, user_id: int, link: str) -> bool:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM sent_notifications WHERE user_id = ? AND news_link = ?", (user_id, link))
            return cursor.fetchone() is not None

# ==========================================
# INTEGRAÇÃO COM IA (Async OpenAI)
# ==========================================
class AIService:
    """Serviço assíncrono para resumos com a API da OpenAI."""
    def __init__(self, api_key: str, model: str):
        self.client = AsyncOpenAI(api_key=api_key) if api_key and "AQUI" not in api_key else None
        self.model = model

    async def summarize(self, title: str, content: str) -> str:
        if not self.client:
            return f"Nota: API OpenAI não configurada. Resumo original:\n{content[:300]}..."

        prompt = (
            "Você é um jornalista de tecnologia especializado. "
            "Resuma a notícia em PORTUGUÊS (Brasil) de forma clara e profissional. "
            "Destaque os 3 pontos principais em tópicos.\n\n"
            f"Título: {title}\nConteúdo: {content}"
        )
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.4
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            LOGGER.error(f"Erro OpenAI: {e}")
            return "Erro ao gerar resumo automático. Por favor, acesse o link para mais detalhes."

# ==========================================
# INTERFACE DO DISCORD (Buttons & Views)
# ==========================================
class NewsPaginationView(discord.ui.View):
    """View interativa para navegação entre as notícias."""
    def __init__(self, news_list: List[dict], ai_service: AIService, db: Database, user_id: int):
        super().__init__(timeout=120)
        self.news_list = news_list
        self.ai_service = ai_service
        self.db = db
        self.current_index = 0
        self.user_id = user_id

    async def create_embed(self):
        item = self.news_list[self.current_index]

        # Resumo sob demanda para economizar tokens
        if not item.get('summary_ai'):
            summary = await self.ai_service.summarize(item['title'], item['summary_raw'])
            self.db.update_ai_summary(item['link'], summary)
            item['summary_ai'] = summary

        color = {
            "security": discord.Color.red(),
            "windows": discord.Color.blue(),
            "linux": discord.Color.green()
        }.get(item['category'], discord.Color.dark_grey())

        embed = discord.Embed(
            title=item['title'],
            url=item['link'],
            description=item['summary_ai'],
            color=color,
            timestamp=datetime.now()
        )
        embed.set_footer(text=f"Fonte: {item['source']} | Notícia {self.current_index + 1} de {len(self.news_list)}")
        return embed

    @discord.ui.button(label="⬅️ Anterior", style=discord.ButtonStyle.primary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Use /buscar para criar sua própria consulta.", ephemeral=True)

        self.current_index = (self.current_index - 1) % len(self.news_list)
        await interaction.response.edit_message(embed=await self.create_embed(), view=self)

    @discord.ui.button(label="➡️ Próxima", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Use /buscar para criar sua própria consulta.", ephemeral=True)

        self.current_index = (self.current_index + 1) % len(self.news_list)
        await interaction.response.edit_message(embed=await self.create_embed(), view=self)

    @discord.ui.button(label="🔄 Atualizar", style=discord.ButtonStyle.secondary)
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Força um novo resumo da IA
        item = self.news_list[self.current_index]
        await interaction.response.defer()
        summary = await self.ai_service.summarize(item['title'], item['summary_raw'])
        self.db.update_ai_summary(item['link'], summary)
        item['summary_ai'] = summary
        await interaction.edit_original_response(embed=await self.create_embed(), view=self)

# ==========================================
# LÓGICA PRINCIPAL DO BOT
# ==========================================
class TechIntelBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.db = Database(DATABASE_NAME)
        self.ai = AIService(OPENAI_API_KEY, OPENAI_MODEL)
        self.session: Optional[aiohttp.ClientSession] = None

    async def setup_hook(self):
        self.session = aiohttp.ClientSession()
        self.auto_collector.start()
        await self.tree.sync()
        LOGGER.info("Bot configurado e comandos sincronizados.")

    async def on_resigned(self):
        if self.session:
            await self.session.close()

    @tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
    async def auto_collector(self):
        LOGGER.info("Iniciando ciclo de coleta assíncrona...")
        await self.process_collection()

    async def fetch_url(self, url: str) -> str:
        """Busca conteúdo de uma URL de forma assíncrona."""
        try:
            async with self.session.get(url, timeout=15) as response:
                if response.status == 200:
                    return await response.text()
        except Exception as e:
            LOGGER.error(f"Erro ao acessar {url}: {e}")
        return ""

    async def process_collection(self):
        # 1. Coleta de Feeds RSS
        for category, urls in RSS_FEEDS.items():
            for url in urls:
                content = await self.fetch_url(url)
                if content:
                    feed = feedparser.parse(content)
                    for entry in feed.entries:
                        title = entry.get("title", "")
                        link = entry.get("link", "")
                        summary = entry.get("summary", "")
                        source = feed.feed.get("title", "Fonte RSS")

                        is_critical = self.check_critical(title, summary, 0)

                        news_item = {
                            "link": link, "title": title, "summary_raw": summary,
                            "category": category, "source": source, "is_critical": is_critical
                        }
                        self.db.save_news(news_item)

                        if is_critical:
                            await self.send_highlight(news_item)

        # 2. Coleta de CVEs
        cve_content = await self.fetch_url(CVE_API_URL)
        if cve_content:
            try:
                import json
                cves = json.loads(cve_content)
                for cve in cves[:10]:
                    cvss = float(cve.get("cvss", 0) or 0)
                    is_critical = self.check_critical(cve.get("id", ""), cve.get("summary", ""), cvss)

                    news_item = {
                        "link": f"https://nvd.nist.gov/vuln/detail/{cve.get('id')}",
                        "title": f"Vulnerabilidade: {cve.get('id')}",
                        "summary_raw": cve.get("summary", ""),
                        "category": "security", "source": "CIRCL CVE API", "is_critical": is_critical
                    }
                    self.db.save_news(news_item)

                    if is_critical:
                        await self.send_highlight(news_item)
            except Exception as e:
                LOGGER.error(f"Erro ao processar JSON de CVEs: {e}")

        # 3. Notificar Monitores via DM
        await self.notify_monitors()

    def check_critical(self, title: str, summary: str, cvss: float) -> int:
        text = (title + " " + summary).lower()
        critical_keywords = ["critical", "zero-day", "massive leak", "data breach", "ransomware", "emergency patch"]

        if cvss >= 9.0:
            return 1
        if any(kw in text for kw in critical_keywords):
            return 1
        return 0

    async def send_highlight(self, item: dict):
        channel = self.get_channel(CHANNEL_ID_HIGHLIGHTS)
        if not channel:
            return

        # Para notícias críticas, geramos o resumo imediatamente
        if not item.get('summary_ai'):
            item['summary_ai'] = await self.ai.summarize(item['title'], item['summary_raw'])
            self.db.update_ai_summary(item['link'], item['summary_ai'])

        if not self.db.was_sent_to_user(CHANNEL_ID_HIGHLIGHTS, item['link']):
            embed = discord.Embed(
                title=f"🚨 ALERTA CRÍTICO: {item['title']}",
                url=item['link'],
                description=item['summary_ai'],
                color=discord.Color.dark_red(),
                timestamp=datetime.now()
            )
            embed.set_footer(text=f"Fonte: {item['source']} | Alerta Automático")
            try:
                await channel.send(embed=embed)
                self.db.mark_as_sent_to_user(CHANNEL_ID_HIGHLIGHTS, item['link'])
            except Exception as e:
                LOGGER.error(f"Erro ao enviar destaque: {e}")

    async def notify_monitors(self):
        monitors = self.db.get_user_monitors()
        for user_id, keyword in monitors:
            relevant_news = self.db.search_news(keyword, limit=1)
            if relevant_news:
                item = relevant_news[0]
                if not self.db.was_sent_to_user(user_id, item['link']):
                    user = self.get_user(user_id) or await self.fetch_user(user_id)
                    if user:
                        try:
                            if not item.get('summary_ai'):
                                item['summary_ai'] = await self.ai.summarize(item['title'], item['summary_raw'])
                                self.db.update_ai_summary(item['link'], item['summary_ai'])

                            embed = discord.Embed(
                                title=f"🔔 Monitoramento: {keyword}",
                                url=item['link'],
                                description=f"**{item['title']}**\n\n{item['summary_ai']}",
                                color=discord.Color.gold()
                            )
                            await user.send(embed=embed)
                            self.db.mark_as_sent_to_user(user_id, item['link'])
                        except discord.Forbidden:
                            pass # DM bloqueada pelo usuário

bot = TechIntelBot()

# ==========================================
# SLASH COMMANDS
# ==========================================

@bot.tree.command(name="buscar", description="Pesquisa notícias no arquivo do bot.")
@app_commands.describe(termo="O que você deseja buscar? (ex: linux, exploit)")
async def buscar(interaction: discord.Interaction, termo: str):
    await interaction.response.defer()
    results = bot.db.search_news(termo, limit=10)

    if not results:
        return await interaction.followup.send(f"Nenhum resultado para '{termo}'.")

    view = NewsPaginationView(results, bot.ai, bot.db, interaction.user.id)
    embed = await view.create_embed()
    await interaction.followup.send(embed=embed, view=view)

@bot.tree.command(name="categoria", description="Exibe as últimas notícias de uma categoria.")
@app_commands.choices(cat=[
    app_commands.Choice(name="Segurança", value="security"),
    app_commands.Choice(name="Windows", value="windows"),
    app_commands.Choice(name="Linux", value="linux"),
])
async def categoria(interaction: discord.Interaction, cat: app_commands.Choice[str]):
    await interaction.response.defer()
    results = bot.db.get_news_by_category(cat.value, limit=5)

    if not results:
        return await interaction.followup.send(f"Nenhuma notícia encontrada em {cat.name}.")

    view = NewsPaginationView(results, bot.ai, bot.db, interaction.user.id)
    embed = await view.create_embed()
    await interaction.followup.send(embed=embed, view=view)

@bot.tree.command(name="monitor", description="Monitora um termo e envia novidades via DM.")
async def monitor(interaction: discord.Interaction, tema: str):
    bot.db.add_monitor(interaction.user.id, tema)
    await interaction.response.send_message(f"✅ Monitoramento ativado para: **{tema}**. Enviarei DMs quando encontrar novidades!", ephemeral=True)

@bot.command(name="check")
async def check_command(ctx):
    """Comando administrativo para forçar coleta."""
    if ctx.author.guild_permissions.administrator:
        await ctx.send("🔄 Iniciando coleta manual...")
        await bot.process_collection()
        await ctx.send("✅ Coleta finalizada!")

# ==========================================
# EVENTOS
# ==========================================
@bot.event
async def on_ready():
    LOGGER.info(f"Bot Online: {bot.user}")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="/buscar"))

if __name__ == "__main__":
    if DISCORD_TOKEN == "SEU_TOKEN_AQUI":
        print("ERRO: Configure o DISCORD_TOKEN no topo do arquivo.")
    else:
        bot.run(DISCORD_TOKEN)
