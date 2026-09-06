from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

import json
import random
import os
import traceback
import asyncio
import discord
from discord import app_commands

# --- 設定 ---
intents = discord.Intents.default()
intents.message_content = True

class FullBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.tree.on_error = self.on_app_command_error

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        print("\n❌ エラーが発生しました ❌")
        traceback.print_exception(type(error), error, error.__traceback__)

client = FullBot()
DATA_FILE = "data.json"
SETTING_FILE = "settings.json"
INITIAL_POINTS = 300  # 救済ポイント

# --- 安全なデータ管理 ---
def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            content = f.read()
            if not content.strip():
                return {}
            return json.loads(content)
    except Exception as e:
        print(f"⚠️ データ読込エラー: {e}")
        return {}

def save_data(data):
    try:
        temp_file = DATA_FILE + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        if os.path.exists(DATA_FILE):
            os.replace(temp_file, DATA_FILE)
        else:
            os.rename(temp_file, DATA_FILE)
    except Exception as e:
        print(f"⚠️ 保存エラー: {e}")

# --- 設定データ管理（スコアボード設置チャンネル用） ---
def load_settings():
    if not os.path.exists(SETTING_FILE):
        return {}
    try:
        with open(SETTING_FILE, "r", encoding="utf-8") as f:
            content = f.read()
            if not content.strip():
                return {}
            return json.loads(content)
    except Exception as e:
        print(f"⚠️ 設定読込エラー: {e}")
        return {}

def save_settings(settings):
    try:
        with open(SETTING_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"⚠️ 設定保存エラー: {e}")

def get_user_data(uid, data: dict) -> dict:
    uid_str = str(uid)
    if uid_str not in data or not isinstance(data[uid_str], dict):
        data[uid_str] = {"points": INITIAL_POINTS, "pekari_stock": 0}
        save_data(data)
    elif "points" not in data[uid_str]:
        data[uid_str]["points"] = INITIAL_POINTS
        data[uid_str]["pekari_stock"] = 0
        save_data(data)
    return data[uid_str]

# --- 専用部屋チェック判定 ---
def is_casino_room(channel: discord.TextChannel) -> bool:
    return channel.name.startswith("🎰-")

# ==========================================
# 専用部屋管理 View & コマンド
# ==========================================
class CloseRoomView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🚪 カジノ部屋を閉じる", style=discord.ButtonStyle.danger, custom_id="close_casino_room")
    async def close_room(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("👋 お疲れ様でした！5秒後にこの部屋を削除します...")
        await asyncio.sleep(5)
        await interaction.channel.delete()

@client.tree.command(name="casino", description="あなた専用のプライベートカジノ部屋を作成します")
@app_commands.describe(category="部屋を作成するカテゴリーを指定します（省略時はこのコマンドを実行した場所と同じカテゴリー）")
async def casino(interaction: discord.Interaction, category: discord.CategoryChannel = None):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    user = interaction.user

    room_name = f"🎰-{user.name.lower()}-カジノ"
    existing_channel = discord.utils.get(guild.channels, name=room_name)

    if existing_channel:
        await interaction.followup.send(f"⚠️ すでにあなた専用のカジノ部屋があります！ 👉 {existing_channel.mention}", ephemeral=True)
        return

    target_category = category if category is not None else interaction.channel.category

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
    }

    try:
        channel = await guild.create_text_channel(
            name=room_name,
            overwrites=overwrites,
            category=target_category,
            topic=f"{user.display_name} 専用カジノルーム"
        )

        view = CloseRoomView()
        await channel.send(
            f"🎰 **{user.mention} 専用カジノへようこそ！** 🎰\n"
            f"ここで `/slot` `/bj` `/janken` `/gacha` `/dive` などのゲームを楽しめます。\n"
            f"遊び終わったら下のボタンを押して部屋を閉じてください！",
            view=view,
            silent=True
        )
        await interaction.followup.send(f"✅ 専用カジノ部屋を作成しました！ 👉 {channel.mention}", ephemeral=True)

    except discord.Forbidden:
        await interaction.followup.send("⚠️ Botに「チャンネルの管理」権限がないため部屋を作成できませんでした。", ephemeral=True)

# ==========================================
# 共通: ベット額変更フォーム (Modal)
# ==========================================
class ChangeBetModal(discord.ui.Modal):
    def __init__(self, game_type, user_id):
        super().__init__(title="賭け金の変更")
        self.game_type = game_type
        self.user_id = str(user_id)
        self.bet_input = discord.ui.TextInput(
            label="新しい賭け金を入力してください",
            placeholder="例: 100",
            min_length=1,
            max_length=10,
            required=True
        )
        self.add_item(self.bet_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_bet = int(self.bet_input.value)
            if new_bet <= 0:
                await interaction.response.send_message("⚠️ 1pt以上を指定してください。", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("⚠️ 数字を入力してください。", ephemeral=True)
            return

        await interaction.response.defer()
        data = load_data()
        user_info = get_user_data(self.user_id, data)

        if user_info["points"] < new_bet:
            user_info["points"] = INITIAL_POINTS
            save_data(data)
            await interaction.followup.send(f"💰 ポイント不足のため **{INITIAL_POINTS} pt** 補給しました！もう一度試してください。", ephemeral=True)
            return

        if self.game_type == "slot":
            reels, msg = process_slot_spin(self.user_id, new_bet, data)
            save_data(data)
            view = SlotView(self.user_id, new_bet)
            await interaction.message.edit(
                content=f"🎰 **スロット**（賭け金: **{new_bet} pt**）\n│ {reels[0]} │ {reels[1]} │ {reels[2]} │\n\n{msg}（所持: **{user_info['points']} pt**）",
                view=view
            )
        elif self.game_type == "bj":
            p_hand, d_hand = [deal_card(), deal_card()], [deal_card(), deal_card()]
            view = BlackjackView(self.user_id, new_bet, p_hand, d_hand)
            await interaction.message.edit(
                content=f"🎮 **ブラックジャック開始**（賭け金: **{new_bet} pt**）\n**手札:** {p_hand} ({calculate_score(p_hand)})\n**ディーラー:** [{d_hand[0]}]",
                view=view
            )
        elif self.game_type == "janken":
            view = JankenView(self.user_id, new_bet)
            await interaction.message.edit(
                content=f"✊✌️✋ **じゃんけん開始**（賭け金: **{new_bet} pt**）\n手を選んでください！",
                view=view
            )

# ==========================================
# 1. スロット機能
# ==========================================
SLOT_SYMBOLS = ["🍒", "🔔", "🍇", "7️⃣", "🍊", "🍉", "💎"]

def process_slot_spin(uid: str, bet: int, data: dict):
    user_info = get_user_data(uid, data)
    pekari_msg = ""
    
    if user_info["pekari_stock"] > 0:
        user_info["pekari_stock"] -= 1
        sym = random.choice(SLOT_SYMBOLS)
        reels = [sym, sym, sym]
        multiplier = 25 if sym == "7️⃣" else 10
        payout = int(bet * multiplier)
        user_info["points"] += (payout - bet)
        rem = user_info["pekari_stock"]
        pekari_msg = f"🔥 **ペカり確変中！** 3つ揃い確定！（残り確変: **{rem}回**）\n"
        msg = f"{pekari_msg}🎉 **超特大ヒット！3つ揃い（{multiplier}倍）！** **+{payout} pt**"
    else:
        is_pekari = random.random() < 0.007
        if is_pekari:
            user_info["pekari_stock"] = 3
            pekari_msg = "💡 **GOGO! CHANCE** 💡\n✨ **ペカッた！次回から3回連続で3つ揃い確定！**\n"

        reels = random.choices(SLOT_SYMBOLS, k=3)
        if reels[0] == reels[1] == reels[2]:
            multiplier = 25 if reels[0] == "7️⃣" else 10
            payout = int(bet * multiplier)
            user_info["points"] += (payout - bet)
            msg = f"{pekari_msg}🎉 **超特大ヒット！3つ揃い（{multiplier}倍）！** **+{payout} pt**"
        elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
            payout = int(bet * 2)
            user_info["points"] += (payout - bet)
            msg = f"{pekari_msg}✨ **プチ当たり！2つ揃い（2倍）！** **+{payout} pt**"
        else:
            user_info["points"] -= bet
            msg = f"{pekari_msg}😭 **ハズレ...** **-{bet} pt**"

    return reels, msg

class SlotView(discord.ui.View):
    def __init__(self, user_id, bet):
        super().__init__(timeout=None)
        self.user_id = str(user_id)
        self.bet = bet

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("⚠️ あなたのゲーム画面ではありません！", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🎰 もう一度回す", style=discord.ButtonStyle.success)
    async def spin_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        data = load_data()
        user_info = get_user_data(self.user_id, data)

        if user_info["points"] < self.bet:
            user_info["points"] = INITIAL_POINTS
            save_data(data)
            await interaction.followup.send(f"💰 ポイント不足のため **{INITIAL_POINTS} pt** 補給しました！もう一度ボタンを押してください。", ephemeral=True)
            return

        reels, msg = process_slot_spin(self.user_id, self.bet, data)
        save_data(data)
        await interaction.message.edit(
            content=f"🎰 **スロット**（賭け金: **{self.bet} pt**）\n│ {reels[0]} │ {reels[1]} │ {reels[2]} │\n\n{msg}（所持: **{user_info['points']} pt**）",
            view=self
        )

    @discord.ui.button(label="💰 賭け金を変更", style=discord.ButtonStyle.secondary)
    async def change_bet(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_data()
        user_info = get_user_data(self.user_id, data)
        if user_info.get("pekari_stock", 0) > 0:
            await interaction.response.send_message("⚠️ **ペカり確変中は賭け金を変更できません！**", ephemeral=True)
            return
        await interaction.response.send_modal(ChangeBetModal("slot", self.user_id))

@client.tree.command(name="slot", description="スロットを回します（専用カジノ部屋限定）")
@app_commands.describe(bet="賭けるポイント数")
async def slot(interaction: discord.Interaction, bet: int):
    if not is_casino_room(interaction.channel):
        await interaction.response.send_message("⚠️ カジノゲームは専用部屋の中でのみ遊べます！", ephemeral=True)
        return
    await interaction.response.defer()
    data = load_data()
    uid = str(interaction.user.id)
    user_info = get_user_data(uid, data)

    if user_info["points"] < bet:
        user_info["points"] = INITIAL_POINTS
        save_data(data)
        await interaction.followup.send(f"💰 ポイント不足のため **{INITIAL_POINTS} pt** 補給しました！もう一度 `/slot` を実行してください。", ephemeral=True)
        return

    if bet <= 0:
        await interaction.followup.send("⚠️ 1pt以上を指定してください。", ephemeral=True)
        return

    reels, msg = process_slot_spin(uid, bet, data)
    save_data(data)
    view = SlotView(uid, bet)
    await interaction.followup.send(
        f"🎰 **スロット**（賭け金: **{bet} pt**）\n│ {reels[0]} │ {reels[1]} │ {reels[2]} │\n\n{msg}（所持: **{user_info['points']} pt**）",
        view=view
    )

# ==========================================
# 2. ブラックジャック機能
# ==========================================
def deal_card():
    return random.choice([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10])

def calculate_score(hand):
    score = sum(hand)
    if 1 in hand and score + 10 <= 21:
        score += 10
    return score

class BJPlayAgainView(discord.ui.View):
    def __init__(self, user_id, bet):
        super().__init__(timeout=None)
        self.user_id = str(user_id)
        self.bet = bet

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("⚠️ あなたのゲームではありません！", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🔄 同じ賭け金で遊ぶ", style=discord.ButtonStyle.primary)
    async def play_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        data = load_data()
        user_info = get_user_data(self.user_id, data)

        if user_info["points"] < self.bet:
            user_info["points"] = INITIAL_POINTS
            save_data(data)
            await interaction.followup.send(f"💰 ポイント不足のため **{INITIAL_POINTS} pt** 補給しました！もう一度押してください。", ephemeral=True)
            return

        p_hand, d_hand = [deal_card(), deal_card()], [deal_card(), deal_card()]
        view = BlackjackView(self.user_id, self.bet, p_hand, d_hand)
        await interaction.message.edit(
            content=f"🎮 **ブラックジャック開始**（賭け金: **{self.bet} pt**）\n**手札:** {p_hand} ({calculate_score(p_hand)})\n**ディーラー:** [{d_hand[0]}]",
            view=view
        )

    @discord.ui.button(label="💰 賭け金を変更", style=discord.ButtonStyle.secondary)
    async def change_bet(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ChangeBetModal("bj", self.user_id))

class BlackjackView(discord.ui.View):
    def __init__(self, user_id, bet, player_hand, dealer_hand):
        super().__init__(timeout=None)
        self.user_id = str(user_id)
        self.bet = bet
        self.player_hand = player_hand
        self.dealer_hand = dealer_hand

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("⚠️ あなたのゲームではありません！", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="HIT (引く)", style=discord.ButtonStyle.primary)
    async def hit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.player_hand.append(deal_card())
        p_score = calculate_score(self.player_hand)

        if p_score > 21:
            data = load_data()
            user_info = get_user_data(self.user_id, data)
            user_info["points"] -= self.bet
            save_data(data)
            again_view = BJPlayAgainView(self.user_id, self.bet)
            await interaction.message.edit(
                content=f"💥 **バースト！**\n**手札:** {self.player_hand} (合計: {p_score})\n**-{self.bet} pt**（残り: **{user_info['points']} pt**）",
                view=again_view
            )
            self.stop()
        else:
            await interaction.message.edit(
                content=f"🎮 **ブラックジャック**（賭け金: **{self.bet} pt**）\n**手札:** {self.player_hand} (合計: {p_score})\n**ディーラー:** [{self.dealer_hand[0]}]\n👉 ボタンを押してください。",
                view=self
            )

    @discord.ui.button(label="STAND (勝負)", style=discord.ButtonStyle.success)
    async def stand_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        p_score = calculate_score(self.player_hand)
        d_score = calculate_score(self.dealer_hand)

        while d_score < 17:
            self.dealer_hand.append(deal_card())
            d_score = calculate_score(self.dealer_hand)

        data = load_data()
        user_info = get_user_data(self.user_id, data)

        if d_score > 21 or p_score > d_score:
            payout = int(self.bet * 2.5)
            profit = payout - self.bet
            user_info["points"] += profit
            res = f"🎉 **勝利！** 賭け金の2.5倍（**{payout} pt**）を獲得！（純増: **+{profit} pt** / 現在: **{user_info['points']} pt**）"
        elif p_score < d_score:
            user_info["points"] -= self.bet
            res = f"😭 **敗北...** **-{self.bet} pt**（残り: **{user_info['points']} pt**）"
        else:
            res = f"🤝 **引き分け！** ポイントの変動はありません。（現在: **{user_info['points']} pt**）"

        save_data(data)
        again_view = BJPlayAgainView(self.user_id, self.bet)
        await interaction.message.edit(
            content=f"🏁 **結果**\n**あなた:** {self.player_hand} ({p_score})\n**ディーラー:** {self.dealer_hand} ({d_score})\n\n{res}",
            view=again_view
        )
        self.stop()

@client.tree.command(name="bj", description="ブラックジャックをプレイします（専用カジノ部屋限定）")
@app_commands.describe(bet="賭けるポイント数")
async def bj(interaction: discord.Interaction, bet: int):
    if not is_casino_room(interaction.channel):
        await interaction.response.send_message("⚠️ カジノゲームは専用部屋の中でのみ遊べます！", ephemeral=True)
        return
    await interaction.response.defer()
    data = load_data()
    uid = str(interaction.user.id)
    user_info = get_user_data(uid, data)

    if user_info["points"] < bet:
        user_info["points"] = INITIAL_POINTS
        save_data(data)
        await interaction.followup.send(f"💰 ポイント不足のため **{INITIAL_POINTS} pt** 補給しました！もう一度 `/bj` を実行してください。", ephemeral=True)
        return

    if bet <= 0:
        await interaction.followup.send("⚠️ 1pt以上を指定してください。", ephemeral=True)
        return

    p_hand, d_hand = [deal_card(), deal_card()], [deal_card(), deal_card()]
    view = BlackjackView(uid, bet, p_hand, d_hand)
    await interaction.followup.send(
        f"🎮 **ブラックジャック開始**（賭け金: **{bet} pt**）\n**手札:** {p_hand} ({calculate_score(p_hand)})\n**ディーラー:** [{d_hand[0]}]",
        view=view
    )

# ==========================================
# 3. じゃんけん機能
# ==========================================
class JankenView(discord.ui.View):
    def __init__(self, user_id, bet):
        super().__init__(timeout=None)
        self.user_id = str(user_id)
        self.bet = bet

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("⚠️ あなたのゲーム画面ではありません！", ephemeral=True)
            return False
        return True

    async def play(self, interaction: discord.Interaction, player_choice: str):
        await interaction.response.defer()
        data = load_data()
        user_info = get_user_data(self.user_id, data)

        if user_info["points"] < self.bet:
            user_info["points"] = INITIAL_POINTS
            save_data(data)
            await interaction.followup.send(f"💰 ポイント不足のため **{INITIAL_POINTS} pt** 補給しました！もう一度試してください。", ephemeral=True)
            return

        bot_choice = random.choice(["グー", "チョキ", "パー"])

        if player_choice == bot_choice:
            res = f"🤝 **引き分け！** （所持: **{user_info['points']} pt**）"
        elif (player_choice == "グー" and bot_choice == "チョキ") or \
             (player_choice == "チョキ" and bot_choice == "パー") or \
             (player_choice == "パー" and bot_choice == "グー"):
            payout = int(self.bet * 2.5)
            profit = payout - self.bet
            user_info["points"] += profit
            res = f"🎉 **勝ち！** **+{profit} pt**！（所持: **{user_info['points']} pt**）"
        else:
            user_info["points"] -= self.bet
            res = f"😭 **負け...** **-{self.bet} pt**（残り: **{user_info['points']} pt**）"

        save_data(data)
        await interaction.message.edit(
            content=f"✊✌️✋ **じゃんけん**（賭け金: **{self.bet} pt**）\nあなた: **{player_choice}** vs Bot: **{bot_choice}**\n\n{res}",
            view=self
        )

    @discord.ui.button(label="✊ グー", style=discord.ButtonStyle.primary)
    async def rock(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.play(interaction, "グー")

    @discord.ui.button(label="✌️ チョキ", style=discord.ButtonStyle.success)
    async def scissors(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.play(interaction, "チョキ")

    @discord.ui.button(label="✋ パー", style=discord.ButtonStyle.danger)
    async def paper(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.play(interaction, "パー")

    @discord.ui.button(label="💰 賭け金を変更", style=discord.ButtonStyle.secondary)
    async def change_bet(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ChangeBetModal("janken", self.user_id))

@client.tree.command(name="janken", description="じゃんけんをします（専用カジノ部屋限定）")
@app_commands.describe(bet="賭けるポイント数")
async def janken(interaction: discord.Interaction, bet: int):
    if not is_casino_room(interaction.channel):
        await interaction.response.send_message("⚠️ カジノゲームは専用部屋の中でのみ遊べます！", ephemeral=True)
        return
    await interaction.response.defer()
    data = load_data()
    uid = str(interaction.user.id)
    user_info = get_user_data(uid, data)

    if user_info["points"] < bet:
        user_info["points"] = INITIAL_POINTS
        save_data(data)
        await interaction.followup.send(f"💰 ポイント不足のため **{INITIAL_POINTS} pt** 補給しました！もう一度 `/janken` を実行してください。", ephemeral=True)
        return

    if bet <= 0:
        await interaction.followup.send("⚠️ 1pt以上を指定してください。", ephemeral=True)
        return

    view = JankenView(uid, bet)
    await interaction.followup.send(f"✊✌️✋ **じゃんけん開始**（賭け金: **{bet} pt**）\n手を選んでください！", view=view)

# ==========================================
# 4. 5000pt 高額ガチャ
# ==========================================
GACHA_COST = 5000
GACHA_ITEMS = [
    ("🌈 UR: 神々の祝福（超絶特大ヒット！）", 500000, 1),
    ("✨ SSR: 伝説の秘宝（超大ヒット！）", 100000, 5),
    ("🌟 SR: 黄金の塊（大ヒット）", 30000, 9),
    ("💎 R: 宝石の袋（中ヒット）", 15000, 18),
    ("🎁 N: ささやかなお小遣い（小ヒット）", 7000, 20),
    ("☘️ N: トントン（元取り）", 5000, 20),
    ("💸 N: ポケットの穴（ちょっと減少）", 3000, 30),
    ("🍂 N: スリ被害（半分没収）", 1000, 20),
    ("💀 N: 一文無し体験（スカ）", 0, 10),
    ("💣 E: 大爆発（大損・完全無）", -10000, 4)
]

def draw_gacha():
    items = GACHA_ITEMS
    weights = [item[2] for item in items]
    selected = random.choices(items, weights=weights, k=1)[0]
    return selected[0], selected[1]

class GachaView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = str(user_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("⚠️ あなたのガチャ画面ではありません！", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🎰 もう一回ガチャを引く (5000pt)", style=discord.ButtonStyle.primary)
    async def spin_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        data = load_data()
        user_info = get_user_data(self.user_id, data)

        if user_info["points"] < GACHA_COST:
            await interaction.followup.send(f"❌ ポイントが足りません！（必要: {GACHA_COST} pt / 所持: {user_info['points']} pt）", ephemeral=True)
            return

        user_info["points"] -= GACHA_COST
        item_name, delta_pts = draw_gacha()
        user_info["points"] += delta_pts
        save_data(data)

        embed = discord.Embed(
            title="🎰 5000pt プレミアムガチャ結果",
            description=f"獲得: **{item_name}**\n\nポイント変動: **{delta_pts - GACHA_COST:+} pt**\n現在の所持ポイント: **{user_info['points']} pt**",
            color=0xffd700 if delta_pts >= GACHA_COST else 0xff0000
        )
        await interaction.message.edit(embed=embed, view=self)

@client.tree.command(name="gacha", description="5000ptで一発逆転ガチャを回します（専用カジノ部屋限定）")
async def gacha(interaction: discord.Interaction):
    if not is_casino_room(interaction.channel):
        await interaction.response.send_message("⚠️ カジノゲームは専用部屋の中でのみ遊べます！", ephemeral=True)
        return
    await interaction.response.defer()
    data = load_data()
    uid = str(interaction.user.id)
    user_info = get_user_data(uid, data)

    if user_info["points"] < GACHA_COST:
        await interaction.followup.send(f"⚠️ ポイントが足りません！（必要: **{GACHA_COST} pt** / 所持: **{user_info['points']} pt**）", ephemeral=True)
        return

    user_info["points"] -= GACHA_COST
    item_name, delta_pts = draw_gacha()
    user_info["points"] += delta_pts
    save_data(data)

    embed = discord.Embed(
        title="🎰 5000pt プレミアムガチャ結果",
        description=f"description=獲得: **{item_name}**\n\nポイント変動: **{delta_pts - GACHA_COST:+} pt**\n現在の所持ポイント: **{user_info['points']} pt**",
        color=0xffd700 if delta_pts >= GACHA_COST else 0xff0000
    )
    view = GachaView(uid)
    await interaction.followup.send(embed=embed, view=view)

# ==========================================
# 5. 深海ダイブ機能（新追加）
# ==========================================
class DiveView(discord.ui.View):
    def __init__(self, user_id, bet, depth=0, oxygen=100):
        super().__init__(timeout=None)
        self.user_id = str(user_id)
        self.bet = bet
        self.depth = depth
        self.oxygen = oxygen

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("⚠️ あなたのダイブ画面ではありません！", ephemeral=True)
            return False
        return True

    def get_multiplier(self, depth):
        if depth >= 5000: return 30.0
        elif depth >= 3000: return 10.0
        elif depth >= 2000: return 5.0
        elif depth >= 1000: return 2.5
        elif depth >= 500: return 1.5
        elif depth >= 100: return 1.1
        return 1.0

    @discord.ui.button(label="⬇️ さらに潜る (ダイブ)", style=discord.ButtonStyle.primary)
    async def dive_deeper(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        # 深度が進むごとに深く（+300m〜+700m）
        add_depth = random.randint(300, 700)
        self.depth += add_depth

        # 酸素消費（深いほど多く消費: 15〜35）
        oxy_loss = random.randint(15, 35) + int(self.depth / 500) * 3
        self.oxygen -= oxy_loss

        # 酸素切れ または 故障・深海の裂け目（確率判定）
        if self.oxygen <= 0:
            data = load_data()
            user_info = get_user_data(self.user_id, data)
            user_info["points"] -= self.bet
            save_data(data)
            self.stop()
            await interaction.message.edit(
                content=f"💀 **酸素が尽きて意識を失いました...（深度: {self.depth}m）**\n**-{self.bet} pt**（所持: **{user_info['points']} pt**）",
                view=None
            )
            return

        # ランダムイベント抽選
        # 深いほど故障率・怪物率アップ
        hazard_chance = 0.15 + (self.depth / 15000)
        roll = random.random()

        if roll < hazard_chance:
            # トラブル発生
            event_type = random.choice(["fault", "monster", "crack"])
            if event_type == "fault":
                data = load_data()
                user_info = get_user_data(self.user_id, data)
                user_info["points"] -= self.bet
                save_data(data)
                self.stop()
                await interaction.message.edit(
                    content=f"⚠️ **潜水艇が故障しました！全額ロスト（深度: {self.depth}m）**\n**-{self.bet} pt**（所持: **{user_info['points']} pt**）",
                    view=None
                )
                return
            elif event_type == "monster":
                # 深海怪物：大ダメージ or 没収
                data = load_data()
                user_info = get_user_data(self.user_id, data)
                user_info["points"] -= self.bet
                save_data(data)
                self.stop()
                await interaction.message.edit(
                    content=f"🦑 **深海怪獣に襲われました！強制浮上＆積荷全没収（深度: {self.depth}m）**\n**-{self.bet} pt**（所持: **{user_info['points']} pt**）",
                    view=None
                )
                return
            else:
                # 深海の裂け目 (大当たり or 全損)
                if random.random() < 0.5:
                    mult = self.get_multiplier(self.depth) * 2
                    payout = int(self.bet * mult)
                    profit = payout - self.bet
                    data = load_data()
                    user_info = get_user_data(self.user_id, data)
                    user_info["points"] += profit
                    save_data(data)
                    self.stop()
                    await interaction.message.edit(
                        content=f"🌀 **深海の裂け目で古代文明の宝を発見！大当たり！（深度: {self.depth}m）**\n🎉 **+{payout} pt 獲得！**（所持: **{user_info['points']} pt**）",
                        view=None
                    )
                    return
                else:
                    data = load_data()
                    user_info = get_user_data(self.user_id, data)
                    user_info["points"] -= self.bet
                    save_data(data)
                    self.stop()
                    await interaction.message.edit(
                        content=f"💥 **深海の裂け目で圧壊しました...（深度: {self.depth}m）**\n**-{self.bet} pt**（所持: **{user_info['points']} pt**）",
                        view=None
                    )
                    return

        # 通常進行（お宝ゲット等）
        mult = self.get_multiplier(self.depth)
        events = ["貝 (x1.2)", "宝石 (x2)", "沈没財宝 (x3)", "巨大生物 (x5)"]
        ev = random.choice(events)

        await interaction.message.edit(
            content=(
                f"🌊 **深海ダイブ中...**\n"
                f"・掛け金: **{self.bet} pt**\n"
                f"・現在の深度: **{self.depth} m** （倍率: **×{mult}**）\n"
                f"・残り酸素: **{self.oxygen}**\n"
                f"・直近の発見: **{ev}**\n\n"
                f"さらに深く潜りますか？それとも浮上して配当を確定させますか？"
            ),
            view=self
        )

    @discord.ui.button(label="🚀 浮上して配当を回収 (リターン)", style=discord.ButtonStyle.success)
    async def return_surface(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        mult = self.get_multiplier(self.depth)
        payout = int(self.bet * mult)
        profit = payout - self.bet

        data = load_data()
        user_info = get_user_data(self.user_id, data)
        user_info["points"] += profit
        save_data(data)
        self.stop()

        await interaction.message.edit(
            content=(
                f"🎉 **無事に浮上成功！**\n"
                f"・到達深度: **{self.depth} m**（倍率: **×{mult}**）\n"
                f"・獲得ポイント: **+{payout} pt**（純増: **+{profit} pt**）\n"
                f"・現在の所持: **{user_info['points']} pt**"
            ),
            view=None
        )

@client.tree.command(name="dive", description="深海ダイブギャンブルを開始します（専用カジノ部屋限定）")
@app_commands.describe(bet="賭けるポイント数")
async def dive(interaction: discord.Interaction, bet: int):
    if not is_casino_room(interaction.channel):
        await interaction.response.send_message("⚠️ カジノゲームは専用部屋の中でのみ遊べます！", ephemeral=True)
        return

    await interaction.response.defer()
    data = load_data()
    uid = str(interaction.user.id)
    user_info = get_user_data(uid, data)

    if user_info["points"] < bet:
        user_info["points"] = INITIAL_POINTS
        save_data(data)
        await interaction.followup.send(f"💰 ポイント不足のため **{INITIAL_POINTS} pt** 補給しました！もう一度 `/dive` を実行してください。", ephemeral=True)
        return

    if bet <= 0:
        await interaction.followup.send("⚠️ 1pt以上を指定してください。", ephemeral=True)
        return

    view = DiveView(uid, bet, depth=0, oxygen=100)
    await interaction.followup.send(
        f"🌊 **深海ダイブ開始！**\n"
        f"・掛け金: **{bet} pt**\n"
        f"・現在の深度: **0 m**（倍率: **×1.0**）\n"
        f"・残り酸素: **100**\n\n"
        f"ボタンを押して潜水を始めてください👇",
        view=view
    )

# ==========================================
# 6. おみくじ・ランキング・その他
# ==========================================
@client.tree.command(name="omikuji", description="今日の運勢を占います")
async def omikuji(interaction: discord.Interaction):
    fortunes = ["大吉 🌟", "中吉 🌸", "小吉 ☘️", "吉 ✨", "末吉 🍃", "凶 ☁️"]
    await interaction.response.send_message(f"⛩️ **おみくじ結果:** 【 **{random.choice(fortunes)}** 】")

# ロール付与・チケット等の機能はそのまま保持
class VerifyView(discord.ui.View):
    def __init__(self, role_id: int):
        super().__init__(timeout=None)
        self.role_id = role_id

    @discord.ui.button(label="✅ 認証する", style=discord.ButtonStyle.success, custom_id="verify_button")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = interaction.guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message("⚠️ 設定されたロールが見つかりません。", ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.response.send_message("⚠️ すでに認証済みです！", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"🎉 認証が完了しました！ **{role.name}** を付与しました。", ephemeral=True)

class MultiRoleSelect(discord.ui.Select):
    def __init__(self, roles: list[discord.Role]):
        options = [
            discord.SelectOption(label=role.name, value=str(role.id), description=f"{role.name} の付け外し")
            for role in roles
        ]
        super().__init__(placeholder="付け外ししたいロールを選んでください...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        role_id = int(self.values[0])
        role = interaction.guild.get_role(role_id)
        if not role:
            await interaction.response.send_message("⚠️ ロールが見つかりません。", ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message(f"❌ **{role.name}** を解除しました。", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"✅ **{role.name}** を付与しました！", ephemeral=True)

class MultiRoleView(discord.ui.View):
    def __init__(self, roles: list[discord.Role]):
        super().__init__(timeout=None)
        self.add_item(MultiRoleSelect(roles))

@client.tree.command(name="setup_verify", description="ワンタップで認証できるボタンパネルを設置します")
@app_commands.describe(role="認証時に付与するロール")
@app_commands.checks.has_permissions(administrator=True)
async def setup_verify(interaction: discord.Interaction, role: discord.Role):
    embed = discord.Embed(
        title="🔒 サーバー認証",
        description="下の「✅ 認証する」ボタンを押すと、サーバーの利用権限が付与されます。",
        color=0x2ecc71
    )
    view = VerifyView(role.id)
    await interaction.channel.send(embed=embed, view=view)
    await interaction.response.send_message("✅ 認証パネルを設置しました！", ephemeral=True)

@client.tree.command(name="setup_roles", description="最大10個まで選べるロール付与パネルを設置します")
@app_commands.describe(
    role1="選択肢1", role2="選択肢2", role3="選択肢3", role4="選択肢4", role5="選択肢5",
    role6="選択肢6", role7="選択肢7", role8="選択肢8", role9="選択肢9", role10="選択肢10"
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_roles(
    interaction: discord.Interaction,
    role1: discord.Role,
    role2: discord.Role = None, role3: discord.Role = None, role4: discord.Role = None, role5: discord.Role = None,
    role6: discord.Role = None, role7: discord.Role = None, role8: discord.Role = None, role9: discord.Role = None, role10: discord.Role = None
):
    roles = [r for r in [role1, role2, role3, role4, role5, role6, role7, role8, role9, role10] if r is not None]
    embed = discord.Embed(
        title="🎭 ロール選択パネル",
        description="メニューから取得・解除したいロールを選択してください。",
        color=0x3498db
    )
    view = MultiRoleView(roles)
    await interaction.channel.send(embed=embed, view=view)
    await interaction.response.send_message(f"✅ {len(roles)}個のロールを設定したパネルを設置しました！", ephemeral=True)

class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 チケットを閉じる", style=discord.ButtonStyle.danger, custom_id="close_ticket_button")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔒 チケットを閉じます。5秒後にこのチャンネルを削除します...")
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete()
        except Exception:
            pass

class TicketSetupView(discord.ui.View):
    def __init__(self, target_category: discord.CategoryChannel = None):
        super().__init__(timeout=None)
        self.target_category = target_category

    @discord.ui.button(label="🎫 お問い合わせを作成", style=discord.ButtonStyle.primary, custom_id="create_ticket_button")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user
        ticket_name = f"チケット-{user.name.lower()}"
        existing_channel = discord.utils.get(guild.channels, name=ticket_name)
        if existing_channel:
            await interaction.response.send_message(f"⚠️ すでにあなた専用の問い合わせチャンネルがあります！ 👉 {existing_channel.mention}", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        category = self.target_category if self.target_category is not None else interaction.channel.category
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }
        try:
            channel = await guild.create_text_channel(
                name=ticket_name,
                overwrites=overwrites,
                category=category,
                topic=f"{user.display_name} の問い合わせチケット"
            )
            view = CloseTicketView()
            await channel.send(
                f"🎫 **{user.mention} 様、お問い合わせありがとうございます！**\n"
                f"スタッフが確認するまで少々お待ちください。用事が済んだら下のボタンでチケットを閉じることができます。",
                view=view
            )
            await interaction.followup.send(f"✅ お問い合わせチャンネルを作成しました！ 👉 {channel.mention}", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("⚠️ Botにチャンネル作成・管理権限がありません。", ephemeral=True)

@client.tree.command(name="setup_ticket", description="問い合わせ用のパネルを設置します（管理者限定）")
@app_commands.describe(
    description="パネルに表示する説明文を入力してください",
    category="チケットを作成するカテゴリーを指定します（省略時はこのコマンドを実行した場所と同じカテゴリー）"
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_ticket(interaction: discord.Interaction, description: str, category: discord.CategoryChannel = None):
    embed = discord.Embed(
        title="🎫 お問い合わせ / サポート",
        description=description,
        color=0x3498db
    )
    view = TicketSetupView(target_category=category)
    await interaction.channel.send(embed=embed, view=view)
    await interaction.response.send_message("✅ 問い合わせパネルを設置しました！", ephemeral=True)

@client.event
async def on_ready():
    print(f"ログインしました: {client.user}")
    try:
        synced = await client.tree.sync()
        print(f"{len(synced)}個のコマンドを同期しました！")
    except Exception as e:
        print(f"同期エラー: {e}")

@client.tree.command(name="datasave", description="現在のデータを手動で保存します（管理者限定）")
async def manual_save(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ このコマンドは管理者のみ実行できます。", ephemeral=True)
        return
    try:
        data = load_data()
        save_data(data)
        await interaction.response.send_message(f"💾 データを手動で保存しました！（現在の登録ユーザー数: {len(data)}人）", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ 保存に失敗しました: {e}", ephemeral=True)

# ── ボット起動・サーバー処理 ──
import os
import threading

def run_flask():
    app.run(host="0.0.0.0", port=8000)

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    client.run(os.getenv("DISCORD_TOKEN"))
