import asyncio
import logging
import sqlite3
import os
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Dict

import discord
from discord.ext import commands, tasks
import feedparser
import requests
from openai import OpenAI

# ==========================================
# CONFIGURAÇÃO DO BOT (INSIRA SEUS DADOS AQUI)
# ==========================================
DISCORD_TOKEN = "SEU_TOKEN_AQUI"
OPENAI_API_KEY = "SUA_CHAVE_OPENAI_AQUI"

# IDs dos canais do Discord para cada categoria (obtenha o ID clicando com botão direito no canal)
CHANNEL_ID_LINUX = 123456789012345678
CHANNEL_ID_WINDOWS = 123456789012345678
CHANNEL_ID_SECURITY = 123456789012345678

# Configurações Gerais
CHECK_INTERVAL_MINUTES = 30
DATABASE_NAME = "tech_news_bot.db"
OPENAI_MODEL = "gpt-4o-mini"

# Feeds RSS para monitorar
RSS_FEEDS = [
    "https://www.bleepingcomputer.com/feed/",
    "https://feeds.feedburner.com/TheHackersNews",
    "https://www.phoronix.com/rss.php",
    "https://news.microsoft.com/feed/",
    "https://linuxmagazine.com/rss/feed/lmi_news",
    "https://gizmodo.com/rss",
]

# API de CVEs (Vulnerabilidades)
CVE_API_URL = "https://cve.circl.lu/api/last"

# Configuração de Logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
LOGGER = logging.getLogger("TechNewsBot")

# ==========================================
# CLASSE DE BANCO DE DADOS (DEDUPLICAÇÃO)
# ==========================================
class Database:
    """Gerencia a persistência de dados para evitar notícias duplicadas."""
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            # Tabela para notícias normais
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS posted_news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    link TEXT UNIQUE NOT NULL,
                    posted_at TEXT NOT NULL
                )
            """)
            # Tabela para vulnerabilidades (CVE)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS shown_cves (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cve_id TEXT UNIQUE NOT NULL,
                    shown_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def is_new_link(self, link: str) -> bool:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM posted_news WHERE link = ?", (link,))
            return cursor.fetchone() is None

    def mark_link_as_posted(self, link: str):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO posted_news (link, posted_at) VALUES (?, ?)",
                           (link, datetime.now(timezone.utc).isoformat()))
            conn.commit()

    def is_new_cve(self, cve_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM shown_cves WHERE cve_id = ?", (cve_id,))
            return cursor.fetchone() is None

    def mark_cve_as_shown(self, cve_id: str):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO shown_cves (cve_id, shown_at) VALUES (?, ?)",
                           (cve_id, datetime.now(timezone.utc).isoformat()))
            conn.commit()

# ==========================================
# INTEGRAÇÃO COM IA (SUMARIZAÇÃO E TRADUÇÃO)
# ==========================================
class AISummarizer:
    """Utiliza a API da OpenAI para resumir e traduzir as notícias."""
    def __init__(self, api_key: str, model: str):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def summarize_and_translate(self, title: str, content: str) -> str:
        """Envia o conteúdo para a IA resumir em português."""
        if not OPENAI_API_KEY or "AQUI" in OPENAI_API_KEY:
            # Fallback caso a API não esteja configurada
            return f"Nota: API OpenAI não configurada. Resumo original:\n{content[:300]}..."

        prompt = (
            "Você é um jornalista de tecnologia especializado em segurança e sistemas operacionais. "
            "Sua tarefa é resumir a notícia abaixo em PORTUGUÊS (Brasil). "
            "O resumo deve ser claro, objetivo e destacar os pontos mais importantes em tópicos. "
            "Mantenha um tom profissional.\n\n"
            f"Título: {title}\n"
            f"Conteúdo: {content}"
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Você é um bot de notícias útil que resume tecnologia em português."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500,
                temperature=0.5
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            LOGGER.error(f"Erro na API da OpenAI: {e}")
            return "Houve um erro ao gerar o resumo automático. Por favor, verifique o link original."

# ==========================================
# COLETA DE DADOS (RSS E CVE)
# ==========================================
class NewsCollector:
    """Responsável por buscar informações em fontes externas."""
    @staticmethod
    def fetch_rss_news() -> List[Dict]:
        all_news = []
        for url in RSS_FEEDS:
            try:
                feed = feedparser.parse(url)
                if feed.bozo:
                    continue
                for entry in feed.entries:
                    all_news.append({
                        "title": entry.get("title", "Sem título"),
                        "link": entry.get("link", ""),
                        "summary": entry.get("summary", ""),
                        "source": feed.feed.get("title", url.split('/')[2])
                    })
            except Exception as e:
                LOGGER.error(f"Erro ao buscar feed {url}: {e}")
        return all_news

    @staticmethod
    def fetch_latest_cves() -> List[Dict]:
        """Busca as últimas vulnerabilidades registradas."""
        try:
            response = requests.get(CVE_API_URL, timeout=15)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            LOGGER.error(f"Erro ao buscar CVEs: {e}")
        return []

# ==========================================
# LÓGICA DO BOT DO DISCORD
# ==========================================
db = Database(DATABASE_NAME)
ai = AISummarizer(OPENAI_API_KEY, OPENAI_MODEL)
collector = NewsCollector()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

def get_category_and_color(title: str, summary: str) -> Tuple[str, discord.Color]:
    """Define a categoria com base na prioridade: Segurança > Windows > Linux."""
    text = (title + " " + summary).lower()

    # Palavras-chave para classificação
    security_kws = ["security", "vulnerability", "exploit", "breach", "cve", "hack", "ransomware", "malware", "segurança", "vulnerabilidade", "ataque", "vazamento", "zero-day"]
    windows_kws = ["windows", "microsoft", "azure", "defender", "outlook", "office 365", "patch tuesday"]
    linux_kws = ["linux", "kernel", "ubuntu", "debian", "fedora", "arch linux", "mint", "rhel", "distro", "gnome", "kde", "open source"]

    if any(kw in text for kw in security_kws):
        return "security", discord.Color.red()
    if any(kw in text for kw in windows_kws):
        return "windows", discord.Color.blue()
    if any(kw in text for kw in linux_kws):
        return "linux", discord.Color.green()

    # Por padrão, se não detectar nada específico, classifica como Linux conforme solicitado
    return "linux", discord.Color.green()

async def process_and_send_news():
    """Função central que orquestra a coleta, resumo e envio."""
    LOGGER.info("Iniciando ciclo de coleta de notícias...")

    # 1. Notícias de Feeds RSS
    news_items = collector.fetch_rss_news()
    for item in news_items:
        if not item["link"] or not db.is_new_link(item["link"]):
            continue

        category, color = get_category_and_color(item["title"], item["summary"])

        # Mapeamento de canal
        channel_id = {
            "security": CHANNEL_ID_SECURITY,
            "windows": CHANNEL_ID_WINDOWS,
            "linux": CHANNEL_ID_LINUX
        }.get(category)

        channel = bot.get_channel(channel_id)
        if channel:
            try:
                # Gera resumo com IA
                summary_pt = ai.summarize_and_translate(item["title"], item["summary"])

                embed = discord.Embed(
                    title=item["title"],
                    url=item["link"],
                    description=summary_pt,
                    color=color,
                    timestamp=datetime.now()
                )
                embed.set_footer(text=f"Fonte: {item['source']} | Categoria: {category.capitalize()}")

                await channel.send(embed=embed)
                db.mark_link_as_posted(item["link"])
                LOGGER.info(f"Notícia enviada: {item['title']} -> {category}")
                await asyncio.sleep(2) # Evita spam e rate limit
            except Exception as e:
                LOGGER.error(f"Erro ao enviar notícia {item['title']}: {e}")

    # 2. Vulnerabilidades (CVE)
    cve_items = collector.fetch_latest_cves()
    security_channel = bot.get_channel(CHANNEL_ID_SECURITY)

    if security_channel:
        for cve in cve_items[:5]: # Limita a 5 por ciclo para evitar flood
            cve_id = cve.get("id")
            if cve_id and db.is_new_cve(cve_id):
                try:
                    summary_raw = cve.get("summary", "Sem descrição.")
                    summary_pt = ai.summarize_and_translate(f"Nova Vulnerabilidade: {cve_id}", summary_raw)

                    embed = discord.Embed(
                        title=f"🚨 Nova Vulnerabilidade: {cve_id}",
                        url=f"https://nvd.nist.gov/vuln/detail/{cve_id}",
                        description=summary_pt,
                        color=discord.Color.dark_red(),
                        timestamp=datetime.now()
                    )
                    embed.add_field(name="Score CVSS", value=cve.get("cvss", "N/A"), inline=True)
                    embed.set_footer(text="Fonte: CIRCL CVE API")

                    await security_channel.send(embed=embed)
                    db.mark_cve_as_shown(cve_id)
                    LOGGER.info(f"CVE enviado: {cve_id}")
                    await asyncio.sleep(2)
                except Exception as e:
                    LOGGER.error(f"Erro ao enviar CVE {cve_id}: {e}")

    LOGGER.info("Ciclo de coleta finalizado.")

# ==========================================
# EVENTOS E COMANDOS
# ==========================================
@bot.event
async def on_ready():
    LOGGER.info(f"Bot online como {bot.user}")
    # Inicia o loop automático se não estiver rodando
    if not auto_post_task.is_running():
        auto_post_task.start()

@tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
async def auto_post_task():
    try:
        await process_and_send_news()
    except Exception as e:
        LOGGER.error(f"Erro no loop automático: {e}")

@bot.command(name="check")
async def check_command(ctx):
    """Comando manual para forçar a verificação de notícias."""
    if ctx.author.bot:
        return
    await ctx.send("🔍 Iniciando verificação manual de notícias e vulnerabilidades...")
    try:
        await process_and_send_news()
        await ctx.send("✅ Verificação concluída e notícias enviadas aos canais respectivos!")
    except Exception as e:
        await ctx.send(f"❌ Ocorreu um erro durante a verificação: {e}")

# Inicialização
if __name__ == "__main__":
    if DISCORD_TOKEN == "SEU_TOKEN_AQUI":
        print("ERRO: Por favor, configure seu DISCORD_TOKEN no topo do arquivo bot.py.")
    else:
        bot.run(DISCORD_TOKEN)
