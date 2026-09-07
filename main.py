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
intents.members = True

class FullBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.tree.on_error = self.on_app_command_error
        self.bg_task = self.loop.create_task(self.ranking_loop())

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        print("\n❌ エラーが発生しました ❌")
        traceback.print_exception(type(error), error, error.__traceback__)

    async def ranking_loop(self):
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await update_all_ranking_boards(self)
            except Exception as e:
                print(f"⚠️ ランキング更新ループエラー: {e}")
            await asyncio.sleep(60)

client = FullBot()
DATA_FILE = "data.json"
SETTING_FILE = "settings.json"
INITIAL_POINTS = 300

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

def is_casino_room(channel: discord.TextChannel) -> bool:
    return channel.name.startswith("🎰-")

# ==========================================
# 📊 ランキング機能（名前表示対応）
# ==========================================
async def create_ranking_embed(guild: discord.Guild, data: dict, bot) -> discord.Embed:
    sorted_users = sorted(
        data.items(),
        key=lambda item: item[1].get("points", 0) if isinstance(item[1], dict) else 0,
        reverse=True
    )[:10]

    desc = ""
    medals = ["🥇", "🥈", "🥉"]

    if not sorted_users:
        desc = "まだ誰もポイントを持っていません。"
    else:
        for i, (uid_str, info) in enumerate(sorted_users):
            rank_icon = medals[i] if i < 3 else f"`#{i+1}`"
            pts = info.get("points", 0) if isinstance(info, dict) else 0
            
            name = f"ユーザーID: {uid_str}"
            try:
                member = guild.get_member(int(uid_str))
                if member:
                    name = member.display_name
                else:
                    user = await bot.fetch_user(int(uid_str))
                    name = user.name
            except Exception:
                pass

            desc += f"{rank_icon} **{name}** : **{pts:,} pt**\n"

    embed = discord.Embed(
        title="🏆 ポイントランキング（リアルタイム）",
        description=desc,
        color=0xf1c40f
    )
    embed.set_footer(text="1分ごとに自動更新されます")
    return embed

async def update_all_ranking_boards(bot):
    settings = load_settings()
    data = load_data()
    if not settings.get("ranking_channels"):
        return

    for guild_id_str, info in list(settings["ranking_channels"].items()):
        guild = bot.get_guild(int(guild_id_str))
        if not guild:
            continue
        channel = guild.get_channel(info["channel_id"])
        if not channel:
            continue
        message_id = info.get("message_id")
        embed = await create_ranking_embed(guild, data, bot)
        try:
            if message_id:
                msg = await channel.fetch_message(message_id)
                await msg.edit(embed=embed)
            else:
                msg = await channel.send(embed=embed)
                info["message_id"] = msg.id
                save_settings(settings)
        except discord.NotFound:
            msg = await channel.send(embed=embed)
            info["message_id"] = msg.id
            save_settings(settings)
        except Exception as e:
            print(f"⚠️ ランキングボード更新エラー: {e}")

@client.tree.command(name="setup_ranking", description="1分ごとに自動更新されるランキングボードを設置します（管理者限定）")
@app_commands.checks.has_permissions(administrator=True)
async def setup_ranking(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    channel = interaction.channel

    data = load_data()
    embed = await create_ranking_embed(guild, data, client)
    msg = await channel.send(embed=embed)

    settings = load_settings()
    if "ranking_channels" not in settings:
        settings["ranking_channels"] = {}

    settings["ranking_channels"][str(guild.id)] = {
        "channel_id": channel.id,
        "message_id": msg.id
    }
    save_settings(settings)
    await interaction.followup.send(f"✅ ランキングボードを設置しました！", ephemeral=True)

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
async def casino(interaction: discord.Interaction, category: discord.CategoryChannel = None):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    user = interaction.user

    room_name = f"🎰-{user.name.lower()}-カジノ"
    existing_channel = discord.utils.get(guild.channels, name=room_name)

    if existing_channel:
        await interaction.followup.send(f"⚠️ すでに専用部屋があります！ 👉 {existing_channel.mention}", ephemeral=True)
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
            f"ここで `/slot` `/bj` `/janken` `/gacha` `/dive` `/haikou` が遊べます！",
            view=view,
            silent=True
        )
        await interaction.followup.send(f"✅ 専用部屋を作成しました！ 👉 {channel.mention}", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("⚠️ 権限不足で部屋を作れませんでした。", ephemeral=True)

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
            await interaction.followup.send(f"💰 ポイント不足のため **{INITIAL_POINTS} pt** 補給しました！", ephemeral=True)
            return

        if self.game_type == "slot":
            reels, msg = process_slot_spin(self.user_id, new_bet, data)
            save_data(data)
            view = SlotView(self.user_id, new_bet)
            await interaction.message.edit(content=f"🎰 **スロット**（賭け金: **{new_bet} pt**）\n│ {reels[0]} │ {reels[1]} │ {reels[2]} │\n\n{msg}", view=view)
        elif self.game_type == "bj":
            p_hand, d_hand = [deal_card(), deal_card()], [deal_card(), deal_card()]
            view = BlackjackView(self.user_id, new_bet, p_hand, d_hand)
            await interaction.message.edit(content=f"🎮 **ブラックジャック開始**（賭け金: **{new_bet} pt**）\n**手札:** {p_hand}", view=view)
        elif self.game_type == "janken":
            view = JankenView(self.user_id, new_bet)
            await interaction.message.edit(content=f"✊✌️✋ **じゃんけん開始**（賭け金: **{new_bet} pt**）", view=view)
        elif self.game_type == "dive":
            view = DiveView(self.user_id, new_bet, depth=0, oxygen=100)
            await interaction.message.edit(content=f"🌊 **深海ダイブ開始！**（賭け金: **{new_bet} pt**）", view=view)
        elif self.game_type == "haikou":
            view = HaikouView(self.user_id, new_bet, stage=0)
            await interaction.message.edit(content=f"🏫 **呪われた廃校 開始！**（賭け金: **{new_bet} pt**）\n現在: 0段\n確定報酬: 0", view=view)

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
        payout = int(bet * 10)
        user_info["points"] += (payout - bet)
        return reels, f"🔥 **ペカり確変中！** **+{payout} pt**"
    else:
        reels = random.choices(SLOT_SYMBOLS, k=3)
        if reels[0] == reels[1] == reels[2]:
            payout = int(bet * 10)
            user_info["points"] += (payout - bet)
            msg = f"🎉 **3つ揃い！** **+{payout} pt**"
        elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
            payout = int(bet * 2)
            user_info["points"] += (payout - bet)
            msg = f"✨ **2つ揃い！** **+{payout} pt**"
        else:
            user_info["points"] -= bet
            msg = f"😭 **ハズレ...** **-{bet} pt**"
        return reels, msg

class SlotView(discord.ui.View):
    def __init__(self, user_id, bet):
        super().__init__(timeout=None)
        self.user_id = str(user_id)
        self.bet = bet

    @discord.ui.button(label="🎰 もう一度回す", style=discord.ButtonStyle.success)
    async def spin_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        data = load_data()
        user_info = get_user_data(self.user_id, data)
        reels, msg = process_slot_spin(self.user_id, self.bet, data)
        save_data(data)
        await interaction.message.edit(content=f"🎰 **スロット**\n│ {reels[0]} │ {reels[1]} │ {reels[2]} │\n\n{msg}", view=self)

    @discord.ui.button(label="💰 賭け金を変更", style=discord.ButtonStyle.secondary)
    async def change_bet(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ChangeBetModal("slot", self.user_id))

@client.tree.command(name="slot", description="スロット（専用カジノ部屋限定）")
async def slot(interaction: discord.Interaction, bet: int):
    if not is_casino_room(interaction.channel):
        await interaction.response.send_message("⚠️ 専用部屋でのみ遊べます！", ephemeral=True)
        return
    await interaction.response.defer()
    data = load_data()
    uid = str(interaction.user.id)
    user_info = get_user_data(uid, data)
    reels, msg = process_slot_spin(uid, bet, data)
    save_data(data)
    await interaction.followup.send(content=f"🎰 **スロット**\n│ {reels[0]} │ {reels[1]} │ {reels[2]} │\n\n{msg}", view=SlotView(uid, bet))

# ==========================================
# 2. ブラックジャック
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

    @discord.ui.button(label="🔄 同じ賭け金で遊ぶ", style=discord.ButtonStyle.primary)
    async def play_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        p_hand, d_hand = [deal_card(), deal_card()], [deal_card(), deal_card()]
        await interaction.message.edit(content=f"🎮 **BJ開始**\n**手札:** {p_hand}", view=BlackjackView(self.user_id, self.bet, p_hand, d_hand))

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

    @discord.ui.button(label="HIT", style=discord.ButtonStyle.primary)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.player_hand.append(deal_card())
        p_score = calculate_score(self.player_hand)
        if p_score > 21:
            data = load_data()
            get_user_data(self.user_id, data)["points"] -= self.bet
            save_data(data)
            await interaction.message.edit(content=f"💥 バースト！ **-{self.bet} pt**", view=BJPlayAgainView(self.user_id, self.bet))
        else:
            await interaction.message.edit(content=f"**手札:** {self.player_hand} ({p_score})", view=self)

    @discord.ui.button(label="STAND", style=discord.ButtonStyle.success)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        p_score = calculate_score(self.player_hand)
        d_score = calculate_score(self.dealer_hand)
        data = load_data()
        user_info = get_user_data(self.user_id, data)
        if p_score > d_score or d_score > 21:
            payout = int(self.bet * 2)
            user_info["points"] += (payout - self.bet)
            res = f"🎉 勝利！ **+{payout} pt**"
        else:
            user_info["points"] -= self.bet
            res = f"😭 敗北... **-{self.bet} pt**"
        save_data(data)
        await interaction.message.edit(content=res, view=BJPlayAgainView(self.user_id, self.bet))

@client.tree.command(name="bj", description="ブラックジャック（専用カジノ部屋限定）")
async def bj(interaction: discord.Interaction, bet: int):
    if not is_casino_room(interaction.channel):
        await interaction.response.send_message("⚠️ 専用部屋でのみ遊べます！", ephemeral=True)
        return
    await interaction.response.defer()
    p_hand, d_hand = [deal_card(), deal_card()], [deal_card(), deal_card()]
    await interaction.followup.send(content=f"🎮 **BJ開始**\n**手札:** {p_hand}", view=BlackjackView(str(interaction.user.id), bet, p_hand, d_hand))

# ==========================================
# 3. じゃんけん
# ==========================================
class JankenView(discord.ui.View):
    def __init__(self, user_id, bet):
        super().__init__(timeout=None)
        self.user_id = str(user_id)
        self.bet = bet

    async def play(self, interaction, choice):
        await interaction.response.defer()
        bot_choice = random.choice(["グー", "チョキ", "パー"])
        data = load_data()
        user_info = get_user_data(self.user_id, data)
        if choice == bot_choice:
            res = "引き分け"
        elif (choice == "グー" and bot_choice == "チョキ") or (choice == "チョキ" and bot_choice == "パー") or (choice == "パー" and bot_choice == "グー"):
            user_info["points"] += self.bet
            res = f"勝ち！ **+{self.bet} pt**"
        else:
            user_info["points"] -= self.bet
            res = f"負け... **-{self.bet} pt**"
        save_data(data)
        await interaction.message.edit(content=f"あなた: {choice} vs Bot: {bot_choice}\n{res}", view=self)

    @discord.ui.button(label="✊ グー", style=discord.ButtonStyle.primary)
    async def r(self, interaction, button): await self.play(interaction, "グー")
    @discord.ui.button(label="✌️ チョキ", style=discord.ButtonStyle.success)
    async def s(self, interaction, button): await self.play(interaction, "チョキ")
    @discord.ui.button(label="✋ パー", style=discord.ButtonStyle.danger)
    async def p(self, interaction, button): await self.play(interaction, "パー")
    @discord.ui.button(label="💰 賭け金変更", style=discord.ButtonStyle.secondary)
    async def cb(self, interaction, button): await interaction.response.send_modal(ChangeBetModal("janken", self.user_id))

@client.tree.command(name="janken", description="じゃんけん（専用カジノ部屋限定）")
async def janken(interaction: discord.Interaction, bet: int):
    if not is_casino_room(interaction.channel):
        await interaction.response.send_message("⚠️ 専用部屋でのみ遊べます！", ephemeral=True)
        return
    await interaction.response.defer()
    await interaction.followup.send(content="✊✌️✋ じゃんけん開始！", view=JankenView(str(interaction.user.id), bet))

# ==========================================
# 4. ガチャ
# ==========================================
@client.tree.command(name="gacha", description="5000ptガチャ（専用カジノ部屋限定）")
async def gacha(interaction: discord.Interaction):
    if not is_casino_room(interaction.channel):
        await interaction.response.send_message("⚠️ 専用部屋でのみ遊べます！", ephemeral=True)
        return
    await interaction.response.defer()
    data = load_data()
    user_info = get_user_data(str(interaction.user.id), data)
    if user_info["points"] < 5000:
        await interaction.followup.send("⚠️ 5000pt必要です。", ephemeral=True)
        return
    user_info["points"] -= 5000
    delta = random.choice([100000, 30000, 5000, 0, -5000])
    user_info["points"] += delta
    save_data(data)
    await interaction.followup.send(content=f"🎰 ガチャ結果！ 変動: {delta:+} pt（所持: {user_info['points']} pt）")

# ==========================================
# 5. 深海ダイブ
# ==========================================
class DivePlayAgainView(discord.ui.View):
    def __init__(self, user_id, bet):
        super().__init__(timeout=None)
        self.user_id = str(user_id)
        self.bet = bet

    @discord.ui.button(label="🔄 同じ賭け金で潜る", style=discord.ButtonStyle.primary)
    async def play_again(self, interaction, button):
        await interaction.message.edit(content="🌊 ダイブ開始！", view=DiveView(self.user_id, self.bet))

    @discord.ui.button(label="💰 賭け金変更", style=discord.ButtonStyle.secondary)
    async def change_bet(self, interaction, button):
        await interaction.response.send_modal(ChangeBetModal("dive", self.user_id))

class DiveView(discord.ui.View):
    def __init__(self, user_id, bet, depth=0, oxygen=100):
        super().__init__(timeout=None)
        self.user_id = str(user_id)
        self.bet = bet
        self.depth = depth
        self.oxygen = oxygen

    @discord.ui.button(label="⬇️ さらに潜る", style=discord.ButtonStyle.primary)
    async def dive(self, interaction, button):
        await interaction.response.defer()
        self.depth += random.randint(300, 600)
        self.oxygen -= 25
        if self.oxygen <= 0 or random.random() < 0.2:
            data = load_data()
            get_user_data(self.user_id, data)["points"] -= self.bet
            save_data(data)
            await interaction.message.edit(content=f"💀 酸素切れまたは事故でロスト（深度:{self.depth}m） **-{self.bet} pt**", view=DivePlayAgainView(self.user_id, self.bet))
        else:
            await interaction.message.edit(content=f"🌊 深度: {self.depth}m / 残り酸素: {self.oxygen}", view=self)

    @discord.ui.button(label="🚀 浮上する", style=discord.ButtonStyle.success)
    async def surface(self, interaction, button):
        await interaction.response.defer()
        payout = int(self.bet * (1.0 + self.depth / 1000))
        data = load_data()
        user_info = get_user_data(self.user_id, data)
        user_info["points"] += (payout - self.bet)
        save_data(data)
        await interaction.message.edit(content=f"🎉 浮上成功！ **+{payout} pt** 獲得！", view=DivePlayAgainView(self.user_id, self.bet))

@client.tree.command(name="dive", description="深海ダイブ（専用カジノ部屋限定）")
async def dive(interaction: discord.Interaction, bet: int):
    if not is_casino_room(interaction.channel):
        await interaction.response.send_message("⚠️ 専用部屋でのみ遊べます！", ephemeral=True)
        return
    await interaction.response.defer()
    await interaction.followup.send(content="🌊 深海ダイブ開始！", view=DiveView(str(interaction.user.id), bet))

# ==========================================
# 6. 🏫 新機能：呪われた廃校ゲーム (/haikou)
# ==========================================
class HaikouPlayAgainView(discord.ui.View):
    def __init__(self, user_id, bet):
        super().__init__(timeout=None)
        self.user_id = str(user_id)
        self.bet = bet

    @discord.ui.button(label="🔄 もう1段登る（再挑戦）", style=discord.ButtonStyle.primary)
    async def play_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        data = load_data()
        user_info = get_user_data(self.user_id, data)
        if user_info["points"] < self.bet:
            user_info["points"] = INITIAL_POINTS
            save_data(data)
        await interaction.message.edit(
            content=f"🏫 **呪われた廃校**（賭け金: **{self.bet} pt**）\n現在: **0段**\n確定報酬: **0 pt**\n次の階段の危険度: ★☆☆☆☆",
            view=HaikouView(self.user_id, self.bet, stage=0)
        )

    @discord.ui.button(label="💰 賭け金を変更", style=discord.ButtonStyle.secondary)
    async def change_bet(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ChangeBetModal("haikou", self.user_id))

class HaikouView(discord.ui.View):
    def __init__(self, user_id, bet, stage=0):
        super().__init__(timeout=None)
        self.user_id = str(user_id)
        self.bet = bet
        self.stage = stage

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("⚠️ あなたのゲーム画面ではありません！", ephemeral=True)
            return False
        return True

    def get_risk_stars(self, stage):
        if stage >= 40: return "★★★★★"
        elif stage >= 30: return "★★★★☆"
        elif stage >= 20: return "★★★☆☆"
        elif stage >= 10: return "★★☆☆☆"
        return "★☆☆☆☆"

    @discord.ui.button(label="⬆️ もう1段登る → 報酬UP", style=discord.ButtonStyle.primary)
    async def climb(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.stage += 1
        
        # 危険度（階層が上がるごとにハズレ・即死率アップ）
        danger_rate = 0.10 + (self.stage * 0.015)
        
        # 途中ランダムイベントの演出用テキスト
        events = ["👻 幽霊", "🩸 血文字", "🔔 鳴るチャイム", "👣 足音", "🚪 勝手に開く教室"]
        current_event = random.choice(events)

        if random.random() < danger_rate:
            # ゲームオーバー（即死・全ロス）
            data = load_data()
            user_info = get_user_data(self.user_id, data)
            user_info["points"] -= self.bet
            save_data(data)
            self.stop()

            await interaction.message.edit(
                content=(
                    f"🏫 **呪われた廃校**（現在: **{self.stage}段**）\n"
                    f"💀 **即死イベント発生！突如現れた怪異に飲み込まれた...**\n"
                    f"・発生した怪異: {current_event}\n"
                    f"・結果: **-{self.bet} pt**（所持: **{user_info['points']} pt**）"
                ),
                view=HaikouPlayAgainView(self.user_id, self.bet)
            )
            return

        # 報酬計算（1段ごとに倍率アップ）
        multiplier = 1.0 + (self.stage * 0.3)
        reward = int(self.bet * multiplier)
        stars = self.get_risk_stars(self.stage)

        await interaction.message.edit(
            content=(
                f"🏫 **呪われた廃校**\n\n"
                f"現在: **{self.stage}段**\n"
                f"💰 確定報酬: **{reward:,} pt**\n"
                f"⚠️ 次の階段の危険度: {stars}\n\n"
                f"直近の気配: {current_event}\n\n"
                f"さらに登りますか？それとも引き返しますか？"
            ),
            view=self
        )

    @discord.ui.button(label="🏃 帰る", style=discord.ButtonStyle.success)
    async def escape(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        multiplier = 1.0 + (self.stage * 0.3)
        payout = int(self.bet * multiplier)
        profit = payout - self.bet

        data = load_data()
        user_info = get_user_data(self.user_id, data)
        user_info["points"] += profit
        save_data(data)
        self.stop()

        await interaction.message.edit(
            content=(
                f"🏫 **無事に生還しました！**\n"
                f"・到達段数: **{self.stage}段**\n"
                f"・獲得報酬: **+{payout:,} pt**（純増: **+{profit:,} pt**）\n"
                f"・現在の所持: **{user_info['points']:,} pt**"
            ),
            view=HaikouPlayAgainView(self.user_id, self.bet)
        )

@client.tree.command(name="haikou", description="呪われた廃校を探索するハイリスク・ハイリターンゲーム（専用カジノ部屋限定）")
@app_commands.describe(bet="賭けるポイント数")
async def haikou(interaction: discord.Interaction, bet: int):
    if not is_casino_room(interaction.channel):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send("⚠️ カジノゲームは専用部屋の中でのみ遊べます！", ephemeral=True)
        return

    await interaction.response.defer()
    data = load_data()
    uid = str(interaction.user.id)
    user_info = get_user_data(uid, data)

    if user_info["points"] < bet:
        user_info["points"] = INITIAL_POINTS
        save_data(data)
        await interaction.followup.send(f"💰 ポイント不足のため **{INITIAL_POINTS} pt** 補給しました！もう一度 `/haikou` を実行してください。", ephemeral=True)
        return

    if bet <= 0:
        await interaction.followup.send("⚠️ 1pt以上を指定してください。", ephemeral=True)
        return

    view = HaikouView(uid, bet, stage=0)
    await interaction.followup.send(
        content=(
            f"🏫 **呪われた廃校へ足を踏み入れた...**（賭け金: **{bet} pt**）\n"
            f"現在: **0段**\n"
            f"💰 確定報酬: **0 pt**\n"
            f"⚠️ 次の階段の危険度: ★☆☆☆☆\n\n"
            f"ボタンを押して不気味な校舎を登ってください👇"
        ),
        view=view
    )

# ==========================================
# その他コマンド (おみくじ・認証・チケット等)
# ==========================================
@client.tree.command(name="omikuji", description="今日の運勢を占います")
async def omikuji(interaction: discord.Interaction):
    fortunes = ["大吉 🌟", "中吉 🌸", "小吉 ☘️", "吉 ✨", "末吉 🍃", "凶 ☁️"]
    await interaction.response.send_message(f"⛩️ **おみくじ結果:** 【 **{random.choice(fortunes)}** 】")

@client.event
async def on_ready():
    print(f"ログインしました: {client.user}")
    try:
        synced = await client.tree.sync()
        print(f"{len(synced)}個のコマンドを同期しました！")
    except Exception as e:
        print(f"同期エラー: {e}")

@client.tree.command(name="datasave", description="データを手動保存（管理者限定）")
async def manual_save(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ 管理者のみ実行可能です。", ephemeral=True)
        return
    data = load_data()
    save_data(data)
    await interaction.response.send_message(f"💾 手動保存しました！（登録数: {len(data)}人）", ephemeral=True)

# ── Flask & Bot起動 ──
import threading
def run_flask():
    app.run(host="0.0.0.0", port=8000)

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    client.run(os.getenv("DISCORD_TOKEN"))
