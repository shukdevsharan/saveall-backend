from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp
import os
import re

app = Flask(__name__)
CORS(app)

SUPPORTED_PATTERNS = [
    r'(https?://)?(www\.)?instagram\.com/(reel|p|tv|stories)/',
    r'(https?://)?(www\.)?(youtube\.com/watch|youtu\.be/|youtube\.com/shorts/)',
    r'(https?://)?(www\.)?(facebook\.com|fb\.watch)',
    r'(https?://)?(www\.)?pinterest\.(com|in)/',
    r'(https?://)?(www\.)?twitter\.com/',
    r'(https?://)?(www\.)?x\.com/',
]

def detect_platform(url):
    if 'instagram.com' in url: return 'Instagram'
    if 'youtube.com' in url or 'youtu.be' in url: return 'YouTube'
    if 'facebook.com' in url or 'fb.watch' in url: return 'Facebook'
    if 'pinterest.com' in url or 'pinterest.in' in url: return 'Pinterest'
    if 'twitter.com' in url or 'x.com' in url: return 'Twitter/X'
    return 'Unknown'

def is_supported_url(url):
    return any(re.search(p, url) for p in SUPPORTED_PATTERNS)

@app.route('/')
def home():
    return jsonify({"status": "SaveAll backend running"})

@app.route('/api/download', methods=['POST'])
def download():
    data = request.get_json()
    url = data.get('url', '').strip()

    if not url:
        return jsonify({"error": "No URL provided"}), 400
    if not is_supported_url(url):
        return jsonify({"error": "URL not supported."}), 400

    platform = detect_platform(url)

    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'format': 'best[ext=mp4]/best',
        'noplaylist': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            video_url = info.get('url')
            title = info.get('title', f'{platform} Video')
            thumbnail = info.get('thumbnail', '')
            duration = info.get('duration', 0)
            uploader = info.get('uploader', '')

            if not video_url:
                formats = info.get('formats', [])
                mp4 = [f for f in formats if f.get('ext') == 'mp4' and f.get('url')]
                if mp4:
                    video_url = mp4[-1]['url']
                else:
                    any_fmt = [f for f in formats if f.get('url')]
                    if any_fmt:
                        video_url = any_fmt[-1]['url']
                    else:
                        return jsonify({"error": "Could not extract video."}), 400

            return jsonify({
                "success": True,
                "platform": platform,
                "downloadUrl": video_url,
                "title": title,
                "thumbnail": thumbnail,
                "duration": duration,
                "uploader": uploader,
            })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
