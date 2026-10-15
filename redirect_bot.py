from __future__ import annotations

import asyncio
import logging
import hmac
import uuid
from collections import deque
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
RECENT_LOGS: deque[str] = deque(maxlen=40)


class MemoryLogHandler(logging.Handler):
    def emit(self, record):
        try:
            RECENT_LOGS.append(self.format(record))
        except Exception:
            pass


_memory_handler = MemoryLogHandler()
_memory_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log.addHandler(_memory_handler)

def normalize_discord_token(value: Optional[str]) -> str:
    """Normalize common copy/paste formatting without logging the secret."""
    token = (value or "").strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}:
        token = token[1:-1].strip()
    # discord.py adds the Bot authorization scheme itself; avoid "Bot Bot <token>".
    if token[:4].lower() == "bot ":
        token = token[4:].strip()
    return token


REPOSITORY = os.getenv("GITHUB_REPOSITORY", "ubaparator/UBAgenGitv0.01")
GH_TOKEN = os.getenv("GH_TOKEN", "").strip()
BOT_TOKEN = normalize_discord_token(os.getenv("DISCORD_BOT_TOKEN"))
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY", "")
SUBTITLE_CALLBACK_SECRET = os.getenv("SUBTITLE_CALLBACK_SECRET", "")
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


def github_dispatch_error(action: str, status: int, body: str) -> str:
    """Return actionable diagnostics without ever exposing the configured token."""
    global LAST_ERROR
    detail = (body or "").strip()
    if status == 403 and ("Resource not accessible" in detail or "personal access token" in detail.lower()):
        message = (
            f"GitHub {action} HTTP 403: GH_TOKEN yetkisi yetersiz. "
            "Render > Environment > GH_TOKEN değerini kontrol et. Fine-grained PAT için "
            "hedef repo ubaparator/UBAgenGitv0.01 seçili olmalı ve Repository permissions "
            "altında Contents = Read and write olmalı (Metadata = Read-only). "
            "Classic PAT kullanıyorsan private repo için repo scope gerekir. "
            "Tokenı değiştirdikten sonra Render servisini redeploy et. Token loglanmadı."
        )
    elif status == 401:
        message = (
            f"GitHub {action} HTTP 401: GH_TOKEN geçersiz, süresi dolmuş veya iptal edilmiş. "
            "GitHub'da tokenı yenile, Render > Environment içindeki GH_TOKEN değerini güncelle "
            "ve servisi redeploy et. Token loglanmadı."
        )
    elif status == 404:
        message = (
            f"GitHub {action} HTTP 404: hedef depo bulunamadı veya token depoya erişemiyor. "
            f"GITHUB_REPOSITORY/REPOSITORY değerini kontrol et (mevcut hedef: {REPOSITORY})."
        )
    else:
        message = f"GitHub {action} HTTP {status}: {detail[:250]}"
    LAST_ERROR = message
    log.error("%s", message)
    return message


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
                message = github_dispatch_error("dispatch", response.status, body)
                raise HTTPException(status_code=502, detail=message)
    job = {
        "requested_at": int(time.time()),
        "codec": codec,
        "has_subtitle": bool(subtitle_url),
        "status": "GitHub Actions'a gönderildi",
    }
    RECENT_JOBS.insert(0, job)
    del RECENT_JOBS[MAX_JOBS:]
    return job


async def dispatch_subtitle_extraction(magnet_link: str, target_lang: str, subtitle_format: str, discord_channel_id: int, message_id: int, job_id: str) -> dict:
    global LAST_ERROR
    if not GH_TOKEN:
        LAST_ERROR = "GH_TOKEN eksik."
        raise HTTPException(status_code=503, detail=LAST_ERROR)
    magnet_link = magnet_link.strip()
    target_lang = (target_lang or "tur").strip().lower() or "tur"
    if not magnet_link.startswith("magnet:?") or len(magnet_link) > 4000 or "\n" in magnet_link or "\r" in magnet_link:
        raise HTTPException(status_code=400, detail="Geçerli bir magnet bağlantısı girilmeli (magnet:? ile başlamalı).")
    import re
    if not re.fullmatch(r"[a-z]{3}", target_lang):
        raise HTTPException(status_code=400, detail="Dil kodu 3 küçük harf olmalı; örnek: tur, eng, ger, fre, spa, jpn.")
    if subtitle_format not in {"srt", "ass"}:
        raise HTTPException(status_code=400, detail="Altyazı türü SRT veya ASS olmalı.")
    payload = {"event_type": "extract_subtitle_request", "client_payload": {"magnet_link": magnet_link, "target_lang": target_lang, "subtitle_format": subtitle_format, "discord_channel_id": str(discord_channel_id), "status_message_id": str(message_id), "job_id": job_id, "requested_at": int(time.time())}}
    headers = {"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "UBAgen-GitHub-Bridge"}
    url = f"https://api.github.com/repos/{REPOSITORY}/dispatches"
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, headers=headers, json=payload) as response:
            body = await response.text()
            if response.status != 204:
                message = github_dispatch_error("subtitle dispatch", response.status, body)
                raise HTTPException(status_code=502, detail=message)
    job = {"requested_at": int(time.time()), "codec": "subtitle-extraction", "has_subtitle": True, "status": f"GitHub Actions'a gönderildi ({target_lang}, {subtitle_format.upper()})"}
    RECENT_JOBS.insert(0, job)
    del RECENT_JOBS[MAX_JOBS:]
    return job

@bot.event
async def on_disconnect():
    global LAST_ERROR
    LAST_ERROR = "Discord Gateway bağlantısı kesildi; yeniden bağlanma bekleniyor."
    log.warning(LAST_ERROR)


@bot.event
async def on_resumed():
    log.info("Discord Gateway bağlantısı yeniden kuruldu.")


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
        await interaction.response.send_message("Bot şu anda yeni iş kabul etmiyor.", ephemeral=False)
        return
    if not video.content_type or not (video.content_type.startswith("video/") or video.filename.lower().endswith((".mp4", ".mkv", ".mov", ".webm", ".avi"))):
        await interaction.response.send_message("Video dosyası eklemelisin.", ephemeral=False)
        return
    subtitle_url = None
    if subtitle:
        if not subtitle.filename.lower().endswith((".ass", ".ssa", ".srt")):
            await interaction.response.send_message("Altyazı dosyası .ass, .ssa veya .srt olmalı.", ephemeral=False)
            return
        subtitle_url = subtitle.url
    await interaction.response.defer(ephemeral=False, thinking=True)
    try:
        job = await dispatch_encode(video.url, subtitle_url, codec.value)
        await interaction.followup.send(
            f"İş GitHub Actions'a gönderildi. Codec: {codec.name}. "
            f"Altyazı: {'var' if subtitle_url else 'yok'}. "
            f"Durum: {job['status']}. İşleri Actions sekmesinden izleyebilirsin.",
            ephemeral=False,
        )
    except HTTPException as exc:
        await interaction.followup.send(str(exc.detail), ephemeral=False)


@tree.command(name="altyazi_ayikla", description="Magnet bağlantısından SRT veya ASS altyazıyı ayıkla ve buraya gönder")
@app_commands.describe(magnet_link="Torrent magnet bağlantısı (magnet:? ile başlamalı)", format="İndirilecek altyazı dosyası türü", dil="Üç harfli altyazı dili kodu; varsayılan tur")
@app_commands.choices(format=[
    app_commands.Choice(name="SRT", value="srt"),
    app_commands.Choice(name="ASS", value="ass"),
])
async def altyazi_ayikla(interaction: discord.Interaction, magnet_link: str, format: app_commands.Choice[str], dil: str = "tur"):
    if not ACCEPTING_JOBS:
        await interaction.response.send_message("Bot şu anda yeni iş kabul etmiyor.", ephemeral=False)
        return
    await interaction.response.defer(ephemeral=False, thinking=True)
    job_id = uuid.uuid4().hex
    try:
        status_message = await interaction.edit_original_response(
            content="**UBAgen ayıklıyor**\nVideo adı: video\nDurum: İstek kuyruğa gönderiliyor..."
        )
        await dispatch_subtitle_extraction(
            magnet_link, dil, format.value, interaction.channel_id, status_message.id, job_id
        )
        await interaction.edit_original_response(
            content=f"**UBAgen ayıklıyor**\nVideo adı: video\nDurum: Torrent indirme bilgisi bekleniyor..."
        )
    except HTTPException as exc:
        await interaction.edit_original_response(content=f"❌ Altyazı işi başlatılamadı: {str(exc.detail)[:1700]}")
    except Exception as exc:
        log.exception("Subtitle request failed")
        await interaction.edit_original_response(content=f"❌ Altyazı işi başlatılamadı: {type(exc).__name__}")

@tree.command(name="stats", description="Bot ve servis durumunu göster")
async def stats(interaction: discord.Interaction):
    uptime = int(time.time() - STARTED_AT)
    text = (
        f"UBAgen: {'açık' if bot.is_ready() else 'Discord bağlantısı yok'}\n"
        f"Servis: {'çalışıyor' if not app.state.stopping else 'kapanıyor'}\n"
        f"Çalışma: {uptime // 3600}s {(uptime % 3600) // 60}d\n"
        f"Son 24 saatteki işler burada tutulmaz; son {len(RECENT_JOBS)} istek bellekte."
    )
    await interaction.response.send_message(text[:1000], ephemeral=False)


@tree.command(name="log", description="Son hata/eksik ayar bilgisini göster")
async def log_command(interaction: discord.Interaction):
    message = LAST_ERROR[:850]
    await interaction.response.send_message(f"Son hata: {message}", ephemeral=False)


@tree.command(name="discord", description="Yeni encode işlerini aç/kapat")
@app_commands.describe(mode="Yeni iş kabulünü aç veya kapat")
@app_commands.choices(mode=[
    app_commands.Choice(name="Aç", value="on"),
    app_commands.Choice(name="Kapat", value="off"),
])
async def discord_mode(interaction: discord.Interaction, mode: app_commands.Choice[str]):
    global ACCEPTING_JOBS
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("Bu komut için Sunucuyu Yönet izni gerekli.", ephemeral=False)
        return
    ACCEPTING_JOBS = mode.value == "on"
    await interaction.response.send_message(
        f"Yeni iş kabulü {'açıldı' if ACCEPTING_JOBS else 'kapatıldı'}. Bot bağlantısı kesilmedi.",
        ephemeral=False,
    )



@app.post("/api/subtitle-progress")
async def subtitle_progress(payload: dict, x_subtitle_callback_secret: Optional[str] = Header(default=None)):
    """Authenticated GitHub Actions callback that edits only the supplied job status message."""
    global LAST_ERROR
    job_id = str(payload.get("job_id", "")).strip()
    channel_id = str(payload.get("channel_id", "")).strip()
    message_id = str(payload.get("message_id", "")).strip()
    if not SUBTITLE_CALLBACK_SECRET:
        LAST_ERROR = "SUBTITLE_CALLBACK_SECRET Render ortamında eksik; canlı altyazı ilerleme güncellemeleri kapalı."
        log.error("Subtitle callback rejected job=%s: callback secret is not configured on Render", job_id or "unknown")
        raise HTTPException(status_code=503, detail=LAST_ERROR)
    if not x_subtitle_callback_secret or not hmac.compare_digest(x_subtitle_callback_secret, SUBTITLE_CALLBACK_SECRET):
        LAST_ERROR = "Altyazı callback kimlik doğrulaması başarısız (401). Render ve GitHub Actions SUBTITLE_CALLBACK_SECRET aynı olmalı."
        log.error("Subtitle callback authentication failed job=%s channel=%s message=%s", job_id or "unknown", channel_id or "unknown", message_id or "unknown")
        raise HTTPException(status_code=401, detail=LAST_ERROR)
    content = str(payload.get("content", "")).strip()
    if not (channel_id.isdigit() and message_id.isdigit() and job_id and content):
        LAST_ERROR = "Altyazı callback alanları eksik/geçersiz (400): job_id, channel_id, message_id, content gerekli."
        log.error("Subtitle callback malformed payload job=%s channel=%s message=%s", job_id or "unknown", channel_id or "unknown", message_id or "unknown")
        raise HTTPException(status_code=400, detail=LAST_ERROR)
    content = content[:1900]
    if not bot.is_ready():
        LAST_ERROR = "Altyazı ilerlemesi güncellenemedi: Discord Gateway bağlı değil (503)."
        log.error("Subtitle callback cannot edit status: Discord not ready; job=%s channel=%s message=%s", job_id, channel_id, message_id)
        raise HTTPException(status_code=503, detail=LAST_ERROR)
    try:
        channel = bot.get_channel(int(channel_id))
        if channel is None:
            channel = await bot.fetch_channel(int(channel_id))
        message = await channel.fetch_message(int(message_id))
        await message.edit(content=content)
        log.info("Subtitle progress updated job=%s channel=%s message=%s chars=%s", job_id, channel_id, message_id, len(content))
    except discord.NotFound as exc:
        LAST_ERROR = f"Altyazı ilerleme mesajı bulunamadı (Discord HTTP {getattr(exc, 'status', 404)}, code {getattr(exc, 'code', 'unknown')}); mesaj silinmiş olabilir."
        log.error("Subtitle callback message/channel not found job=%s channel=%s message=%s discord_code=%s", job_id, channel_id, message_id, getattr(exc, "code", "unknown"))
        raise HTTPException(status_code=404, detail=LAST_ERROR)
    except discord.Forbidden as exc:
        LAST_ERROR = f"Botun ilerleme mesajına erişim/düzenleme izni yok (Discord HTTP {getattr(exc, 'status', 403)}, code {getattr(exc, 'code', 'unknown')}). Kanal izinlerini ve doğru bot tokenını kontrol et."
        log.error("Subtitle callback forbidden job=%s channel=%s message=%s discord_code=%s", job_id, channel_id, message_id, getattr(exc, "code", "unknown"))
        raise HTTPException(status_code=403, detail=LAST_ERROR)
    except discord.HTTPException as exc:
        LAST_ERROR = f"Discord ilerleme güncelleme hatası: HTTP {getattr(exc, 'status', 'unknown')}, code {getattr(exc, 'code', 'unknown')}."
        log.exception("Subtitle callback Discord HTTP error job=%s channel=%s message=%s", job_id, channel_id, message_id)
        raise HTTPException(status_code=502, detail=LAST_ERROR)
    except Exception as exc:
        LAST_ERROR = f"Altyazı callback hatası: {type(exc).__name__}: {str(exc)[:250]}"
        log.exception("Subtitle callback could not edit status job=%s channel=%s message=%s", job_id, channel_id, message_id)
        raise HTTPException(status_code=502, detail=LAST_ERROR)
    return {"ok": True, "job_id": job_id}

@app.get("/health")
async def health():
    stopping = getattr(app.state, "stopping", False)
    task_failed = bot_task is not None and bot_task.done() and not stopping
    # Render checks this endpoint. A dead Discord background task must not look
    # healthy merely because FastAPI is still serving HTTP requests.
    # A rejected token is configuration trouble, not something a restart fixes.
    token_rejected = "401 Unauthorized" in LAST_ERROR
    if task_failed and not token_rejected:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "service": "ubagen-github-bridge",
                "discord_ready": False,
                "discord_task_running": False,
                "uptime_seconds": int(time.time() - STARTED_AT),
                "accepting_jobs": ACCEPTING_JOBS,
            },
        )
    return {
        "ok": True,
        "service": "ubagen-github-bridge",
        "discord_ready": bot.is_ready(),
        "discord_user_id": str(bot.user.id) if bot.user else None,
        "discord_task_running": bot_task is not None and not bot_task.done(),
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


@app.get("/api/diagnostics")
async def diagnostics(x_dashboard_key: Optional[str] = Header(default=None)):
    auth(x_dashboard_key)
    checks = [
        {"name": "Render servisi", "ok": True, "detail": "API isteğe yanıt verdi."},
        {"name": "Discord bot tokenı", "ok": bool(BOT_TOKEN), "detail": "Tanımlı" if BOT_TOKEN else "DISCORD_BOT_TOKEN eksik; Render Environment bölümüne ekle."},
        {"name": "Discord Gateway", "ok": bot.is_ready(), "detail": "Bağlı" if bot.is_ready() else (LAST_ERROR if "Discord tokenı Discord tarafından reddedildi" in LAST_ERROR else "Bağlı değil; Render loglarını ve bot davetini kontrol et.")},
        {"name": "GitHub tokenı", "ok": bool(GH_TOKEN), "detail": "Tanımlı" if GH_TOKEN else "GH_TOKEN eksik; encode işlerini başlatamaz."},
        {"name": "Panel anahtarı", "ok": bool(DASHBOARD_API_KEY), "detail": "Tanımlı" if DASHBOARD_API_KEY else "DASHBOARD_API_KEY eksik."},
        {"name": "Depo hedefi", "ok": REPOSITORY == "ubaparator/UBAgenGitv0.01", "detail": REPOSITORY},
        {"name": "İş kabulü", "ok": ACCEPTING_JOBS, "detail": "Açık" if ACCEPTING_JOBS else "Yönetici /discord komutuyla yeni işleri açabilir."},
    ]
    return {
        "ok": all(item["ok"] for item in checks),
        "checked_at": int(time.time()),
        "uptime_seconds": int(time.time() - STARTED_AT),
        "checks": checks,
        "last_error": LAST_ERROR,
        "logs": list(RECENT_LOGS)[-25:],
    }


@app.get("/api/logs")
async def logs(x_dashboard_key: Optional[str] = Header(default=None)):
    auth(x_dashboard_key)
    return {"last_error": LAST_ERROR, "logs": list(RECENT_LOGS)[-25:]}


async def run_discord_bot():
    global LAST_ERROR
    try:
        await bot.start(BOT_TOKEN)
    except discord.LoginFailure:
        # Never log the token or any environment value. Discord 401 means the
        # value received by this process was not accepted as a bot token.
        LAST_ERROR = (
            "Discord tokenı Discord tarafından reddedildi (401 Unauthorized). "
            "Render > Environment > DISCORD_BOT_TOKEN değerinin Developer Portal > "
            "Bot sekmesindeki Bot Token olduğundan emin ol; Client Secret veya Client ID "
            "kullanma. Değeri yeniden kaydet ve servisi redeploy et. Token loglanmadı."
        )
        log.error("%s", LAST_ERROR)
    except Exception as exc:
        LAST_ERROR = f"Discord bot başlatılamadı: {type(exc).__name__}: {exc}"
        log.exception("Discord bot startup failed")


@app.on_event("startup")
async def start_bot():
    global bot_task, LAST_ERROR
    app.state.stopping = False
    if BOT_TOKEN:
        bot_task = asyncio.create_task(run_discord_bot())
    else:
        LAST_ERROR = "DISCORD_BOT_TOKEN eksik."
        log.error("DISCORD_BOT_TOKEN missing; HTTP health endpoint remains available.")


@app.on_event("shutdown")
async def stop_bot():
    app.state.stopping = True
    if not bot.is_closed():
        await bot.close()
    if bot_task and not bot_task.done():
        bot_task.cancel()
