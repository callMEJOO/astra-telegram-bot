import os, time, threading, tempfile, requests, queue, asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# =======================
# ENV
# =======================
BOT_TOKEN = os.getenv("BOT_TOKEN")

# موقعك (Provider) — بيطلع appToken جاهز
INTERNAL_TOKEN_ENDPOINT = os.getenv(
    "INTERNAL_TOKEN_ENDPOINT",
    "https://astra.app/internal/token"  # عدّلها لو اسمها مختلف
)

# =======================
# PRIVATE CHAT
# =======================
ALLOWED_CHAT_ID = 5169610078

# =======================
# ASTRA / TOPAZ
# =======================
PROCESS_URL  = "https://api.topazlabs.com/video/"
STATUS_URL   = "https://api.topazlabs.com/video/{jobId}"
DOWNLOAD_URL = "https://api.topazlabs.com/video/{fileId}"

# =======================
# SETTINGS
# =======================
MAX_CONCURRENT = 1
USER_DAILY_LIMIT = 5
POLL_INTERVAL = 4
TIMEOUT = 120
TOKEN_MAX_USES = 10
DEBUG = True

# =======================
# STATE
# =======================
job_queue = queue.Queue()
active_jobs = 0
user_usage = {}

# =======================
# TOKEN MANAGER
# =======================
class TokenManager:
    def __init__(self, max_uses):
        self.token = None
        self.max_uses = max_uses
        self.uses = 0

    def fetch(self):
        r = requests.get(INTERNAL_TOKEN_ENDPOINT, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        self.token = data.get("token") or data.get("appToken")
        self.uses = 0
        if not self.token:
            raise RuntimeError("NO_TOKEN_FROM_PROVIDER")

    def get(self):
        if not self.token or self.uses >= self.max_uses:
            self.fetch()
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

def debug_log(title, resp):
    if not DEBUG:
        return
    msg = f"🧪 {title}\n"
    if hasattr(resp, "status_code"):
        msg += f"Status: {resp.status_code}\n"
        try:
            msg += resp.text[:3500]
        except:
            pass
    else:
        msg += str(resp)
    print(msg)
    return msg

def allow_user(uid):
    day = int(time.time()) // 86400
    key = (uid, day)
    user_usage[key] = user_usage.get(key, 0) + 1
    return user_usage[key] <= USER_DAILY_LIMIT

# =======================
# ASTRA CALLS
# =======================
def create_job():
    payload = {
        "source": {"container": "mp4"},
        "output": {
            "resolution": {"width": 1920, "height": 1080},
            "frameRate": 30,
            "audioTransfer": "Copy",
            "audioCodec": "AAC",
            "videoEncoder": "H264",
            "videoProfile": "High",
            "dynamicCompressionLevel": "High",
        },
        "filters": [{"model": "slf-2"}],
    }
    r = requests.post(PROCESS_URL, headers=headers(), json=payload, timeout=TIMEOUT)
    debug_log("CREATE JOB", r)
    r.raise_for_status()
    return r.json()

def get_status(job_id):
    r = requests.get(STATUS_URL.format(jobId=job_id), headers=headers(), timeout=TIMEOUT)
    debug_log("JOB STATUS", r)
    r.raise_for_status()
    return r.json()

def download_result(file_id):
    r = requests.get(DOWNLOAD_URL.format(fileId=file_id), headers=headers(), stream=True, timeout=TIMEOUT)
    debug_log("DOWNLOAD", r)
    r.raise_for_status()
    return r

# =======================
# WORKER
# =======================
def worker(loop, app):
    global active_jobs
    while True:
        chat_id = job_queue.get()
        active_jobs += 1
        try:
            job = create_job()
            job_id = job.get("jobId")

            while True:
                st = get_status(job_id)
                if st.get("status") == "completed":
                    r = download_result(st.get("resultFileId"))
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as f:
                        for c in r.iter_content(1024 * 1024):
                            f.write(c)
                        asyncio.run_coroutine_threadsafe(
                            app.bot.send_video(chat_id, video=open(f.name, "rb")),
                            loop
                        )
                    break
                time.sleep(POLL_INTERVAL)

        except Exception as e:
            asyncio.run_coroutine_threadsafe(
                app.bot.send_message(chat_id, f"❌ حصل خطأ:\n{e}"),
                loop
            )
        finally:
            active_jobs -= 1
            job_queue.task_done()
            time.sleep(1)

# =======================
# TELEGRAM
# =======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    await update.message.reply_text("👋 ابعت الفيديو")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return

    global active_jobs
    if active_jobs >= MAX_CONCURRENT:
        await update.message.reply_text("⏳ مستنيين دورك")
        return

    uid = update.effective_user.id
    if not allow_user(uid):
        await update.message.reply_text("🚫 وصلت للحد اليومي")
        return

    # مجرد Trigger للتجربة
    job_queue.put(update.effective_chat.id)
    await update.message.reply_text("📥 استلمت الطلب – شغالين")

# =======================
# ASYNC MAIN
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
