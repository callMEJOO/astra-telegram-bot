import os, time, queue, threading, tempfile, requests
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters

# =======================
# REQUIRED ENV ONLY
# =======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ASTRA_TOKEN = os.getenv("ASTRA_ACCESS_TOKEN")

# =======================
# FIXED CHAT ID (PRIVATE)
# =======================
ALLOWED_CHAT_ID = 5169610078

# =======================
# TOPAZ / ASTRA ENDPOINTS
# =======================
PROCESS_URL  = "https://api.topazlabs.com/video/"
STATUS_URL   = "https://api.topazlabs.com/video/{jobId}"
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
jobs = queue.Queue()
active = 0
token_uses = 0
user_usage = {}

# =======================
# HELPERS
# =======================
def headers():
    return {
        "Authorization": f"Bearer {ASTRA_TOKEN}",
        "Accept": "*/*",
        "User-Agent": "Mozilla/5.0"
    }

def use_token():
    global token_uses
    token_uses += 1
    if token_uses > TOKEN_MAX_USES:
        raise RuntimeError("TOKEN_LIMIT_REACHED")

def allow_user(uid):
    day = int(time.time()) // 86400
    key = (uid, day)
    user_usage[key] = user_usage.get(key, 0) + 1
    return user_usage[key] <= USER_DAILY_LIMIT

# =======================
# TOPAZ / ASTRA
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
            "dynamicCompressionLevel": "High"
        },
        "filters": [{"model": "slf-2"}],
        "notifications": {"webhookUrl": "https://astra.app/api/hooks/video-status"}
    }

    r = requests.post(
        PROCESS_URL,
        headers=headers(),
        json=payload,
        timeout=TIMEOUT
    )
    r.raise_for_status()
    return r.json()

def get_status(job_id):
    r = requests.get(
        STATUS_URL.format(jobId=job_id),
        headers=headers(),
        timeout=TIMEOUT
    )
    r.raise_for_status()
    return r.json()

def download_result(file_id):
    r = requests.get(
        DOWNLOAD_URL.format(fileId=file_id),
        headers=headers(),
        stream=True,
        timeout=TIMEOUT
    )
    r.raise_for_status()
    return r

# =======================
# WORKER
# =======================
def worker():
    global active
    while True:
        chat_id, path, ctx = jobs.get()
        active += 1
        try:
            job = create_job(path)
            job_id = job.get("jobId")

            while True:
                st = get_status(job_id)
                if st.get("status") == "completed":
                    file_id = st.get("resultFileId")
                    r = download_result(file_id)

                    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as f:
                        for chunk in r.iter_content(1024 * 1024):
                            f.write(chunk)
                        ctx.bot.send_video(chat_id, video=open(f.name, "rb"))
                    break

                time.sleep(POLL_INTERVAL)

        except Exception:
            try:
                ctx.bot.send_message(chat_id, "❌ حصل خطأ أثناء المعالجة.")
            except:
                pass
        finally:
            active -= 1
            jobs.task_done()
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

    global active
    uid = update.effective_user.id

    if not allow_user(uid):
        await update.message.reply_text("🚫 وصلت للحد اليومي")
        return

    if active >= MAX_CONCURRENT:
        await update.message.reply_text("⏳ مستنيين دورك")
        return

    file = await update.message.video.get_file()
    path = f"/tmp/{file.file_id}.mp4"
    await file.download_to_drive(path)

    jobs.put((update.effective_chat.id, path, context))
    await update.message.reply_text("📥 استلمت الفيديو")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))

    threading.Thread(target=worker, daemon=True).start()
    app.run_polling()

if __name__ == "__main__":
    main()
