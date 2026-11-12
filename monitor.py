import os, re, json, asyncio, requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
STATE_FILE = "seen_movies.json"

THEATRES = [
    {
        "name": "Star Cineplex (All Dhaka Branches)",
        "url": "https://cineplexbd.com/showtime",
        "low": 350, "high": 1000,
        "tip": "Cheapest: Weekday Matinee < 3 PM (৳350). Best experience: Dolby Atmos at Bashundhara/SKS/Sony Square."
    },
    {
        "name": "Blockbuster Cinemas (Jamuna Future Park)",
        "url": "https://blockbusterbd.com/Schedule",
        "low": 400, "high": 800,
        "tip": "Best value: 12:00 PM–3:00 PM Sun–Wed in IRIS/UTSHOB halls (৳400) before Kuril rush hour."
    },
    {
        "name": "Lion Cinemas (Keraniganj)",
        "url": "https://lioncinemas.com/",
        "low": 300, "high": 600,
        "tip": "Lowest multiplex ticket price in Greater Dhaka (৳300) on weekday afternoons."
    },
    {
        "name": "Shyamoli Cinema (Shyamoli Square)",
        "url": "https://shyamolicinema.com/",
        "low": 300, "high": 400,
        "tip": "Best budget central-west option (৳300)."
    }
]

IGNORE_WORDS = {
    "movie schedule", "now showing", "upcoming", "show time", "show times",
    "get tickets", "buy tickets", "home", "login", "register", "contact",
    "club royale", "fan club", "career", "rolling the reel", "all movies",
    "2d", "3d", "no info", "watch trailer", "details", "book"
}

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"known_movies": [], "last_update_id": 0, "catalog": {}}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def tg_api(method, payload):
    return requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}", json=payload).json()

def clean_title(raw):
    title = re.sub(r"\s+", " ", raw).strip(" -–—|•*◆★")
    if len(title) < 3 or len(title) > 55:
        return None
    if title.lower() in IGNORE_WORDS or re.match(r"^[\d\s:APMampm৳TkBDT]+$", title):
        return None
    if any(x in title.lower() for x in ["pm", "am", "booked", "filling fast", "jamuna future park", "level 5"]):
        return None
    return title

def extract_movies_from_html(html, theatre_url):
    soup = BeautifulSoup(html, "html.parser")
    found = {}

    # Blockbuster specific structured list items & headings, plus general headings across sites
    candidates = soup.select("h1, h2, h3, h4, .movie-title, .film-title, .title, li strong, a[href*='movie'], a[href*='Movie']")
    for el in candidates:
        title = clean_title(el.get_text(" ", strip=True))
        if not title:
            continue
        parent_text = el.parent.get_text(" ", strip=True) if el.parent else ""
        times = sorted(set(re.findall(r"\b(?:1[0-2]|0?[1-9]):[0-5][0-9]\s*(?:AM|PM|am|pm)\b", parent_text)))
        found[title] = times[:6]

    return found

async def scrape_all():
    catalog = {}  # { "Movie Title": [ {theatre, url, low, high, tip, times}, ... ] }
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        for t in THEATRES:
            try:
                await page.goto(t["url"], timeout=25000, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)
                movies_here = extract_movies_from_html(await page.content(), t["url"])
                for title, times in movies_here.items():
                    # Match case-insensitively with existing catalog keys
                    existing_key = next((k for k in catalog if k.lower() == title.lower()), title)
                    catalog.setdefault(existing_key, []).append({
                        "theatre": t["name"],
                        "url": t["url"],
                        "low": t["low"],
                        "high": t["high"],
                        "tip": t["tip"],
                        "times": times
                    })
            except Exception as e:
                print(f"Error scraping {t['name']}: {e}")
        await browser.close()
    return catalog

def format_movie_details(title, entries):
    entries.sort(key=lambda x: x["low"])
    cheapest = entries[0]
    lines = [
        f"🎬 *{title} — Dhaka Ticket & Time Breakdown*\n",
        f"🏆 *Cheapest Option:* {cheapest['theatre']} (from *৳{cheapest['low']}*)\n"
    ]
    for e in entries:
        slots = ", ".join(e["times"]) if e["times"] else "Check booking link"
        lines.append(
            f"🏛️ *{e['theatre']}*\n"
            f"   • Price: *৳{e['low']} – ৳{e['high']}*\n"
            f"   • Showtimes: {slots}\n"
            f"   • 💡 {e['tip']}\n"
            f"   • 🔗 {e['url']}\n"
        )
    return "\n".join(lines)

def handle_user_button_clicks(state):
    updates = tg_api("getUpdates", {"offset": state["last_update_id"] + 1, "timeout": 2})
    for upd in updates.get("result", []):
        state["last_update_id"] = upd["update_id"]
        cb = upd.get("callback_query")
        if cb and str(cb["message"]["chat"]["id"]) == str(CHAT_ID):
            chosen_movie = cb["data"]
            tg_api("answerCallbackQuery", {"callback_query_id": cb["id"], "text": f"Loading {chosen_movie}..."})
            entries = state["catalog"].get(chosen_movie)
            if entries:
                tg_api("sendMessage", {
                    "chat_id": CHAT_ID,
                    "text": format_movie_details(chosen_movie, entries),
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True
                })
        # Also allow typing /movies anytime to see the interactive picker
        msg = upd.get("message", {})
        if str(msg.get("chat", {}).get("id")) == str(CHAT_ID) and msg.get("text", "").strip().lower() in ["/movies", "/start"]:
            send_movie_picker(list(state["catalog"].keys()), "🎥 *Currently Showing in Dhaka — Which movie do you want to see?*")

def send_movie_picker(movie_titles, header_text):
    if not movie_titles:
        return
    # Build clickable Telegram inline buttons (1 movie per row)
    keyboard = [[{"text": f"🎟️ {m}", "callback_data": m[:60]}] for m in movie_titles[:15]]
    tg_api("sendMessage", {
        "chat_id": CHAT_ID,
        "text": header_text + "\n\n👇 *Tap a movie below to see cheapest theatres & best times:*",
        "parse_mode": "Markdown",
        "reply_markup": {"inline_keyboard": keyboard}
    })

async def main():
    state = load_state()
    catalog = await scrape_all()

    if catalog:
        state["catalog"] = catalog
        known_lower = {m.lower() for m in state["known_movies"]}
        new_movies = [m for m in catalog.keys() if m.lower() not in known_lower]

        if new_movies:
            state["known_movies"] = list(catalog.keys())
            new_list = "\n".join([f"• *{m}*" for m in new_movies])
            send_movie_picker(
                list(catalog.keys()),
                f"🆕 *New Movies Detected in Dhaka!*\n{new_list}\n\n*Which movie do you want to see?*"
            )

    handle_user_button_clicks(state)
    save_state(state)

asyncio.run(main())
