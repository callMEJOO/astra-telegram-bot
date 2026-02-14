import os, tempfile
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from .queue import job_queue, worker
from .limits import allow
from .astra_client import upload_video, create_job, get_status, download_result

BOT_TOKEN = os.getenv("BOT_TOKEN")
ASTRA_TOKEN = os.getenv("ASTRA_ACCESS_TOKEN")

# PLACEHOLDERS — ركب endpoints الحقيقية عندك
UPLOAD_URL = "<UPLOAD_ENDPOINT>"
PROCESS_URL = "<PROCESS_ENDPOINT>"
STATUS_URL_TMPL = "<STATUS_ENDPOINT>/{jobId}"
DOWNLOAD_URL_TMPL = "<DOWNLOAD_ENDPOINT>/{fileId}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 ابعت الفيديو وهنبدأ المعالجة.")

def process_job(job):
    chat_id, video_path, context = job

    up = upload_video(UPLOAD_URL, video_path, ASTRA_TOKEN)
    payload = {
        "fileId": up.get("fileId"),
        "filters": [{"model": "astra"}]
    }
    jobr = create_job(PROCESS_URL, payload, ASTRA_TOKEN)
    job_id = jobr.get("jobId")

    while True:
        st = get_status(STATUS_URL_TMPL.format(jobId=job_id), ASTRA_TOKEN)
        if st.get("status") == "completed":
            out_id = st.get("resultFileId")
            r = download_result(DOWNLOAD_URL_TMPL.format(fileId=out_id), ASTRA_TOKEN)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as f:
                for chunk in r.iter_content(1024 * 1024):
                    f.write(chunk)
                context.bot.send_video(chat_id, video=open(f.name, "rb"))
            break

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not allow(uid):
        await update.message.reply_text("🚫 وصلت للحد اليومي.")
        return
    file = await update.message.video.get_file()
    path = f"/tmp/{file.file_id}.mp4"
    await file.download_to_drive(path)
    job_queue.put((update.effective_chat.id, path, context))
    await update.message.reply_text("⏳ استلمت الفيديو—جاري المعالجة.")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    import threading
    threading.Thread(target=worker, args=(process_job,), daemon=True).start()
    app.run_polling()

if __name__ == "__main__":
    main()
