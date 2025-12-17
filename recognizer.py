import os
import time
import hmac
import hashlib
import base64
import json
import requests
import tempfile
import mimetypes
from pydub import AudioSegment
import yt_dlp

class MusicRecognizer:
    def __init__(self, acr_host, acr_key, acr_secret, netease_api=None):
        self.acr_host = acr_host
        self.acr_key = acr_key
        self.acr_secret = acr_secret
        self.netease_api = netease_api or "http://localhost:3000"

    def _generate_acr_signature(self, http_method, uri, access_key, data_type, signature_version, timestamp):
        string_to_sign = f"{http_method}\n{uri}\n{access_key}\n{data_type}\n{signature_version}\n{timestamp}"
        sign = base64.b64encode(hmac.new(self.acr_secret.encode('ascii'), string_to_sign.encode('ascii'), digestmod=hashlib.sha1).digest()).decode('ascii')
        return sign

    def _recognize_segment(self, file_path):
        """Identify a single audio segment using ACRCloud V1"""
        if not self.acr_host or not self.acr_key or not self.acr_secret:
            return {"status": {"code": -1, "msg": "Missing credentials"}}

        request_url = f"https://{self.acr_host}/v1/identify"
        http_method = "POST"
        http_uri = "/v1/identify"
        data_type = "audio"
        signature_version = "1"
        timestamp = str(int(time.time()))

        string_to_sign = f"{http_method}\n{http_uri}\n{self.acr_key}\n{data_type}\n{signature_version}\n{timestamp}"
        sign = base64.b64encode(hmac.new(self.acr_secret.encode('ascii'), string_to_sign.encode('ascii'), digestmod=hashlib.sha1).digest()).decode('ascii')

        f = open(file_path, "rb")
        sample_bytes = os.path.getsize(file_path)

        files = {'sample': f}
        data = {
            'access_key': self.acr_key,
            'sample_bytes': sample_bytes,
            'timestamp': timestamp,
            'signature': sign,
            'data_type': data_type,
            'signature_version': signature_version
        }

        try:
            r = requests.post(request_url, files=files, data=data, timeout=20)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"status": {"code": -1, "msg": str(e)}}
        finally:
            f.close()

    def _search_netease(self, title, artist):
        """Search Netease Cloud Music for the song"""
        if not self.netease_api:
            return []
        
        keyword = f"{title} {artist}".strip()
        try:
            url = f"{self.netease_api}/search"
            params = {"keywords": keyword, "limit": 3}
            r = requests.get(url, params=params, timeout=10)
            if r.status_code == 200:
                data = r.json()
                songs = data.get("result", {}).get("songs", [])
                return [{
                    "name": s.get("name"),
                    "artists": ", ".join([a["name"] for a in s.get("artists", [])]),
                    "album": s.get("album", {}).get("name"),
                    "id": s.get("id")
                } for s in songs]
        except Exception:
            pass
        return []

    def process_video(self, video_url, cookies_path=None, proxy=None):
        """Main entry point: Download -> Slice -> Recognize -> Search"""
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': '%(id)s.%(ext)s',
            'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3'}],
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': 15,  # Add timeout
            'retries': 3,          # Add retries
        }
        
        if proxy:
            ydl_opts['proxy'] = proxy

        if cookies_path and os.path.exists(cookies_path):
            ydl_opts['cookiefile'] = cookies_path

        results = {
            "segments_processed": 0,
            "tracks_found": [],
            "acr_raw": [],
            "download_info": {},
            "debug_log": []
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            ydl_opts['paths'] = {'home': temp_dir}
            
            # 1. Download
            # Strategy: First try with provided options. If it fails and looks like a network error,
            # and no explicit proxy was given, try stripping environment proxies (fallback for "Turned off VPN" case).
            
            def run_download(options):
                with yt_dlp.YoutubeDL(options) as ydl:
                    info = ydl.extract_info(video_url, download=True)
                    filename = ydl.prepare_filename(info).rsplit('.', 1)[0] + '.mp3'
                    return info, filename

            try:
                # Add robustness options
                ydl_opts['source_address'] = '0.0.0.0' # Force IPv4
                ydl_opts['nocheckcertificate'] = True  # Ignore SSL errors
                
                try:
                    info, filename_base = run_download(ydl_opts)
                except Exception as first_error:
                    # If failed, and we didn't explicitly set a proxy in ydl_opts (meaning we used system env),
                    # let's try to "clear" the proxy and retry.
                    # CRITICAL FIX: We must temporarily unset os.environ variables because yt-dlp/urllib might prioritize them
                    print("Download failed. Detect potential stale proxy in env. Retrying with CLEARED env vars...")
                    results["debug_log"].append("⚠️ Network failed. Attempting to clear system proxy env vars and retry...")
                    
                    # Backup current env
                    backup_env = {}
                    proxy_vars = ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']
                    for var in proxy_vars:
                        if var in os.environ:
                            backup_env[var] = os.environ.pop(var)
                    
                    try:
                        # Retry with empty proxy option AND cleared environment
                        retry_opts = ydl_opts.copy()
                        retry_opts['proxy'] = "" 
                        info, filename_base = run_download(retry_opts)
                    except Exception as second_error:
                        raise second_error # If it fails again, raise the new error
                    finally:
                        # Restore env (good citizenship)
                        for var, val in backup_env.items():
                            os.environ[var] = val

                filepath = os.path.join(temp_dir, filename_base)
                results["download_info"] = {
                    "title": info.get('title'),
                    "duration": info.get('duration'),
                    "file_size": os.path.getsize(filepath) if os.path.exists(filepath) else 0
                }
            except Exception as e:
                return {"error": f"Video download failed: {str(e)} \n(提示: 请检查网络或在高级配置中填入有效代理)"}

            # 2. Slice and Recognize
            try:
                audio = AudioSegment.from_file(filepath)
                total_len = len(audio) # milliseconds
                
                # Strategy: For medleys, we need to scan the whole file.
                # To save time/quota, we use a stride.
                # - Segment length: 15s
                # - Stride: 
                #   - Continuous scanning (step = 15s) to ensure we don't miss short songs in a medley.
                
                segment_len = 15 * 1000
                step = 15 * 1000  # No gaps, continuous coverage

                all_candidates = []
                
                last_winner_title = None

                # Scan entire file with step
                for i in range(0, total_len, step):
                    # Stop if we are too close to end
                    if i + segment_len > total_len:
                        break
                        
                    segment = audio[i:i+segment_len]
                    seg_path = os.path.join(temp_dir, f"seg_{i}.mp3")
                    segment.export(seg_path, format="mp3")
                    
                    acr_res = self._recognize_segment(seg_path)
                    results["segments_processed"] += 1
                    
                    time_str = f"{i//1000//60:02d}:{i//1000%60:02d}"
                    log_entry = f"[{time_str}] Status: {acr_res.get('status', {}).get('code')}"
                    
                    if acr_res.get("status", {}).get("code") == 0:
                        matches = acr_res.get("metadata", {}).get("music", [])
                        
                        segment_logs = []
                        valid_candidates = []
                        
                        for music in matches:
                            title = music.get("title")
                            score = music.get("score", 0)
                            
                            # Filter 1: Base Score
                            if score < 30:
                                continue
                            
                            valid_candidates.append({
                                "title": title,
                                "artists": music.get("artists", []),
                                "acrid": music.get("acrid"),
                                "score": score,
                                "timestamp_ms": i,
                                "raw_match": music
                            })
                        
                        # Selection Logic: Pick ONE best match for this slice
                        if valid_candidates:
                            # Sort key: 
                            # 1. Score (Highest)
                            # 2. Continuity (Matches previous winner)
                            # 3. Title Length (Shortest) - heuristic for "Original" vs "Remix"
                            valid_candidates.sort(key=lambda x: (
                                x["score"], 
                                1 if x["title"] == last_winner_title else 0, 
                                -len(x["title"])
                            ), reverse=True)
                            
                            best_match = valid_candidates[0]
                            last_winner_title = best_match["title"]
                            
                            # Log the winner
                            segment_logs.append(f"✅ {best_match['title']}({best_match['score']})")
                            
                            # Log skipped high-score candidates (for debugging/user visibility)
                            if len(valid_candidates) > 1:
                                skipped_titles = [c['title'] for c in valid_candidates[1:]]
                                segment_logs.append(f"[Skipped: {'; '.join(skipped_titles)}]")

                            # Only add the winner to candidates
                            all_candidates.append(best_match)
                        else:
                            # No valid candidates (all low score)
                            last_winner_title = None 

                        log_entry += " | " + "; ".join(segment_logs)
                    else:
                         log_entry += f" | Msg: {acr_res.get('status', {}).get('msg')}"
                    
                    results["debug_log"].append(log_entry)

                # Aggregation for Medley:
                # We want to list ALL unique songs found, not just the most frequent.
                # 1. Group by ACRID
                track_map = {}
                for cand in all_candidates:
                    acrid = cand["acrid"]
                    
                    # 1.1 De-duplication Logic (Crucial for Mashups)
                    # Many mashups return slightly different titles for the same song (e.g., "Peaches" vs "Peaches (Remix)")
                    # We should normalize titles to avoid duplicates in the UI.
                    
                    # Simple normalization: Lowercase, remove anything in brackets/parentheses
                    # This helps merge "Stay" and "Stay (Remix)"
                    import re
                    clean_title = re.sub(r"[\(\[].*?[\)\]]", "", cand["title"]).strip().lower()
                    
                    # Also use the cleaned title as a secondary key if ACRID is different but song is likely same
                    # But be careful not to merge different songs with same name.
                    # For now, let's trust ACRID but add a title-based dedup pass later.
                    
                    if acrid not in track_map:
                        track_map[acrid] = cand
                    else:
                        # Keep the instance with highest score
                        if cand["score"] > track_map[acrid]["score"]:
                            track_map[acrid] = cand
                        # Also update timestamp if this instance appeared earlier? 
                        # No, we want the *first* appearance usually, or the best match appearance.
                        # Let's keep the timestamp of the highest score match for now, 
                        # OR keep the earliest timestamp?
                        # User usually wants to know when the song *starts*.
                        if cand["timestamp_ms"] < track_map[acrid]["timestamp_ms"]:
                             track_map[acrid]["timestamp_ms"] = cand["timestamp_ms"]

                # 2. Convert to list and sort by timestamp (appearance order)
                sorted_tracks = sorted(track_map.values(), key=lambda x: x["timestamp_ms"])
                
                # 2.5 Title-based Deduplication (Post-processing)
                # This fixes "Stay" vs "Stay - Shane Thompson" appearing as two results
                unique_titles = {}
                final_tracks = []
                
                # Pre-processing: We want to prefer the version with the SHORTEST title (usually original)
                # or the one with the HIGHEST score.
                # Let's group by simplified title first.
                
                for track in sorted_tracks:
                    # Normalize title for dedup: "Peaches (Remix)" -> "peaches"
                    clean_title = re.sub(r"[\(\[].*?[\)\]]", "", track["title"]).strip().lower()
                    # Also remove artists from title if present "Stay - Justin Bieber" -> "Stay"
                    if " - " in clean_title:
                        clean_title = clean_title.split(" - ")[0].strip()
                    
                    if clean_title not in unique_titles:
                        unique_titles[clean_title] = track
                        final_tracks.append(track)
                    else:
                        existing = unique_titles[clean_title]
                        # Merge logic:
                        # 1. Update max score
                        existing["score"] = max(existing["score"], track["score"])
                        
                        # 2. Keep the cleaner title (shorter is usually better/official)
                        # e.g. "Stay" vs "Stay - Shane Thompson" -> Keep "Stay"
                        if len(track["title"]) < len(existing["title"]):
                            existing["title"] = track["title"]
                            existing["artists"] = track["artists"]
                        
                        # 3. If scores are equal, but new one has "Justin Bieber" in artist, prefer it?
                        # (Optional enhancement)
                
                results["debug_log"].append(f"\n--- Final Aggregation: {len(final_tracks)} Unique Tracks (Deduped) ---")

                # 3. Final Result Construction
                for track in final_tracks:  
                    artist_str = ", ".join([a["name"] for a in track["artists"]])
                    title = track["title"]
                    score = track["score"]
                    
                    log_entry = f"Final: {title} ({score})"

                    # --- Garbage Filtering Strategy (Enhanced) ---
                    
                    # 1. Explicit Blacklist (Expanded based on feedback)
                    blacklist = ["E.V.C", "Audio", "Unknown", "Track", "Test", "ä", "å", "è", "é", "ç", "ð", "Mashup", "Remix", "Bootleg", "Mix", "+", "Ludacris", "lo-lo-lo", "Pop Danthology"]
                    # Added "Pop Danthology" to blacklist
                    
                    if any(bad in title for bad in blacklist) or title.isdigit():
                        log_entry += " -> ❌ REJECTED (Blacklist/Mojibake/Derivative)"
                        results["debug_log"].append(log_entry)
                        continue

                    # 2. Mojibake Detection
                    suspicious_chars = ["Ã", "â", "ä", "å", "ç", "è", "é", "ð", "ñ", "ò", "ó", "ô", "õ", "ö"]
                    is_suspicious = any(char in title for char in suspicious_chars)
                    
                    if is_suspicious:
                         log_entry += " -> ❌ REJECTED (Suspicious)"
                         results["debug_log"].append(log_entry)
                         continue
                        
                    # 3. Netease Verification (Relaxed)
                    netease_matches = self._search_netease(title, artist_str)
                    
                    if score < 40 and not netease_matches:
                        log_entry += " -> ❌ REJECTED (No Netease)"
                        results["debug_log"].append(log_entry)
                        continue

                    log_entry += " -> ✅ PASSED"
                    results["debug_log"].append(log_entry)

                    # Format timestamp
                    seconds = track["timestamp_ms"] // 1000
                    time_str = f"{seconds//60:02d}:{seconds%60:02d}"
                    
                    results["tracks_found"].append({
                        "title": title,
                        "artist": artist_str,
                        "score": score,
                        "timestamp": time_str,
                        "netease_matches": netease_matches
                    })

            except Exception as e:
                return {"error": f"Audio processing failed: {str(e)}", "partial_results": results}

        return results
