import os
import re
import urllib.request
import asyncio
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import discord
from discord.ext import tasks
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("YouTubeCounterBot")

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
YOUTUBE_URL = os.getenv("YOUTUBE_CHANNEL_URL", "https://www.youtube.com/@wjd-d4z")
GUILD_ID = int(os.getenv("GUILD_ID", "1564580022604406814"))
PORT = int(os.getenv("PORT", 8080))

# Tiny health check web server for Render / Cloud hosting free web service
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"YouTube Counter Bot is running 24/7!")
    def log_message(self, format, *args):
        return

def run_web_server():
    try:
        server = HTTPServer(("0.0.0.0", PORT), HealthCheckHandler)
        logger.info(f"Health check web server running on port {PORT}")
        server.serve_forever()
    except Exception as e:
        logger.warning(f"Web server could not bind to port {PORT} (might be already bound or local): {e}")

threading.Thread(target=run_web_server, daemon=True).start()

intents = discord.Intents.default()
client = discord.Client(intents=intents)

def fetch_youtube_subscribers(url: str) -> str:
    """Fetch subscriber count from YouTube channel page without using API quota."""
    try:
        # Add random query param to bust intermediate CDN caches
        import time
        cache_buster_url = f"{url}?_cb={int(time.time())}"
        req = urllib.request.Request(
            cache_buster_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache"
            }
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8")

        m1 = re.search(r'"subscriberCountText":\{"simpleText":"([^"]+)"\}', html)
        if m1:
            raw = m1.group(1)
            return re.sub(r'(?i)\s*subscribers?', '', raw).strip()

        m2 = re.search(r'"subscriberCountText":\{"accessibility":\{"accessibilityData":\{"label":"([^"]+)"\}\}', html)
        if m2:
            raw = m2.group(1)
            return re.sub(r'(?i)\s*subscribers?', '', raw).strip()

        all_subs = re.findall(r'([\d.,KkMmBb]+)\s*(?:subscribers|subscriber)', html, re.IGNORECASE)
        if all_subs:
            return all_subs[0].strip()

    except Exception as e:
        logger.error(f"Error fetching YouTube subs: {e}")

    return None

def format_channel_name(sub_count: str) -> str:
    small_caps = {
        '0': '0', '1': '1', '2': '2', '3': '3', '4': '4', '5': '5', '6': '6', '7': '7', '8': '8', '9': '9',
        'k': 'ᴋ', 'K': 'ᴋ', 'm': 'ᴍ', 'M': 'ᴍ', 'b': 'ʙ', 'B': 'ʙ', '.': '.', ',': ','
    }
    styled_num = "".join(small_caps.get(c, c) for c in sub_count)
    return f"〔🔴〕ꜱᴜʙꜱ: {styled_num}"

@tasks.loop(minutes=2)
async def update_counter_task():
    try:
        guild = client.get_guild(GUILD_ID)
        if not guild:
            logger.warning(f"Guild {GUILD_ID} not found or bot not in guild yet.")
            return

        subs = await asyncio.to_thread(fetch_youtube_subscribers, YOUTUBE_URL)
        if not subs:
            logger.warning("Could not fetch subscriber count from YouTube.")
            return

        target_name = format_channel_name(subs)
        logger.info(f"Fetched subscriber count: '{subs}'. Formatted name: '{target_name}'")

        counter_channel = None
        for vc in guild.voice_channels:
            if "ꜱᴜʙꜱ:" in vc.name or "subscribers" in vc.name.lower() or "subs:" in vc.name.lower():
                counter_channel = vc
                break

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                connect=False
            )
        }
        if guild.me:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                manage_channels=True,
                connect=True
            )

        # Find stats category or create one
        stats_cat = discord.utils.get(guild.categories, name="📊│ꜱᴇʀᴠᴇʀ ꜱᴛᴀᴛꜱ")

        if not counter_channel:
            counter_channel = await guild.create_voice_channel(
                name=target_name,
                category=stats_cat,
                overwrites=overwrites,
                position=0,
                reason="YouTube Live Subscriber Counter"
            )
            logger.info(f"Created new subscriber counter channel: {counter_channel.name} (id={counter_channel.id})")
        else:
            edit_kwargs = {"name": target_name, "reason": "YouTube Live Subscriber Update"}
            if stats_cat and counter_channel.category != stats_cat:
                edit_kwargs["category"] = stats_cat
            if counter_channel.name != target_name or counter_channel.category != stats_cat:
                await counter_channel.edit(**edit_kwargs)
                logger.info(f"Updated counter channel: {target_name}")
            else:
                logger.info("Channel name is already up-to-date.")

    except Exception as e:
        logger.error(f"Error during update_counter_task: {e}", exc_info=True)

@client.event
async def on_ready():
    logger.info(f"YouTube Counter Bot logged in as {client.user} (ID: {client.user.id})")
    if not update_counter_task.is_running():
        update_counter_task.start()
        logger.info("Started 10-minute subscriber counter update task.")

if __name__ == "__main__":
    if not TOKEN:
        logger.critical("No DISCORD_BOT_TOKEN found in .env!")
    else:
        client.run(TOKEN)
