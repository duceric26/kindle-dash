#!/usr/bin/env python3
"""Tạo ảnh màn hình Kindle: mức dùng Claude + lịch + nhắc nhở + tin Claude.

Cấu hình bằng biến môi trường (xem README / hướng dẫn):
  ICS_URL        link iCal bí mật của Google Calendar        (bắt buộc cho phần lịch)
  TODO_URL       link raw của gist todo.txt                   (nhắc nhở, cách A)
  TASKS_URL      link Web app của Google Apps Script (kèm ?key=...)  (nhắc nhở, cách C - ưu tiên cao nhất)
  GT_CLIENT_ID, GT_CLIENT_SECRET, GT_REFRESH_TOKEN             (nhắc nhở, cách B: Google Tasks OAuth)
  USAGE_URL      link raw của usage.json                      (mức dùng Claude, tùy chọn)
  IMG_NAME       tên file ảnh (chuỗi ngẫu nhiên dài)
  KW, KH         độ phân giải Kindle, mặc định 1072 x 1448
  TZ_NAME        múi giờ, mặc định Asia/Ho_Chi_Minh
  HN_QUERIES     từ khóa Hacker News, cách nhau bằng dấu phẩy
  REDDIT_SUBS    subreddit, cách nhau bằng dấu phẩy
  GH_REPOS       repo GitHub để theo dõi bản phát hành
  YT_CHANNELS    channel_id YouTube (tùy chọn)
  NEWS_N         số tin hiển thị (mặc định 5)
  DEMO_NEWS=1    dùng tin giả (để thử ngoại tuyến)
"""
import os, sys, json, datetime as dt, xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo
import requests, icalendar, recurring_ical_events
from PIL import Image, ImageDraw, ImageFont

BW, BH = 1072, 1448                       # khung vẽ chuẩn, sau đó co về đúng độ phân giải máy
OW, OH = int(os.environ.get("KW", BW)), int(os.environ.get("KH", BH))
TZ = ZoneInfo(os.environ.get("TZ_NAME", "Asia/Ho_Chi_Minh"))
UA = {"User-Agent": "kindle-dash/1.0 (personal e-ink dashboard)"}
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONTB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
WD = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
WDL = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
now = dt.datetime.now(TZ)

def log(*a): print(*a, file=sys.stderr)
def F(size, bold=False): return ImageFont.truetype(FONTB if bold else FONT, size)
def get(url):
    if url.startswith("/") or os.path.exists(url):      # cho phép file cục bộ khi thử
        return open(url, "rb").read()
    r = requests.get(url, headers=UA, timeout=30); r.raise_for_status(); return r.content
def ago(t):
    s = (now - t).total_seconds()
    if s < 3600: return f"{max(int(s // 60), 1)} phút trước"
    if s < 86400: return f"{int(s // 3600)}g trước"
    return f"{int(s // 86400)} ngày trước"

# ---------------------------------------------------------------- LỊCH
def load_events():
    url = os.environ.get("ICS_URL")
    if not url: return None
    try:
        cal = icalendar.Calendar.from_ical(get(url))
        day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
        out = []
        for e in recurring_ical_events.of(cal).between(day0, day0 + dt.timedelta(days=2)):
            s = e["DTSTART"].dt
            allday = not isinstance(s, dt.datetime)
            if allday: st = dt.datetime.combine(s, dt.time(0), TZ)
            else: st = s.astimezone(TZ) if s.tzinfo else s.replace(tzinfo=TZ)
            if allday and st < day0: st = day0           # sự kiện cả ngày kéo dài nhiều ngày
            out.append((st, allday, str(e.get("SUMMARY", "(không tên)"))))
        out.sort(key=lambda r: (r[0].date(), not r[1], r[0]))
        return out
    except Exception as ex:
        log("LỖI lịch:", ex); return None

def event_rows(evs):
    """Trả về tối đa 5 dòng: (nhãn, nội dung, đã qua?)."""
    if evs is None: return [("", "Không tải được lịch", False)]
    today, tom = now.date(), now.date() + dt.timedelta(days=1)
    rows = []
    for st, allday, title in evs:
        if st.date() == today:
            rows.append(("Cả ngày" if allday else st.strftime("%H:%M"), title, (not allday) and st < now))
    for st, allday, title in evs:
        if st.date() == tom and len(rows) < 5:
            rows.append(("Ngày mai" + ("" if allday else st.strftime(" %H:%M")), title, False))
    return rows[:5] or [("", "Hôm nay không có lịch", False)]

# ---------------------------------------------------------------- NHẮC NHỞ
def todos_gist(url):
    out = []
    for line in get(url).decode("utf-8", "ignore").splitlines():
        t = line.strip()
        if not t: continue
        low = t.lower()
        if low.startswith("[x]"): out.append((t[3:].strip(), True))
        elif low.startswith("[ ]"): out.append((t[3:].strip(), False))
        else: out.append((t.lstrip("-* ").strip(), False))
    return out

def todos_google():
    r = requests.post("https://oauth2.googleapis.com/token", timeout=30, data={
        "client_id": os.environ["GT_CLIENT_ID"], "client_secret": os.environ["GT_CLIENT_SECRET"],
        "refresh_token": os.environ["GT_REFRESH_TOKEN"], "grant_type": "refresh_token"})
    r.raise_for_status()
    h = {"Authorization": "Bearer " + r.json()["access_token"]}
    lists = requests.get("https://tasks.googleapis.com/tasks/v1/users/@me/lists", headers=h, timeout=30).json().get("items", [])
    items = []
    for lst in lists[:5]:
        j = requests.get(f"https://tasks.googleapis.com/tasks/v1/lists/{lst['id']}/tasks", headers=h, timeout=30,
                         params={"showCompleted": "false", "showHidden": "false", "maxResults": 50}).json()
        for t in j.get("items", []):
            if t.get("title", "").strip(): items.append({"title": t["title"].strip(), "due": t.get("due")})
    return [(t["title"], False) for t in order_tasks(items)]

def order_tasks(tasks):
    """Thứ tự: hôm nay + sắp tới (gần nhất trước) -> chưa có hạn -> quá hạn (mới quá hạn trước)."""
    today = now.strftime("%Y-%m-%d")
    due10 = lambda t: (t.get("due") or "")[:10]
    up = sorted([t for t in tasks if due10(t) and due10(t) >= today], key=due10)
    nodue = [t for t in tasks if not due10(t)]
    over = sorted([t for t in tasks if due10(t) and due10(t) < today], key=due10, reverse=True)
    return up + nodue + over

def todos_appsscript(url):
    """Đọc JSON do Google Apps Script trả về: [{"title":..., "due":..., "list":...}, ...]"""
    data = json.loads(get(url).decode("utf-8", "ignore"))
    if not isinstance(data, list): raise RuntimeError(f"Apps Script trả về không đúng dạng: {str(data)[:80]}")
    data = [t for t in data if str(t.get("title", "")).strip()]
    return [(t["title"].strip(), False) for t in order_tasks(data)]

def load_todos():
    """None = chưa cấu hình; False = có cấu hình nhưng tải lỗi; list = kết quả."""
    try:
        if os.environ.get("TASKS_URL"): items = todos_appsscript(os.environ["TASKS_URL"])
        elif os.environ.get("GT_REFRESH_TOKEN"): items = todos_google()
        elif os.environ.get("TODO_URL"): items = todos_gist(os.environ["TODO_URL"])
        else: return None
        return sorted(items, key=lambda x: x[1])[:6]      # việc chưa xong lên trước (sort ổn định)
    except Exception as ex:
        log("LỖI nhắc nhở:", ex); return False

# ---------------------------------------------------------------- MỨC DÙNG
def load_usage():
    url = os.environ.get("USAGE_URL")
    if not url: return None
    try: return json.loads(get(url))
    except Exception as ex: log("LỖI usage:", ex); return None

# ---------------------------------------------------------------- TIN
ATOM = "{http://www.w3.org/2005/Atom}"
def parse_feed(url, n=8):
    root = ET.fromstring(get(url)); out = []
    for e in root.iter(ATOM + "entry"):
        title = (e.findtext(ATOM + "title") or "").strip()
        upd = e.findtext(ATOM + "updated") or e.findtext(ATOM + "published") or ""
        try: t = dt.datetime.fromisoformat(upd.replace("Z", "+00:00")).astimezone(TZ)
        except Exception: t = now
        out.append((title, t))
        if len(out) >= n: break
    return out

def news_hn():
    out, seen = [], set()
    for q in os.environ.get("HN_QUERIES", "Anthropic,Claude Code").split(","):
        j = requests.get("https://hn.algolia.com/api/v1/search_by_date", headers=UA, timeout=30,
            params={"query": q.strip(), "tags": "story", "numericFilters": "points>=20", "hitsPerPage": 10}).json()
        for h in j.get("hits", []):
            if h["title"] in seen: continue
            seen.add(h["title"])
            out.append(("HACKER NEWS", h["title"], f"{h['points']} ▲",
                        dt.datetime.fromtimestamp(h["created_at_i"], TZ)))
    return out

def news_reddit():
    out = []
    for sub in os.environ.get("REDDIT_SUBS", "ClaudeAI").split(","):
        sub = sub.strip()
        for title, t in parse_feed(f"https://www.reddit.com/r/{sub}/top/.rss?t=day", 5):
            out.append(("REDDIT", title, f"r/{sub}", t))
    return out

def news_github():
    out = []
    for repo in os.environ.get("GH_REPOS", "anthropics/claude-code").split(","):
        repo = repo.strip()
        for title, t in parse_feed(f"https://github.com/{repo}/releases.atom", 3):
            out.append(("GITHUB", f"{repo.split('/')[-1]} {title}", ago(t), t))
    return out

def news_youtube():
    out = []
    for cid in filter(None, (c.strip() for c in os.environ.get("YT_CHANNELS", "").split(","))):
        for title, t in parse_feed(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}", 3):
            out.append(("YOUTUBE", title, ago(t), t))
    return out

def load_news():
    if os.environ.get("DEMO_NEWS"):
        h = lambda x: now - dt.timedelta(hours=x)
        return [("REDDIT", "Người dùng chia sẻ mẹo viết prompt dài cho dự án lớn", "412 ▲", h(2)),
                ("HACKER NEWS", "Thảo luận: cách dùng agent tự động hóa việc viết code", "238 ▲", h(4)),
                ("GITHUB", "claude-code v0.0.0 (ghi chú thay đổi)", "6g trước", h(6)),
                ("BLUESKY", "Bài đăng về quy trình làm việc với Claude hằng ngày", "96 ♥", h(7)),
                ("BLOG", "Anthropic đăng thông báo sản phẩm mới", "hôm qua", h(20))]
    n = int(os.environ.get("NEWS_N", 5))
    groups = []
    for fn in (news_reddit, news_hn, news_github, news_youtube):
        try: groups.append(sorted(fn(), key=lambda x: x[3], reverse=True))
        except Exception as ex: log("LỖI tin", fn.__name__, ex)
    picked, i = [], 0                                   # lấy luân phiên giữa các nguồn
    while len(picked) < n and any(i < len(g) for g in groups):
        for g in groups:
            if i < len(g) and len(picked) < n: picked.append(g[i])
        i += 1
    for k, (s, t, m, ts) in enumerate(picked):          # nguồn có điểm thì giữ, còn lại ghi giờ
        if s in ("REDDIT",): picked[k] = (s, t, f"{m} · {ago(ts)}", ts)
    return sorted(picked, key=lambda x: x[3], reverse=True)

# ---------------------------------------------------------------- VẼ
img = Image.new("L", (BW, BH), 255); d = ImageDraw.Draw(img)
def fit(text, font, maxw):
    if d.textlength(text, font=font) <= maxw: return text
    while text and d.textlength(text + "…", font=font) > maxw: text = text[:-1]
    return text.rstrip() + "…"
def wrap(text, font, maxw, maxlines):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= maxw: cur = t
        else: lines.append(cur); cur = w
    lines.append(cur)
    if len(lines) > maxlines:
        lines = lines[:maxlines]; lines[-1] = fit(lines[-1] + " …", font, maxw)
    return lines
def tag(x, y, s):
    fn = F(22, True); w = d.textlength(s, font=fn) + 20
    d.rectangle((x, y, x + w, y + 34), fill=0); d.text((x + 10, y + 5), s, font=fn, fill=255); return w
def bar(x, y, w, h, pct, fill=0):
    pct = max(0, min(100, pct))
    d.rectangle((x, y, x + w, y + h), outline=0, width=3)
    d.rectangle((x + 3, y + 3, x + 3 + int((w - 6) * pct / 100), y + h - 3), fill=fill)

# đầu trang
d.rectangle((0, 0, BW, 130), fill=0)
d.text((40, 22), f"{WD[now.weekday()]} {now:%d/%m}", font=F(64, True), fill=255)
d.text((40, 92), f"{WDL[now.weekday()]}, {now:%d/%m/%Y}", font=F(26), fill=255)
d.text((BW - 40, 14), "cập nhật lúc", font=F(22), fill=255, anchor="ra")
d.text((BW - 40, 44), now.strftime("%H:%M"), font=F(64, True), fill=255, anchor="ra")

y = 150
usage = load_usage()
if usage:
    d.text((40, y), "CLAUDE", font=F(26, True), fill=0)
    d.text((40, y + 30), f"{int(usage.get('session_pct', 0))}%", font=F(96, True), fill=0)
    rm = usage.get("session_reset_min")
    sub = "phiên 5 giờ" + (f" · reset sau {rm // 60}g {rm % 60:02d}p" if rm is not None else "")
    d.text((300, y + 50), sub, font=F(28), fill=0)
    bar(300, y + 95, BW - 340, 34, usage.get("session_pct", 0))
    if usage.get("week_pct") is not None:
        d.text((300, y + 142), f"Tuần {int(usage['week_pct'])}%", font=F(26, True), fill=0)
        bar(450, y + 144, BW - 490, 26, usage["week_pct"], fill=90)
    y += 195
    d.line((40, y, BW - 40, y), fill=0, width=4); y += 20
else:
    y += 5

# lịch + nhắc nhở
cx, rx, colw = 40, 560, 470
d.text((cx, y), "LỊCH HÔM NAY", font=F(30, True), fill=0)
d.text((rx, y), "NHẮC NHỞ", font=F(30, True), fill=0)
top = y + 50; ye = ye0 = top
for label, title, past in event_rows(load_events()):
    col = 150 if past else 0
    if label: d.text((cx, ye), label, font=F(26, True), fill=col); ye += 34
    for ln in wrap(title, F(28), colw, 2): d.text((cx, ye), ln, font=F(28), fill=col); ye += 36
    ye += 14
yt = top
todos = load_todos()
if todos is None: d.text((rx, yt), "Chưa cấu hình nhắc nhở", font=F(28), fill=120); yt += 60
elif todos is False: d.text((rx, yt), "Không tải được nhắc nhở", font=F(28), fill=120); yt += 60
elif not todos: d.text((rx, yt), "Không có việc tồn đọng 🎉".replace(" 🎉", ""), font=F(28), fill=0); yt += 60
else:
    for title, done in todos:
        lines = wrap(title, F(28), colw - 50, 2)
        d.rectangle((rx, yt + 4, rx + 28, yt + 32), outline=0, width=3)
        if done:
            d.line((rx + 5, yt + 18, rx + 12, yt + 28), fill=0, width=4); d.line((rx + 12, yt + 28, rx + 25, yt + 8), fill=0, width=4)
        for i, ln in enumerate(lines):
            d.text((rx + 44, yt + i * 34), ln, font=F(28), fill=140 if done else 0)
            if done: d.line((rx + 44, yt + 16 + i * 34, rx + 44 + d.textlength(ln, font=F(28)), yt + 16 + i * 34), fill=140, width=2)
        yt += len(lines) * 34 + 26
y = max(ye, yt, top + 380) + 5                       # chừa chỗ tối thiểu cho 6 việc
d.line((540, top - 8, 540, y - 10), fill=170, width=2)
d.line((40, y, BW - 40, y), fill=0, width=4); y += 20

# tin
d.text((40, y), "TIN CLAUDE", font=F(30, True), fill=0); y += 55
news = load_news()
maxl = 1 if (BH - 60 - y) < len(news) * 105 else 2
if not news: d.text((40, y), "Không tải được tin", font=F(28), fill=120)
for src, title, meta, _ in news:
    if y > BH - 110: break
    w = tag(40, y, src); d.text((40 + w + 14, y + 4), fit(meta, F(24), BW - 120 - w), font=F(24), fill=100); y += 44
    for ln in wrap(title, F(30, True), BW - 80, maxl): d.text((40, y), ln, font=F(30, True), fill=0); y += 40
    y += 12

out = img if (OW, OH) == (BW, BH) else img.resize((OW, OH), Image.LANCZOS)
os.makedirs("out", exist_ok=True)
name = os.environ.get("IMG_NAME", "dash")
out.convert("L").save(f"out/{name}.png")
print("OK", f"out/{name}.png", out.size, out.mode)
