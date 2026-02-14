import os, asyncio, requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# =======================
# ENV
# =======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
LOGIN_EMAIL = os.getenv("LOGIN_EMAIL")
LOGIN_PASSWORD = os.getenv("LOGIN_PASSWORD")

# =======================
# CHAT
# =======================
ALLOWED_CHAT_ID = 5169610078

# =======================
# URLS (زي بوستمان)
# =======================
LOGIN_URL = "https://astra.app/auth/callback/credentials?"
SESSION_URL = "https://astra.app/api/session"

# =======================
# TOKEN MANAGER
# =======================
class TokenManager:
    def __init__(self):
        self.s = requests.Session()
        self.token = None
        self.uses = 0
        self.max_uses = 10

    def fetch_token(self):
        # ---------- POST (زي بوستمان بالحرف)
        body = (
            f"email={LOGIN_EMAIL}"
            f"&password={LOGIN_PASSWORD}"
            f"&callbackUrl=%2Fexplore"
        )

        self.s.post(
            LOGIN_URL,
            data=body,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.149 Safari/537.36",
                "Pragma": "no-cache",
                "Accept": "*/*",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            allow_redirects=True,
            timeout=60,
        )

        # ---------- GET (زي بوستمان بالحرف)
        r = self.s.get(
            SESSION_URL,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.149 Safari/537.36",
                "Pragma": "no-cache",
                "Accept": "*/*",
            },
            timeout=60,
        )

        src = r.text
        print("🧪 SESSION RAW:", src[:500])

        # ---------- PARSE LR زي ما انت عامل
        left = 'appToken":"'
        right = '","'

        if left not in src:
            raise RuntimeError("appToken LEFT delimiter not found")

        token = src.split(left, 1)[1].split(right, 1)[0]

        if not token:
            raise RuntimeError("appToken EMPTY")

        self.token = token
        self.uses = 0
        print("✅ TOKEN OK:", token[:25], "...")

    def get(self):
        if not self.token or self.uses >= self.max_uses:
            self.fetch_token()
        self.uses += 1
        return self.token

token_mgr = TokenManager()

# =======================
# TELEGRAM
# =======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    await update.message.reply_text("👋 شغال – ابعت أي رسالة")

async def handle_any(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    try:
        t = token_mgr.get()
        await update.message.reply_text(f"✅ TOKEN\n{t[:30]}...")
    except Exception as e:
        await update.message.reply_text(f"❌ Error\n{e}")

# =======================
# MAIN
# =======================
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ALL, handle_any))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
