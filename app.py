from __future__ import annotations

import json
import os
import re
import socket
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urljoin, urlparse, quote

import requests
from bs4 import BeautifulSoup
from flask import Flask, Response, jsonify, render_template, request

BASE_DOMAIN = "czbooks.net"
CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1",
    "Accept-Language": "zh-TW,zh-CN;q=0.9,en;q=0.6",
}

REQUEST_DELAY_SECONDS = 0.8
_last_request_time = 0.0

app = Flask(__name__)


@dataclass
class Chapter:
    title: str
    url: str


def get_local_ip() -> str:
    """Find the LAN IP address for opening from iPhone."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def polite_get(url: str) -> str:
    global _last_request_time
    parsed = urlparse(url)
    if BASE_DOMAIN not in parsed.netloc:
        raise ValueError("只允許抓取 czbooks.net 網址")

    elapsed = time.time() - _last_request_time
    if elapsed < REQUEST_DELAY_SECONDS:
        time.sleep(REQUEST_DELAY_SECONDS - elapsed)

    response = requests.get(url, headers=HEADERS, timeout=20)
    _last_request_time = time.time()
    response.raise_for_status()

    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding
    return response.text


def safe_cache_name(url: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", urlparse(url).path.strip("/")) or "home"


def safe_filename(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name).strip()
    return name[:80] or "novel"


def book_cache_path(book_url: str) -> Path:
    return CACHE_DIR / f"book_{safe_cache_name(book_url)}.json"


def chapter_cache_path(chapter_url: str) -> Path:
    return CACHE_DIR / f"chapter_{safe_cache_name(chapter_url)}.json"


def load_json(path: Path) -> dict | None:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_book(html: str, book_url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    book_title = "CZBooks 小說"

    for line in soup.get_text("\n", strip=True).split("\n"):
        match = re.search(r"《(.+?)》", line)
        if match:
            book_title = match.group(1).strip()
            break

    chapters: list[Chapter] = []

    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        full_url = urljoin(book_url, a["href"])
        parsed = urlparse(full_url)

        if BASE_DOMAIN not in parsed.netloc:
            continue

        is_chapter_link = bool(re.search(r"/n/[^/]+/[^/?#]+", parsed.path))
        looks_like_chapter = bool(
            re.search(r"第\s*\d+\s*[章頁]|番外|楔子|序章|終章|完結|完本|Chapter\s*\d+", text, re.I)
        )

        if is_chapter_link and looks_like_chapter and not any(ch.url == full_url for ch in chapters):
            chapters.append(Chapter(title=text, url=full_url))

    if not chapters:
        raise ValueError("沒有找到章節列表。請確認你貼的是小說目錄頁。")

    return {"title": book_title, "url": book_url, "chapters": [asdict(ch) for ch in chapters]}


def extract_chapter(html: str, chapter_url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "nav", "header", "footer", "form", "button", "input"]):
        tag.decompose()

    lines = [line.strip() for line in soup.get_text("\n").splitlines()]
    lines = [line for line in lines if line]

    start_index = 0
    for i, line in enumerate(lines):
        if re.search(r"^《.+?》.+", line) or re.search(r"^第\s*\d+\s*[章頁]", line):
            start_index = i
            break

    stop_patterns = [
        "鍵盤左右鍵", "上一章", "下一章", "章節問題回報", "翻譯有問題",
        "聯繫方式", "隱私權政策", "歡迎交換友站"
    ]
    body_lines: list[str] = []

    for line in lines[start_index:]:
        if any(word in line for word in stop_patterns):
            break
        if line in {"繁简轉換", "[繁]", "[简]", "[回報錯誤]"}:
            continue
        if "選擇背景顏色" in line or "選擇字體大小" in line:
            continue
        body_lines.append(line)

    title = body_lines[0] if body_lines else "未命名章節"
    content = "\n\n".join(body_lines[1:]).strip() if len(body_lines) > 1 else ""

    if len(content) < 50:
        raise ValueError("正文抓取結果太短，可能是網站版型變更或被阻擋。")

    return {
        "title": title,
        "url": chapter_url,
        "content": content,
        "cached_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def get_or_fetch_chapter(chapter_url: str, refresh: bool = False) -> dict:
    path = chapter_cache_path(chapter_url)
    if not refresh:
        cached = load_json(path)
        if cached:
            return cached
    html = polite_get(chapter_url)
    data = extract_chapter(html, chapter_url)
    save_json(path, data)
    return data


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/book")
def api_book():
    payload = request.get_json(force=True)
    book_url = payload.get("url", "").strip()
    if not book_url:
        return jsonify({"error": "請輸入小說目錄頁 URL"}), 400
    if not book_url.startswith("http"):
        book_url = "https://" + book_url

    try:
        path = book_cache_path(book_url)
        cached = load_json(path)
        if cached and not payload.get("refresh"):
            return jsonify(cached)

        html = polite_get(book_url)
        data = extract_book(html, book_url)
        save_json(path, data)
        return jsonify(data)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/chapter")
def api_chapter():
    payload = request.get_json(force=True)
    chapter_url = payload.get("url", "").strip()
    if not chapter_url:
        return jsonify({"error": "缺少章節 URL"}), 400
    try:
        return jsonify(get_or_fetch_chapter(chapter_url, bool(payload.get("refresh"))))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/prefetch")
def api_prefetch():
    payload = request.get_json(force=True)
    chapter_url = payload.get("url", "").strip()
    try:
        if chapter_url:
            get_or_fetch_chapter(chapter_url, False)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 200


@app.post("/api/export/current")
def api_export_current():
    payload = request.get_json(force=True)
    chapter_url = payload.get("url", "").strip()
    try:
        chapter = get_or_fetch_chapter(chapter_url, False)
        text = f"{chapter['title']}\n\n{chapter['content']}\n"
        filename = quote(safe_filename(chapter["title"]) + ".txt")
        return Response(
            text,
            mimetype="text/plain; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    ip = get_local_ip()
    print("\n========================================")
    print("CZBooks iPhone 閱讀器已啟動")
    print(f"電腦開啟：http://127.0.0.1:5000")
    print(f"iPhone 開啟：http://{ip}:5000")
    print("請確認 iPhone 和電腦在同一個 Wi-Fi")
    print("========================================\n")
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
