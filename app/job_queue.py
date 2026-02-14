import time, queue, threading, os

job_queue = queue.Queue()
ACTIVE = 0
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT_JOBS", "1"))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SEC", "4"))

def worker(process_fn):
    global ACTIVE
    while True:
        job = job_queue.get()
        ACTIVE += 1
        try:
            process_fn(job)
        finally:
            ACTIVE -= 1
            job_queue.task_done()
            time.sleep(1)  # jitter
