import os, re, asyncio, requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

THEATRES = [
    ("Star Cineplex (All Dhaka Branches)", "https://cineplexbd.com/showtime", 350, 1000, "Cheapest: Weekday Matinee < 3 PM (৳350)"),
    ("Blockbuster Cinemas (Jamuna Future Park)", "https://blockbusterbd.com/Schedule", 400, 800, "Best: 12 PM–3 PM Sun–Wed in IRIS/UTSHOB (৳400)"),
    ("Lion Cinemas (Keraniganj)", "https://lioncinemas.com/", 300, 600, "Cheapest modern multiplex in Greater Dhaka (৳300)"),
    ("Shyamoli Cinema (Shyamoli Square)", "https://shyamolicinema.com/", 300, 400, "Best budget central-west option (৳300)")
]

def send_tg(msg):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown", "disable_web_page_preview": True}
    )

async def scan():
    with open("movies.txt") as f:
        movies = [line.strip() for line in f if line.strip()]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        for name, url, low, high, tip in THEATRES:
            try:
                await page.goto(url, timeout=25000, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)
                text = BeautifulSoup(await page.content(), "html.parser").get_text(" ", strip=True)
                for movie in movies:
                    tokens = [w for w in re.sub(r"[^a-z0-9\s]", " ", movie.lower()).split() if len(w) > 1]
                    if tokens and all(t in text.lower() for t in tokens):
                        times = ", ".join(sorted(set(re.findall(r"\b(?:1[0-2]|0?[1-9]):[0-5][0-9]\s*(?:AM|PM|am|pm)\b", text)))[:6]) or "Check link"
                        send_tg(f"🚨 *{movie} TICKETS LIVE!*\n🏛️ *{name}*\n💰 From *৳{low}* (up to ৳{high})\n🕒 Slots: {times}\n💡 {tip}\n🔗 {url}")
            except Exception as e:
                print(f"Error {name}: {e}")
        await browser.close()

asyncio.run(scan())
