# main.py (RSS General Feed + Filter Version)

import requests
import time
import json
from datetime import datetime, timezone, timedelta
import os
import asyncio
import logging
import feedparser # <-- RSS အတွက် library
import re # <-- Text searching အတွက်
from bs4 import BeautifulSoup # <-- HTML parsing အတွက်

# --- Telegram Bot Library ---
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes

# config.py file ထဲက setting တွေကို import လုပ်ခြင်း
try:
    from config import BOT_TOKEN
except ImportError:
    print("Error: config.py file ကို ရှာမတွေ့ပါ (သို့) BOT_TOKEN မရှိပါ။")
    exit()

# --- Settings ---
# !!! --- General Crypto Feed URL ကိုပဲ သုံးပါတော့မယ် --- !!!
TRADINGVIEW_GENERAL_CRYPTO_FEED_URL = "https://www.tradingview.com/markets/cryptocurrencies/ideas/feed/"
TIME_FILTER_SECONDS = 86400 # 1 ရက် (seconds)

# --- Global Variables ---
IS_CURRENTLY_FETCHING = False # "သော့"

# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Windows Event Loop Fix ---
if os.name == 'nt':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# --- Helper Functions ---
def clean_html(raw_html):
    """HTML tags တွေကို ဖယ်ရှားပြီး text ကို ရှင်းလင်း"""
    if not raw_html: return ""
    try:
        soup = BeautifulSoup(raw_html, "html.parser")
        text = soup.get_text(separator=" ")
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    except Exception: return raw_html

def infer_position(title, summary):
    """Title နဲ့ Summary ထဲက keywords တွေ ကြည့်ပြီး Long/Short ခန့်မှန်း"""
    text_lower = (title + " " + summary).lower()
    is_long = any(word in text_lower for word in ['long', 'bull', 'buy', 'up', 'bounce', 'rally', 'breakout', 'target', 'support'])
    is_short = any(word in text_lower for word in ['short', 'bear', 'sell', 'down', 'reject', 'drop', 'breakdown', 'resistance'])
    if is_long and not is_short: return "Long", "🟢"
    elif is_short and not is_long: return "Short", "🔴"
    else: return "Unknown", "⚪️"

def extract_image_url(entry):
    """Entry ထဲက image URL ကို ရှာဖွေ (Enclosure or Summary)"""
    image_url = None
    if 'enclosures' in entry and entry.enclosures and entry.enclosures[0].get('url'):
        image_url = entry.enclosures[0].get('url')
    elif 'summary' in entry:
        try:
            soup = BeautifulSoup(entry.summary, "html.parser")
            img_tag = soup.find('img')
            if img_tag and img_tag.get('src'): image_url = img_tag.get('src')
        except Exception: pass
    if image_url and image_url.startswith('/'): image_url = "https://www.tradingview.com" + image_url
    if image_url and not image_url.startswith('http'): image_url = None
    return image_url

# -----------------------------------------------------------------
# --- RSS Feed Fetcher Function (General Feed + Filter) ---
# -----------------------------------------------------------------
def fetch_and_parse_feed(requested_symbols: list): # <-- Symbol list ကို လက်ခံမယ်
    """General crypto feed ကို fetch လုပ်ပြီး တောင်းဆိုထားတဲ့ symbols အတွက် filter လုပ်မယ်"""
    target_url = TRADINGVIEW_GENERAL_CRYPTO_FEED_URL
    log_symbols = ",".join(requested_symbols)
    logger.info(f"Fetching GENERAL crypto RSS feed from {target_url} to filter for symbols: [{log_symbols}]")
    headers = {'User-Agent': 'Mozilla/5.0'}

    fetched_ideas = []
    try:
        response = requests.get(target_url, headers=headers, timeout=20)
        response.raise_for_status()
        feed = feedparser.parse(response.content)

        if feed.bozo:
            logger.warning(f"Error parsing general feed: {feed.bozo_exception}")
            return None # Error signal

        if not feed.entries:
            logger.info("No entries found in general crypto RSS feed.")
            return [] # Idea မရှိရင် list အလွတ် ပြန်

        logger.info(f"Found {len(feed.entries)} total entries in general feed.")

        now_utc = datetime.now(timezone.utc)
        time_threshold = now_utc - timedelta(seconds=TIME_FILTER_SECONDS)

        for entry in feed.entries:
            published_time_struct = entry.get('published_parsed')
            published_dt_utc = None
            if published_time_struct:
                try:
                    published_dt_utc = datetime.fromtimestamp(time.mktime(published_time_struct), timezone.utc)
                except (TypeError, ValueError):
                     logger.warning(f"Could not parse date for entry: {entry.get('title')}")
                     continue

                # --- !!! အဓိက Filtering Logic !!! ---
                # ၁) ၂၄ နာရီအတွင်း ဟုတ်မဟုတ် စစ်ဆေးပါ
                if published_dt_utc >= time_threshold:
                    entry_title_upper = entry.get('title', '').upper()
                    entry_link_upper = entry.get('link', '').upper()
                    
                    # ၂) တောင်းဆိုထားတဲ့ symbol တစ်ခုခုနဲ့ ကိုက်ညီမှု ရှိမရှိ စစ်ဆေးပါ
                    matched_symbol = None
                    for req_sym in requested_symbols:
                        # Title မှာ "BTCUSDT" or "BTC/USDT" or "BITCOIN" စသဖြင့် ပါသလား?
                        # Link ထဲမှာ "/BTCUSDT/" ပါသလား? (ဒါက ပိုသေချာနိုင်)
                        if f"/{req_sym}/" in entry_link_upper or req_sym in entry_title_upper:
                             matched_symbol = req_sym
                             break # ကိုက်ညီတာ တွေ့ရင် loop က ထွက်

                    if matched_symbol:
                        # ကိုက်ညီမှု ရှိမှ idea ကို process လုပ်ပါ
                        summary_text = clean_html(entry.get('summary', ''))
                        position, position_emoji = infer_position(entry.get('title',''), summary_text)
                        image_url = extract_image_url(entry)

                        fetched_ideas.append({
                            'title': entry.get('title', 'N/A'),
                            'symbol': matched_symbol, # ကိုက်ညီတဲ့ symbol ကို ထည့်
                            'type': position,
                            'position_emoji': position_emoji,
                            'likes_count': 0,
                            'published_time': time.mktime(published_time_struct),
                            'image_url': image_url,
                            'full_link': entry.get('link', ''),
                            'summary': summary_text
                        })
                # --- !!! Filtering Logic ပြီးဆုံးပါပြီ !!! ---

        # Sort by published time, most recent first
        fetched_ideas.sort(key=lambda x: x['published_time'], reverse=True)
        logger.info(f"Filtered {len(fetched_ideas)} ideas for symbols [{log_symbols}] within the last 24 hours.")
        return fetched_ideas

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching general crypto RSS feed: {e}")
        return None # Network error ဆို None ပြန်
    except Exception as e:
        logger.error(f"Unexpected error processing general feed: {e}", exc_info=True)
        return None # တခြား Error ဆို None ပြန်

# --- (format_message_caption function - No changes needed) ---
def format_message_caption(idea):
    title = idea.get('title', 'N/A')
    symbol = idea.get('symbol', 'N/A')
    idea_type = idea.get('type', 'Unknown')
    position_emoji = idea.get('position_emoji', '⚪️')
    timestamp = idea.get('published_time', time.time())
    date_str = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M')

    caption = f"<b>{symbol} Idea 🔥</b>\n\n"
    caption += f"<b>Title:</b> {title}\n"
    caption += f"<b>Position:</b> {idea_type} {position_emoji}\n"
    caption += f"<b>Date:</b> {date_str} 🗓️"
    return caption

# -----------------------------------------------------------------
# --- Bot Logic (General Feed Version) ---
# -----------------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start command - အသုံးပြုနည်း ရှင်းပြ"""
    user = update.message.from_user
    logger.info(f"/start command received from user {user.id} ({user.username})")
    await update.message.reply_text(
        f"မင်္ဂလာပါ {user.first_name}!\n\n"
        f"Crypto pair အတွက် TradingView idea များကို ရယူရန်:\n\n"
        f"➡️ နောက်ဆုံး idea တစ်ခုတည်းကို ရယူရန်:\n"
        f"`/idea SYMBOL`\n"
        f"(ဥပမာ: `/idea BTCUSDT`)\n\n"
        f"➡️ နောက်ဆုံး ၂၄ နာရီအတွင်း idea အားလုံးကို တစ်ခုချင်း ရယူရန်:\n"
        f"`/idea SYMBOL1,SYMBOL2,...` (ကော်မာခံ၍)\n"
        f"(ဥပမာ: `/idea BTCUSDT,ETHUSDT,SOLUSDT`)\n\n"
        f"Bot သည် ideas များကို ရှာဖွေပြီး သင့်ထံ တိုက်ရိုက် ပြန်လည် ပေးပို့ပါမည်။",
        parse_mode='Markdown'
    )

async def idea_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/idea command ကို လက်ခံပြီး၊ general feed ကို fetch/filter၊ User ကို reply ပြန်"""
    user = update.message.from_user
    chat_id = update.message.chat_id

    if not context.args:
        # ... (Argument မပါရင် error ပြန်တာ အရင်အတိုင်း) ...
        logger.warning(f"User {user.id} called /idea without arguments.")
        await update.message.reply_text("ကျေးဇူးပြု၍ Symbol တစ်ခု သို့မဟုတ် တစ်ခုထက်ပို၍ (ကော်မာခံပြီး) ထည့်ပေးပါ။\nဥပမာ: `/idea BTCUSDT` သို့မဟုတ် `/idea BTCUSDT,ETHUSDT`", parse_mode='Markdown')
        return

    symbols_input = "".join(context.args)
    symbols_to_fetch = [s.strip().upper() for s in symbols_input.split(',') if s.strip()]

    if not symbols_to_fetch:
        # ... (Symbol အလွတ်ဖြစ်နေရင် error ပြန်တာ အရင်အတိုင်း) ...
        logger.warning(f"User {user.id} provided empty symbols.")
        await update.message.reply_text("Symbol များ မှားယွင်းနေပါသည်။\nဥပမာ: `/idea BTCUSDT`", parse_mode='Markdown')
        return

    log_symbols = ",".join(symbols_to_fetch)
    logger.info(f"/idea command received for symbols: [{log_symbols}] from user {user.id} ({user.username})")

    global IS_CURRENTLY_FETCHING
    if IS_CURRENTLY_FETCHING:
        # ... (Cooldown အရင်အတိုင်း) ...
        logger.warning(f"Fetcher is already running. User {user.id} tried to call /idea [{log_symbols}].")
        await update.message.reply_text("Bot သည် ယခုလက်ရှိ အခြား request တစ်ခုကို လုပ်ဆောင်နေပါသည်။ ပြီးဆုံးမှ နောက်တစ်ကြိမ် ပြန်လည် ကြိုးစားပါ။")
        return

    is_single_symbol_request = len(symbols_to_fetch) == 1

    try:
        IS_CURRENTLY_FETCHING = True
        await update.message.reply_text(f"`{log_symbols}` အတွက် TradingView Ideas များကို ရှာဖွေနေပါသည်။ ခဏစောင့်ပါ...", parse_mode='Markdown')

        # --- !!! Feed Fetcher ကို Thread သီးသန့်မှာ ခေါ်ပါ (Symbol list ပေးပြီး) !!! ---
        logger.info(f"Calling feed fetcher for symbols [{log_symbols}] in a separate thread...")
        all_recent_ideas = await asyncio.to_thread(fetch_and_parse_feed, symbols_to_fetch) # <-- symbol list ပေးလိုက်
        logger.info(f"Feed fetcher for [{log_symbols}] finished.")

        # --- Fetcher အဖြေကို စစ်ဆေးပါ ---
        if all_recent_ideas is None: # Fetch/Parse မှာ Error တက်ခဲ့ရင်
             logger.error(f"Feed fetcher failed critically for symbols [{log_symbols}].")
             await update.message.reply_text(f"တောင်းဆိုထားသော Symbol များအတွက် Feed ကို ရယူရာတွင် Error ဖြစ်သွားပါသည်။", parse_mode='Markdown')
             return
        elif not all_recent_ideas: # List အလွတ် (Idea မရှိတာ၊ Filter လုပ်လို့ မကျန်တာ)
            logger.info(f"Feed fetcher returned no matching ideas for symbols [{log_symbols}].")
            await update.message.reply_text(f"တောင်းဆိုထားသော Symbol များ (`{log_symbols}`) အတွက် နောက်ဆုံး ၂၄ နာရီအတွင်း idea အသစ်များ ရှာမတွေ့ပါ။", parse_mode='Markdown')
            return

        # --- User ကို Reply ပြန်ပို့ခြင်း Logic (အရင်အတိုင်းနီးပါး) ---
        ideas_to_send = []
        if is_single_symbol_request:
            ideas_to_send = all_recent_ideas[:1] # Sort ပြီးသားမို့ ပထမဆုံး එකက နောက်ဆုံး එක
            count_text = "နောက်ဆုံး idea"
        else:
            ideas_to_send = all_recent_ideas
            count_text = f"နောက်ဆုံး ၂၄ နာရီအတွင်း idea {len(ideas_to_send)} ခု"

        if not ideas_to_send:
             await update.message.reply_text(f"`{log_symbols}` အတွက် နောက်ဆုံး ၂၄ နာရီအတွင်း idea အသစ်များ ရှာမတွေ့ပါ။", parse_mode='Markdown')
             return

        await update.message.reply_text(f"`{log_symbols}` အတွက် {count_text} တွေ့ရှိပါသည်။ ပေးပို့နေပါသည်...", parse_mode='Markdown')

        sent_count = 0
        for idea in ideas_to_send: # Already sorted, newest first
            image_url = idea.get('image_url')
            full_link = idea.get('full_link')
            caption = format_message_caption(idea)
            keyboard = [[InlineKeyboardButton("View on TradingView", url=full_link)]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            try:
                if image_url:
                    logger.info(f"Replying with photo for {idea['symbol']} to user {user.id}: {idea.get('title')}")
                    await update.message.reply_photo( photo=image_url, caption=caption, parse_mode=ParseMode.HTML, reply_markup=reply_markup )
                else:
                    logger.info(f"Replying with text (no image) for {idea['symbol']} to user {user.id}: {idea.get('title')}")
                    await update.message.reply_text( text=caption, parse_mode=ParseMode.HTML, reply_markup=reply_markup, disable_web_page_preview=False)
                sent_count += 1
                await asyncio.sleep(1.5)

            except TelegramError as e:
                logger.error(f"Error replying to user {user.id} for idea '{idea.get('title')}': {e}")
                try:
                    error_caption = caption + f"\n\n<i>(Media ကို ပို့ရာတွင် အမှားအယွင်း ရှိခဲ့နိုင်ပါသည်။)</i>"
                    await update.message.reply_text( text=error_caption, parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup, disable_web_page_preview=True)
                    await asyncio.sleep(0.5)
                except Exception as e2: logger.error(f"Error sending text fallback reply: {e2}")

        logger.info(f"Finished processing /idea [{log_symbols}] for user {user.id}. Sent {sent_count} replies.")

    except Exception as e:
        logger.error(f"Error in /idea command handler for [{log_symbols}]: {e}", exc_info=True)
        try:
            await update.message.reply_text(f"အမှားအယွင်း တစ်ခုခု ဖြစ်သွားပါသည်: {e}")
        except Exception: pass
    finally:
        IS_CURRENTLY_FETCHING = False
        logger.info("Fetching lock released.")

# --- Bot ကို Run မယ့် Main Function (Polling Version - Graceful Shutdown Fix) ---
async def main():
    """Bot ကို စတင် အလုပ်လုပ်ခိုင်းမယ်"""
    print("Bot စတင် အလုပ်လုပ်ပါပြီ။ Command များကို နားထောင်နေပါသည်...")

    # load_posted_ideas() # <-- မလိုတော့

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("idea", idea_command))

    print("Bot polling ကို စတင်ပါပြီ... (Ctrl+C နှိပ်ပြီး ရပ်နိုင်သည်)")

    async with application:
        await application.initialize()
        await application.start()
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)

        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
