import os
import tempfile
from yt_dlp import YoutubeDL
import requests
import mimetypes

def download_audio(url, out_dir):
    base = os.path.join(out_dir, "audio")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": base + ".%(ext)s",
        "quiet": True,
    }
    cookiefile = os.environ.get("YTDLP_COOKIEFILE")
    if cookiefile and os.path.exists(cookiefile):
        ydl_opts["cookiefile"] = cookiefile
    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception:
        raise
    for ext in ("webm", "m4a", "mp3", "opus", "aac"):
        p = base + f".{ext}"
        if os.path.exists(p):
            return p
    return base

def slice_segments(audio_path, segment_ms=15000, step_ms=10000, max_segments=20):
    try:
        from pydub import AudioSegment
        segments = []
        audio = AudioSegment.from_file(audio_path)
        i = 0
        t = 0
        while t < len(audio) and i < max_segments:
            end = min(t + segment_ms, len(audio))
            seg = audio[t:end]
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            seg.export(tmp.name, format="wav")
            segments.append(tmp.name)
            i += 1
            t += step_ms
        return segments or [audio_path]
    except Exception:
        return [audio_path]

def acr_recognize(wav_path):
    host = os.environ.get("ACR_HOST", "")
    key = os.environ.get("ACR_ACCESS_KEY", "")
    secret = os.environ.get("ACR_ACCESS_SECRET", "")
    if not host or not key or not secret:
        return None
    import hmac, hashlib, base64, time
    ts = str(int(time.time()))
    try:
        sb = str(os.path.getsize(wav_path))
    except Exception:
        sb = ""
    ct = mimetypes.guess_type(wav_path)[0] or "audio/mpeg"
    files = {"sample": (os.path.basename(wav_path), open(wav_path, "rb"), ct)}
    hosts = []
    if host.startswith("http"):
        hosts.append(host)
    else:
        hosts.append("https://" + host)
        if host.endswith(".cn"):
            hosts.append("https://" + host.replace(".cn", ".com"))
    versions = ["1", "2"]
    attempts = []
    for h in hosts:
        url = f"{h}/v1/identify"
        for ver in versions:
            data = {
                "access_key": key,
                "data_type": "audio",
                "signature_version": ver,
                "timestamp": ts,
            }
            if sb:
                data["sample_bytes"] = sb
            if ver == "1":
                sig_str = f"{key}\n{data['data_type']}\n{ver}\n{ts}"
            else:
                sig_str = f"{key}\n{sb}\n{ts}"
            sign = base64.b64encode(hmac.new(secret.encode(), sig_str.encode(), digestmod=hashlib.sha1).digest()).decode()
            data["signature"] = sign
            try:
                r = requests.post(url, data=data, files=files, timeout=30)
                obj = r.json() if r.headers.get("content-type","" ).startswith("application/json") else {"status":{"code":r.status_code},"error":r.text}
            except Exception as e:
                obj = {"status": {"code": -1}, "error": str(e)}
            attempts.append({"host": h, "version": ver, "sig_str": sig_str, "status": obj.get("status"), "raw": obj})
            if obj.get("status", {}).get("code") == 0:
                return obj
    return {"status": {"code": attempts[-1]["status"]["code"] if attempts else -1}, "attempts": attempts}

def parse_acr_result(obj):
    res = []
    if not obj or obj.get("status", {}).get("code") != 0:
        return res
    md = obj.get("metadata", {})
    for item in md.get("music", []):
        title = item.get("title") or ""
        artists = ", ".join([a.get("name") for a in item.get("artists", []) if a.get("name")])
        if title:
            res.append({"title": title, "artists": artists})
    return res

def search_netease(keywords, api_base):
    q = {"keywords": keywords, "limit": 5}
    try:
        r = requests.get(f"{api_base}/search", params=q, timeout=15)
        if r.status_code != 200:
            return {"matches": [], "raw": {"status": r.status_code}}
        data = r.json()
        songs = data.get("result", {}).get("songs", []) or []
        out = []
        for s in songs:
            out.append({
                "id": s.get("id"),
                "name": s.get("name"),
                "artists": ", ".join([a.get("name") for a in s.get("artists", []) if a.get("name")]),
                "album": (s.get("album") or {}).get("name")
            })
        return {"matches": out, "raw": data}
    except Exception:
        return {"matches": [], "raw": {}}

def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python video_music_recognizer.py <video_url>")
        return
    url = sys.argv[1]
    api_base = os.environ.get("NETEASE_API_BASE", "http://localhost:3000")
    with tempfile.TemporaryDirectory() as td:
        mp3 = download_audio(url, td)
        segs = slice_segments(mp3)
        found = []
        seen = set()
        for w in segs:
            obj = acr_recognize(w)
            parsed = parse_acr_result(obj)
            for it in parsed:
                key = (it["title"], it["artists"])
                if key not in seen:
                    seen.add(key)
                    found.append(it)
        print("Detected tracks:")
        for it in found:
            print(f"- {it['title']} | {it['artists']}")
        print("Netease matches:")
        for it in found:
            kws = it["title"] + (" " + it["artists"] if it["artists"] else "")
            matches = search_netease(kws, api_base)
            print(f"[{kws}]")
            for m in matches:
                print(f"  - {m['name']} | {m['artists']} | {m['album']} | id={m['id']}")

def analyze_video(url, api_base=None):
    api = api_base or os.environ.get("NETEASE_API_BASE", "http://localhost:3000")
    acr_host = os.environ.get("ACR_HOST", "")
    with tempfile.TemporaryDirectory() as td:
        mp3 = download_audio(url, td)
        size_bytes = 0
        duration_ms = None
        try:
            size_bytes = os.path.getsize(mp3)
        except Exception:
            size_bytes = 0
        try:
            from pydub import AudioSegment
            duration_ms = len(AudioSegment.from_file(mp3))
        except Exception:
            duration_ms = None
        segs = slice_segments(mp3)
        found = []
        seen = set()
        acr_details = []
        for idx, w in enumerate(segs, start=1):
            obj = acr_recognize(w)
            parsed = parse_acr_result(obj)
            acr_details.append({"segment": idx, "raw": obj})
            for it in parsed:
                key = (it["title"], it["artists"])
                if key not in seen:
                    seen.add(key)
                    found.append(it)
        out = []
        for it in found:
            kws = it["title"] + (" " + it["artists"] if it["artists"] else "")
            matches = search_netease(kws, api)
            out.append({"query": kws, "matches": matches["matches"], "raw": matches["raw"]})
        return {"tracks": found, "netease": out, "api_base": api, "segments": len(segs), "acr": acr_details, "acr_host": acr_host, "download": {"path": mp3, "bytes": size_bytes, "duration_ms": duration_ms}}

if __name__ == "__main__":
    main()
