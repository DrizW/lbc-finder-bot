import os
import json
import asyncio
import threading
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import lbc

load_dotenv()

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")

# Reference to the Searcher instance — injected from main.py
_searcher = None

def set_searcher(s):
    global _searcher
    _searcher = s


# ─────────────────────────────────────────────
# Settings helpers
# ─────────────────────────────────────────────

def load_settings() -> dict:
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_settings(settings: dict):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=4, ensure_ascii=False)


# ─────────────────────────────────────────────
# Geocoding (OpenStreetMap Nominatim — free, no key needed)
# ─────────────────────────────────────────────

def geocode_city(city_name: str) -> tuple[float, float] | None:
    """Returns (lat, lng) for a given city name, or None if not found."""
    try:
        import urllib.request
        import urllib.parse
        url = (
            "https://nominatim.openstreetmap.org/search?"
            + urllib.parse.urlencode({"q": city_name, "format": "json", "limit": 1})
        )
        req = urllib.request.Request(url, headers={"User-Agent": "lbc-finder-bot/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        print(f"[Geocoding] Erreur pour '{city_name}': {e}")
    return None


# ─────────────────────────────────────────────
# Autobuy button
# ─────────────────────────────────────────────

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


# ─────────────────────────────────────────────
# Bot
# ─────────────────────────────────────────────

class LbcBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print("[Bot] Commandes Slash synchronisées.")


bot = LbcBot()


# ─────────────────────────────────────────────
# Slash commands
# ─────────────────────────────────────────────

@bot.tree.command(
    name="addsearch",
    description="Ajoute ou met à jour une niche de recherche Leboncoin"
)
@app_commands.describe(
    niche="Nom de la niche (ex: Poussette Cybex)",
    keywords="Mots-clés de recherche (ex: poussette cybex)",
    prix_max="Prix maximum en euros",
    ville="Ville pour la recherche géolocalisée (laisser vide = France entière)",
    rayon_km="Rayon en km autour de la ville (défaut: 20)"
)
async def addsearch(
    interaction: discord.Interaction,
    niche: str,
    keywords: str,
    prix_max: int,
    ville: str = "",
    rayon_km: int = 20
):
    await interaction.response.defer(ephemeral=True)

    entry = {
        "keywords": keywords,
        "max_price": prix_max,
        "city": ville,
        "lat": None,
        "lng": None,
        "radius_km": rayon_km,
    }

    # Geocode the city if provided
    if ville.strip():
        coords = await asyncio.get_event_loop().run_in_executor(
            None, geocode_city, ville
        )
        if coords:
            entry["lat"], entry["lng"] = coords
        else:
            await interaction.followup.send(
                f"⚠️ Impossible de trouver la ville `{ville}`. "
                "Vérifiez l'orthographe ou laissez le champ vide pour chercher en France entière.",
                ephemeral=True
            )
            return

    # Save to settings
    settings = load_settings()
    settings[niche] = entry
    save_settings(settings)

    # Build lbc search and inject it live into the Searcher
    if _searcher is not None:
        from config.handler import handle
        from model import Search, Parameters

        params_kwargs = {"text": keywords}
        if entry["lat"] and entry["lng"]:
            params_kwargs["locations"] = [
                lbc.City(
                    lat=entry["lat"],
                    lng=entry["lng"],
                    radius=entry["radius_km"] * 1000,
                    city=ville,
                )
            ]

        search_obj = Search(
            name=niche,
            parameters=Parameters(**params_kwargs),
            delay=60,
            handler=handle,
        )
        _searcher.add_search_thread(search_obj)

    # Build confirmation message
    location_info = f"autour de **{ville}** ({rayon_km} km)" if ville else "**France entière**"
    await interaction.followup.send(
        f"✅ Niche **{niche}** ajoutée !\n"
        f"🔍 Mots-clés : `{keywords}`\n"
        f"💶 Prix max : `{prix_max} €`\n"
        f"📍 Localisation : {location_info}",
        ephemeral=True
    )


@bot.tree.command(
    name="delsearch",
    description="Supprime une niche de recherche"
)
@app_commands.describe(niche="Nom de la niche à supprimer")
async def delsearch(interaction: discord.Interaction, niche: str):
    settings = load_settings()
    if niche not in settings:
        await interaction.response.send_message(
            f"❌ La niche `{niche}` est introuvable.", ephemeral=True
        )
        return

    del settings[niche]
    save_settings(settings)

    if _searcher is not None:
        _searcher.remove_search_thread(niche)

    await interaction.response.send_message(
        f"🗑️ Niche **{niche}** supprimée. Le bot ne cherche plus cette niche.",
        ephemeral=True
    )


@bot.tree.command(
    name="listsearches",
    description="Affiche toutes les niches de recherche actives"
)
async def listsearches(interaction: discord.Interaction):
    settings = load_settings()
    if not settings:
        await interaction.response.send_message(
            "📭 Aucune niche configurée. Utilisez `/addsearch` pour en ajouter une.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="🔎 Niches actives",
        color=discord.Color.blurple()
    )
    for name, cfg in settings.items():
        if isinstance(cfg, dict):
            location = f"{cfg.get('city', '')} ({cfg.get('radius_km', 20)} km)" if cfg.get("city") else "France entière"
            embed.add_field(
                name=f"📦 {name}",
                value=(
                    f"**Mots-clés :** `{cfg.get('keywords', '—')}`\n"
                    f"**Prix max :** `{cfg.get('max_price', '∞')} €`\n"
                    f"**Zone :** {location}"
                ),
                inline=False
            )
        else:
            # Legacy format (simple int price)
            embed.add_field(name=f"📦 {name}", value=f"Prix max : `{cfg} €`", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ─────────────────────────────────────────────
# Alert sender (called from search threads)
# ─────────────────────────────────────────────

def send_alert_threadsafe(ad: lbc.Ad, search_name: str):
    """Thread-safe: sends a Discord alert from a non-async thread."""
    channel_id = os.getenv("DISCORD_CHANNEL_ID")
    if not channel_id:
        print("[Bot] DISCORD_CHANNEL_ID manquant dans les variables d'environnement.")
        return

    channel = bot.get_channel(int(channel_id))
    if not channel:
        print(f"[Bot] Canal Discord introuvable ({channel_id}).")
        return

    embed = discord.Embed(
        title=ad.subject,
        url=ad.url,
        color=discord.Color.brand_green()
    )
    embed.add_field(name="💶 Prix", value=f"{ad.price} €", inline=True)
    embed.add_field(name="📦 Niche", value=search_name, inline=True)

    if hasattr(ad, "images") and ad.images:
        embed.set_thumbnail(url=ad.images[0])

    view = AutobuyView(str(ad.id))

    asyncio.run_coroutine_threadsafe(
        channel.send(embed=embed, view=view),
        bot.loop
    )


# ─────────────────────────────────────────────
# Start
# ─────────────────────────────────────────────

def start_bot():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ DISCORD_TOKEN manquant dans les variables d'environnement.")
        return
    bot.run(token)
