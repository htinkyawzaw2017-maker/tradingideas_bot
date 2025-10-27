# tradingideas_bot

This Telegram bot scrapes the latest TradingView ideas for specified cryptocurrency symbols using Selenium and replies directly to the user who requested them via Telegram commands.

* **Selenium Scraping:** TradingView ဝဘ်ဆိုက် (`tradingview.com/symbols/SYMBOL/ideas/`) ကို တိုက်ရိုက် scrape လုပ်ပြီး data ရယူပါသည်။
* **Specific Symbol Request:** User က crypto pair symbol တစ်ခု (သို့မဟုတ် တစ်ခုထက်ပို၍) ကို သတ်မှတ်ပြီး idea တောင်းဆိုနိုင်သည် (`/idea SYMBOL` or `/idea SYMBOL1,SYMBOL2,...`)။
* **Time Filtering:** နောက်ဆုံး ၂၄ နာရီအတွင်း update ဖြစ်ထားသော idea များကိုသာ စစ်ထုတ် ပေးပို့ပါသည်။
* **Reply Logic:**
    * Symbol တစ်ခုတည်း တောင်းဆိုလျှင် နောက်ဆုံး idea **တစ်ခုတည်း** ကို ပြန်လည် ပေးပို့သည်။
    * Symbols အများကြီး (ကော်မာခံ၍) တောင်းဆိုလျှင် ၂၄ နာရီအတွင်းက ideas **အားလုံး** ကို (နောက်ဆုံး အရင်) တစ်ခုချင်း ပြန်လည် ပေးပို့သည်။
* **Formatted Reply:** User ဆီသို့ ပုံ (Image)၊ ခေါင်းစဉ် (Title), ခန့်မှန်း Position (Long/Short), Likes အရေအတွက်, ရက်စွဲ (Date), နှင့် မူရင်း TradingView link ခလုတ် ပါဝင်သော message ဖြင့် reply ပြန်ပေးသည်။
* **Cooldown:** Bot က scraping လုပ်နေစဉ်အတွင်း နောက်ထပ် request များ ထပ်မံ လက်မခံဘဲ user ကို ခဏ စောင့်ရန် အကြောင်းကြားသည်။
* **Error Handling:** Scraping လုပ်ရာတွင်၊ Telegram သို့ ပို့ရာတွင် ဖြစ်ပေါ်နိုင်သော error များကို ကိုင်တွယ်ပေးသည်။

## Requirements (လိုအပ်ချက်များ)

* Python 3.8+ (ဥပမာ: 3.11)
* Google Chrome browser (Local တွင် run ရန်အတွက်)
* ChromeDriver (Local တွင် run ရန်အတွက် - Chrome version နှင့် ကိုက်ညီရမည်)
* `requirements.txt` file ထဲတွင် ပါဝင်သော Python libraries များ:
    * `python-telegram-bot`
    * `requests`
    * `selenium`
    * `beautifulsoup4`
    * `httpx`
