import os
import json
import asyncio
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import lbc

load_dotenv()

# Get settings path relative to this file to be safe
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")

class AutobuyView(discord.ui.View):
    def __init__(self, ad_id: str):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="⚡ Acheter",
                style=discord.ButtonStyle.link,
                url=f"https://www.leboncoin.fr/paiement/achat_immediat/{ad_id}"
            )
        )

class LbcBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print("Bot commands synced.")

bot = LbcBot()

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}

def save_settings(settings):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=4)

@bot.tree.command(name="setprice", description="Définir le prix maximum pour une niche")
@app_commands.describe(niche="Le nom de la recherche/niche", montant="Le prix maximum")
async def setprice(interaction: discord.Interaction, niche: str, montant: int):
    settings = load_settings()
    settings[niche] = montant
    save_settings(settings)
    await interaction.response.send_message(f"✅ Prix maximum pour la niche `{niche}` défini à `{montant} €`.", ephemeral=True)

def send_alert_threadsafe(ad: lbc.Ad, search_name: str):
    """
    Envoie une alerte Discord. Doit être appelée depuis un autre thread.
    """
    channel_id = os.getenv("DISCORD_CHANNEL_ID")
    if not channel_id:
        print("DISCORD_CHANNEL_ID manquant dans les variables d'environnement.")
        return

    channel = bot.get_channel(int(channel_id))
    if not channel:
        print(f"Canal Discord introuvable ({channel_id}). Le bot est-il bien sur le serveur ?")
        return

    embed = discord.Embed(
        title=ad.subject,
        url=ad.url,
        color=discord.Color.brand_green()
    )
    embed.add_field(name="Prix", value=f"{ad.price} €", inline=False)
    embed.add_field(name="Niche", value=search_name, inline=False)
    
    if hasattr(ad, "images") and ad.images:
        embed.set_thumbnail(url=ad.images[0])

    view = AutobuyView(str(ad.id))

    # Thread-safe coroutine execution
    asyncio.run_coroutine_threadsafe(
        channel.send(embed=embed, view=view),
        bot.loop
    )

def start_bot():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ DISCORD_TOKEN manquant dans les variables d'environnement.")
        return
    bot.run(token)
