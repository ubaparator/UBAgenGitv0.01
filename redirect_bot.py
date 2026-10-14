from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from fastapi.responses import JSONResponse

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("ubagen-bridge")

REPOSITORY = os.getenv("GITHUB_REPOSITORY", "ubaparator/UBAgenGitv0.01")
GH_TOKEN = os.getenv("GH_TOKEN", "")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY", "")
STARTED_AT = time.time()
LAST_ERROR = "Henüz hata kaydı yok."
ACCEPTING_JOBS = True
RECENT_JOBS: list[dict] = []
MAX_JOBS = 30

intents = discord.Intents.default()
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)
app = FastAPI(title="UBAgen GitHub Bridge", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["https://ubaparator.github.io", "http://localhost", "http://127.0.0.1:5500"], allow_credentials=False, allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Content-Type", "X-Dashboard-Key"])
bot_task: Optional[asyncio.Task] = None


class EncodeRequest(BaseModel):
    video_url: HttpUrl
    subtitle_url: Optional[HttpUrl] = None
    codec: str = "h264"


def auth(key: Optional[str]) -> None:
    if not DASHBOARD_API_KEY:
        raise HTTPException(status_code=503, detail="DASHBOARD_API_KEY Render ortamında ayarlanmamış.")
    if not key or key != DASHBOARD_API_KEY:
        raise HTTPException(status_code=401, detail="Yetkisiz. Yönetim anahtarını kontrol et.")


def public_http_url(value: str) -> bool:
    # URLs are validated as HTTP(S); the worker downloads them in an isolated runner.
    return value.startswith("https://") or value.startswith("http://")


async def dispatch_encode(video_url: str, subtitle_url: Optional[str], codec: str) -> dict:
    global LAST_ERROR
    if not GH_TOKEN:
        LAST_ERROR = "GH_TOKEN eksik."
        raise HTTPException(status_code=503, detail=LAST_ERROR)
    if codec not in {"h264", "h265"}:
        raise HTTPException(status_code=400, detail="Codec h264 veya h265 olmalı.")
    if not public_http_url(video_url) or (subtitle_url and not public_http_url(subtitle_url)):
        raise HTTPException(status_code=400, detail="Yalnızca HTTP(S) bağlantıları destekleniyor.")

    payload = {
        "event_type": "encode_request",
        "client_payload": {
            "video_url": video_url,
            "subtitle_url": subtitle_url or "",
            "codec": codec,
            "requested_at": int(time.time()),
        },
    }
    headers = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "UBAgen-GitHub-Bridge",
    }
    url = f"https://api.github.com/repos/{REPOSITORY}/dispatches"
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, headers=headers, json=payload) as response:
            body = await response.text()
            if response.status != 204:
                LAST_ERROR = f"GitHub dispatch HTTP {response.status}: {body[:350]}"
                log.error(LAST_ERROR)
                raise HTTPException(status_code=502, detail="GitHub Actions işi başlatılamadı. /log komutuna bak.")
    job = {
        "requested_at": int(time.time()),
        "codec": codec,
        "has_subtitle": bool(subtitle_url),
        "status": "GitHub Actions'a gönderildi",
    }
    RECENT_JOBS.insert(0, job)
    del RECENT_JOBS[MAX_JOBS:]
    return job


@bot.event
async def on_ready():
    try:
        synced = await tree.sync()
        log.info("Discord connected as %s; synced %s slash commands", bot.user, len(synced))
    except Exception as exc:
        global LAST_ERROR
        LAST_ERROR = f"Slash komut senkronizasyonu: {type(exc).__name__}: {exc}"
        log.exception("Slash command sync failed")


@tree.command(name="encodeal", description="Videoyu GitHub Actions üzerinde H.264/H.265 kodla")
@app_commands.describe(video="Kodlanacak video dosyası", subtitle="İsteğe bağlı ASS/SRT altyazı dosyası")
@app_commands.choices(codec=[
    app_commands.Choice(name="H.264", value="h264"),
    app_commands.Choice(name="H.265", value="h265"),
])
async def encodeal(
    interaction: discord.Interaction,
    video: discord.Attachment,
    codec: app_commands.Choice[str],
    subtitle: Optional[discord.Attachment] = None,
):
    if not ACCEPTING_JOBS:
        await interaction.response.send_message("Bot şu anda yeni iş kabul etmiyor.", ephemeral=True)
        return
    if not video.content_type or not (video.content_type.startswith("video/") or video.filename.lower().endswith((".mp4", ".mkv", ".mov", ".webm", ".avi"))):
        await interaction.response.send_message("Video dosyası eklemelisin.", ephemeral=True)
        return
    subtitle_url = None
    if subtitle:
        if not subtitle.filename.lower().endswith((".ass", ".ssa", ".srt")):
            await interaction.response.send_message("Altyazı dosyası .ass, .ssa veya .srt olmalı.", ephemeral=True)
            return
        subtitle_url = subtitle.url
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        job = await dispatch_encode(video.url, subtitle_url, codec.value)
        await interaction.followup.send(
            f"İş GitHub Actions'a gönderildi. Codec: {codec.name}. "
            f"Altyazı: {'var' if subtitle_url else 'yok'}. "
            f"Durum: {job['status']}. İşleri Actions sekmesinden izleyebilirsin.",
            ephemeral=True,
        )
    except HTTPException as exc:
        await interaction.followup.send(str(exc.detail), ephemeral=True)


@tree.command(name="stats", description="Bot ve servis durumunu göster")
async def stats(interaction: discord.Interaction):
    uptime = int(time.time() - STARTED_AT)
    text = (
        f"UBAgen: {'açık' if bot.is_ready() else 'Discord bağlantısı yok'}\n"
        f"Servis: {'çalışıyor' if not app.state.stopping else 'kapanıyor'}\n"
        f"Çalışma: {uptime // 3600}s {(uptime % 3600) // 60}d\n"
        f"Son 24 saatteki işler burada tutulmaz; son {len(RECENT_JOBS)} istek bellekte."
    )
    await interaction.response.send_message(text[:1000], ephemeral=True)


@tree.command(name="log", description="Son hata/eksik ayar bilgisini göster")
async def log_command(interaction: discord.Interaction):
    message = LAST_ERROR[:850]
    await interaction.response.send_message(f"Son hata: {message}", ephemeral=True)


@tree.command(name="discord", description="Yeni encode işlerini aç/kapat")
@app_commands.describe(mode="Yeni iş kabulünü aç veya kapat")
@app_commands.choices(mode=[
    app_commands.Choice(name="Aç", value="on"),
    app_commands.Choice(name="Kapat", value="off"),
])
async def discord_mode(interaction: discord.Interaction, mode: app_commands.Choice[str]):
    global ACCEPTING_JOBS
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("Bu komut için Sunucuyu Yönet izni gerekli.", ephemeral=True)
        return
    ACCEPTING_JOBS = mode.value == "on"
    await interaction.response.send_message(
        f"Yeni iş kabulü {'açıldı' if ACCEPTING_JOBS else 'kapatıldı'}. Bot bağlantısı kesilmedi.",
        ephemeral=True,
    )


@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": "ubagen-github-bridge",
        "discord_ready": bot.is_ready(),
        "uptime_seconds": int(time.time() - STARTED_AT),
        "accepting_jobs": ACCEPTING_JOBS,
    }


@app.get("/api/jobs")
async def jobs(x_dashboard_key: Optional[str] = Header(default=None)):
    auth(x_dashboard_key)
    return {"jobs": RECENT_JOBS, "discord_ready": bot.is_ready(), "uptime_seconds": int(time.time() - STARTED_AT)}


@app.post("/api/encode")
async def encode(request: EncodeRequest, x_dashboard_key: Optional[str] = Header(default=None)):
    auth(x_dashboard_key)
    return await dispatch_encode(str(request.video_url), str(request.subtitle_url) if request.subtitle_url else None, request.codec)


@app.get("/api/config-check")
async def config_check(x_dashboard_key: Optional[str] = Header(default=None)):
    auth(x_dashboard_key)
    return {
        "github_token_configured": bool(GH_TOKEN),
        "discord_token_configured": bool(BOT_TOKEN),
        "dashboard_key_configured": bool(DASHBOARD_API_KEY),
        "repository": REPOSITORY,
    }


@app.on_event("startup")
async def start_bot():
    global bot_task
    app.state.stopping = False
    if BOT_TOKEN:
        bot_task = asyncio.create_task(bot.start(BOT_TOKEN))
    else:
        log.error("DISCORD_BOT_TOKEN missing; HTTP health endpoint remains available.")


@app.on_event("shutdown")
async def stop_bot():
    app.state.stopping = True
    if not bot.is_closed():
        await bot.close()
    if bot_task and not bot_task.done():
        bot_task.cancel()
