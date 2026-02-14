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
# ENV CHECK
# =======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

# =======================
# ADMIN / LINKS
# =======================
ADMIN_ID = 5169610078
TIKTOK_URL = "https://www.tiktok.com/@0ver4me"

# =======================
# TOPAZ
# =======================
TOPAZ_CREATE_URL = "https://api.topazlabs.com/video/"
POLL_DELAY = 8          # seconds
MAX_WAIT = 20 * 60      # 20 minutes

# =======================
# MEMORY (RAM)
# =======================
users = {}              # uid -> sub info
pending_msg = {}        # uid -> message_id (for live dashboard)

# =======================
# TIME HELPERS
# =======================
def now(): return int(time.time())
def today(): return int(time.time() // 86400)

# =======================
# ADMIN CHECK
# =======================
def is_admin(uid):
    return uid == ADMIN_ID

# =======================
# TOKEN MANAGER (REUSE >= 10)
# =======================
class TokenManager:
    def __init__(self, max_uses=10):
        self.token = None
        self.uses = 0
        self.max_uses = max_uses

    def fetch_token(self):
        """
        ❗❗ ضع منطقك الحقيقي هنا لجلب التوكن الصالح
        لازم ترجع STRING صالح.
        مثال (Pseudo):
          - login
          - get session
          - extract appToken
          - return appToken
        """
        raise RuntimeError("TOKEN_FETCH_NOT_IMPLEMENTED")

    def get(self):
        if not self.token or self.uses >= self.max_uses:
            self.token = self.fetch_token()
            self.uses = 0
        self.uses += 1
        return self.token

token_mgr = TokenManager(max_uses=10)

# =======================
# SUBSCRIPTIONS
# =======================
def is_subscribed(uid):
    if is_admin(uid):
        return True
    u = users.get(uid)
    return u and u["expires"] > now()

def can_use(uid):
    if is_admin(uid):
        return True, None

    u = users.get(uid)
    if not u or u["expires"] <= now():
        return False, "❌ Subscription required"

    if u["last_day"] != today():
        u["used_today"] = 0
        u["last_day"] = today()

    if u["used_today"] >= u["daily_limit"]:
        return False, "🚫 Daily limit reached"

    return True, None

# =======================
# UI (BUTTONS)
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
        "source": {"container":"mp4","size":1,"duration":2,"frameCount":60,"frameRate":30,
                   "resolution":{"width":576,"height":576}},
        "output": {"resolution":{"width":1080,"height":1080},"frameRate":30,
                   "audioTransfer":"Copy","audioCodec":"AAC","videoEncoder":"H264",
                   "videoProfile":"High","dynamicCompressionLevel":"High","videoBitrate":540540},
        "overrides":{"isPaidDiffusion":True},
        "notifications":{"webhookUrl":"https://astra.app/api/hooks/video-status"},
        "filters":[{"model":"slf-2"}],
    }

def payload_60():
    return {
        "source": {"container":"mp4","size":1,"duration":2,"frameCount":60,"frameRate":30,
                   "resolution":{"width":576,"height":576}},
        "output": {"resolution":{"width":1080,"height":1080},"frameRate":60,
                   "audioTransfer":"Copy","audioCodec":"AAC","videoEncoder":"H264",
                   "videoProfile":"High","dynamicCompressionLevel":"High","videoBitrate":540540},
        "overrides":{"isPaidDiffusion":True},
        "notifications":{"webhookUrl":"https://astra.app/api/hooks/video-status"},
        "filters":[{"model":"slf-2"},{"model":"apo-8","fps":60,"slowmo":1}],
    }

# =======================
# TOPAZ FLOW
# =======================
def create_job(payload):
    r = requests.post(
        TOPAZ_CREATE_URL,
        headers={
            "Authorization": f"Bearer {token_mgr.get()}",
            "Accept": "*/*",
            "User-Agent": "Mozilla/5.0",
        },
        json=payload,
        timeout=120
    )
    r.raise_for_status()
    return r.json()

def poll_job(status_url, progress_cb):
    start = time.time()
    last_update = 0
    while time.time() - start < MAX_WAIT:
        r = requests.get(
            status_url,
            headers={"Authorization": f"Bearer {token_mgr.get()}"},
            timeout=60
        )
        r.raise_for_status()
        data = r.json()

        # LIVE DASHBOARD UPDATE (every ~15s)
        if time.time() - last_update > 15:
            elapsed = int(time.time() - start)
            progress_cb(elapsed, data.get("status", "processing"))
            last_update = time.time()

        if data.get("status") == "completed":
            return data
        if data.get("status") == "failed":
            raise RuntimeError("Topaz job failed")

        time.sleep(POLL_DELAY)

    raise TimeoutError("Topaz job timeout")

def download_video(url):
    r = requests.get(url, stream=True, timeout=300)
    r.raise_for_status()
    f = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    for chunk in r.iter_content(1024 * 1024):
        if chunk:
            f.write(chunk)
    f.close()
    return f.name

# =======================
# HANDLERS
# =======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in users:
        users[uid] = {"expires": 0, "daily_limit": 0, "used_today": 0, "last_day": today()}
        await context.bot.send_message(ADMIN_ID, f"👤 New user\nID: {uid}")
    await update.message.reply_text("Choose an option 👇", reply_markup=main_menu())

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if q.data == "start":
