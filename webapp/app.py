from flask import Flask, request, render_template, jsonify, redirect, url_for
import os
import sys
import threading
import uuid
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from recognizer import MusicRecognizer

app = Flask(__name__)

# In-memory job store (Note: This will be cleared if app restarts)
JOBS = {}

# Helper to get env vars
def get_config():
    return {
           # --- 请修改以下三行 ---
        "ACR_HOST": "identify-cn-north-1.acrcloud.cn",  # 这里的地址可能需要根据您实际的改
        "ACR_ACCESS_KEY": "您的AccessKey",
        "ACR_ACCESS_SECRET": "您的SecretKey",
        # -------------------

        "NETEASE_API": os.environ.get("NETEASE_API_BASE", "http://localhost:3000"),
        "COOKIES_PATH": os.environ.get("YTDLP_COOKIEFILE", "")   
    }

def process_task(job_id, video_url, config_overrides):
    try:
        # Extract config
        acr_host = config_overrides.get('acr_host')
        acr_key = config_overrides.get('acr_key')
        acr_secret = config_overrides.get('acr_secret')
        cookies_path = config_overrides.get('cookies_path')
        netease_api = config_overrides.get('netease_api')
        proxy = config_overrides.get('proxy')

        recognizer = MusicRecognizer(acr_host, acr_key, acr_secret, netease_api)
        result = recognizer.process_video(video_url, cookies_path, proxy)
        
        JOBS[job_id]["status"] = "done"
        JOBS[job_id]["result"] = result
        
        if "error" in result:
             JOBS[job_id]["error"] = result["error"]

    except Exception as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error"] = str(e)

@app.route('/', methods=['GET'])
def index():
    config = get_config()
    job_id = request.args.get('job_id')
    result = None
    error = None

    if job_id and job_id in JOBS:
        job = JOBS[job_id]
        if job["status"] == "done":
            result = job["result"]
            if "error" in job:
                error = job["error"]
        elif job["status"] == "error":
            error = job.get("error", "Unknown error")
        elif job["status"] == "processing":
            # If still processing, just show loading or similar
            # But usually frontend handles this. If user refreshes, we might want to show "Still processing"
            pass
    
    # If job_id is invalid (e.g. server restarted), clear it
    if job_id and job_id not in JOBS:
        # Instead of redirecting immediately, maybe just show the form again?
        # Or better, just let it render with result=None, effectively resetting the view.
        # Redirecting causes a loop if the user refreshes with an old job_id.
        # But for clarity, let's redirect to clean URL.
        return redirect(url_for('index'))
    
    return render_template('index.html', result=result, error=error, config=config, job_id=job_id)

@app.route('/result', methods=['POST'])
def handle_form_submit():
    # Legacy synchronous fallback OR redirect to async flow
    # Since we are moving to async, let's make this endpoint start the task and return the page with job_id
    config = get_config()
    data = request.form
    video_url = data.get('url', '').strip()
    
    # Allow overriding config from form
    acr_host = data.get('acr_host', '').strip() or config["ACR_HOST"]
    acr_key = data.get('acr_key', '').strip() or config["ACR_ACCESS_KEY"]
    acr_secret = data.get('acr_secret', '').strip() or config["ACR_ACCESS_SECRET"]
    cookies_path = data.get('cookies_path', '').strip() or config["COOKIES_PATH"]
    netease_api = data.get('netease_api', '').strip() or config["NETEASE_API"]
    proxy = data.get('proxy', '').strip()

    if not video_url:
        return render_template('index.html', error="请输入视频网址", config=config)
    elif not (acr_host and acr_key and acr_secret):
        return render_template('index.html', error="请配置 ACRCloud 凭据", config=config)

    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "status": "processing",
        "start_time": time.time()
    }

    config_overrides = {
        "acr_host": acr_host,
        "acr_key": acr_key,
        "acr_secret": acr_secret,
        "cookies_path": cookies_path,
        "netease_api": netease_api,
        "proxy": proxy
    }

    thread = threading.Thread(target=process_task, args=(job_id, video_url, config_overrides))
    thread.daemon = True
    thread.start()

    # Redirect to index with job_id to trigger polling view
    return redirect(url_for('index', job_id=job_id))

@app.route('/api/status/<job_id>', methods=['GET'])
def check_status(job_id):
    if job_id not in JOBS:
        return jsonify({"status": "not_found"}), 404
    
    job = JOBS[job_id]
    return jsonify({
        "status": job["status"],
        "error": job.get("error")
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
