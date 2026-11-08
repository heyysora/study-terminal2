# Study Terminal for TradingView (optional Chrome extension)

Not required. The desktop app's screen copilot already reads TradingView from the screen. The extension
is a lighter, more private alternative for TradingView in Chrome:

- It sends only the **active TradingView tab's title and address** (for example `AAPL 342.37 ▼ −0.52%` and
  `…/chart/?symbol=NASDAQ:AAPL&interval=5`) to the app on this computer (`127.0.0.1`).
- No screenshots, no page contents, no cookies, nothing from your TradingView account, nothing sent to the internet.
- It only has access to tradingview.com and 127.0.0.1. Other sites are invisible to it.
- The badge shows the app's current answer for that symbol (`—` = NO TRADE, `watch` = watch-only idea).

What it can't do: TradingView doesn't always put the chart interval in the address. When it's missing, the
app says so and analyzes your default timeframe.

## Install (Developer mode, about a minute)
1. In Study Terminal: **Settings > Chrome extension**, turn it on and copy the pairing token.
2. In Chrome, open `chrome://extensions`, switch on **Developer mode** (top right), click **Load unpacked**, and pick this
   `extension` folder (installed app: `%LOCALAPPDATA%\Programs\Study Terminal\_internal\extension`).
3. Click the extension's icon > **Settings**, paste the token, **Save and test**.

To remove it: `chrome://extensions` > Remove. To cut it off from the app: turn it off in Settings, or rotate the token.
