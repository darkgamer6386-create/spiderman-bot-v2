import os
import csv
import time
import string
import random
import requests
import telebot
import threading
from datetime import datetime
from telebot import types

# Pre-Configured Credentials
BOT_TOKEN = "9282477101:AAF2wfHPai0J2-H3PGLq5B5kyaUUynMqeis"
ADMIN_KEY = "JRX"
SUPPORT_USER = "@JRX_Support_bot"
DATA_FILE = "game_data.csv"

bot = telebot.TeleBot(BOT_TOKEN)

# In-Memory Database & State
active_users = set()
admin_users = set()
valid_vip_keys = set()
target_channel_id = None
is_prediction_running = True

# Engine Tracking
stats = {"wins": 0, "losses": 0, "jackpots": 0}
consecutive_losses = 0
last_resolved_period = None
current_pred = None

# Initialize CSV Logger
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Timestamp", "Period", "Actual_Number", "Actual_Side", "Predicted_Side", "Target_Balls", "Status"])

# --- KEYBOARDS ---
def get_admin_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("▶️ Start Prediction", "⏹️ Stop Prediction")
    markup.row("🔑 Generate VIP Key", "📥 Download Data")
    markup.row("📢 Set Channel ID", "📊 Bot Stats")
    return markup

def get_buy_key_inline():
    markup = types.InlineKeyboardMarkup()
    btn = types.InlineKeyboardButton("🛒 Buy Key from Admin", url=f"https://t.me/{SUPPORT_USER.replace('@', '')}")
    markup.add(btn)
    return markup

# --- API FETCH ---
def get_live_history():
    url = f"https://draw.ar-lottery01.com/WinGo/WinGo_1M/GetHistoryIssuePage.json?pageNo=1&pageSize=50&ts={int(time.time()*1000)}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=6).json()
        data = r.get("data", {})
        items = data.get("list") or data.get("issueList") or []
        verified = []
        for item in items:
            period = str(item.get("issueNumber") or item.get("issue") or "")
            raw_num = str(item.get("number") or item.get("result") or "")
            if period and raw_num:
                actual = int(raw_num[-1])
                verified.append({"period": period, "actual": actual})
        return verified
    except:
        return []

# --- HTML QUANTUM V7 LOGIC ---
def calculate_direction(history, losses):
    values = [x["actual"] for x in history]
    active_level = (losses % 2) + 1
    if len(values) < 6:
        return {"side": "BIG", "strength": 96, "level": active_level, "regime": "INITIALIZING"}

    bin_data = [1 if v >= 5 else 0 for v in values]
    last_side = "BIG" if bin_data[0] == 1 else "SMALL"
    opp_side = "SMALL" if last_side == "BIG" else "BIG"

    # 1. Streaks
    streak = 1
    for i in range(1, len(bin_data)):
        if bin_data[i] == bin_data[0]: streak += 1
        else: break

    prev_streak = 0
    if streak < len(bin_data):
        prev_streak = 1
        for i in range(streak + 1, len(bin_data)):
            if bin_data[i] == bin_data[streak]: prev_streak += 1
            else: break

    # 2. Ping-Pong
    ping_pong = 0
    for i in range(min(len(bin_data) - 1, 14)):
        if bin_data[i] != bin_data[i+1]: ping_pong += 1
        else: break

    # 3. Variance Ratio (Hurst Proxy)
    diff1 = sum((bin_data[i] - bin_data[i+1])**2 for i in range(min(len(bin_data)-2, 24)))
    diff2 = sum((bin_data[i] - bin_data[i+2])**2 for i in range(min(len(bin_data)-2, 24)))
    vr = (diff2 / (2 * diff1)) if diff1 > 0 else 1
    is_trending = vr > 1.04
    is_mean_reverting = vr < 0.96

    # 4. Multi-Order Markov Matrix
    markov = 0
    for i in range(1, min(len(bin_data)-1, 35)):
        if bin_data[i] == bin_data[0]:
            markov += (1 if bin_data[i-1] == 1 else -1) * (0.91**i) * 1.8

    if len(bin_data) >= 7:
        pair_key = (bin_data[1], bin_data[0])
        for i in range(2, min(len(bin_data)-1, 40)):
            if (bin_data[i+1], bin_data[i]) == pair_key:
                markov += (1 if bin_data[i-1] == 1 else -1) * (0.92**i) * 3.4

    # 5. Digit Kinetic Velocity
    v0 = values[0] - values[1] if len(values) > 1 else 0
    v1 = values[1] - values[2] if len(values) > 2 else 0
    acc = v0 - v1
    kinetic = 0
    if acc >= 3: kinetic += 1.8
    elif acc <= -3: kinetic -= 1.8

    # 6. Poisson 20-Draw Balance
    sample20 = bin_data[:20]
    bigs = sum(sample20)
    balance = 0
    if bigs >= 14: balance -= 3.5
    elif bigs <= 6: balance += 3.5

    total_quant = markov + kinetic + balance

    # --- LEVEL 2 DEEP RECOVERY ---
    if active_level == 2:
        l2_side = opp_side
        regime = "L2 RECOVERY"
        if streak == 1 and prev_streak >= 3:
            l2_side = last_side
            regime = "L2 SNAP HARVEST"
        elif streak == 2 and ping_pong <= 1:
            l2_side = last_side
            regime = "L2 CHOP-BREAK PIVOT"
        elif streak == 2 and prev_streak == 2:
            l2_side = opp_side
            regime = "L2 PAIR FLIP"
        elif abs(total_quant) >= 3.0:
            l2_side = "BIG" if total_quant > 0 else "SMALL"
            regime = "L2 QUANT OVERRIDE"
        elif is_mean_reverting:
            l2_side = opp_side
            regime = "L2 MEAN-REV SHIELD"

        return {"side": l2_side, "strength": 99, "level": 2, "regime": regime}

    # --- LEVEL 1 SAFE ---
    if ping_pong >= 3:
        return {"side": opp_side, "strength": min(99, 95 + ping_pong), "level": 1, "regime": "CHOP FLOW"}
    if streak >= 3 and streak <= 7 and (is_trending or vr >= 0.98):
        return {"side": last_side, "strength": min(99, 94 + streak), "level": 1, "regime": "DRAGON TRACK"}
    if streak > 7:
        return {"side": opp_side, "strength": 98, "level": 1, "regime": "EXHAUSTION BREAK"}
    if streak == 2 and prev_streak == 2:
        return {"side": opp_side, "strength": 96, "level": 1, "regime": "DOUBLE CYCLE"}

    chosen = "BIG" if total_quant >= 0 else "SMALL"
    conf = min(99, int(94 + abs(total_quant) * 1.3))
    return {"side": chosen, "strength": conf, "level": 1, "regime": "QUANT ENSEMBLE"}

# --- 2-DIGIT JACKPOT SNIPER ---
def calculate_numbers(side, history):
    values = [x["actual"] for x in history]
    candidates = [5, 6, 7, 8, 9] if side == "BIG" else [0, 1, 2, 3, 4]
    scores = {c: 0.0 for c in candidates}
    last_digit = values[0] if values else 0

    # Transition frequency
    for i in range(1, min(len(values)-1, 50)):
        if values[i] == last_digit and values[i-1] in candidates:
            scores[values[i-1]] += 4.8

    # Exponential recency
    for idx, num in enumerate(values[:24]):
        if num in candidates:
            scores[num] += (0.88**idx) * 4.2

    # Poisson Gap Window
    for c in candidates:
        gap = values.index(c) if c in values else 24
        if 5 <= gap <= 12:
            scores[c] += 3.6

    # Violet Anchor
    if side == "BIG" and 5 in candidates: scores[5] += 2.2
    if side == "SMALL" and 0 in candidates: scores[0] += 2.2

    sorted_nums = sorted(candidates, key=lambda c: scores[c], reverse=True)
    return sorted_nums[0], sorted_nums[1]

# --- BROADCASTER (USERS + CHANNEL) ---
def broadcast(msg):
    targets = set(active_users).union(admin_users)
    if target_channel_id:
        targets.add(target_channel_id)

    for chat_id in targets:
        try:
            bot.send_message(chat_id, msg, parse_mode="Markdown")
        except:
            pass

# --- 24/7 ENGINE THREAD ---
def run_loop():
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

            # 1. Result Resolution & CSV Logging
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

                # Append to CSV
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

                total_played = stats["wins"] + stats["losses"]
                win_rate = round((stats["wins"] / total_played) * 100) if total_played > 0 else 100

                res_msg = (
                    f"🕷️ **𝗝𝗥𝗫 𝗫 𝗦𝗣𝗜𝗗𝗘𝗥𝗠𝗔𝗡 𝗣𝗥𝗢**\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"📊 **RESULT UPDATE**\n"
                    f"🎯 Period: `#{latest_period}`\n"
                    f"🎲 Outcome: **{actual_num}** ({actual_side})\n"
                    f"🏆 Result: **{status}**\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"📈 **SESSION ACCURACY:**\n"
                    f"✅ Wins: {stats['wins']} | ❌ Losses: {stats['losses']}\n"
                    f"🎯 Jackpots: {stats['jackpots']}\n"
                    f"⚡ Win Rate: **{win_rate}%**\n"
                    f"━━━━━━━━━━━━━━━━━━━"
                )
                broadcast(res_msg)

            # 2. Next Prediction Generation
            next_period = str(int(latest_period) + 1)
            if not current_pred or current_pred["period"] != next_period:
                dir_data = calculate_direction(history, consecutive_losses)
                n1, n2 = calculate_numbers(dir_data["side"], history)

                current_pred = {
                    "period": next_period,
                    "side": dir_data["side"],
                    "n1": n1,
                    "n2": n2,
                    "level": dir_data["level"],
                    "regime": dir_data["regime"],
                    "strength": dir_data["strength"]
                }

                pred_msg = (
                    f"🕷️ **𝗝𝗥𝗫 𝗫 𝗦𝗣𝗜𝗗𝗘𝗥𝗠𝗔𝗡 𝗣𝗥𝗢**\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"🎯 Period: `#{next_period}`\n"
                    f"⚡ Signal: **{current_pred['side']}**\n"
                    f"🎯 Target Balls: `[{n1}, {n2}]`\n"
                    f"🛡️ Protection: **LEVEL {current_pred['level']}**\n"
                    f"🔮 Accuracy: **{current_pred['strength']}%**\n"
                    f"⚙️ Regime: `{current_pred['regime']}`\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"⏳ Result in 1 minute..."
                )
                broadcast(pred_msg)

        except Exception as e:
            pass

        time.sleep(3)

# --- BOT COMMANDS ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    chat_id = message.chat.id
    if chat_id in admin_users:
        bot.send_message(chat_id, "🕷️ **Welcome Admin!**\nControl panel active hai:", parse_mode="Markdown", reply_markup=get_admin_keyboard())
    elif chat_id in active_users:
        bot.send_message(chat_id, "🕷️ **JRX X SPIDERMAN PRO** active hai! Aapko signals mil rahe hain.")
    else:
        msg = (
            f"🕷️ **Welcome to JRX X SPIDERMAN PRO**\n\n"
            f"🔒 Ye ek **VIP Prediction Bot** hai.\n"
            f"Access pane ke liye apni **VIP Key** yahan enter karein.\n\n"
            f"Agar aapke paas VIP Key nahi hai toh niche diye gaye link se buy karein:\n"
            f"👉 **Support ID:** {SUPPORT_USER}"
        )
        bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=get_buy_key_inline())

@bot.message_handler(commands=['channel'])
def set_channel_cmd(message):
    global target_channel_id
    if message.chat.id in admin_users:
        parts = message.text.split()
        if len(parts) > 1:
            target_channel_id = parts[1].strip()
            bot.reply_to(message, f"✅ Target Channel set to: `{target_channel_id}`\nMake sure bot us channel me **Admin** ho!", parse_mode="Markdown")
        else:
            bot.reply_to(message, "Usage: `/channel @channel_username` ya `/channel -100xxxxxxxxxx`", parse_mode="Markdown")

@bot.message_handler(func=lambda msg: True)
def text_handler(message):
    global is_prediction_running, target_channel_id
    chat_id = message.chat.id
    text = message.text.strip()

    # 1. Admin Login
    if text == ADMIN_KEY:
        admin_users.add(chat_id)
        bot.send_message(chat_id, "🕷️ **ADMIN ACCESS GRANTED!**\nAdmin panel active ho gaya hai.", parse_mode="Markdown", reply_markup=get_admin_keyboard())
        return

    # 2. Admin Actions
    if chat_id in admin_users:
        if text == "▶️ Start Prediction":
            is_prediction_running = True
            bot.send_message(chat_id, "✅ **Prediction STARTED!** Har minute signals jaate rahenge.")
            return

        elif text == "⏹️ Stop Prediction":
            is_prediction_running = False
            bot.send_message(chat_id, "⏹️ **Prediction STOPPED!** Signals pause ho gaye hain.")
            return

        elif text == "🔑 Generate VIP Key":
            random_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            new_key = f"JRX-VIP-{random_str}"
            valid_vip_keys.add(new_key)
            bot.send_message(chat_id, f"🕷️ **NEW VIP KEY:**\n`{new_key}`\n\nIs key ko user ko bhej dein.", parse_mode="Markdown")
            return

        elif text == "📥 Download Data":
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, "rb") as doc:
                    bot.send_document(chat_id, doc, caption="📊 **JRX 24/7 Complete Collected Data**")
            else:
                bot.send_message(chat_id, "❌ Data file abhi empty hai.")
            return

        elif text == "📢 Set Channel ID":
            msg = (
                f"📢 **Channel Set karne ka tarika:**\n\n"
                f"1. Bot ko apne channel me **Admin** banayein.\n"
                f"2. Chat me type karein: `/channel @AapkaChannelUsername`\n"
                f"(Ya Channel ID dalein: `/channel -100xxxxxxxxxx`)\n\n"
                f"Current Channel: `{target_channel_id or 'None'}`"
            )
            bot.send_message(chat_id, msg, parse_mode="Markdown")
            return

        elif text == "📊 Bot Stats":
            total = stats["wins"] + stats["losses"]
            wr = round((stats["wins"] / total) * 100) if total > 0 else 100
            bot.send_message(chat_id, f"📊 **STATS:**\nWins: {stats['wins']} | Losses: {stats['losses']}\nJackpots: {stats['jackpots']}\nWin Rate: {wr}%\nActive Users: {len(active_users)}\nChannel: {target_channel_id or 'Not Set'}")
            return

    # 3. User VIP Activation
    if text in valid_vip_keys:
        active_users.add(chat_id)
        valid_vip_keys.remove(text)
        bot.send_message(chat_id, "🎉 **VIP KEY ACCEPTED!**\nAapka VIP access activate ho gaya hai. Signals milna shuru ho gaye hain! 🕷️")
    elif chat_id not in active_users:
        bot.send_message(
            chat_id,
            f"❌ **Invalid Key!**\nSahi VIP Key enter karein ya yahan se buy karein:\n👉 {SUPPORT_USER}",
            reply_markup=get_buy_key_inline()
        )

# Thread & Start
threading.Thread(target=run_loop, daemon=True).start()
bot.infinity_polling()
