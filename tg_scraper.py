"""
tg_scraper.py — Telegram channel trade scraper
Incremental — only fetches messages newer than last run.
Appends new trades to tg_trades.csv.
"""

import os
import re
import csv
import json
import asyncio
from datetime import datetime, timezone
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID      = int(os.environ.get('TG_API_ID', '30918330'))
API_HASH    = os.environ.get('TG_API_HASH', 'f0e35bade52a90fd960d7cb3d8cfbb07')
SESSION     = os.environ.get('TG_SESSION', '')
CHANNEL_ID  = int(os.environ.get('TG_CHANNEL_ID', '-1002940195231'))
OUTPUT_FILE = 'tg_trades.csv'
STATE_FILE  = 'tg_scraper_state.json'

# A message is a trade if it carries ANY of these tags. #REVERSAL, #MOMENTUM,
# and #PULLBACK also tell us the setup type directly — no more guessing/manual
# tagging later. If only #POSITIONAL appears with none of the other three,
# setup_type comes back blank rather than a guessed default, since we don't
# actually know it.
TAG_PATTERN = re.compile(r'#(POSITIONAL|REVERSAL|MOMENTUM|PULLBACK)', re.IGNORECASE)

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {'last_message_id': 0}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

def parse_trade(text, date, msg_id):
    tags_found = {m.group(1).upper() for m in TAG_PATTERN.finditer(text)}
    if not tags_found:
        return None

    if 'REVERSAL' in tags_found:
        setup_type = 'REVERSAL'
    elif 'MOMENTUM' in tags_found:
        setup_type = 'MOMENTUM'
    elif 'PULLBACK' in tags_found:
        setup_type = 'PULLBACK'
    else:
        setup_type = ''  # only #POSITIONAL seen — genuinely unknown, left blank on purpose

    lines = [l.strip() for l in text.strip().split('\n') if l.strip()]
    ticker = None
    for i, line in enumerate(lines):
        if TAG_PATTERN.search(line):
            rest = TAG_PATTERN.sub('', line).strip()
            rest = re.sub(r'[^A-Z0-9&]', '', rest.upper())
            if rest:
                ticker = rest
            elif i + 1 < len(lines):
                ticker = re.sub(r'[^A-Z0-9&]', '', lines[i+1].upper())
            break
    if not ticker:
        return None

    def extract_price(pattern, text, extra_flags=0):
        m = re.search(pattern, text, re.IGNORECASE | extra_flags)
        if m:
            try: return float(re.sub(r'[^0-9.]', '', m.group(1)))
            except: return None
        return None

    # Some calls use "BUY AT" instead of "BUY ABOVE" -- both are recognized
    # here, since only matching ABOVE silently dropped every AT-phrased
    # message entirely (buy_above came back None -> parse_trade() returns
    # None before anything gets written to the CSV).
    buy_above = extract_price(r'BUY\s*(?:ABOVE|AT)\s*:?\s*([\d,\.]+)', text)
    # ^ without re.MULTILINE only matches the very start of the whole
    # message -- since every real message starts with the tag/ticker/buy
    # above lines first, this silently never matched at all, leaving
    # orig_sl/orig_tgt permanently blank in the CSV output.
    sl        = extract_price(r'^SL\s*:?\s*([\d,\.]+)', text, re.MULTILINE)
    tgt       = extract_price(r'^TGT\s*:?\s*([\d,\.]+)', text, re.MULTILINE)

    if not buy_above:
        return None

    return {
        'msg_id':      msg_id,
        'ticker':      ticker,
        'setup_type':  setup_type,
        'entry_date':  date.strftime('%Y-%m-%d'),
        'entry_time':  date.strftime('%H:%M'),
        'entry_price': buy_above,
        'orig_sl':     sl or '',
        'orig_tgt':    tgt or '',
        'raw_message': text[:300].replace('\n', ' ')
    }

def load_existing_msg_ids():
    if not os.path.exists(OUTPUT_FILE):
        return set()
    with open(OUTPUT_FILE) as f:
        reader = csv.DictReader(f)
        return {int(row['msg_id']) for row in reader if row.get('msg_id')}

async def scrape():
    state = load_state()
    last_id = state['last_message_id']
    existing_ids = load_existing_msg_ids()
    is_first_run = last_id == 0
    print(f"{'First run — fetching all messages' if is_first_run else f'Incremental run — fetching messages after ID {last_id}'}")

    async with TelegramClient(StringSession(SESSION), API_ID, API_HASH) as client:
        print(f"Connected. Scraping channel {CHANNEL_ID}...")
        new_trades = []
        total = 0
        max_id = last_id
        kwargs = {} if is_first_run else {'min_id': last_id}
        async for message in client.iter_messages(CHANNEL_ID, limit=None, **kwargs):
            if not message.text:
                continue
            total += 1
            if message.id in existing_ids:
                continue
            trade = parse_trade(message.text, message.date.replace(tzinfo=None), message.id)
            if trade:
                new_trades.append(trade)
            if message.id > max_id:
                max_id = message.id
        print(f"Messages scanned: {total}, New trades found: {len(new_trades)}")
        if new_trades:
            new_trades.sort(key=lambda x: (x['entry_date'], x['entry_time']))
            fields = ['msg_id','ticker','setup_type','entry_date','entry_time','entry_price','orig_sl','orig_tgt','raw_message']
            file_exists = os.path.exists(OUTPUT_FILE)
            with open(OUTPUT_FILE, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                if not file_exists:
                    writer.writeheader()
                writer.writerows(new_trades)
            print(f"Appended {len(new_trades)} new trades to {OUTPUT_FILE}")
        else:
            if not os.path.exists(OUTPUT_FILE):
                with open(OUTPUT_FILE, 'w', newline='') as f:
                    csv.DictWriter(f, fieldnames=['msg_id','ticker','setup_type','entry_date','entry_time','entry_price','orig_sl','orig_tgt','raw_message']).writeheader()
            print("No new trades found.")
        if max_id > last_id:
            save_state({'last_message_id': max_id})
            print(f"State updated — last message ID: {max_id}")

if __name__ == '__main__':
    asyncio.run(scrape())
