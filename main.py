# main.py (Selenium Polling, Advanced Reply Logic)

import requests
import time
import json
from datetime import datetime, timezone, timedelta
import os
import asyncio
import logging
import re
from bs4 import BeautifulSoup # <-- Summary သန့်စင်ဖို့ ဆက်သုံးနိုင်

# --- Telegram Bot Library ---
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes

# --- Selenium Imports (ပြန်ထည့်ပါ) ---
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# config.py file ထဲက setting တွေကို import လုပ်ခြင်း
try:
    from config import BOT_TOKEN
except ImportError:
    print("Error: config.py file ကို ရှာမတွေ့ပါ (သို့) BOT_TOKEN မရှိပါ။")
    exit()

# --- Settings ---
# Selenium Driver Paths (Render မှာဆိုရင် Auto-Install လုပ်ရနိုင်)
# Local မှာဆိုရင် အရင်အတိုင်း ထားပါ
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Default paths - Render မှာဆိုရင် ဒီ file တွေ ရှိချင်မှ ရှိမယ်
DRIVER_PATH_LOCAL = os.path.join(BASE_DIR, 'chrome_driver', 'chromedriver.exe')
BROWSER_PATH_LOCAL = os.path.join(BASE_DIR, 'chrome_driver', 'chrome-win64', 'chrome.exe')

# TradingView URL
TRADINGVIEW_SYMBOL_IDEAS_BASE_URL = "https://www.tradingview.com/symbols/{symbol}/ideas/"
TIME_FILTER_SECONDS = 86400 # 1 ရက် (seconds)

# --- Global Variables ---
IS_CURRENTLY_SCRAPING = False # "သော့"

# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Windows Event Loop Fix ---
if os.name == 'nt':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# --- Helper Functions (From RSS version - Likes/Position မပါ) ---
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
    # Selenium ကနေ တိုက်ရိုက် Position ယူမှာမို့ ဒီ function ကို အရင်လိုပဲ ထားခဲ့နိုင်
    text_lower = (title + " " + summary).lower()
    is_long = any(word in text_lower for word in ['long', 'bull', 'buy', 'up', 'bounce', 'rally', 'breakout', 'target', 'support'])
    is_short = any(word in text_lower for word in ['short', 'bear', 'sell', 'down', 'reject', 'drop', 'breakdown', 'resistance'])
    if is_long and not is_short: return "Long", "🟢"
    elif is_short and not is_long: return "Short", "🔴"
    else: return "Unknown", "⚪️"

# -----------------------------------------------------------------
# --- Selenium Scraper Function (ပြန်လည် အသုံးပြု) ---
# -----------------------------------------------------------------
def setup_selenium_driver():
    """Selenium Driver ကို Setup လုပ်မယ် (Render အတွက်ပါ ထည့်စဉ်းစား)"""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") # Recommended headless mode
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920x1080") # Needed for some sites in headless
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36") # Stable UA

    # Render Environment Check (Buildpack က Chrome/Driver ထည့်ပေးတတ်တယ်)
    # RENDER environment variable ရှိမရှိ စစ်ဆေး
    is_render = os.environ.get('RENDER') == 'true'

    if is_render:
        logger.info("Running on Render environment. Using default driver paths.")
        # Render ရဲ့ Python buildpack က chromedriver ကို PATH ထဲ ထည့်ပေးတတ်တယ်
        # Browser path ကိုလည်း သီးသန့် သတ်မှတ်စရာ မလိုတတ်
        try:
            # Service object မလိုဘဲ တိုက်ရိုက် ခေါ်ကြည့်မယ်
            driver = webdriver.Chrome(options=chrome_options)
            logger.info("Selenium driver initialized using Render's default paths.")
            return driver
        except Exception as e:
            logger.error(f"Failed to initialize driver on Render with default paths: {e}")
            # Fallback to trying specific paths if needed, or raise error
            # For simplicity, we'll let it fail if defaults don't work
            raise e
    else:
        # Local Environment
        logger.info("Running on local environment. Using local driver paths.")
        if not os.path.exists(DRIVER_PATH_LOCAL):
            logger.error(f"Local ChromeDriver not found at: {DRIVER_PATH_LOCAL}")
            return None
        if not os.path.exists(BROWSER_PATH_LOCAL):
            logger.error(f"Local Chrome Browser not found at: {BROWSER_PATH_LOCAL}")
            return None
        chrome_options.binary_location = BROWSER_PATH_LOCAL
        service = Service(executable_path=DRIVER_PATH_LOCAL)
        try:
            driver = webdriver.Chrome(service=service, options=chrome_options)
            logger.info("Selenium driver initialized using local paths.")
            return driver
        except Exception as e:
            logger.error(f"Failed to initialize driver on local machine: {e}")
            raise e


def fetch_ideas_selenium(symbol: str): # <-- Function name ပြောင်းထား
    """Specific symbol အတွက် TradingView Ideas page ကို Selenium ဖြင့် Scrape လုပ်မယ်"""
    target_url = TRADINGVIEW_SYMBOL_IDEAS_BASE_URL.format(symbol=symbol.upper())
    logger.info(f"Starting Selenium scraper for symbol: {symbol.upper()} at {target_url}")

    driver = None
    try:
        driver = setup_selenium_driver() # Driver ကို setup လုပ်
        if driver is None:
            return None # Driver setup မအောင်မြင်ရင် None ပြန်

        logger.info(f"Navigating to {target_url}")
        driver.get(target_url)

        # --- Check for symbol not found page ---
        page_source_lower = driver.page_source.lower()
        if "symbol lookup" in page_source_lower or "we looked everywhere" in page_source_lower:
            logger.warning(f"Symbol {symbol.upper()} not found on TradingView.")
            return [] # Symbol မတွေ့ရင် list အလွတ် ပြန်

        # --- Cookie Consent ---
        try:
            WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.tv-dialog__accept-button"))
            ).click()
            logger.info("Cookie accept button clicked.")
            time.sleep(2)
        except TimeoutException:
            logger.info("Cookie pop-up not found or timed out.")

        # --- Wait for Idea Cards ---
        logger.info("Waiting for idea cards ('article' tag) to load...")
        try:
            WebDriverWait(driver, 45).until(
                EC.presence_of_element_located((By.TAG_NAME, "article"))
            )
        except TimeoutException:
             logger.warning(f"Timeout waiting for 'article' elements for symbol {symbol.upper()}. Page might have no ideas or structure changed.")
             # Screenshot ရိုက်ကြည့်နိုင် (local မှာ run ရင်)
             # if not (os.environ.get('RENDER') == 'true'): driver.save_screenshot(f"{symbol}_timeout.png")
             return []

        logger.info("Page loaded. Starting data extraction...")
        idea_cards = driver.find_elements(By.TAG_NAME, "article")

        if not idea_cards:
            logger.info(f"No 'article' elements found for symbol {symbol.upper()}.")
            return []

        scraped_ideas = []
        now_ts = time.time()
        time_limit_ts = now_ts - TIME_FILTER_SECONDS

        for i, card in enumerate(idea_cards[:30]): # နည်းနည်း ပိုယူထားမယ် (Filter မလုပ်ခင်)
            try:
                # --- Extract Data (Selectors from previous working version) ---
                title_element = card.find_element(By.CSS_SELECTOR, 'a.title-tkslJwxl')
                full_link = title_element.get_attribute('href')
                title = title_element.text.strip()
                if not title: title = title_element.get_attribute('title')

                timestamp = now_ts # Default to now if time extraction fails
                try:
                    time_element = card.find_element(By.TAG_NAME, 'time')
                    dt_str = time_element.get_attribute('datetime')
                    timestamp = datetime.fromisoformat(dt_str.replace('Z', '+00:00')).timestamp()
                except: pass

                # --- !!! အချိန် စစ်ထုတ်ခြင်း (Scraping လုပ်ရင်း) !!! ---
                if timestamp < time_limit_ts:
                    logger.debug(f"Idea older than 24h skipped: {title}")
                    continue # ၂၄ နာရီထက် ပိုဟောင်းရင် ဒီ card ကို ကျော်ပါ

                # --- ကျန်တဲ့ Data တွေ ဆက်ထုတ်ပါ ---
                image_element = card.find_element(By.CSS_SELECTOR, 'img.image-gDIex6UB')
                image_url = image_element.get_attribute('src') or image_element.get_attribute('data-src')

                current_symbol = symbol.upper()

                idea_type = 'Unknown'
                position_emoji = '⚪️'
                try:
                    type_element = card.find_element(By.CSS_SELECTOR, 'span.idea-strategy-icon-wrap-cbI7LT3N')
                    idea_type_str = type_element.get_attribute('title') # "Short" or "Long"
                    if idea_type_str == 'Long':
                         idea_type, position_emoji = 'Long', '🟢'
                    elif idea_type_str == 'Short':
                         idea_type, position_emoji = 'Short', '🔴'
                except: pass

                likes_count = 0
                try:
                    likes_element = card.find_element(By.CSS_SELECTOR, 'button[data-qa-id="ui-lib-card-like-button"]')
                    likes_str = likes_element.text.strip()
                    if 'K' in likes_str: likes_count = int(float(likes_str.replace('K', '')) * 1000)
                    elif likes_str.isdigit(): likes_count = int(likes_str)
                except: pass

                if image_url and image_url.startswith('/'):
                    image_url = "https://www.tradingview.com" + image_url
                if image_url and not image_url.startswith('http'):
                    image_url = None # Invalid image URL

                scraped_ideas.append({
                    'title': title, 'symbol': current_symbol, 'type': idea_type,
                    'position_emoji': position_emoji, # Emoji ကိုပါ ထည့်သိမ်း
                    'likes_count': likes_count, # Likes ပါ ပြန်ထည့်ထား
                    'published_time': timestamp,
                    'image_url': image_url, 'full_link': full_link
                })

            except NoSuchElementException as e:
                # logger.warning(f"Could not scrape some element in card #{i+1} for {symbol.upper()}: {e.msg}")
                pass

        # Sort by published time, most recent first (24h filter လုပ်ပြီးသား)
        scraped_ideas.sort(key=lambda x: x['published_time'], reverse=True)
        logger.info(f"Successfully scraped {len(scraped_ideas)} ideas within 24h for {symbol.upper()}.")
        return scraped_ideas

    except Exception as e:
        logger.error(f"Error during Selenium scraping for {symbol.upper()}: {e}", exc_info=True)
        # Screenshot ရိုက်ကြည့်နိုင် (local မှာ run ရင်)
        # if driver and not (os.environ.get('RENDER') == 'true'): driver.save_screenshot(f"{symbol}_error.png")
        return None # Error ဖြစ်ရင် None ပြန်
    finally:
        if driver:
            driver.quit()
            logger.info(f"Chrome driver quit for {symbol.upper()}.")

# --- (format_message_caption function - Likes ပါ ပြန်ထည့်) ---
def format_message_caption(idea):
    title = idea.get('title', 'N/A')
    symbol = idea.get('symbol', 'N/A')
    idea_type = idea.get('type', 'Unknown')
    position_emoji = idea.get('position_emoji', '⚪️')
    likes = idea.get('likes_count', 0) # Likes ပါ ပြန်ထည့်ထား
    timestamp = idea.get('published_time', time.time())
    date_str = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M')

    caption = f"<b>{symbol} Idea 🔥</b>\n\n"
    caption += f"<b>Title:</b> {title}\n"
    caption += f"<b>Position:</b> {idea_type} {position_emoji}\n"
    caption += f"<b>Likes:</b> {likes} 🚀\n" # Likes ပါ ပြန်ထည့်ထား
    caption += f"<b>Date:</b> {date_str} 🗓️"
    return caption

# -----------------------------------------------------------------
# --- Bot Logic (Selenium Version, Advanced Reply Logic) ---
# -----------------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start command - အသုံးပြုနည်း ရှင်းပြ"""
    user = update.message.from_user
    logger.info(f"/start command received from user {user.id} ({user.username})")
    await update.message.reply_text(
        f"မင်္ဂလာပါ MCM TradingIdeas Bot မှကြိုဆိုပါတယ်{user.first_name}!\n\n"
        f"Crypto pair အတွက် TradingView idea များကို ရယူရန်:\n\n"
        f"➡️ နောက်ဆုံး idea တစ်ခုတည်းကို ရယူရန်:\n"
        f"`/idea SYMBOL`\n"
        f"(ဥပမာ: `/idea BTCUSDT`)\n\n"
        f"➡️ နောက်ဆုံး ၂၄ နာရီအတွင်း idea အားလုံးကို တစ်ခုချင်း ရယူရန်:\n"
        f"`/idea SYMBOL1,SYMBOL2,...` (ကော်မာခံ၍)\n"
        f"(ဥပမာ: `/idea BTCUSDT,ETHUSDT,SOLUSDT`)\n\n"
        f"Bot သည် ideas များကို ရှာဖွေပြီး သင့်ထံ တိုက်ရိုက် ပြန်လည် ပေးပို့ပါမည်။ (Selenium ကို အသုံးပြုထားပါသည်။)", # Selenium သုံးကြောင်း ထည့်ရေးထား
        parse_mode='Markdown'
    )

async def idea_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/idea command ကို လက်ခံပြီး၊ scraper ကို ခေါ်၊ User ကို reply ပြန်"""
    user = update.message.from_user
    chat_id = update.message.chat_id

    # ... (Argument parsing အရင်အတိုင်း) ...
    if not context.args:
        logger.warning(f"User {user.id} called /idea without arguments.")
        await update.message.reply_text("ကျေးဇူးပြု၍ Symbol တစ်ခု သို့မဟုတ် တစ်ခုထက်ပို၍ (ကော်မာခံပြီး) ထည့်ပေးပါ။\nဥပမာ: `/idea BTCUSDT` သို့မဟုတ် `/idea BTCUSDT,ETHUSDT`", parse_mode='Markdown')
        return
    symbols_input = "".join(context.args)
    symbols_to_fetch = [s.strip().upper() for s in symbols_input.split(',') if s.strip()]
    if not symbols_to_fetch:
        logger.warning(f"User {user.id} provided empty symbols.")
        await update.message.reply_text("Symbol များ မှားယွင်းနေပါသည်။\nဥပမာ: `/idea BTCUSDT`", parse_mode='Markdown')
        return
    log_symbols = ",".join(symbols_to_fetch)
    logger.info(f"/idea command received for symbols: [{log_symbols}] from user {user.id} ({user.username})")

    # ... (Cooldown check အရင်အတိုင်း) ...
    global IS_CURRENTLY_SCRAPING
    if IS_CURRENTLY_SCRAPING:
        logger.warning(f"Scraper is already running. User {user.id} tried to call /idea [{log_symbols}].")
        await update.message.reply_text("Bot သည် ယခုလက်ရှိ အခြား request တစ်ခုကို လုပ်ဆောင်နေပါသည်။ ပြီးဆုံးမှ နောက်တစ်ကြိမ် ပြန်လည် ကြိုးစားပါ။")
        return

    is_single_symbol_request = len(symbols_to_fetch) == 1

    try:
        IS_CURRENTLY_SCRAPING = True
        await update.message.reply_text(f"TradingView မှ `{log_symbols}` အတွက် Ideas များကို Selenium ဖြင့် ရှာဖွေနေပါသည်။ ဤလုပ်ငန်းစဉ်သည် **၁-၂ မိနစ်ခန့်** ကြာနိုင်ပါသည်။ ခဏစောင့်ပါ...", parse_mode='Markdown') # အချိန်ပိုကြာနိုင်ကြောင်း ထည့်ရေးထား

        all_recent_ideas = []
        fetch_successful = True

        # --- !!! Selenium Scraper ကို Thread သီးသန့်မှာ ခေါ်ပါ !!! ---
        for symbol in symbols_to_fetch:
            logger.info(f"Calling Selenium scraper for {symbol} in a separate thread...")
            # fetch_ideas_selenium က list (ideas) or [] or None ပြန်ပေးမယ်
            ideas_list = await asyncio.to_thread(fetch_ideas_selenium, symbol) # <-- Selenium function ကို ခေါ်
            logger.info(f"Selenium scraper for {symbol} finished.")

            if ideas_list is None: # Scraper မှာ Error တက်ခဲ့ရင်
                 logger.error(f"Selenium scraper failed critically for symbol {symbol}.")
                 fetch_successful = False
                 await update.message.reply_text(f"⚠️ `{symbol}` အတွက် Scrape လုပ်ရာတွင် Error ဖြစ်သွားပါသည်။", parse_mode='Markdown')
                 continue
            elif ideas_list: # ideas တွေ့ရင် ပေါင်းထည့် (အချိန် filter လုပ်ပြီးသား)
                all_recent_ideas.extend(ideas_list)

        # --- (ကျန်တဲ့ Result Handling & Reply Logic က အရင်အတိုင်းနီးပါး) ---
        if not fetch_successful and not all_recent_ideas:
             await update.message.reply_text(f"တောင်းဆိုထားသော Symbol များအတွက် Idea များ ရယူရာတွင် အမှားအယွင်းများ ဖြစ်ပေါ်ခဲ့ပါသည်။")
             return
        if not all_recent_ideas:
            logger.info(f"Selenium scraper returned no recent ideas for symbols: [{log_symbols}].")
            await update.message.reply_text(f"တောင်းဆိုထားသော Symbol များ (`{log_symbols}`) အတွက် နောက်ဆုံး ၂၄ နာရီအတွင်း idea အသစ်များ ရှာမတွေ့ပါ။", parse_mode='Markdown')
            return

        # Sort all collected ideas by time, most recent first
        all_recent_ideas.sort(key=lambda x: x['published_time'], reverse=True)

        ideas_to_send = []
        if is_single_symbol_request:
            ideas_to_send = all_recent_ideas[:1]
            count_text = "နောက်ဆုံး idea"
        else:
            ideas_to_send = all_recent_ideas
            count_text = f"နောက်ဆုံး ၂၄ နာရီအတွင်း idea {len(ideas_to_send)} ခု"

        if not ideas_to_send:
             await update.message.reply_text(f"`{log_symbols}` အတွက် နောက်ဆုံး ၂၄ နာရီအတွင်း idea အသစ်များ ရှာမတွေ့ပါ။", parse_mode='Markdown')
             return

        await update.message.reply_text(f"`{log_symbols}` အတွက် {count_text} တွေ့ရှိပါသည်။ ပေးပို့နေပါသည်...", parse_mode='Markdown')

        sent_count = 0
        for idea in ideas_to_send:
            image_url = idea.get('image_url')
            full_link = idea.get('full_link')
            caption = format_message_caption(idea) # Likes ပါတဲ့ caption အသစ်
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
        IS_CURRENTLY_SCRAPING = False
        logger.info("Scraping lock released.")

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