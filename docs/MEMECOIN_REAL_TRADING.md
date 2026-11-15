# Real memecoin trading, outside Study Terminal

Study Terminal only practises memecoins. It never holds a wallet or a private key, so nothing in it can spend your money. This
guide is for when you decide to trade for real, using a separate tool.

Commands below come from the pumpfun-cli README (github.com/chainstacklabs/pumpfun-cli, Apache-2.0), read on 2026-11-14.
Check that README before you run anything; it changes.

## Before anything: what you're signing up for

- Most new memecoins lose most of their value, many within hours. Rug pulls (the creator or insiders selling everything) are common.
- On-chain trades can't be undone. A wrong address or a bad token means the money is gone.
- Prices can drop 50% between one check and the next. A "stop" only exists if you're there to sell, and in a thin pool your
  sell itself pushes the price down.
- Only use money you'd be fine losing completely.

## The setup (once)

pumpfun-cli says native Windows isn't tested; its supported route on Windows is WSL (a Linux system inside Windows). This is the
one place you'll need a terminal.

1. **Install WSL.** Open PowerShell as administrator and run `wsl --install`, then restart. Open "Ubuntu" from the Start menu
   and pick a username and password.
2. **Install uv** (it handles Python) inside Ubuntu, following https://docs.astral.sh/uv/getting-started/installation/.
3. **Install pumpfun-cli:** `uv tool install git+https://github.com/chainstacklabs/pumpfun-cli.git`
4. **Get a free Solana RPC address** (Chainstack or Helius have free plans; you sign up, no payment), then:
   `pumpfun config set rpc <your RPC address>`
   You can paste the same address into Study Terminal > Settings > Memecoins to make its holder check work.
5. **Make a separate wallet just for this:** `pumpfun wallet create`. Pick a strong password. The README says keys are
   encrypted on disk (AES-256-GCM + scrypt), need the password for any key operation, and never appear in output or logs.
   Never use your main wallet, and never paste a seed phrase or private key into any website, bot or AI chat.
6. **Put in only a small amount of SOL.** Check it with `pumpfun wallet balance`.

## Every trade

1. **Check the token in Study Terminal first** (Memecoins > paste the address). If it says *High risk*, skip it.
2. **Decide before you buy:** how much (small), and the price where you'll sell if it goes wrong.
3. **Look at it from the command line:** `pumpfun info <mint>` (price, bonding-curve progress, reserves).
4. **Dry run first:** `pumpfun buy <mint> 0.05 --dry-run` shows what would happen and sends nothing.
5. **Then the real buy:** `pumpfun buy <mint> 0.05 --slippage <percent>`
6. **Confirm it landed:** `pumpfun tx-status <signature>`
7. **Selling:** `pumpfun sell <mint> ...` (check `pumpfun sell --help` for the amount options), dry run first if unsure.
8. **Write it in Study Terminal's journal**, including why you bought and what you'd do differently.

## Tools I left out on purpose

- **solana-sniper-mcp** buys brand-new launches automatically in live mode. Its MCP server has no password (anything on your
  computer that can reach it can tell it to buy), and some of its routes charge fees. Auto-buying new launches is the
  fastest way to get rugged.
- **pumpclaw** lets an AI agent run pumpfun-cli for you, which means the AI can spend from your wallet. If you ever try it, set
  your AI tool so every command needs your approval, never "always allow", and keep the wallet small.
- Neither is connected to Study Terminal, and Study Terminal won't connect to a wallet.

## Rules worth keeping

- A daily loss limit you don't break (for example, the amount of one trade).
- No buying in the first hour of a token's life.
- Never "export" your wallet unless you're moving it, and never send the export file anywhere.
- If you're chasing losses, stop for the day. Practise in Study Terminal instead.


## Other tools looked at (0.15.0)

- **pumpfun-agent-skill** is a set of instructions for an AI agent to drive pumpfun-cli (the tool in this guide). Its safety rules match this guide: keys never leave your machine, dry run first, a separate wallet. Its buy, sell, launch and wallet commands were not built into Study Terminal.
- **pumpfun-utilities** shows a real wallet's open positions and keeps a trade journal, read-only, inside Claude Code. Study Terminal's practice journal borrows its main rule: your reasons are never filled in for you.
- **ccxt** is used inside Study Terminal for public crypto prices only, with every order and account function switched off.
