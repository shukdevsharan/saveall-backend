from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import yt_dlp
import os
import re
import urllib.request
import urllib.error
import json
import requests

app = Flask(__name__)
CORS(app, origins="*")

RAPIDAPI_KEY = os.environ.get('RAPIDAPI_KEY', '')

SUPPORTED_PATTERNS = [
    r'(https?://)?(www\.)?instagram\.com/(reel|p|tv|stories)/',
    r'(https?://)?(www\.)?(youtube\.com/watch|youtu\.be/|youtube\.com/shorts/)',
    r'(https?://)?(www\.)?(facebook\.com|fb\.watch)',
    r'(https?://)?(www\.)?pinterest\.(com|in)/',
    r'(https?://)?(www\.)?twitter\.com/',
    r'(https?://)?(www\.)?x\.com/',
    r'(https?://)?(www\.)?tiktok\.com/',
]

PROXY_HEADERS = {
    'Twitter/X': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Referer': 'https://twitter.com/',
        'Origin': 'https://twitter.com',
    },
    'Instagram': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Referer': 'https://www.instagram.com/',
    },
    'Facebook': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Referer': 'https://www.facebook.com/',
    },
    'Pinterest': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Referer': 'https://www.pinterest.com/',
    },
    'YouTube': {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    },
    'default': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    }
}


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
    base_opts = {
        'quiet': True,
        'skip_download': True,
        'noplaylist': True,
        'format': 'best[ext=mp4]/best',
    }
    if platform == 'YouTube':
        base_opts.update({
            'format': 'best[ext=mp4][height<=720]/best[ext=mp4]/best',
            'extractor_args': {
                'youtube': {
                    'player_client': ['tv_embedded', 'mweb', 'ios'],
                    'player_skip': ['webpage'],
                }
            },
            'http_headers': PROXY_HEADERS['YouTube'],
        })
    elif platform == 'Twitter/X':
        base_opts.update({'format': 'best[ext=mp4]/best', 'http_headers': PROXY_HEADERS['Twitter/X']})
    elif platform == 'Pinterest':
        base_opts.update({'format': 'best[ext=mp4]/best', 'http_headers': PROXY_HEADERS['Pinterest']})
    elif platform == 'Facebook':
        base_opts.update({'format': 'best[ext=mp4]/best', 'http_headers': PROXY_HEADERS['Facebook']})
    elif platform == 'Instagram':
        base_opts.update({'format': 'best[ext=mp4]/best', 'http_headers': PROXY_HEADERS['Instagram']})
    return base_opts


def extract_best_url(info):
    if info.get('url'):
        return info['url']
    formats = info.get('formats', [])
    mp4_formats = [f for f in formats if f.get('ext') == 'mp4' and f.get('url') and f.get('vcodec') != 'none']
    if mp4_formats:
        mp4_formats.sort(key=lambda f: (f.get('height') or 0), reverse=True)
        return mp4_formats[0]['url']
    any_formats = [f for f in formats if f.get('url')]
    if any_formats:
        any_formats.sort(key=lambda f: (f.get('filesize') or f.get('filesize_approx') or 0), reverse=True)
        return any_formats[0]['url']
    return None


def try_rapidapi_ytdownloader(url):
    """RapidAPI YT Downloader by Gagan Thakur"""
    if not RAPIDAPI_KEY:
        return None
    try:
        import urllib.parse
        video_id = ''
        if 'youtu.be/' in url:
            video_id = url.split('youtu.be/')[-1].split('?')[0]
        elif 'v=' in url:
            video_id = url.split('v=')[-1].split('&')[0]
        elif 'shorts/' in url:
            video_id = url.split('shorts/')[-1].split('?')[0]
        if not video_id:
            return None

        api_url = f"https://yt-downloader1.p.rapidapi.com/api?id={video_id}"
        headers = {
            "x-rapidapi-key": RAPIDAPI_KEY,
            "x-rapidapi-host": "yt-downloader1.p.rapidapi.com"
        }
        resp = requests.get(api_url, headers=headers, timeout=15)
        data = resp.json()

        video_url = None
        if isinstance(data, dict):
            for key in ['url', 'downloadUrl', 'link', 'mp4']:
                if data.get(key):
                    video_url = data[key]
                    break
            if not video_url and data.get('formats'):
                for f in data['formats']:
                    if f.get('url') and 'mp4' in f.get('mimeType', ''):
                        video_url = f['url']
                        break

        if video_url:
            return {
                "success": True,
                "platform": "YouTube",
                "downloadUrl": video_url,
                "title": data.get('title', 'YouTube Video'),
                "thumbnail": data.get('thumbnail', ''),
                "duration": data.get('duration', 0),
                "uploader": data.get('author', ''),
                "filename": "saveall_youtube_video.mp4"
            }
    except Exception:
        pass
    return None


def try_cobalt_fallback(url):
    """cobalt.tools fallback — free, no key needed"""
    try:
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


@app.route('/')
def home():
    return jsonify({
        "status": "SaveAll backend running ✅",
        "rapidapi_key_loaded": bool(RAPIDAPI_KEY),
        "supports": ["Instagram", "YouTube", "Facebook", "Pinterest", "Twitter/X", "TikTok"]
    })


@app.route('/api/download', methods=['POST'])
def download():
    data = request.get_json()
    url = data.get('url', '').strip()

    if not url:
        return jsonify({"error": "No URL provided"}), 400
    if not is_supported_url(url):
        return jsonify({"error": "URL not supported."}), 400

    platform = detect_platform(url)

    # YouTube: try all methods in order
    if platform == 'YouTube':
        # 1. yt-dlp
        try:
            ydl_opts = get_ydl_opts(platform)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info.get('_type') == 'playlist':
                    entries = info.get('entries', [])
                    info = entries[0] if entries else None
                if info:
                    video_url = extract_best_url(info)
                    if video_url:
                        return jsonify({
                            "success": True,
                            "platform": "YouTube",
                            "downloadUrl": video_url,
                            "title": info.get('title', 'YouTube Video'),
                            "thumbnail": info.get('thumbnail', ''),
                            "duration": info.get('duration', 0),
                            "uploader": info.get('uploader', ''),
                            "filename": "saveall_youtube_video.mp4"
                        })
        except Exception:
            pass

        # 2. RapidAPI
        result = try_rapidapi_ytdownloader(url)
        if result:
            return jsonify(result)

        # 3. cobalt.tools
        result = try_cobalt_fallback(url)
        if result:
            return jsonify(result)

        return jsonify({"error": "YouTube download failed. The video may be private or unavailable."}), 503

    # Non-YouTube platforms
    ydl_opts = get_ydl_opts(platform)
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info.get('_type') == 'playlist':
                entries = info.get('entries', [])
                if entries:
                    info = entries[0]
                else:
                    return jsonify({"error": "No videos found."}), 400

            video_url = extract_best_url(info)
            if not video_url:
                return jsonify({"error": "Could not extract video URL."}), 400

            needs_proxy = platform in ['Twitter/X', 'Instagram', 'Facebook', 'Pinterest']
            if needs_proxy:
                import urllib.parse
                download_url = f"/api/proxy?url={urllib.parse.quote(video_url)}&platform={urllib.parse.quote(platform)}"
            else:
                download_url = video_url

            return jsonify({
                "success": True,
                "platform": platform,
                "downloadUrl": download_url,
                "title": info.get('title', f'{platform} Video'),
                "thumbnail": info.get('thumbnail', ''),
                "duration": info.get('duration', 0),
                "uploader": info.get('uploader', '') or info.get('channel', ''),
                "filename": f"saveall_{platform.lower().replace('/', '_')}_video.mp4"
            })

    except yt_dlp.utils.DownloadError as e:
        err = str(e)
        if 'Private' in err or 'Login' in err or 'Sign in' in err:
            return jsonify({"error": f"This {platform} video is private or requires login."}), 403
        if 'age' in err.lower():
            return jsonify({"error": "This video is age-restricted."}), 403
        return jsonify({"error": f"Could not fetch video. Make sure the link is public. ({platform})"}), 400
    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500


@app.route('/api/proxy')
def proxy_video():
    video_url = request.args.get('url', '').strip()
    platform = request.args.get('platform', 'default').strip()

    if not video_url:
        return jsonify({"error": "No URL provided"}), 400

    allowed_domains = [
        'video.twimg.com', 'cdninstagram.com', 'instagram.com',
        'fbcdn.net', 'facebook.com', 'pinimg.com', 'pinterest.com',
        'googlevideo.com', 'youtube.com', 'youtu.be', 'ytimg.com', 'tiktokcdn.com',
    ]
    from urllib.parse import urlparse
    parsed = urlparse(video_url)
    hostname = parsed.hostname or ''
    if not any(domain in hostname for domain in allowed_domains):
        return jsonify({"error": "Proxy not allowed for this domain"}), 403

    headers = PROXY_HEADERS.get(platform, PROXY_HEADERS['default'])
    if 'Range' in request.headers:
        headers['Range'] = request.headers['Range']

    try:
        resp = requests.get(video_url, headers=headers, stream=True, timeout=30)
        if resp.status_code not in (200, 206):
            return jsonify({"error": f"CDN returned {resp.status_code}"}), resp.status_code

        content_type = resp.headers.get('Content-Type', 'video/mp4')
        content_length = resp.headers.get('Content-Length')
        response_headers = {
            'Content-Type': content_type,
            'Content-Disposition': 'attachment; filename="saveall_video.mp4"',
            'Accept-Ranges': 'bytes',
            'Access-Control-Allow-Origin': '*',
        }
        if content_length:
            response_headers['Content-Length'] = content_length
        if resp.headers.get('Content-Range'):
            response_headers['Content-Range'] = resp.headers['Content-Range']

        def generate():
            for chunk in resp.iter_content(chunk_size=1024 * 64):
                if chunk:
                    yield chunk

        return Response(stream_with_context(generate()), headers=response_headers, status=resp.status_code)

    except requests.exceptions.Timeout:
        return jsonify({"error": "Request timed out"}), 504
    except Exception as e:
        return jsonify({"error": f"Proxy error: {str(e)}"}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
