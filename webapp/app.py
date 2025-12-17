from flask import Flask, request, render_template, jsonify
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from recognizer import MusicRecognizer

app = Flask(__name__)

# Helper to get env vars
def get_config():
    return {
        "ACR_HOST": os.environ.get("ACR_HOST", ""),
        "ACR_ACCESS_KEY": os.environ.get("ACR_ACCESS_KEY", ""),
        "ACR_ACCESS_SECRET": os.environ.get("ACR_ACCESS_SECRET", ""),
        "NETEASE_API": os.environ.get("NETEASE_API_BASE", "http://localhost:3000"),
        "COOKIES_PATH": os.environ.get("YTDLP_COOKIEFILE", "")
    }

@app.route('/', methods=['GET', 'POST'])
def index():
    result = None
    error = None
    config = get_config()

    if request.method == 'POST':
        video_url = request.form.get('url', '').strip()
        
        # Allow overriding config from form
        acr_host = request.form.get('acr_host', '').strip() or config["ACR_HOST"]
        acr_key = request.form.get('acr_key', '').strip() or config["ACR_ACCESS_KEY"]
        acr_secret = request.form.get('acr_secret', '').strip() or config["ACR_ACCESS_SECRET"]
        cookies_path = request.form.get('cookies_path', '').strip() or config["COOKIES_PATH"]
        netease_api = request.form.get('netease_api', '').strip() or config["NETEASE_API"]
        proxy = request.form.get('proxy', '').strip() # New proxy field

        if not video_url:
            error = "请输入视频网址"
        elif not (acr_host and acr_key and acr_secret):
            error = "请配置 ACRCloud 凭据 (Host/Key/Secret)"
        else:
            try:
                recognizer = MusicRecognizer(acr_host, acr_key, acr_secret, netease_api)
                # Pass proxy to process_video
                result = recognizer.process_video(video_url, cookies_path, proxy)
                if "error" in result:
                    error = result["error"]
            except Exception as e:
                error = str(e)

    return render_template('index.html', result=result, error=error, config=config)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
