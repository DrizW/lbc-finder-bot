import os
import json
import asyncio
import datetime
import threading
import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
import lbc

load_dotenv()

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")
STATS_FILE = os.path.join(os.path.dirname(__file__), "stats.json")

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
# Stats helpers
# ─────────────────────────────────────────────

_stats_lock = threading.Lock()


def load_stats() -> dict:
    if not os.path.exists(STATS_FILE):
        return {}
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_stats(stats: dict):
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=4, ensure_ascii=False)


def record_stat(niche: str, key: str, increment: int = 1):
    """Thread-safe stat increment."""
    with _stats_lock:
        stats = load_stats()
        if niche not in stats:
            stats[niche] = {"found": 0, "filtered": 0, "alerted": 0, "last_alert": None}
        stats[niche][key] = stats[niche].get(key, 0) + increment
        if key == "alerted":
            stats[niche]["last_alert"] = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
        save_stats(stats)


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
        daily_summary.start()
        print("[Bot] Résumé quotidien programmé à 9h00.")


bot = LbcBot()


# ─────────────────────────────────────────────
# Helper: build Search object from a settings entry
# ─────────────────────────────────────────────

def _build_search(name: str, cfg: dict):
    from config.handler import handle
    from model import Search, Parameters

    params_kwargs = {"text": cfg.get("keywords", name)}

    if cfg.get("lat") and cfg.get("lng"):
        params_kwargs["locations"] = [
            lbc.City(
                lat=cfg["lat"],
                lng=cfg["lng"],
                radius=cfg.get("radius_km", 20) * 1000,
                city=cfg.get("city", ""),
            )
        ]

    if cfg.get("owner_type") == "private":
        params_kwargs["owner_type"] = lbc.OwnerType.PRIVATE

    return Search(
        name=name,
        parameters=Parameters(**params_kwargs),
        delay=60,
        handler=handle,
    )


# ─────────────────────────────────────────────
# Slash commands
# ─────────────────────────────────────────────

# Condition choices
CONDITION_CHOICES = [
    app_commands.Choice(name="Tous les états", value="all"),
    app_commands.Choice(name="Neuf", value="1"),
    app_commands.Choice(name="Très bon état", value="2"),
    app_commands.Choice(name="Bon état", value="3"),
    app_commands.Choice(name="État correct", value="4"),
    app_commands.Choice(name="Pour pièces", value="5"),
]


@bot.tree.command(
    name="addsearch",
    description="Ajoute ou met à jour une niche de recherche Leboncoin"
)
@app_commands.describe(
    niche="Nom de la niche (ex: Poussette Cybex)",
    keywords="Mots-clés de recherche (ex: poussette cybex)",
    prix_max="Prix maximum en euros",
    prix_min="Prix minimum en euros (alerte 🚨 si en dessous, potentielle pépite)",
    ville="Ville pour la recherche géolocalisée (laisser vide = France entière)",
    rayon_km="Rayon en km autour de la ville (défaut: 20)",
    particuliers_seulement="Ne montrer que les annonces de particuliers",
)
@app_commands.choices(etat=CONDITION_CHOICES)
async def addsearch(
    interaction: discord.Interaction,
    niche: str,
    keywords: str,
    prix_max: int,
    prix_min: int = 0,
    ville: str = "",
    rayon_km: int = 20,
    particuliers_seulement: bool = False,
    etat: app_commands.Choice[str] = None,
):
    await interaction.response.defer(ephemeral=True)

    entry = {
        "keywords": keywords,
        "max_price": prix_max,
        "min_price": prix_min,
        "city": ville,
        "lat": None,
        "lng": None,
        "radius_km": rayon_km,
        "owner_type": "private" if particuliers_seulement else "all",
        "condition": etat.value if etat and etat.value != "all" else None,
        "paused": False,
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
                "Vérifiez l'orthographe ou laissez le champ vide pour la France entière.",
                ephemeral=True
            )
            return

    # Save to settings
    settings = load_settings()
    settings[niche] = entry
    save_settings(settings)

    # Inject live into the Searcher
    if _searcher is not None:
        _searcher.add_search_thread(_build_search(niche, entry))

    # Build confirmation message
    location_info = f"autour de **{ville}** ({rayon_km} km)" if ville else "**France entière**"
    extras = []
    if particuliers_seulement:
        extras.append("👤 Particuliers uniquement")
    if prix_min > 0:
        extras.append(f"🚨 Alerte pépite sous `{prix_min} €`")
    if etat and etat.value != "all":
        extras.append(f"🏷️ État : `{etat.name}`")

    await interaction.followup.send(
        f"✅ Niche **{niche}** ajoutée !\n"
        f"🔍 Mots-clés : `{keywords}`\n"
        f"💶 Prix max : `{prix_max} €`\n"
        f"📍 Localisation : {location_info}"
        + (("\n" + "\n".join(extras)) if extras else ""),
        ephemeral=True
    )


@bot.tree.command(name="delsearch", description="Supprime une niche de recherche")
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
        f"🗑️ Niche **{niche}** supprimée.", ephemeral=True
    )


@bot.tree.command(name="pause", description="Met une niche en pause")
@app_commands.describe(niche="Nom de la niche à mettre en pause")
async def pause(interaction: discord.Interaction, niche: str):
    settings = load_settings()
    if niche not in settings:
        await interaction.response.send_message(f"❌ Niche `{niche}` introuvable.", ephemeral=True)
        return

    settings[niche]["paused"] = True
    save_settings(settings)

    if _searcher is not None:
        _searcher.remove_search_thread(niche)

    await interaction.response.send_message(
        f"⏸️ Niche **{niche}** mise en pause. Utilisez `/resume` pour la relancer.",
        ephemeral=True
    )


@bot.tree.command(name="resume", description="Relance une niche en pause")
@app_commands.describe(niche="Nom de la niche à relancer")
async def resume(interaction: discord.Interaction, niche: str):
    settings = load_settings()
    if niche not in settings:
        await interaction.response.send_message(f"❌ Niche `{niche}` introuvable.", ephemeral=True)
        return

    settings[niche]["paused"] = False
    save_settings(settings)

    if _searcher is not None:
        _searcher.add_search_thread(_build_search(niche, settings[niche]))

    await interaction.response.send_message(
        f"▶️ Niche **{niche}** relancée !", ephemeral=True
    )


@bot.tree.command(name="listsearches", description="Affiche toutes les niches actives")
async def listsearches(interaction: discord.Interaction):
    settings = load_settings()
    if not settings:
        await interaction.response.send_message(
            "📭 Aucune niche configurée. Utilisez `/addsearch` pour en ajouter une.",
            ephemeral=True
        )
        return

    embed = discord.Embed(title="🔎 Niches configurées", color=discord.Color.blurple())
    for name, cfg in settings.items():
        if not isinstance(cfg, dict):
            continue
        status = "⏸️ En pause" if cfg.get("paused") else "✅ Active"
        location = f"{cfg.get('city', '')} ({cfg.get('radius_km', 20)} km)" if cfg.get("city") else "France entière"
        extras = []
        if cfg.get("owner_type") == "private":
            extras.append("👤 Particuliers uniquement")
        if cfg.get("min_price", 0) > 0:
            extras.append(f"🚨 Pépite < {cfg['min_price']} €")
        embed.add_field(
            name=f"{status} — {name}",
            value=(
                f"**Mots-clés :** `{cfg.get('keywords', '—')}`\n"
                f"**Prix :** `{cfg.get('min_price', 0)} € → {cfg.get('max_price', '∞')} €`\n"
                f"**Zone :** {location}"
                + (("\n" + " · ".join(extras)) if extras else "")
            ),
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="stats", description="Statistiques de recherche par niche")
async def stats_cmd(interaction: discord.Interaction):
    stats = load_stats()
    if not stats:
        await interaction.response.send_message(
            "📊 Aucune statistique disponible pour le moment.", ephemeral=True
        )
        return

    embed = discord.Embed(
        title="📊 Statistiques",
        color=discord.Color.gold(),
        description="Résumé depuis le dernier démarrage du bot."
    )
    for name, s in stats.items():
        embed.add_field(
            name=f"📦 {name}",
            value=(
                f"🔍 Trouvées : `{s.get('found', 0)}`\n"
                f"🚫 Filtrées : `{s.get('filtered', 0)}`\n"
                f"🔔 Alertées : `{s.get('alerted', 0)}`\n"
                f"🕐 Dernière alerte : `{s.get('last_alert', 'Jamais')}`"
            ),
            inline=True
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="simulate", description="Teste une recherche sans la lancer")
@app_commands.describe(
    keywords="Mots-clés à tester",
    ville="Ville (optionnel)",
    rayon_km="Rayon en km (défaut: 20)"
)
async def simulate(
    interaction: discord.Interaction,
    keywords: str,
    ville: str = "",
    rayon_km: int = 20
):
    await interaction.response.defer(ephemeral=True)

    def run_simulate():
        try:
            from lbc import Client, Sort
            client = Client()
            params = {"text": keywords}
            if ville.strip():
                coords = geocode_city(ville)
                if coords:
                    params["locations"] = [
                        lbc.City(lat=coords[0], lng=coords[1], radius=rayon_km * 1000, city=ville)
                    ]
            response = client.search(**params, sort=Sort.NEWEST)
            return response.total, response.ads[:3]
        except Exception as e:
            return None, str(e)

    total, result = await asyncio.get_event_loop().run_in_executor(None, run_simulate)

    if total is None:
        await interaction.followup.send(f"❌ Erreur lors de la simulation : `{result}`", ephemeral=True)
        return

    location_info = f"autour de **{ville}** ({rayon_km} km)" if ville else "**France entière**"
    embed = discord.Embed(
        title=f"🧪 Simulation — `{keywords}`",
        description=f"📍 {location_info}\n📋 **{total} annonce(s)** trouvée(s) sur Leboncoin en ce moment.",
        color=discord.Color.orange()
    )
    for ad in result:
        embed.add_field(
            name=ad.subject[:50],
            value=f"💶 {ad.price} € — [Voir l'annonce]({ad.url})",
            inline=False
        )
    embed.set_footer(text="Simulation uniquement — aucune recherche n'a été démarrée.")
    await interaction.followup.send(embed=embed, ephemeral=True)


# ─────────────────────────────────────────────
# Daily summary (every day at 09:00)
# ─────────────────────────────────────────────

@tasks.loop(time=datetime.time(hour=9, minute=0, tzinfo=datetime.timezone.utc))
async def daily_summary():
    channel_id = os.getenv("DISCORD_CHANNEL_ID")
    if not channel_id:
        return
    channel = bot.get_channel(int(channel_id))
    if not channel:
        return

    stats = load_stats()
    settings = load_settings()
    if not stats:
        return

    embed = discord.Embed(
        title="☀️ Résumé quotidien — lbc-finder",
        color=discord.Color.gold(),
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )

    total_alerted = 0
    for name, s in stats.items():
        paused = settings.get(name, {}).get("paused", False) if isinstance(settings.get(name), dict) else False
        status = "⏸️" if paused else "✅"
        embed.add_field(
            name=f"{status} {name}",
            value=(
                f"🔍 Trouvées : `{s.get('found', 0)}`  "
                f"🚫 Filtrées : `{s.get('filtered', 0)}`  "
                f"🔔 Alertées : `{s.get('alerted', 0)}`"
            ),
            inline=False
        )
        total_alerted += s.get("alerted", 0)

    embed.set_footer(text=f"Total alertes envoyées : {total_alerted}")
    await channel.send(embed=embed)


# ─────────────────────────────────────────────
# Alert sender (called from search threads)
# ─────────────────────────────────────────────

def send_alert_threadsafe(ad: lbc.Ad, search_name: str, is_bargain: bool = False):
    """Thread-safe: sends a Discord alert from a non-async thread."""
    channel_id = os.getenv("DISCORD_CHANNEL_ID")
    if not channel_id:
        print("[Bot] DISCORD_CHANNEL_ID manquant.")
        return

    channel = bot.get_channel(int(channel_id))
    if not channel:
        print(f"[Bot] Canal introuvable ({channel_id}).")
        return

    color = discord.Color.red() if is_bargain else discord.Color.brand_green()
    title_prefix = "🚨 PÉPITE DÉTECTÉE — " if is_bargain else ""

    embed = discord.Embed(
        title=f"{title_prefix}{ad.subject}",
        url=ad.url,
        color=color,
        timestamp=datetime.datetime.now(datetime.timezone.utc)
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
