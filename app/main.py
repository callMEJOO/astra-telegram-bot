import os
import time
import requests
import tempfile
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

# =======================
# ENV
# =======================
BOT_TOKEN = os.getenv("BOT_TOKEN")

# =======================
# BRAND / ADMIN
# =======================
ADMIN_ID = 5169610078
TIKTOK_URL = "https://www.tiktok.com/@0ver4me"
BRAND = "🌐 Digital Life"

# =======================
# TOPAZ
# =======================
TOPAZ_CREATE_URL = "https://api.topazlabs.com/video/"
TOPAZ_STATUS_POLL = 8      # seconds
TOPAZ_MAX_WAIT = 20 * 60  # 20 minutes

# =======================
# IN-MEMORY DB
# =======================
users = {}
pending_quality = {}   # uid -> "30" | "60"
pending_file = {}      # uid -> telegram file_id

# =======================
# TIME
# =======================
def now(): return int(time.time())
def today(): return int(time.time() // 86400)

# =======================
# TOKEN MANAGER (>=10 USES)
# =======================
class TokenManager:
    def __init__(self, max_uses=10):
        self.token = None
        self.uses = 0
        self.max_uses = max_uses

    def fetch_token(self):
        # 🔒 ضع منطقك الحقيقي هنا (login/session)
        self.token = "INTERNAL_TOKEN"
        self.uses = 0

    def get(self):
        if not self.token or self.uses >= self.max_uses:
            self.fetch_token()
        self.uses += 1
        return self.token

token_mgr = TokenManager(10)

# =======================
# SUBSCRIPTIONS
# =======================
def is_subscribed(uid):
    u = users.get(uid)
    return u and u["expires"] > now()

def can_use(uid):
    u = users.get(uid)
    if not u or not is_subscribed(uid):
        return False, "❌ Subscription required"
    if u["last_day"] != today():
        u["used_today"] = 0
        u["last_day"] = today()
    if u["used_today"] >= u["daily_limit"]:
        return False, "🚫 Daily limit reached"
    return True, None

# =======================
# UI
# =======================
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Start Processing", callback_data="start")],
        [InlineKeyboardButton("📊 My Status", callback_data="status")],
        [InlineKeyboardButton("📩 Contact", url=TIKTOK_URL)],
    ])

def quality_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1080p • 30 FPS", callback_data="q30")],
        [InlineKeyboardButton("1080p • 60 FPS (Slow Motion)", callback_data="q60")],
    ])

# =======================
# TOPAZ PAYLOADS (AS PROVIDED)
# =======================
def payload_30():
    return {
        "source": {
            "container": "mp4", "size": 1, "duration": 2,
            "frameCount": 60, "frameRate": 30,
            "resolution": {"width": 576, "height": 576}
        },
        "output": {
            "resolution": {"width": 1080, "height": 1080},
            "frameRate": 30, "audioTransfer": "Copy",
            "audioCodec": "AAC", "videoEncoder": "H264",
            "videoProfile": "High", "dynamicCompressionLevel": "High",
            "videoBitrate": 540540
        },
        "overrides": {"isPaidDiffusion": True},
        "notifications": {"webhookUrl": "https://mysite.app/api/hooks/video-status"},
        "filters": [{"model": "slf-2"}]
    }

def payload_60():
    return {
        "source": {
            "container": "mp4", "size": 1, "duration": 2,
            "frameCount": 60, "frameRate": 30,
            "resolution": {"width": 576, "height": 576}
        },
        "output": {
            "resolution": {"width": 1080, "height": 1080},
            "frameRate": 60, "audioTransfer": "Copy",
            "audioCodec": "AAC", "videoEncoder": "H264",
            "videoProfile": "High", "dynamicCompressionLevel": "High",
            "videoBitrate": 540540
        },
        "overrides": {"isPaidDiffusion": True},
        "notifications": {"webhookUrl": "https://mysite.app/api/hooks/video-status"},
        "filters": [
            {"model": "slf-2"},
            {"model": "apo-8", "fps": 60, "slowmo": 1}
        ]
    }

def topaz_create(payload):
    r = requests.post(
        TOPAZ_CREATE_URL,
        headers={
            "Authorization": f"Bearer {token_mgr.get()}",
            "Accept": "*/*",
            "User-Agent": "Mozilla/5.0",
        },
        json=payload,
        timeout=120,
    )
    r.raise_for_status()
    return r.json()  # expect job info

def topaz_poll(job):
    """
    EXPECTED:
    job may contain: status_url OR id to poll.
    Adjust fields if your response differs.
    """
    status_url = job.get("statusUrl") or job.get("status_url")
    start = time.time()
    while time.time() - start < TOPAZ_MAX_WAIT:
        r = requests.get(
            status_url,
            headers={"Authorization": f"Bearer {token_mgr.get()}"},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("status") == "completed":
            return data
        if data.get("status") == "failed":
            raise RuntimeError("Topaz job failed")
        time.sleep(TOPAZ_STATUS_POLL)
    raise TimeoutError("Topaz job timeout")

def download_result(result_url):
    r = requests.get(result_url, stream=True, timeout=300)
    r.raise_for_status()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    for chunk in r.iter_content(1024 * 1024):
        if chunk:
            tmp.write(chunk)
    tmp.close()
    return tmp.name

# =======================
# HANDLERS
# =======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in users:
        users[uid] = {"expires": 0, "daily_limit": 0, "used_today": 0, "last_day": today()}
        await context.bot.send_message(
            ADMIN_ID,
            f"👤 New user\nID: {uid}\n@{update.effective_user.username}"
        )
    await update.message.reply_text(
        f"👋 Welcome\n{BRAND}\nChoose an option 👇",
        reply_markup=main_menu()
    )

async def on_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if q.data == "start":
        ok, msg = can_use(uid)
        if not ok:
            await q.message.edit_text(msg, reply_markup=main_menu())
            return
        await q.message.edit_text("📤 Upload your video", reply_markup=None)

    elif q.data == "status":
        if not is_subscribed(uid):
            await q.message.edit_text("❌ No active subscription", reply_markup=main_menu())
            return
        u = users[uid]
        days_left = (u["expires"] - now()) // 86400
        await q.message.edit_text(
            f"⏳ Remaining: {days_left} days\n"
            f"🎯 Daily limit: {u['daily_limit']}\n"
            f"📊 Used today: {u['used_today']}\n{BRAND}",
            reply_markup=main_menu()
        )

    elif q.data in ("q30", "q60"):
        pending_quality[uid] = q.data
        await q.message.edit_text(
            "⚙️ Processing started...\n"
            "⏳ Estimated time: 2–5 minutes\n"
            f"{BRAND}"
        )

        # Build payload
        payload = payload_30() if q.data == "q30" else payload_60()
        job = topaz_create(payload)
        result = topaz_poll(job)

        # Adjust this field to your real result URL:
        result_url = result.get("resultUrl") or result.get("download_url")
        video_path = download_result(result_url)

        users[uid]["used_today"] += 1

        await context.bot.send_video(
            chat_id=uid,
            video=open(video_path, "rb"),
            caption=f"✅ Done!\n{BRAND}"
        )

async def on_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    pending_file[uid] = update.message.video.file_id
    await update.message
