from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp
import os
import re
import urllib.request

app = Flask(__name__)
CORS(app)

SUPPORTED_PATTERNS = [
    r'(https?://)?(www\.)?instagram\.com/(reel|p|tv|stories)/',
    r'(https?://)?(www\.)?(youtube\.com/watch|youtu\.be/|youtube\.com/shorts/)',
    r'(https?://)?(www\.)?(facebook\.com|fb\.watch)',
    r'(https?://)?(www\.)?pinterest\.(com|in)/',
    r'(https?://)?(www\.)?twitter\.com/',
    r'(https?://)?(www\.)?x\.com/',
    r'(https?://)?(www\.)?tiktok\.com/',
]

def detect_platform(url):
    if 'instagram.com' in url: return 'Instagram'
    if 'youtube.com' in url or 'youtu.be' in url: return 'YouTube'
    if 'facebook.com' in url or 'fb.watch' in url: return 'Facebook'
    if 'pinterest.com' in url or 'pinterest.in' in url: return 'Pinterest'
    if 'twitter.com' in url or 'x.com' in url: return 'Twitter/X'
    if 'tiktok.com' in url: return 'TikTok'
    return 'Unknown'

def is_supported_url(url):
    return any(re.search(p, url) for p in SUPPORTED_PATTERNS)

def get_ydl_opts(platform):
    """Build yt-dlp options based on platform."""

    base_opts = {
        'quiet': True,
        'skip_download': True,
        'noplaylist': True,
        'format': 'best[ext=mp4]/best',
    }

    if platform == 'YouTube':
        base_opts.update({
            'format': 'best[ext=mp4]/best',
            # KEY FIX: Use mweb + ios player clients — bypasses bot detection
            'extractor_args': {
                'youtube': {
                    'player_client': ['mweb', 'ios'],
                    'player_skip': ['webpage'],
                }
            },
            'http_headers': {
                'User-Agent': (
                    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
                    'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 '
                    'Mobile/15E148 Safari/604.1'
                ),
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            },
        })

    elif platform == 'Twitter/X':
        base_opts.update({
            'format': 'best[ext=mp4]/best',
            'http_headers': {
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/125.0.0.0 Safari/537.36'
                ),
            },
        })

    elif platform == 'Pinterest':
        base_opts.update({
            'format': 'best[ext=mp4]/best',
            'http_headers': {
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/125.0.0.0 Safari/537.36'
                ),
                'Referer': 'https://www.pinterest.com/',
            },
        })

    elif platform == 'Facebook':
        base_opts.update({
            'format': 'best[ext=mp4]/best',
            'http_headers': {
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/125.0.0.0 Safari/537.36'
                ),
            },
        })

    return base_opts


def extract_best_url(info):
    """Try multiple ways to get the best direct video URL."""
    # 1. Direct URL on info dict
    if info.get('url'):
        return info['url']

    # 2. Best mp4 format
    formats = info.get('formats', [])
    mp4_formats = [f for f in formats if f.get('ext') == 'mp4' and f.get('url') and f.get('vcodec') != 'none']
    if mp4_formats:
        # sort by quality (filesize or height)
        mp4_formats.sort(key=lambda f: (f.get('height') or 0), reverse=True)
        return mp4_formats[0]['url']

    # 3. Any format with a URL
    any_formats = [f for f in formats if f.get('url')]
    if any_formats:
        any_formats.sort(key=lambda f: (f.get('filesize') or f.get('filesize_approx') or 0), reverse=True)
        return any_formats[0]['url']

    return None


@app.route('/')
def home():
    return jsonify({
        "status": "SaveAll backend running ✅",
        "supports": ["Instagram", "YouTube", "Facebook", "Pinterest", "Twitter/X", "TikTok"]
    })


@app.route('/api/download', methods=['POST'])
def download():
    data = request.get_json()
    url = data.get('url', '').strip()

    if not url:
        return jsonify({"error": "No URL provided"}), 400
    if not is_supported_url(url):
        return jsonify({"error": "URL not supported. Paste a link from Instagram, YouTube, Facebook, Pinterest, or Twitter/X."}), 400

    platform = detect_platform(url)
    ydl_opts = get_ydl_opts(platform)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            # Handle playlists (take first item)
            if info.get('_type') == 'playlist':
                entries = info.get('entries', [])
                if entries:
                    info = entries[0]
                else:
                    return jsonify({"error": "No videos found in this link."}), 400

            video_url = extract_best_url(info)

            if not video_url:
                return jsonify({"error": "Could not extract video URL. The video may be private or unavailable."}), 400

            title = info.get('title', f'{platform} Video')
            thumbnail = info.get('thumbnail', '')
            duration = info.get('duration', 0)
            uploader = info.get('uploader', '') or info.get('channel', '')

            return jsonify({
                "success": True,
                "platform": platform,
                "downloadUrl": video_url,
                "title": title,
                "thumbnail": thumbnail,
                "duration": duration,
                "uploader": uploader,
                "filename": f"saveall_{platform.lower().replace('/', '_')}_video.mp4"
            })

    except yt_dlp.utils.DownloadError as e:
        err = str(e)
        # YouTube bot detection — try cobalt.tools as fallback
        if platform == 'YouTube' and ('Sign in' in err or 'bot' in err.lower() or 'cookies' in err.lower()):
            fallback = try_cobalt_fallback(url)
            if fallback:
                return jsonify(fallback)
            return jsonify({
                "error": "YouTube is blocking this server. This is a temporary issue. Please try again in a minute, or try a different video."
            }), 503

        if 'Private' in err or 'Login' in err or 'Sign in' in err:
            return jsonify({"error": f"This {platform} video is private or requires login. Only public videos work."}), 403
        if 'age' in err.lower():
            return jsonify({"error": "This video is age-restricted and cannot be downloaded."}), 403
        if 'not available' in err.lower() or 'removed' in err.lower():
            return jsonify({"error": "This video is no longer available."}), 404

        return jsonify({"error": f"Could not fetch video. Make sure the link is correct and the video is public. ({platform})"}), 400

    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500


def try_cobalt_fallback(url):
    """Try cobalt.tools API as fallback for YouTube bot-blocked requests."""
    try:
        import json
        req = urllib.request.Request(
            'https://api.cobalt.tools/',
            data=json.dumps({
                "url": url,
                "videoQuality": "720",
                "audioFormat": "mp3",
                "filenameStyle": "classic"
            }).encode(),
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'User-Agent': 'SaveAll/1.0'
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            if result.get('url'):
                return {
                    "success": True,
                    "platform": "YouTube",
                    "downloadUrl": result['url'],
                    "title": "YouTube Video",
                    "thumbnail": "",
                    "duration": 0,
                    "uploader": "",
                    "filename": "saveall_youtube_video.mp4"
                }
    except Exception:
        pass
    return None


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
