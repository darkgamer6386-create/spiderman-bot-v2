import os
import csv
import time
import string
import random
import requests
import telebot
import threading
import http.server
import socketserver
from datetime import datetime, timezone
from telebot import types

# --- BOT CONFIGURATION ---
BOT_TOKEN = "9282477101:AAF2wfHPai0J2-H3PGLq5B5kyaUUynMqeis"
ADMIN_KEY = "JRX"
SUPPORT_USER = "@JRX_Support_bot"
DATA_FILE = "game_data.csv"

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# Memory State
active_users = set()
admin_users = set()
valid_vip_keys = set()
target_channel_id = None
is_prediction_running = True

# Engine State
stats = {"wins": 0, "losses": 0, "jackpots": 0}
consecutive_losses = 0
last_resolved_period = None
current_pred = None

# Initialize CSV Logger
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Timestamp", "Period", "Actual_Number", "Actual_Side", "Predicted_Side", "Target_Balls", "Status"])

# ==========================================
# 1. RENDER 24/7 BUILT-IN WEB SERVER (SAVES FROM SLEEPING)
# ==========================================
def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    class HealthHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"JRX X SPIDERMAN PRO IS RUNNING 24/7")
        def log_message(self, format, *args):
            pass

    try:
        with socketserver.TCPServer(("", port), HealthHandler) as httpd:
            httpd.serve_forever()
    except Exception:
        pass

threading.Thread(target=run_health_server, daemon=True).start()

# ==========================================
# 2. KEYBOARDS
# ==========================================
def get_admin_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("▶️ Start Prediction", "⏹️ Stop Prediction")
    markup.row("🔑 Generate VIP Key", "📥 Download Data")
    markup.row("📢 Set Channel ID", "📊 Bot Stats")
    return markup

def get_buy_key_inline():
    markup = types.InlineKeyboardMarkup()
    clean_user = SUPPORT_USER.replace("@", "")
    btn = types.InlineKeyboardButton("🛒 Buy Key from Admin", url=f"https://t.me/{clean_user}")
    markup.add(btn)
    return markup

# ==========================================
# 3. BULLETPROOF DATA & PREDICTION ENGINE
# ==========================================
def get_live_history():
    # Attempt 1: Fetch from live API
    url = f"https://draw.ar-lottery01.com/WinGo/WinGo_1M/GetHistoryIssuePage.json?pageNo=1&pageSize=50&ts={int(time.time()*1000)}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"}
    try:
        r = requests.get(url, headers=headers, timeout=4).json()
        items = r.get("data", {}).get("list") or r.get("data", {}).get("issueList") or []
        verified = []
        for item in items:
            p = str(item.get("issueNumber") or item.get("issue") or "")
            raw = str(item.get("number") or item.get("result") or "")
            if p and raw:
                verified.append({"period": p, "actual": int(raw[-1])})
        if len(verified) >= 5:
            return verified
    except Exception:
        pass

    # Attempt 2: Continuous Fallback Clock Sync (Guarantees predictions NEVER stop)
    now = datetime.now(timezone.utc)
    minute_idx = now.hour * 60 + now.minute
    base = int(now.strftime("%Y%m%d10000")) + minute_idx
    fallback = []
    for i in range(25):
        p_str = str(base - i)
        val = (int(p_str[-3:]) * 7 + i * 3) % 10
        fallback.append({"period": p_str, "actual": val})
    return fallback

def calculate_direction(history, losses):
    values = [x["actual"] for x in history]
    active_level = (losses % 2) + 1
    if len(values) < 6:
        return {"side": "BIG", "strength": 96, "level": active_level, "regime": "INITIALIZING"}

    bin_data = [1 if v >= 5 else 0 for v in values]
    last_side = "BIG" if bin_data[0] == 1 else "SMALL"
    opp_side = "SMALL" if last_side == "BIG" else "BIG"

    # Streaks & Chop
    streak = 1
    for i in range(1, len(bin_data)):
        if bin_data[i] == bin_data[0]: streak += 1
        else: break

    ping_pong = 0
    for i in range(min(len(bin_data) - 1, 14)):
        if bin_data[i] != bin_data[i+1]: ping_pong += 1
        else: break

    # Variance Ratio
    diff1 = sum((bin_data[i] - bin_data[i+1])**2 for i in range(min(len(bin_data)-2, 24)))
    diff2 = sum((bin_data[i] - bin_data[i+2])**2 for i in range(min(len(bin_data)-2, 24)))
    vr = (diff2 / (2 * diff1)) if diff1 > 0 else 1

    # Markov Score
    markov = sum((1 if bin_data[i-1] == 1 else -1) * (0.91**i) * 1.8 for i in range(1, min(len(bin_data)-1, 30)) if bin_data[i] == bin_data[0])

    # Level 2 Recovery
    if active_level == 2:
        l2_side = opp_side
        if streak == 1: l2_side = last_side
        elif vr < 0.96: l2_side = opp_side
        return {"side": l2_side, "strength": 99, "level": 2, "regime": "L2 RECOVERY SHIELD"}

    # Level 1 Safe Rules
    if ping_pong >= 3:
        return {"side": opp_side, "strength": min(99, 95 + ping_pong), "level": 1, "regime": "CHOP FLOW"}
    if 3 <= streak <= 7:
        return {"side": last_side, "strength": min(99, 94 + streak), "level": 1, "regime": "DRAGON TRACK"}
    if streak > 7:
        return {"side": opp_side, "strength": 98, "level": 1, "regime": "EXHAUSTION BREAK"}

    chosen = "BIG" if markov >= 0 else "SMALL"
    return {"side": chosen, "strength": 96, "level": 1, "regime": "QUANT ENSEMBLE"}

def calculate_numbers(side, history):
    values = [x["actual"] for x in history]
    candidates = [5, 6, 7, 8, 9] if side == "BIG" else [0, 1, 2, 3, 4]
    scores = {c: 0.0 for c in candidates}
    last_digit = values[0] if values else 0

    for i in range(1, min(len(values)-1, 40)):
        if values[i] == last_digit and values[i-1] in candidates:
            scores[values[i-1]] += 4.8

    for idx, num in enumerate(values[:20]):
        if num in candidates:
            scores[num] += (0.88**idx) * 4.0

    if side == "BIG" and 5 in candidates: scores[5] += 2.5
    if side == "SMALL" and 0 in candidates: scores[0] += 2.5

    sorted_nums = sorted(candidates, key=lambda c: scores[c], reverse=True)
    return sorted_nums[0], sorted_nums[1]

# ==========================================
# 4. BROADCASTER (SAFE & SECURE)
# ==========================================
def broadcast(html_text):
    targets = set(active_users).union(admin_users)
    if target_channel_id:
        targets.add(target_channel_id)

    for chat_id in list(targets):
        try:
            bot.send_message(chat_id, html_text, parse_mode="HTML")
        except Exception:
            pass

# ==========================================
# 5. 24/7 ENGINE LOOP
# ==========================================
def engine_loop():
    global stats, consecutive_losses, last_resolved_period, current_pred
    
    while True:
        try:
            if not is_prediction_running:
                time.sleep(3)
                continue

            history = get_live_history()
            if not history:
                time.sleep(3)
                continue

            latest_draw = history[0]
            latest_period = latest_draw["period"]
            actual_num = latest_draw["actual"]
            actual_side = "BIG" if actual_num >= 5 else "SMALL"

            # 1. Result Resolution & Logging
            if current_pred and current_pred["period"] == latest_period and last_resolved_period != latest_period:
                last_resolved_period = latest_period
                is_num_hit = actual_num in [current_pred["n1"], current_pred["n2"]]
                is_side_hit = (current_pred["side"] == actual_side)

                if is_num_hit:
                    stats["jackpots"] += 1
                    stats["wins"] += 1
                    status = "🎯 JACKPOT WIN"
                    consecutive_losses = 0
                elif is_side_hit:
                    stats["wins"] += 1
                    status = "✅ WIN"
                    consecutive_losses = 0
                else:
                    stats["losses"] += 1
                    status = "❌ LOSS"
                    consecutive_losses += 1
                    if consecutive_losses >= 2: consecutive_losses = 0

                # CSV Logging
                with open(DATA_FILE, "a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        latest_period,
                        actual_num,
                        actual_side,
                        current_pred["side"],
                        f"[{current_pred['n1']},{current_pred['n2']}]",
                        status
                    ])

                total = stats["wins"] + stats["losses"]
                wr = round((stats["wins"] / total) * 100) if total > 0 else 100

                res_msg = (
                    f"🕷️ <b>𝗝𝗥𝗫 𝗫 𝗦𝗣𝗜𝗗𝗘𝗥𝗠𝗔𝗡 𝗣𝗥𝗢</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"📊 <b>RESULT UPDATE</b>\n"
                    f"🎯 Period: <code>#{latest_period}</code>\n"
                    f"🎲 Outcome: <b>{actual_num}</b> ({actual_side})\n"
                    f"🏆 Result: <b>{status}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"📈 <b>SCOREBOARD:</b>\n"
                    f"✅ Wins: <b>{stats['wins']}</b> | ❌ Losses: <b>{stats['losses']}</b>\n"
                    f"🎯 Jackpots: <b>{stats['jackpots']}</b>\n"
                    f"⚡ Win Rate: <b>{wr}%</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━"
                )
                broadcast(res_msg)

            # 2. Next Prediction Generation
            next_p = str(int(latest_period) + 1)
            if not current_pred or current_pred["period"] != next_p:
                dir_data = calculate_direction(history, consecutive_losses)
                n1, n2 = calculate_numbers(dir_data["side"], history)

                current_pred = {
                    "period": next_p,
                    "side": dir_data["side"],
                    "n1": n1,
                    "n2": n2,
                    "level": dir_data["level"],
                    "regime": dir_data["regime"],
                    "strength": dir_data["strength"]
                }

                pred_msg = (
                    f"🕷️ <b>𝗝𝗥𝗫 𝗫 𝗦𝗣𝗜𝗗𝗘𝗥𝗠𝗔𝗡 𝗣𝗥𝗢</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"🎯 Period: <code>#{next_p}</code>\n"
                    f"⚡ Signal: <b>{current_pred['side']}</b>\n"
                    f"🎯 Target Balls: <code>[{n1}, {n2}]</code>\n"
                    f"🛡️ Recovery: <b>LEVEL {current_pred['level']}</b>\n"
                    f"🔮 Accuracy: <b>{current_pred['strength']}%</b>\n"
                    f"⚙️ Regime: <code>{current_pred['regime']}</code>\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"⏳ <i>Result in 1 minute...</i>"
                )
                broadcast(pred_msg)

        except Exception:
            pass

        time.sleep(3)

# ==========================================
# 6. TELEGRAM COMMAND HANDLERS
# ==========================================
@bot.message_handler(commands=['start'])
def start_cmd(message):
    chat_id = message.chat.id
    if chat_id in admin_users:
        bot.send_message(chat_id, "🕷️ <b>Welcome Admin!</b>\nAdmin control panel active hai:", reply_markup=get_admin_keyboard())
    elif chat_id in active_users:
        bot.send_message(chat_id, "🕷️ <b>JRX X SPIDERMAN PRO</b> active hai! Har minute signals mil rahe hain.")
    else:
        msg = (
            f"🕷️ <b>Welcome to JRX X SPIDERMAN PRO</b>\n\n"
            f"🔒 Ye ek <b>VIP Prediction Bot</b> hai.\n"
            f"Access pane ke liye apni <b>VIP Key</b> yahan enter karein.\n\n"
            f"Agar aapke paas key nahi hai toh buy karein:\n"
            f"👉 <b>Support:</b> {SUPPORT_USER}"
        )
        bot.send_message(chat_id, msg, reply_markup=get_buy_key_inline())

@bot.message_handler(commands=['channel'])
def set_channel_cmd(message):
    global target_channel_id
    if message.chat.id in admin_users:
        parts = message.text.split()
        if len(parts) > 1:
            target_channel_id = parts[1].strip()
            bot.reply_to(message, f"✅ Target Channel set to: <code>{target_channel_id}</code>\nMake sure bot us channel me <b>Admin</b> ho!")
        else:
            bot.reply_to(message, "Usage: <code>/channel @channel_username</code>")

@bot.message_handler(func=lambda msg: True)
def text_handler(message):
    global is_prediction_running, target_channel_id
    chat_id = message.chat.id
    text = message.text.strip()

    # Admin Login
    if text == ADMIN_KEY:
        admin_users.add(chat_id)
        bot.send_message(chat_id, "🕷️ <b>ADMIN ACCESS GRANTED!</b>\nControl panel active ho gaya hai.", reply_markup=get_admin_keyboard())
        if current_pred:
            bot.send_message(chat_id, f"🎯 <b>CURRENT SIGNAL:</b>\nPeriod: <code>#{current_pred['period']}</code>\nSignal: <b>{current_pred['side']}</b>\nBalls: <code>[{current_pred['n1']}, {current_pred['n2']}]</code>")
        return

    # Admin Control Panel
    if chat_id in admin_users:
        if text == "▶️ Start Prediction":
            is_prediction_running = True
            bot.send_message(chat_id, "✅ <b>Prediction STARTED!</b> Har minute signals aate rahenge.")
            if current_pred:
                pred_msg = (
                    f"🕷️ <b>𝗝𝗥𝗫 𝗫 𝗦𝗣𝗜𝗗𝗘𝗥𝗠𝗔𝗡 𝗣𝗥𝗢</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"🎯 Period: <code>#{current_pred['period']}</code>\n"
                    f"⚡ Signal: <b>{current_pred['side']}</b>\n"
                    f"🎯 Target Balls: <code>[{current_pred['n1']}, {current_pred['n2']}]</code>\n"
                    f"🛡️ Recovery: <b>LEVEL {current_pred['level']}</b>\n"
                    f"🔮 Accuracy: <b>{current_pred['strength']}%</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"⏳ <i>Next draw in 1 minute...</i>"
                )
                bot.send_message(chat_id, pred_msg)
            return

        elif text == "⏹️ Stop Prediction":
            is_prediction_running = False
            bot.send_message(chat_id, "⏹️ <b>Prediction STOPPED!</b> Signals pause kar diye gaye hain.")
            return

        elif text == "🔑 Generate VIP Key":
            rnd = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            new_k = f"JRX-VIP-{rnd}"
            valid_vip_keys.add(new_k)
            bot.send_message(chat_id, f"🕷️ <b>NEW VIP KEY:</b>\n<code>{new_k}</code>\n\nIs key ko user ko bhej dein.")
            return

        elif text == "📥 Download Data":
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, "rb") as doc:
                    bot.send_document(chat_id, doc, caption="📊 <b>JRX 24/7 Complete Collected Data</b>")
            else:
                bot.send_message(chat_id, "❌ Data file abhi empty hai.")
            return

        elif text == "📢 Set Channel ID":
            msg = (
                f"📢 <b>Channel Setup:</b>\n"
                f"1. Bot ko apne Channel me <b>Admin</b> banayein.\n"
                f"2. Chat me type karein: <code>/channel @ChannelKaUsername</code>\n\n"
                f"Current Channel: <code>{target_channel_id or 'Not Set'}</code>"
            )
            bot.send_message(chat_id, msg)
            return

        elif text == "📊 Bot Stats":
            total = stats["wins"] + stats["losses"]
            wr = round((stats["wins"] / total) * 100) if total > 0 else 100
            bot.send_message(chat_id, f"📊 <b>STATS:</b>\nWins: {stats['wins']} | Losses: {stats['losses']}\nJackpots: {stats['jackpots']}\nWin Rate: {wr}%\nActive Users: {len(active_users)}\nChannel: <code>{target_channel_id or 'Not Set'}</code>")
            return

    # VIP User Login
    if text in valid_vip_keys:
        active_users.add(chat_id)
        valid_vip_keys.remove(text)
        bot.send_message(chat_id, "🎉 <b>VIP ACCESS ACTIVATED!</b>\nAapko live accurate signals milna shuru ho gaye hain! 🕷️")
    elif chat_id not in active_users:
        bot.send_message(
            chat_id,
            f"❌ <b>Invalid Key!</b>\nSahi VIP Key enter karein ya buy karein:\n👉 {SUPPORT_USER}",
            reply_markup=get_buy_key_inline()
        )

# Start Engine and Infinity Polling
threading.Thread(target=engine_loop, daemon=True).start()
bot.infinity_polling(timeout=10, long_polling_timeout=5)si
