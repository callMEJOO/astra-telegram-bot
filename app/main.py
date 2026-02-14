import os
import time
import threading
import tempfile
import requests
import queue

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =======================
# ENV (REQUIRED)
# =======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ASTRA_TOKEN = os.getenv("ASTRA_ACCESS_TOKEN")

# =======================
# PRIVATE CHAT ONLY
# =======================
ALLOWED_CHAT_ID = 5169610078

# =======================
# TOPAZ / ASTRA ENDPOINTS
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
        raise RuntimeError("TOKEN_LIMIT_REACHED")

def allow_user(user_id: int) -> bool:
    day = int(time.time()) // 86400
    key = (user_id, day)
    user_usage[key] = user_usage.get(key, 0) + 1
    return user_usage[key] <= USER_DAILY_LIMIT

# =======================
# TOPAZ / ASTRA LOGIC
# =======================
def create_job(video_path: str):
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
        "notifications": {
            "webhookUrl": "https://astra.app/api/hooks/video-status"
        },
    }

    response = requests.post(
        PROCESS_URL,
        headers=headers(),
        json=payload,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()

def get_status(job_id: str):
    response = requests.get(
        STATUS_URL.format(jobId=job_id),
        headers=headers(),
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()

def download_result(file_id: str):
    response = requests.get(
        DOWNLOAD_URL.format(fileId=file_id),
        headers=headers(),
        stream=True,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response

# =======================
# WORKER THREAD
# =======================
def worker():
    global active_jobs

    while True:
        chat_id, video_path, context = job_queue.get()
        active_jobs += 1

        try:
            job = create_job(video_path)
            job_id = job.get("jobId")

            while True:
                status = get_status(job_id)

                if status.get("status") == "completed":
                    file_id = status.get("resultFileId")
                    result = download_result(file_id)

                    with tempfile.NamedTemporaryFile(
                        delete=False, suffix=".mp4"
                    ) as f:
                        for chunk in result.iter_content(1024 * 1024):
                            f.write(chunk)

                        context.bot.send_video(
                            chat_id, video=open(f.name, "rb")
                        )
                    break

                time.sleep(POLL_INTERVAL)

        except Exception as e:
            try:
                context.bot.send_message(
                    chat_id, "❌ حصل خطأ أثناء المعالجة"
                )
            except Exception:
                pass

        finally:
            active_jobs -= 1
            job_queue.task_done()
            time.sleep(1)

# =======================
# TELEGRAM HANDLERS
# =======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    await update.message.reply_text("👋 ابعت الفيديو")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return

    if active_jobs >= MAX_CONCURRENT:
        await update.message.reply_text("⏳ مستنيين دورك")
        return

    user_id = update.effective_user.id
    if not allow_user(user_id):
        await update.message.reply_text("🚫 وصلت للحد اليومي")
        return

    video = await update.message.video.get_file()
    path = f"/tmp/{video.file_id}.mp4"
    await video.download_to_drive(path)

    job_queue.put((update.effective_chat.id, path, context))
    await update.message.reply_text("📥 استلمت الفيديو")

# =======================
# MAIN
# =======================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))

    threading.Thread(target=worker, daemon=True).start()
    app.run_polling()

if __name__ == "__main__":
    main()
