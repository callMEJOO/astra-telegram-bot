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
# BRAND / ADMIN
# =======================
ADMIN_ID = 5169610078
TIKTOK_URL = "https://www.tiktok.com/@0ver4me"
BRAND = "🌐 Digital Life"

# =======================
# TOPAZ
# =======================
TOPAZ_URL = "https://api.topazlabs.com/video/"
POLL_DELAY = 8
MAX_WAIT = 20 * 60

# =======================
# MEMORY
# =======================
users = {}
waiting_quality = {}
waiting_video = {}

# =======================
# TIME
# =======================
def now(): return int(time.time())
def today(): return int(time.time() // 86400)

# =======================
# TOKEN MANAGER (>=10)
# =======================
class TokenManager:
    def __init__(self, max_uses=10):
        self.token = None
        self.uses = 0
        self.max_uses = max_uses

    def fetch_token(self):
        # 🔒 put your real logic here
        self.token = "INTERNAL_TOKEN"
        self.uses = 0

    def get(self):
        if not self.token or self.uses >= self.max_uses:
            self.fetch_token()
        self.uses += 1
        return self.token

token_mgr = TokenManager(10)

# =======================
# SUBS
# =======================
def is_sub(uid):
    return uid in users and users[uid]["expires"] > now()

def can_use(uid):
    if not is_sub(uid):
        return False, "❌ Subscription required"
    if users[uid]["last_day"] != today():
        users[uid]["used"] = 0
        users[uid]["last_day"] = today()
    if users[uid]["used"] >= users[uid]["limit"]:
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
# TOPAZ PAYLOADS
# =======================
def payload_30():
    return {
        "source": {"container":"mp4","size":1,"duration":2,"frameCount":60,"frameRate":30,"resolution":{"width":576,"height":576}},
        "output": {"resolution":{"width":1080,"height":1080},"frameRate":30,"audioTransfer":"Copy","audioCodec":"AAC",
                   "videoEncoder":"H264","videoProfile":"High","dynamicCompressionLevel":"High","videoBitrate":540540},
        "overrides":{"isPaidDiffusion":True},
        "notifications":{"webhookUrl":"https://astra.app/api/hooks/video-status"},
        "filters":[{"model":"slf-2"}],
    }

def payload_60():
    return {
        "source": {"container":"mp4","size":1,"duration":2,"frameCount":60,"frameRate":30,"resolution":{"width":576,"height":576}},
        "output": {"resolution":{"width":1080,"height":1080},"frameRate":60,"audioTransfer":"Copy","audioCodec":"AAC",
                   "videoEncoder":"H264","videoProfile":"High","dynamicCompressionLevel":"High","videoBitrate":540540},
        "overrides":{"isPaidDiffusion":True},
        "notifications":{"webhookUrl":"https://astra.app/api/hooks/video-status"},
        "filters":[{"model":"slf-2"},{"model":"apo-8","fps":60,"slowmo":1}],
    }

# =======================
# TOPAZ FLOW
# =======================
def create_job(payload):
    r = requests.post(
        TOPAZ_URL,
        headers={"Authorization": f"Bearer {token_mgr.get()}"},
        json=payload,
        timeout=120
    )
    r.raise_for_status()
    return r.json()

def poll_job(status_url):
    start = time.time()
    while time.time() - start < MAX_WAIT:
        r = requests.get(
            status_url,
            headers={"Authorization": f"Bearer {token_mgr.get()}"},
            timeout=60
        )
        r.raise_for_status()
        j = r.json()
        if j.get("status") == "completed":
            return j
        if j.get("status") == "failed":
            raise RuntimeError("Topaz failed")
        time.sleep(POLL_DELAY)
    raise TimeoutError("Timeout")

def download_video(url):
    r = requests.get(url, stream=True, timeout=300)
    r.raise_for_status()
    f = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    for c in r.iter_content(1024*1024):
        if c:
            f.write(c)
    f.close()
    return f.name

# =======================
# HANDLERS
# =======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in users:
        users[uid] = {"expires":0,"limit":0,"used":0,"last_day":today()}
        await context.bot.send_message(ADMIN_ID, f"👤 New user\nID: {uid}")
    await update.message.reply_text(
        f"👋 Welcome\n{BRAND}",
        reply_markup=main_menu()
    )

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if q.data == "start":
        ok, msg = can_use(uid)
        if not ok:
            await q.message.edit_text(msg, reply_markup=main_menu())
            return
        await q.message.edit_text("📤 Upload your video\n" + BRAND)

    elif q.data == "status":
        if not is_sub(uid):
            await q.message.edit_text("❌ No subscription", reply_markup=main_menu())
            return
        u = users[uid]
        days = (u["expires"] - now()) // 86400
        await q.message.edit_text(
            f"⏳ Remaining: {days} days\n🎯 Daily limit: {u['limit']}\n📊 Used today: {u['used']}\n{BRAND}",
            reply_markup=main_menu()
        )

    elif q.data in ("q30","q60"):
        await q.message.edit_text(
            "⚙️ Processing...\n⏳ Estimated 2–5 minutes\n" + BRAND
        )
        try:
            payload = payload_30() if q.data == "q30" else payload_60()
            job = create_job(payload)
            status_url = job.get("statusUrl") or job.get("status_url")
            result = poll_job(status_url)
            result_url = result.get("resultUrl") or result.get("download_url")

            path = download_video(result_url)
            users[uid]["used"] += 1

            await context.bot.send_video(
                chat_id=uid,
                video=open(path,"rb"),
                caption=f"✅ Done\n{BRAND}"
            )
        except Exception as e:
            await context.bot.send_message(uid, f"❌ Failed\n{e}\n{BRAND}")

async def on_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ Video received\nChoose quality 👇",
        reply_markup=quality_menu()
    )

# =======================
# ADMIN
# =======================
async def give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    uid = int(context.args[0])
    days = int(context.args[1])
    limit = int(context.args[2])
    users[uid] = {"expires": now()+days*86400, "limit": limit, "used":0, "last_day":today()}
    await update.message.reply_text("✅ Activated")
    await context.bot.send_message(uid, "🎉 Subscription active\n" + BRAND)

# =======================
# MAIN
# =======================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("give", give))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.VIDEO, on_video))
    app.run_polling()

if __name__ == "__main__":
    main()
