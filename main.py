# main.py (RSS Feed, Advanced Reply Logic)

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
TRADINGVIEW_SYMBOL_IDEAS_FEED_BASE_URL = "https://www.tradingview.com/symbols/{symbol}/ideas/feed/"
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
    if not raw_html:
        return ""
    try:
        soup = BeautifulSoup(raw_html, "html.parser")
        text = soup.get_text(separator=" ")
        # Multiple spaces/newlines တွေကို single space ပြောင်း
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    except Exception:
        return raw_html # Error တက်ရင် မူရင်းအတိုင်း ပြန်ပေး

def infer_position(title, summary):
    """Title နဲ့ Summary ထဲက keywords တွေ ကြည့်ပြီး Long/Short ခန့်မှန်း"""
    text_lower = (title + " " + summary).lower()
    is_long = any(word in text_lower for word in ['long', 'bull', 'buy', 'up', 'bounce', 'rally', 'breakout'])
    is_short = any(word in text_lower for word in ['short', 'bear', 'sell', 'down', 'reject', 'drop', 'breakdown'])

    if is_long and not is_short:
        return "Long", "🟢"
    elif is_short and not is_long:
        return "Short", "🔴"
    else:
        # Conflicting or no keywords
        return "Unknown", "⚪️" # Neutral or Unknown

def extract_image_url(entry):
    """Entry ထဲက image URL ကို ရှာဖွေ (Enclosure or Summary)"""
    image_url = None
    if 'enclosures' in entry and entry.enclosures and entry.enclosures[0].get('url'):
        image_url = entry.enclosures[0].get('url')
    elif 'summary' in entry:
        # Summary (HTML) ထဲက ပထမဆုံး img tag ကို ရှာကြည့်မယ် (bs4 သုံးပြီး)
        try:
            soup = BeautifulSoup(entry.summary, "html.parser")
            img_tag = soup.find('img')
            if img_tag and img_tag.get('src'):
                image_url = img_tag.get('src')
        except Exception:
            pass # Parsing error ဖြစ်ရင် ကျော်ပါ

    # Relative URL ဖြစ်နေရင် domain ပေါင်းပေးမယ်
    if image_url and image_url.startswith('/'):
        image_url = "https://www.tradingview.com" + image_url
    # Image URL မှန်မမှန် အခြေခံ စစ်ဆေးမှု (အလုပ်မလုပ်နိုင်တဲ့ base64 data:image တွေကို ဖယ်ရှား)
    if image_url and not image_url.startswith('http'):
        image_url = None 
    return image_url

# -----------------------------------------------------------------
# --- RSS Feed Fetcher Function ---
# -----------------------------------------------------------------
def fetch_and_parse_feed(symbol: str):
    """Specific symbol အတွက် RSS Feed ကို fetch လုပ်ပြီး ideas တွေကို parse လုပ်မယ်"""
    target_url = TRADINGVIEW_SYMBOL_IDEAS_FEED_BASE_URL.format(symbol=symbol.upper())
    logger.info(f"Fetching RSS feed for symbol: {symbol.upper()} from {target_url}")
    headers = {'User-Agent': 'Mozilla/5.0'} # Simple user agent

    fetched_ideas = []
    try:
        response = requests.get(target_url, headers=headers, timeout=20) # Timeout တိုးထား
        response.raise_for_status() 

        feed = feedparser.parse(response.content)

        if feed.bozo:
            logger.warning(f"Error parsing feed for {symbol.upper()}: {feed.bozo_exception}")
            return None # Error signal

        if not feed.entries:
            logger.info(f"No entries found in RSS feed for {symbol.upper()}.")
            return [] # Idea မရှိရင် list အလွတ် ပြန်

        logger.info(f"Found {len(feed.entries)} entries in feed for {symbol.upper()}.")

        now_utc = datetime.now(timezone.utc)
        time_threshold = now_utc - timedelta(seconds=TIME_FILTER_SECONDS)

        for entry in feed.entries:
            published_time_struct = entry.get('published_parsed')
            published_dt_utc = None
            if published_time_struct:
                try:
                    # struct_time ကို UTC datetime object ပြောင်းပါ
                    published_dt_utc = datetime.fromtimestamp(time.mktime(published_time_struct), timezone.utc)
                except (TypeError, ValueError):
                     logger.warning(f"Could not parse date for entry: {entry.get('title')}")
                     continue # Date parse မလုပ်နိုင်ရင် ကျော်ပါ

                # ၂၄ နာရီအတွင်း ဟုတ်မဟုတ် စစ်ဆေးပါ
                if published_dt_utc >= time_threshold:
                    summary_text = clean_html(entry.get('summary', ''))
                    position, position_emoji = infer_position(entry.get('title',''), summary_text)
                    image_url = extract_image_url(entry)
                    
                    fetched_ideas.append({
                        'title': entry.get('title', 'N/A'),
                        'symbol': symbol.upper(),
                        'type': position, # Inferred position
                        'position_emoji': position_emoji,
                        'likes_count': 0, # Not available
                        'published_time': time.mktime(published_time_struct),
                        'image_url': image_url, 
                        'full_link': entry.get('link', ''),
                        'summary': summary_text # Cleaned summary
                    })
                # else: 
                    # logger.debug(f"Idea older than 24h: {entry.get('title')}")

        # Sort by published time, most recent first
        fetched_ideas.sort(key=lambda x: x['published_time'], reverse=True)
        logger.info(f"Found {len(fetched_ideas)} ideas within the last 24 hours for {symbol.upper()}.")
        return fetched_ideas

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching RSS feed for {symbol.upper()}: {e}")
        if hasattr(e, 'response') and e.response is not None and e.response.status_code == 404:
             logger.warning(f"Received 404, symbol {symbol.upper()} likely not found.")
             return [] 
        return None 
    except Exception as e:
        logger.error(f"Unexpected error processing feed for {symbol.upper()}: {e}", exc_info=True)
        return None 

# --- (format_message_caption function - Screenshot နဲ့ တူအောင် ပြင်ထား) ---
def format_message_caption(idea):
    title = idea.get('title', 'N/A')
    symbol = idea.get('symbol', 'N/A')
    idea_type = idea.get('type', 'Unknown')
    position_emoji = idea.get('position_emoji', '⚪️')
    # likes = idea.get('likes_count', 0) # RSS မှာ မပါ
    timestamp = idea.get('published_time', time.time())
    # Format date like "2025-10-27 15:35"
    date_str = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M')

    # Screenshot format
    caption = f"<b>{symbol} Idea 🔥</b>\n\n"
    caption += f"<b>Title:</b> {title}\n"
    caption += f"<b>Position:</b> {idea_type} {position_emoji}\n"
    # caption += f"<b>Likes:</b> {likes} 🚀\n" # Likes မပါ
    caption += f"<b>Date:</b> {date_str} 🗓️" # Newline မပါ
    return caption

# --- Channel ထဲ ပို့တဲ့ Function (Commented out) ---
# def send_to_telegram(idea):
#     # ... (code from previous version) ...
#     pass

# -----------------------------------------------------------------
# --- Bot Logic (RSS, Reply Logic အသစ်) ---
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
    """/idea command ကို လက်ခံပြီး၊ symbol ခွဲ၊ feed ကို fetch၊ User ကို reply ပြန်"""
    user = update.message.from_user
    chat_id = update.message.chat_id

    if not context.args:
        logger.warning(f"User {user.id} called /idea without arguments.")
        await update.message.reply_text("ကျေးဇူးပြု၍ Symbol တစ်ခု သို့မဟုတ် တစ်ခုထက်ပို၍ (ကော်မာခံပြီး) ထည့်ပေးပါ။\nဥပမာ: `/idea BTCUSDT` သို့မဟုတ် `/idea BTCUSDT,ETHUSDT`", parse_mode='Markdown')
        return

    # Symbol တွေကို ကော်မာ (,) နဲ့ ခွဲထုတ်ပါ၊ space တွေကို ဖယ်ပါ
    symbols_input = "".join(context.args)
    symbols_to_fetch = [s.strip().upper() for s in symbols_input.split(',') if s.strip()]

    if not symbols_to_fetch:
        logger.warning(f"User {user.id} provided empty symbols.")
        await update.message.reply_text("Symbol များ မှားယွင်းနေပါသည်။\nဥပမာ: `/idea BTCUSDT`", parse_mode='Markdown')
        return
        
    log_symbols = ",".join(symbols_to_fetch)
    logger.info(f"/idea command received for symbols: [{log_symbols}] from user {user.id} ({user.username})")

    global IS_CURRENTLY_FETCHING
    if IS_CURRENTLY_FETCHING:
        logger.warning(f"Fetcher is already running. User {user.id} tried to call /idea [{log_symbols}].")
        await update.message.reply_text("Bot သည် ယခုလက်ရှိ အခြား request တစ်ခုကို လုပ်ဆောင်နေပါသည်။ ပြီးဆုံးမှ နောက်တစ်ကြိမ် ပြန်လည် ကြိုးစားပါ။")
        return

    # Determine if single or multiple symbols requested (for logic later)
    is_single_symbol_request = len(symbols_to_fetch) == 1

    try:
        IS_CURRENTLY_FETCHING = True
        await update.message.reply_text(f"`{log_symbols}` အတွက် TradingView Ideas များကို ရှာဖွေနေပါသည်။ ခဏစောင့်ပါ...", parse_mode='Markdown')

        all_recent_ideas = []
        fetch_successful = True
        
        # --- Symbol တစ်ခုချင်းစီအတွက် Feed ကို fetch လုပ်ပါ ---
        for symbol in symbols_to_fetch:
            logger.info(f"Calling feed fetcher for {symbol} in a separate thread...")
            # fetch_and_parse_feed က list (ideas) or [] or None ပြန်ပေးမယ်
            ideas_list = await asyncio.to_thread(fetch_and_parse_feed, symbol)
            logger.info(f"Feed fetcher for {symbol} finished.")

            if ideas_list is None: # Fetch/Parse မှာ Error တက်ခဲ့ရင်
                 logger.error(f"Feed fetcher failed critically for symbol {symbol}.")
                 # User ကို အသိပေးပြီး ဆက်လုပ်မလား၊ ရပ်မလား? လောလောဆယ် ဆက်လုပ်မယ်။
                 fetch_successful = False
                 await update.message.reply_text(f"⚠️ `{symbol}` အတွက် Feed ကို ရယူရာတွင် Error ဖြစ်သွားပါသည်။", parse_mode='Markdown')
                 continue # နောက် symbol ကို ဆက် fetch
            elif ideas_list: # ideas တွေ့ရင် all_recent_ideas list ထဲ ပေါင်းထည့်
                all_recent_ideas.extend(ideas_list)
        
        # Fetching အားလုံး ပြီးဆုံး
        if not fetch_successful and not all_recent_ideas:
             # Critical error တွေပဲ ကြုံခဲ့ပြီး idea လုံးဝ မရရင်
             await update.message.reply_text(f"တောင်းဆိုထားသော Symbol များအတွက် Idea များ ရယူရာတွင် အမှားအယွင်းများ ဖြစ်ပေါ်ခဲ့ပါသည်။")
             return

        if not all_recent_ideas:
            logger.info(f"No recent ideas found for any requested symbols: [{log_symbols}].")
            await update.message.reply_text(f"တောင်းဆိုထားသော Symbol များ (`{log_symbols}`) အတွက် နောက်ဆုံး ၂၄ နာရီအတွင်း idea အသစ်များ ရှာမတွေ့ပါ။", parse_mode='Markdown')
            return

        # Sort all collected ideas by time, most recent first
        all_recent_ideas.sort(key=lambda x: x['published_time'], reverse=True)
        
        # --- User ကို Reply ပြန်ပို့ခြင်း Logic ---
        ideas_to_send = []
        if is_single_symbol_request:
            # Single symbol တောင်းရင် နောက်ဆုံး တစ်ခုပဲ ယူ
            ideas_to_send = all_recent_ideas[:1] 
            count_text = "နောက်ဆုံး idea"
            found_count = 1 if ideas_to_send else 0
        else:
            # Multiple symbols တောင်းရင် အကုန်ယူ
            ideas_to_send = all_recent_ideas
            count_text = f"နောက်ဆုံး ၂၄ နာရီအတွင်း idea {len(ideas_to_send)} ခု"
            found_count = len(ideas_to_send)

        if not ideas_to_send:
             # ဒါက single symbol တောင်းပြီး filter လုပ်လို့ မကျန်တော့တဲ့ case မှာ ဖြစ်နိုင်
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
                if image_url: # Image URL ရှိမှ ပုံနဲ့ပို့
                    logger.info(f"Replying with photo for {idea['symbol']} to user {user.id}: {idea.get('title')}")
                    await update.message.reply_photo(
                        photo=image_url, caption=caption, parse_mode=ParseMode.HTML, reply_markup=reply_markup )
                else: # Image မပါရင် စာသား သက်သက်ပဲ ပို့မယ်
                    logger.info(f"Replying with text (no image) for {idea['symbol']} to user {user.id}: {idea.get('title')}")
                    await update.message.reply_text(
                        text=caption, parse_mode=ParseMode.HTML, reply_markup=reply_markup, disable_web_page_preview=False)
                sent_count += 1
                await asyncio.sleep(1.5) # Message တွေ ဆက်တိုက် မပို့အောင် နည်းနည်း နား

            except TelegramError as e:
                logger.error(f"Error replying to user {user.id} for idea '{idea.get('title')}': {e}")
                try: # Error တက်ရင် စာသားပဲ ထပ်ပို့ကြည့်မယ်
                    error_caption = caption + f"\n\n<i>(Media ကို ပို့ရာတွင် အမှားအယွင်း ရှိခဲ့နိုင်ပါသည်။)</i>"
                    await update.message.reply_text( text=error_caption, parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup, disable_web_page_preview=True)
                    await asyncio.sleep(0.5)
                except Exception as e2: logger.error(f"Error sending text fallback reply: {e2}")

        logger.info(f"Finished processing /idea [{log_symbols}] for user {user.id}. Sent {sent_count} replies.")
        # Confirmation message ထပ်မပို့တော့

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