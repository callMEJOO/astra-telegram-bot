import os
import time
import threading
import tempfile
import requests
import queue
import asyncio

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =======================
# ENV
# =======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ASTRA_TOKEN = os.getenv("ASTRA_ACCESS_TOKEN")

# =======================
# PRIVATE CHAT
# =======================
ALLOWED_CHAT_ID = 5169610078

# =======================
# TOPAZ / ASTRA
# =======================
PROCESS_URL = "https://api.topazlabs.com/video/"
STATUS_URL = "https://api.topazlabs.com/video/{jobId}"
DOWNLOAD_URL = "https://api.topazlabs.com/video/{fileId}"

# =======================
# SETTINGS
# =======================
MAX_CONCURRENT = 1
USER_DAILY_LIMIT = 2
POLL_INTERVAL = 4
TIMEOUT = 120
TOKEN_MAX_USES = 10

# =======================
# STATE
# =======================
job_queue = queue.Queue()
active_jobs = 0
token_uses = 0
user_usage = {}

# =======================
# HELPERS
# =======================
def headers():
    return {
        "Authorization": f"Bearer {ASTRA_TOKEN}",
        "Accept": "*/*",
        "User-Agent": "Mozilla/5.0",
    }

def use_token():
    global token_uses
    token_uses += 1
    if token_uses > TOKEN_MAX_USES:
        raise RuntimeError("TOKEN_LIMIT")

def allow_user(uid):
    day = int(time.time()) // 86400
    key = (uid, day)
    user_usage[key] = user_usage.get(key, 0) + 1
    return user_usage[key] <= USER_DAILY_LIMIT

# =======================
# ASTRA
# =======================
def create_job(video_path):
    use_token()
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

    r = requests.post(
        PROCESS_URL,
        headers=headers(),
        json=payload,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()

def get_status(job_id):
    r = requests.get(
        STATUS_URL.format(jobId=job_id),
        headers=headers(),
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()

def download_result(file_id):
    r = requests.get(
        DOWNLOAD_URL.format(fileId=file_id),
        headers=headers(),
        stream=True,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r

# =======================
# WORKER THREAD
# =======================
def worker(loop):
    global active_jobs

    while True:
        chat_id, video_path, app = job_queue.get()
        active_jobs += 1

        try:
            job = create_job(video_path)
            job_id = job["jobId"]

            while True:
                st = get_status(job_id)
                if st["status"] == "completed":
                    r = download_result(st["resultFileId"])
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as f:
                        for c in r.iter_content(1024 * 1024):
                            f.write(c)

                        asyncio.run_coroutine_threadsafe(
                            app.bot.send_video(chat_id, video=open(f.name, "rb")),
                            loop,
                        )
                    break
                time.sleep(POLL_INTERVAL)

        except Exception:
            asyncio.run_coroutine_threadsafe(
                app.bot.send_message(chat_id, "❌ حصل خطأ أثناء المعالجة"),
                loop,
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

    file = await update.message.video.get_file()
    path = f"/tmp/{file.file_id}.mp4"
    await file.download_to_drive(path)

    job_queue.put((update.effective_chat.id, path, context.application))
    await update.message.reply_text("📥 استلمت الفيديو")

# =======================
# ASYNC MAIN (FIX)
# =======================
async def main_async():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))

    loop = asyncio.get_running_loop()
    threading.Thread(target=worker, args=(loop,), daemon=True).start()

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()  # keep alive

# =======================
# ENTRY
# =======================
if __name__ == "__main__":
    asyncio.run(main_async())
