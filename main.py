import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput
import os
import json
import asyncio
from datetime import datetime, timedelta, timezone
import logging
from dotenv import load_dotenv

load_dotenv()

# -------------------- CONFIG & DATA --------------------
CONFIG_PATH = "config.json"
DATA_PATH = "user.json"
KEY_FILE = "key.txt"
REDEEMED_FILE = "redeemed.txt"
LOG_CHANNEL_ID = None
TRACKED_VCS = set()
PAUSED = False
DATA_LOCK = asyncio.Lock()

DEFAULT_CONFIG = {
    "prefix": "!",
    "log_channel_id": "",
    "tracked_vcs": [],
    "points_normal": 3,
    "points_stream": 5,
    "max_points_cap": 300,
    "key_cost": 90,
    "daily_limit": 2,
    "min_account_age_days": 14,
    "panel_image_url": "",
    "panel_thumbnail_url": ""
}

def load_config():
    global CONFIG, LOG_CHANNEL_ID, TRACKED_VCS
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
    with open(CONFIG_PATH, "r") as f:
        CONFIG = json.load(f)
    LOG_CHANNEL_ID = CONFIG.get("log_channel_id")
    TRACKED_VCS = set(CONFIG.get("tracked_vcs", []))

load_config()

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:    raise ValueError("BOT_TOKEN not found in .env file")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix=CONFIG["prefix"], intents=intents)

# -------------------- DATA MANAGEMENT --------------------
users_data = {}

def load_users():
    global users_data
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, "r") as f:
            users_data = json.load(f)

def save_users():
    with open(DATA_PATH, "w") as f:
        json.dump(users_data, f, indent=4)

def get_user_data(member_id):
    mid = str(member_id)
    if mid not in users_data:
        users_data[mid] = {
            "available_points": 0,
            "total_earned": 0,
            "redeemed_count": 0,
            "daily_redeems": 0,
            "last_redeem_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "blacklisted": False,
            "whitelisted": False
        }
    return users_data[mid]

def save_user_data(member_id, data):
    users_data[str(member_id)] = data
    save_users()

def read_keys():
    if not os.path.exists(KEY_FILE):
        open(KEY_FILE, "w").close()
    with open(KEY_FILE, "r") as f:
        keys = [k.strip() for k in f.readlines() if k.strip()]
    return keys

def write_keys(keys):
    with open(KEY_FILE, "w") as f:
        f.write("\n".join(keys) + ("\n" if keys else ""))
def log_redeemed(key, user_id):
    with open(REDEEMED_FILE, "a") as f:
        f.write(f"{key} | {user_id} | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}\n")

async def send_log(embed: discord.Embed):
    if LOG_CHANNEL_ID:
        channel = bot.get_channel(int(LOG_CHANNEL_ID))
        if channel:
            try:
                await channel.send(embed=embed)
            except discord.Forbidden:
                pass

# -------------------- BOT EVENTS --------------------
@bot.event
async def on_ready():
    load_users()
    print(f"Logged in as {bot.user.name}")
    points_loop.start()

@bot.event
async def on_member_join(member):
    data = get_user_data(member.id)
    age_days = (datetime.now(timezone.utc) - member.created_at).days
    if age_days < CONFIG["min_account_age_days"] and not data.get("whitelisted", False):
        data["blacklisted"] = True
        save_user_data(member.id, data)
        log_embed = discord.Embed(title="Auto Blacklist", description=f"User {member.name} added to blacklist due to new account (<14 days).", color=0xFF4444)
        await send_log(log_embed)

# -------------------- COMMANDS --------------------
@bot.command(name="panel")
async def public_panel(ctx):
    if not ctx.author.guild_permissions.administrator:
        await ctx.send(embed=discord.Embed(title="Access Denied", description="Sirf Admins is command ko use kar sakte hain.", color=0xFF4444))
        return
    
    embed = create_public_panel_embed()
    view = PublicPanelView()
    await ctx.send(embed=embed, view=view)

@bot.command(name="status")
async def bot_status(ctx):
    keys = read_keys()
    embed = discord.Embed(title="Bot Status", description="Full System Status", color=0x4A90E2, timestamp=datetime.now(timezone.utc))
    embed.set_footer(text="Power By SUBHAN")
    embed.add_field(name="State", value="Paused" if PAUSED else "Active")
    embed.add_field(name="Available Keys", value=str(len(keys)))
    embed.add_field(name="Tracked VCs", value=str(len(TRACKED_VCS)))    embed.add_field(name="Database Size", value=f"{len(users_data)} Users")
    await ctx.send(embed=embed)

@bot.command(name="admin")
async def admin_panel(ctx):
    if not ctx.author.guild_permissions.administrator:
        return
    embed = discord.Embed(title="Admin Control Panel", description="Manage bot functions securely.", color=0x2C2F33, timestamp=datetime.now(timezone.utc))
    embed.set_footer(text="Power By SUBHAN")
    view = AdminView()
    await ctx.send(embed=embed, view=view)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    embed = discord.Embed(title="Error", description=f"Koi internal error aaya: {str(error)}", color=0xFF4444)
    await ctx.send(embed=embed)

# -------------------- EMBED GENERATORS --------------------
def create_public_panel_embed():
    keys = read_keys()
    status = "Paused" if PAUSED else "Active"
    embed = discord.Embed(title="Warrior Points Earner", 
                          description="**Kaise Points Kamaein:**\nSpecific Voice Channels join karein. Har minute 3 points milenge. Screen Share karein to 5 points.\n\n**Rules:**\n- AFK, Deafen ya Mute per points nahi milenge.\n- Max limit 300 points hai.\n- 90 points par 1 Key redeem hoti hai.\n- Daily limit: 2 keys.\n- Account 2 weeks se purana hona chahiye.", 
                          color=0x1A1A1A, timestamp=datetime.now(timezone.utc))
    embed.set_footer(text="Power By SUBHAN")
    embed.set_image(url=CONFIG.get("panel_image_url", ""))
    embed.set_thumbnail(url=CONFIG.get("panel_thumbnail_url", ""))
    embed.add_field(name="Live Stock", value=f"{len(keys)} Keys Available")
    embed.add_field(name="Bot Status", value=status)
    return embed

# -------------------- UI VIEWS & INTERACTIONS --------------------
class PublicPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Check Points", style=discord.ButtonStyle.primary, custom_id="check_points")
    async def check_points(self, interaction: discord.Interaction):
        data = get_user_data(interaction.user.id)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if data["last_redeem_date"] != today:
            data["daily_redeems"] = 0
            data["last_redeem_date"] = today
            save_user_data(interaction.user.id, data)

        embed = discord.Embed(title="Account Status", description=f"Profile: {interaction.user.display_name}\nUser ID: {interaction.user.id}", color=0x4A90E2, timestamp=datetime.now(timezone.utc))
        embed.set_footer(text="Power By SUBHAN")
        embed.add_field(name="Available Points", value=f"{data['available_points']}/{CONFIG['max_points_cap']}")        embed.add_field(name="Total All-Time Earning", value=str(data['total_earned']))
        embed.add_field(name="Daily Key Limit", value=f"{data['daily_redeems']}/{CONFIG['daily_limit']}")
        embed.add_field(name="Redeemed Count", value=str(data['redeemed_count']))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Get Key", style=discord.ButtonStyle.success, custom_id="get_key")
    async def get_key(self, interaction: discord.Interaction):
        data = get_user_data(interaction.user.id)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if data["last_redeem_date"] != today:
            data["daily_redeems"] = 0
            data["last_redeem_date"] = today
            save_user_data(interaction.user.id, data)

        if data["blacklisted"]:
            embed = discord.Embed(title="Access Restricted", description="Aapka account blacklist mein hai. Points ya keys redeem nahi kar sakte.", color=0xFF4444)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        
        if data["available_points"] < CONFIG["key_cost"]:
            embed = discord.Embed(title="Insufficient Points", description=f"Key ke liye {CONFIG['key_cost']} points chahiye. Aapke paas {data['available_points']} hain.", color=0xFF4444)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
            
        if data["daily_redeems"] >= CONFIG["daily_limit"]:
            embed = discord.Embed(title="Daily Limit Reached", description=f"Aapki daily key limit ({CONFIG['daily_limit']}/2) poori ho chuki hai.", color=0xFF4444)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        async with DATA_LOCK:
            keys = read_keys()
            if not keys:
                embed = discord.Embed(title="Out of Stock", description="Abhi koi keys available nahi hain.", color=0xFF4444)
                return await interaction.response.send_message(embed=embed, ephemeral=True)

            redeemed_key = keys.pop(0)
            write_keys(keys)
            log_redeemed(redeemed_key, interaction.user.id)
            data["available_points"] -= CONFIG["key_cost"]
            data["redeemed_count"] += 1
            data["daily_redeems"] += 1
            save_user_data(interaction.user.id, data)

        try:
            dm_embed = discord.Embed(title="Key Redeemed", description=f"Aapki Key: `{redeemed_key}`\nShukriya Warrior!", color=0x00FF7F, timestamp=datetime.now(timezone.utc))
            dm_embed.set_footer(text="Power By SUBHAN")
            await interaction.user.send(embed=dm_embed)
            embed = discord.Embed(title="Success", description="Key aapke DM mein bhej di gayi hai.", color=0x00FF7F)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
            log_e = discord.Embed(title="Key Redeemed", description=f"{interaction.user.mention} redeemed a key.", color=0x00FF7F)
            await send_log(log_e)
        except discord.Forbidden:            embed = discord.Embed(title="Failed", description="DMs band hain. Please DMs enable karein.", color=0xFF4444)
            await interaction.response.send_message(embed=embed, ephemeral=True)

class AdminView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Add New Keys", style=discord.ButtonStyle.primary)
    async def add_keys(self, interaction: discord.Interaction):
        modal = AddKeysModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Check Keys", style=discord.ButtonStyle.secondary)
    async def check_keys(self, interaction: discord.Interaction):
        keys = read_keys()
        with open(REDEEMED_FILE, "r") as f:
            redeemed_count = len([l for l in f if l.strip()])
        embed = discord.Embed(title="Key Inventory", description="Current Stock Status", color=0x4A90E2, timestamp=datetime.now(timezone.utc))
        embed.set_footer(text="Power By SUBHAN")
        embed.add_field(name="Available", value=str(len(keys)))
        embed.add_field(name="Redeemed", value=str(redeemed_count))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Add Blacklist", style=discord.ButtonStyle.danger)
    async def add_blacklist(self, interaction: discord.Interaction):
        modal = ManageUserModal(action="add_blacklist")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Remove Blacklist", style=discord.ButtonStyle.secondary)
    async def remove_blacklist(self, interaction: discord.Interaction):
        modal = ManageUserModal(action="remove_blacklist")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Allow (Whitelist)", style=discord.ButtonStyle.success)
    async def allow_user(self, interaction: discord.Interaction):
        modal = ManageUserModal(action="allow")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Edit Points", style=discord.ButtonStyle.primary)
    async def edit_points(self, interaction: discord.Interaction):
        modal = ManageUserModal(action="edit_points")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Pause/Resume Bot", style=discord.ButtonStyle.gray)
    async def toggle_pause(self, interaction: discord.Interaction):
        global PAUSED
        PAUSED = not PAUSED
        status = "Paused" if PAUSED else "Resumed"
        embed = discord.Embed(title="System Toggle", description=f"Bot status: {status}", color=0x4A90E2)
        embed.set_footer(text="Power By SUBHAN")        await interaction.response.send_message(embed=embed)
        await send_log(embed)

class AddKeysModal(Modal, title="Add New Keys (Line by Line)"):
    keys_input = TextInput(label="Enter Keys (One per line)", style=discord.TextStyle.paragraph, required=True)
    async def on_submit(self, interaction: discord.Interaction):
        keys = [k.strip() for k in self.keys_input.value.split("\n") if k.strip()]
        if not keys:
            return await interaction.response.send_message("Koi valid key nahi mili.", ephemeral=True)
        async with DATA_LOCK:
            current = read_keys()
            current.extend(keys)
            write_keys(current)
        embed = discord.Embed(title="Keys Added", description=f"{len(keys)} keys successfully added.", color=0x00FF7F)
        embed.set_footer(text="Power By SUBHAN")
        await interaction.response.send_message(embed=embed, ephemeral=True)

class ManageUserModal(Modal, title="Manage User"):
    user_id_input = TextInput(label="User ID", placeholder="Enter Discord User ID", required=True)
    value_input = TextInput(label="Value / Points", placeholder="Leave empty if not needed", required=False)
    
    def __init__(self, action: str):
        super().__init__()
        self.action = action
        self.title = {
            "add_blacklist": "Add to Blacklist",
            "remove_blacklist": "Remove from Blacklist",
            "allow": "Whitelist User",
            "edit_points": "Edit User Points"
        }[action]

    async def on_submit(self, interaction: discord.Interaction):
        try:
            uid = int(self.user_id_input.value.strip())
        except ValueError:
            return await interaction.response.send_message("Invalid User ID.", ephemeral=True)

        data = get_user_data(uid)
        msg = ""
        if self.action == "add_blacklist":
            data["blacklisted"] = True
            msg = f"User {uid} Blacklisted."
        elif self.action == "remove_blacklist":
            data["blacklisted"] = False
            msg = f"User {uid} Blacklist se remove ho gaya."
        elif self.action == "allow":
            data["whitelisted"] = True
            msg = f"User {uid} Allowed/Whitelisted."
        elif self.action == "edit_points":
            try:                pts = int(self.value_input.value.strip())
                data["available_points"] = pts
                data["total_earned"] += pts
                msg = f"User {uid} points updated to {pts}."
            except ValueError:
                return await interaction.response.send_message("Points must be a number.", ephemeral=True)

        save_user_data(uid, data)
        embed = discord.Embed(title="User Updated", description=msg, color=0x4A90E2)
        embed.set_footer(text="Power By SUBHAN")
        await interaction.response.send_message(embed=embed, ephemeral=True)

# -------------------- POINTS LOOP --------------------
@tasks.loop(minutes=1)
async def points_loop():
    if PAUSED:
        return

    for guild in bot.guilds:
        for member in guild.members:
            if not member.voice or member.voice.channel.id not in TRACKED_VCS:
                continue

            vc_state = member.voice
            if vc_state.self_deaf or vc_state.self_mute or vc_state.channel.is_afk():
                continue

            data = get_user_data(member.id)
            age_days = (datetime.now(timezone.utc) - member.created_at).days

            if age_days < CONFIG["min_account_age_days"] and not data.get("whitelisted", False):
                if not data["blacklisted"]:
                    data["blacklisted"] = True
                    save_user_data(member.id, data)
                    await send_log(discord.Embed(title="Auto Blacklist", description=f"{member.name} (<14 days) auto-blacklisted.", color=0xFF4444))
                continue

            if data["blacklisted"]:
                continue

            pts = CONFIG["points_stream"] if vc_state.self_stream else CONFIG["points_normal"]
            if data["available_points"] + pts <= CONFIG["max_points_cap"]:
                data["available_points"] += pts
            else:
                diff = CONFIG["max_points_cap"] - data["available_points"]
                if diff > 0:
                    data["available_points"] += diff
            data["total_earned"] += pts
            save_user_data(member.id, data)
@points_loop.before_loop
async def before_points():
    await bot.wait_until_ready()

# -------------------- RUN --------------------
if __name__ == "__main__":
    for f in [DATA_PATH, KEY_FILE, REDEEMED_FILE]:
        if not os.path.exists(f):
            open(f, "w").close()
    load_users()
    bot.run(TOKEN)
