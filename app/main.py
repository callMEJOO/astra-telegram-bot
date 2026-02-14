import os, time, threading, tempfile, requests, queue, asyncio
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
# LOGIN + SESSION ENDPOINTS (موقعك)
# =======================
LOGIN_URL = "https://astra.app/auth/callback/credentials"
SESSION_URL = "https://astra.app/api/session"

# =======================
# ASTRA / TOPAZ
# =======================
PROCESS_URL  = "https://api.topazlabs.com/video/"
STATUS_URL   = "https://api.topazlabs.com/video/{jobId}"
DOWNLOAD_URL = "https://api.topazlabs.com/video/{fileId}"

# =======================
# SETTINGS
# =======================
TOKEN_MAX_USES = 10
TIMEOUT = 120
DEBUG = True

# =======================
# STATE
# =======================
job_queue = queue.Queue()
active_jobs = 0

# =======================
# TOKEN MANAGER
# =======================
class TokenManager:
    def __init__(self, max_uses):
        self.token = None
        self.uses = 0
        self.max_uses = max_uses
        self.session = requests.Session()

    def login(self):
        payload = {
            "email": LOGIN_EMAIL,
            "password": LOGIN_PASSWORD,
            "callbackUrl": "/explore",
        }
        r = self.session.post(
            LOGIN_URL,
            data=payload,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "*/*",
                "Pragma": "no-cache",
            },
            timeout=TIMEOUT,
        )
        if DEBUG:
            print("🧪 LOGIN STATUS:", r.status_code)

    def fetch_token(self):
        self.login()  # لازم تتعمل حتى لو مفيش response
        r = self.session.get(
            SESSION_URL,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "*/*",
                "Pragma": "no-cache",
            },
            timeout=TIMEOUT,
        )
        if DEBUG:
            print("🧪 SESSION STATUS:", r.status_code)
            print(r.text[:1000])

        r.raise_for_status()
        data = r.json()
        self.token = data.get("appToken")
        if not self.token:
            raise RuntimeError("NO appToken FOUND")
        self.uses = 0

    def get(self):
        if not self.token or self.uses >= self.max_uses:
            self.fetch_token()
        self.uses += 1
        return self.token

token_mgr = TokenManager(TOKEN_MAX_USES)

# =======================
# HELPERS
# =======================
def headers():
    return {
        "Authorization": f"Bearer {token_mgr.get()}",
        "Accept": "*/*",
        "User-Agent": "Mozilla/5.0",
    }

# =======================
# ASTRA
# =======================
def create_job():
    payload = {
        "source": {"container": "mp4"},
        "filters": [{"model": "slf-2"}],
    }
    r = requests.post(PROCESS_URL, headers=headers(), json=payload, timeout=TIMEOUT)
    if DEBUG:
        print("🧪 CREATE JOB:", r.status_code, r.text[:500])
    r.raise_for_status()
    return r.json()

# =======================
# TELEGRAM
# =======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    await update.message.reply_text("👋 شغال… ابعت أي فيديو للتجربة")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return

    job_queue.put(update.effective_chat.id)
    await update.message.reply_text("🚀 بدأنا… شوف اللوجز")

# =======================
# WORKER
# =======================
def worker(loop, app):
    while True:
        chat_id = job_queue.get()
        try:
            job = create_job()
            asyncio.run_coroutine_threadsafe(
                app.bot.send_message(chat_id, f"✅ Job Created\n{job}"),
                loop,
            )
        except Exception as e:
            asyncio.run_coroutine_threadsafe(
                app.bot.send_message(chat_id, f"❌ Error\n{e}"),
                loop,
            )
        finally:
            job_queue.task_done()

# =======================
# MAIN
# =======================
async def main_async():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))

    loop = asyncio.get_running_loop()
    threading.Thread(target=worker, args=(loop, app), daemon=True).start()

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main_async())
