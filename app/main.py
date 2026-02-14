import os, time, threading, requests, queue, asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# =======================
# ENV
# =======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
LOGIN_EMAIL = os.getenv("LOGIN_EMAIL")
LOGIN_PASSWORD = os.getenv("LOGIN_PASSWORD")

# =======================
# PRIVATE CHAT
# =======================
ALLOWED_CHAT_ID = 5169610078

# =======================
# YOUR SITE ENDPOINTS
# =======================
LOGIN_URL   = "https://astra.app/auth/callback/credentials"
SESSION_URL = "https://astra.app/api/session"

# =======================
# SETTINGS
# =======================
TOKEN_MAX_USES = 10
TIMEOUT = 120
DEBUG = True

# =======================
# TOKEN MANAGER
# =======================
class TokenManager:
    def __init__(self, max_uses):
        self.session = requests.Session()
        self.token = None
        self.uses = 0
        self.max_uses = max_uses

    def login(self):
        payload = (
            f"email={LOGIN_EMAIL}"
            f"&password={LOGIN_PASSWORD}"
            f"&callbackUrl=%2Fexplore"
        )
        r = self.session.post(
            LOGIN_URL,
            data=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "Mozilla/5.0",
                "Accept": "*/*",
                "Pragma": "no-cache",
            },
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        if DEBUG:
            print("🧪 LOGIN STATUS:", r.status_code)

    def fetch_token(self):
        self.login()

        r = self.session.get(
            SESSION_URL,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Pragma": "no-cache",
            },
            timeout=TIMEOUT,
        )

        print("🧪 SESSION STATUS:", r.status_code)
        print("🧪 SESSION RAW:", r.text[:1000])

        try:
            data = r.json()
        except Exception as e:
            raise RuntimeError(f"SESSION_JSON_PARSE_ERROR: {e}")

        if not data or not isinstance(data, dict):
            raise RuntimeError(f"SESSION_JSON_INVALID: {data}")

        print("🧪 SESSION KEYS:", list(data.keys()))

        # حاول في الـ root
        token = data.get("appToken") or data.get("token")

        # لو متغلف جوه object
        if not token:
            for v in data.values():
                if isinstance(v, dict):
                    token = v.get("appToken") or v.get("token")
                    if token:
                        break

        if not token:
            raise RuntimeError(f"APP_TOKEN_NOT_FOUND | JSON={data}")

        self.token = token
        self.uses = 0
        if DEBUG:
            print("🧪 TOKEN OK:", token[:20], "...")

    def get(self):
        if not self.token or self.uses >= self.max_uses:
            self.fetch_token()
        self.uses += 1
        return self.token

token_mgr = TokenManager(TOKEN_MAX_USES)

# =======================
# TELEGRAM HANDLERS
# =======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    await update.message.reply_text("👋 شغال… ابعت أي رسالة للتجربة")

async def handle_any(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    try:
        t = token_mgr.get()
        await update.message.reply_text(f"✅ TOKEN OK\n{t[:30]}...")
    except Exception as e:
        await update.message.reply_text(f"❌ Error\n{e}")

# =======================
# MAIN
# =======================
async def main_async():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ALL, handle_any))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main_async())
