import os
import json
import asyncio
import datetime
import threading
import re
import unicodedata
import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
from searcher.logger import logger
import lbc

load_dotenv()

APP_DIR = os.path.dirname(__file__)
DATA_DIR = os.getenv("LBC_DATA_DIR", os.path.join(os.getcwd(), "data"))
SETTINGS_FILE = os.getenv("LBC_SETTINGS_FILE", os.path.join(DATA_DIR, "settings.json"))
STATS_FILE = os.getenv("LBC_STATS_FILE", os.path.join(DATA_DIR, "stats.json"))

# Reference to the Searcher instance — injected from main.py
_searcher = None


def set_searcher(s):
    global _searcher
    _searcher = s


def get_settings_path() -> str:
    return SETTINGS_FILE


def normalize_text(value: str) -> str:
    return " ".join(value.strip().split())


STOPWORDS = {
    "a",
    "au",
    "aux",
    "avec",
    "de",
    "des",
    "du",
    "en",
    "et",
    "la",
    "le",
    "les",
    "l",
    "pour",
    "sur",
    "un",
    "une",
}


def normalize_for_match(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode(
        "ascii", "ignore"
    ).decode("ascii")
    return text.lower()


def keyword_tokens(value: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", normalize_for_match(value))
    return [token for token in tokens if len(token) > 1 and token not in STOPWORDS]


# ─────────────────────────────────────────────
# Settings helpers
# ─────────────────────────────────────────────

def load_settings() -> dict:
    path = get_settings_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_settings(settings: dict):
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
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
    os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
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


def get_alert_channel():
    channel_id = os.getenv("DISCORD_CHANNEL_ID")
    if not channel_id:
        return None, "DISCORD_CHANNEL_ID manquant"
    try:
        channel = bot.get_channel(int(channel_id))
    except ValueError:
        return None, "DISCORD_CHANNEL_ID invalide"
    if not channel:
        return None, f"Canal introuvable ({channel_id})"
    return channel, None


def _ad_field(ad: lbc.Ad, *names, default=None):
    for name in names:
        if hasattr(ad, name):
            value = getattr(ad, name)
            if value is not None:
                return value
    return default


def _ad_condition(ad: lbc.Ad) -> str | None:
    for source_name in ("attributes", "options"):
        source = getattr(ad, source_name, None)
        if isinstance(source, dict):
            for key in ("condition", "item_condition", "etat"):
                value = source.get(key)
                if value is not None:
                    return str(value)
        elif isinstance(source, list):
            for item in source:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key") or item.get("name") or item.get("id") or "")
                if key in {"condition", "item_condition", "etat"}:
                    value = item.get("value") or item.get("values")
                    if value is not None:
                        return str(value)
    return None


def _ad_match_text(ad: lbc.Ad) -> str:
    parts = [
        _ad_field(ad, "subject", "title", default=""),
        _ad_field(ad, "body", "description", default=""),
    ]
    for source_name in ("attributes", "options"):
        source = getattr(ad, source_name, None)
        if isinstance(source, dict):
            parts.extend(str(value) for value in source.values() if value is not None)
        elif isinstance(source, list):
            for item in source:
                if isinstance(item, dict):
                    parts.extend(str(value) for value in item.values() if value is not None)
    return normalize_for_match(" ".join(parts))


def _missing_keywords(ad: lbc.Ad, cfg: dict) -> list[str]:
    if cfg.get("filtrage_strict") is False:
        return []

    tokens = cfg.get("mots_obligatoires")
    if not isinstance(tokens, list):
        tokens = keyword_tokens(cfg.get("keywords", ""))

    if not tokens:
        return []

    searchable = _ad_match_text(ad)
    return [token for token in tokens if token not in searchable]


def _missing_brand(ad: lbc.Ad, cfg: dict) -> str | None:
    brand = normalize_text(cfg.get("marque", ""))
    if not brand:
        return None

    searchable = _ad_match_text(ad)
    brand_tokens = keyword_tokens(brand)
    if not brand_tokens:
        return None

    if all(token in searchable for token in brand_tokens):
        return None
    return brand


def get_filter_reason(ad: lbc.Ad, cfg: dict) -> str | None:
    max_price = cfg.get("max_price")
    min_price = cfg.get("min_price", 0)
    condition = cfg.get("condition")
    price = _ad_field(ad, "price")

    if max_price is not None and price is not None and price > max_price:
        return f"prix {price} € > max {max_price} €"

    missing_brand = _missing_brand(ad, cfg)
    if missing_brand:
        return f"marque absente: {missing_brand}"

    if condition:
        ad_condition = _ad_condition(ad)
        if ad_condition and ad_condition != str(condition):
            return f"etat {ad_condition} != {condition}"

    missing = _missing_keywords(ad, cfg)
    if missing:
        return f"mot(s)-clé(s) absent(s): {', '.join(missing)}"

    return None


def is_bargain_ad(ad: lbc.Ad, cfg: dict) -> bool:
    min_price = cfg.get("min_price", 0)
    price = _ad_field(ad, "price")
    return min_price > 0 and price is not None and price < min_price


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
    def __init__(self, ad_url: str):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="Voir l'annonce",
                style=discord.ButtonStyle.link,
                url=ad_url,
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

    query = f"{cfg.get('keywords', name)} {cfg.get('marque', '')}".strip()
    params_kwargs = {"text": query}
    max_price = cfg.get("max_price")

    if isinstance(max_price, (int, float)) and max_price > 0:
        params_kwargs["price"] = [0, max_price]

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
    name="ajouter-niche",
    description="Ajoute ou met à jour une niche de recherche Leboncoin"
)
@app_commands.describe(
    niche="Nom de la niche (ex: Poussette Cybex)",
    mots_cles="Objet recherché (ex: poussette, siege auto, robot tondeuse)",
    marque="Marque obligatoire (ex: cybex, bugaboo, stokke)",
    prix_max="Prix maximum en euros",
    prix_min="Prix minimum en euros (alerte 🚨 si en dessous, potentielle pépite)",
    ville="Ville pour la recherche géolocalisée (laisser vide = France entière)",
    rayon_km="Rayon en km autour de la ville (défaut: 20)",
    particuliers_seulement="Ne montrer que les annonces de particuliers",
    filtrage_strict="Exige que les mots-clés importants soient présents dans l'annonce",
)
@app_commands.choices(etat=CONDITION_CHOICES)
async def ajouterniche(
    interaction: discord.Interaction,
    niche: str,
    mots_cles: str,
    prix_max: int,
    marque: str = "",
    prix_min: int = 0,
    ville: str = "",
    rayon_km: int = 20,
    particuliers_seulement: bool = False,
    filtrage_strict: bool = True,
    etat: app_commands.Choice[str] = None,
):
    await interaction.response.defer(ephemeral=True)
    niche = normalize_text(niche)
    mots_cles = normalize_text(mots_cles)
    marque = normalize_text(marque)
    ville = normalize_text(ville)

    if not niche:
        await interaction.followup.send(
            "❌ Le nom de la niche ne peut pas être vide.",
            ephemeral=True
        )
        return

    if not mots_cles:
        await interaction.followup.send(
            "❌ Les mots-clés ne peuvent pas être vides.",
            ephemeral=True
        )
        return

    if len(niche) > 80:
        await interaction.followup.send(
            "❌ Le nom de la niche est trop long (80 caractères maximum).",
            ephemeral=True
        )
        return

    if prix_max <= 0:
        await interaction.followup.send(
            "❌ Le prix maximum doit être supérieur à 0 €.",
            ephemeral=True
        )
        return

    if prix_min < 0:
        await interaction.followup.send(
            "❌ Le seuil pépite ne peut pas être négatif.",
            ephemeral=True
        )
        return

    if prix_min > prix_max:
        await interaction.followup.send(
            "❌ Le seuil pépite doit être inférieur ou égal au prix maximum.",
            ephemeral=True
        )
        return

    if rayon_km <= 0:
        await interaction.followup.send(
            "❌ Le rayon doit être supérieur à 0 km.",
            ephemeral=True
        )
        return

    entry = {
        "keywords": mots_cles,
        "marque": marque,
        "max_price": prix_max,
        "min_price": prix_min,
        "city": ville,
        "lat": None,
        "lng": None,
        "radius_km": rayon_km,
        "owner_type": "private" if particuliers_seulement else "all",
        "condition": etat.value if etat and etat.value != "all" else None,
        "filtrage_strict": filtrage_strict,
        "mots_obligatoires": keyword_tokens(mots_cles),
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
    duplicate = next(
        (
            name
            for name, existing in settings.items()
            if name != niche
            and isinstance(existing, dict)
            and normalize_text(existing.get("keywords", "")).lower() == mots_cles.lower()
            and normalize_text(existing.get("marque", "")).lower() == marque.lower()
            and normalize_text(existing.get("city", "")).lower() == ville.lower()
            and existing.get("max_price") == prix_max
        ),
        None,
    )
    if duplicate:
        await interaction.followup.send(
            f"❌ Une niche très similaire existe déjà : `{duplicate}`.",
            ephemeral=True
        )
        return

    settings[niche] = entry
    save_settings(settings)
    logger.info(
        "[%s] Niche enregistrée: mots_cles=%r marque=%r prix_max=%s seuil_pepite=%s ville=%r rayon=%s vendeur=%s etat=%s",
        niche,
        mots_cles,
        marque or "non définie",
        prix_max,
        prix_min,
        ville or "France entière",
        rayon_km,
        entry["owner_type"],
        entry["condition"] or "all",
    )

    # Inject live into the Searcher
    if _searcher is not None:
        _searcher.add_search_thread(_build_search(niche, entry))

    # Build confirmation message
    location_info = f"autour de **{ville}** ({rayon_km} km)" if ville else "**France entière**"
    extras = []
    if particuliers_seulement:
        extras.append("👤 Particuliers uniquement")
    if marque:
        extras.append(f"🏷️ Marque obligatoire : `{marque}`")
    if prix_min > 0:
        extras.append(f"🚨 Alerte pépite sous `{prix_min} €`")
    if etat and etat.value != "all":
        extras.append(f"🏷️ État : `{etat.name}`")
    if filtrage_strict:
        extras.append("🎯 Filtrage strict activé")

    await interaction.followup.send(
        f"✅ Niche **{niche}** ajoutée !\n"
        f"🔍 Mots-clés : `{mots_cles}`\n"
        + (f"🏷️ Marque : `{marque}`\n" if marque else "")
        + f"💶 Prix max : `{prix_max} €`\n"
        f"📍 Localisation : {location_info}"
        + (("\n" + "\n".join(extras)) if extras else ""),
        ephemeral=True
    )


@bot.tree.command(name="supprimer-niche", description="Supprime une niche de recherche")
@app_commands.describe(niche="Nom de la niche à supprimer")
async def supprimerniche(interaction: discord.Interaction, niche: str):
    settings = load_settings()
    if niche not in settings:
        await interaction.response.send_message(
            f"❌ La niche `{niche}` est introuvable.", ephemeral=True
        )
        return

    del settings[niche]
    save_settings(settings)
    logger.info("[%s] Niche supprimée.", niche)

    if _searcher is not None:
        _searcher.remove_search_thread(niche)

    await interaction.response.send_message(
        f"🗑️ Niche **{niche}** supprimée.", ephemeral=True
    )


@bot.tree.command(name="vider-niches", description="Supprime toutes les niches configurées")
async def viderlesniches(interaction: discord.Interaction):
    settings = load_settings()
    if not settings:
        await interaction.response.send_message(
            "📭 Aucune niche configurée.", ephemeral=True
        )
        return

    for niche in list(settings.keys()):
        if _searcher is not None:
            _searcher.remove_search_thread(niche)

    save_settings({})
    logger.info("Toutes les niches ont été supprimées.")
    await interaction.response.send_message(
        "🧹 Toutes les niches ont été supprimées. Vous pouvez repartir avec `/ajouter-niche`.",
        ephemeral=True
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
    logger.info("[%s] Niche mise en pause.", niche)

    if _searcher is not None:
        _searcher.remove_search_thread(niche)

    await interaction.response.send_message(
        f"⏸️ Niche **{niche}** mise en pause. Utilisez `/reprendre` pour la relancer.",
        ephemeral=True
    )


@bot.tree.command(name="reprendre", description="Relance une niche en pause")
@app_commands.describe(niche="Nom de la niche à relancer")
async def reprendre(interaction: discord.Interaction, niche: str):
    settings = load_settings()
    if niche not in settings:
        await interaction.response.send_message(f"❌ Niche `{niche}` introuvable.", ephemeral=True)
        return

    settings[niche]["paused"] = False
    save_settings(settings)
    logger.info("[%s] Niche relancée.", niche)

    if _searcher is not None:
        _searcher.add_search_thread(_build_search(niche, settings[niche]))

    await interaction.response.send_message(
        f"▶️ Niche **{niche}** relancée !", ephemeral=True
    )


@bot.tree.command(name="niches", description="Affiche toutes les niches configurées")
async def niches(interaction: discord.Interaction):
    settings = load_settings()
    if not settings:
        await interaction.response.send_message(
            "📭 Aucune niche configurée. Utilisez `/ajouter-niche` pour en ajouter une.",
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
        if cfg.get("marque"):
            extras.append(f"🏷️ Marque : {cfg['marque']}")
        if cfg.get("owner_type") == "private":
            extras.append("👤 Particuliers uniquement")
        if cfg.get("min_price", 0) > 0:
            extras.append(f"🚨 Pépite < {cfg['min_price']} €")
        if cfg.get("filtrage_strict", True):
            extras.append("🎯 Filtrage strict")
        embed.add_field(
            name=f"{status} — {name}",
            value=(
                f"**Mots-clés :** `{cfg.get('keywords', '—')}`\n"
                f"**Marque :** `{cfg.get('marque') or '—'}`\n"
                f"**Prix :** `{cfg.get('min_price', 0)} € → {cfg.get('max_price', '∞')} €`\n"
                f"**Zone :** {location}"
                + (("\n" + " · ".join(extras)) if extras else "")
            ),
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="diagnostic", description="Affiche le diagnostic de configuration du bot")
async def diagnostic(interaction: discord.Interaction):
    settings = load_settings()
    channel, channel_error = get_alert_channel()
    active_searches = _searcher.active_searches() if _searcher is not None else []

    embed = discord.Embed(
        title="🛠️ Diagnostic LBC-FINDER",
        color=discord.Color.teal(),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    embed.add_field(name="Configuration", value=f"`{get_settings_path()}`", inline=False)
    embed.add_field(name="Statistiques", value=f"`{STATS_FILE}`", inline=False)
    embed.add_field(name="Données", value=f"`{DATA_DIR}`", inline=False)
    embed.add_field(name="Niches configurées", value=f"`{len(settings)}`", inline=True)
    embed.add_field(name="Recherches lancées", value=f"`{len(active_searches)}`", inline=True)
    embed.add_field(
        name="Salon alertes",
        value=f"✅ {channel.mention}" if channel else f"❌ {channel_error}",
        inline=False,
    )
    if active_searches:
        embed.add_field(
            name="Niches actives",
            value=", ".join(f"`{name}`" for name in active_searches[:15]),
            inline=False,
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="alerte-test", description="Envoie une alerte de test dans le salon configuré")
async def alertetest(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    channel, channel_error = get_alert_channel()
    if not channel:
        await interaction.followup.send(f"❌ {channel_error}", ephemeral=True)
        return

    embed = discord.Embed(
        title="✅ Alerte de test LBC-FINDER",
        description="Si ce message apparaît, le bot peut envoyer des alertes dans ce salon.",
        color=discord.Color.green(),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    embed.add_field(name="Salon", value=channel.mention, inline=True)
    embed.add_field(name="Demandé par", value=interaction.user.mention, inline=True)

    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        await interaction.followup.send(
            "❌ Le bot n'a pas la permission d'envoyer un message dans le salon configuré.",
            ephemeral=True,
        )
        logger.exception("Impossible d'envoyer l'alerte de test: permission refusée.")
        return
    except discord.HTTPException as exc:
        await interaction.followup.send(
            f"❌ Erreur Discord pendant l'envoi de l'alerte de test : `{exc}`",
            ephemeral=True,
        )
        logger.exception("Impossible d'envoyer l'alerte de test.")
        return

    await interaction.followup.send("✅ Alerte de test envoyée.", ephemeral=True)


@bot.tree.command(name="statistiques", description="Statistiques de recherche par niche")
async def statistiques(interaction: discord.Interaction):
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


@bot.tree.command(name="tester", description="Teste une recherche sans la lancer")
@app_commands.describe(
    mots_cles="Objet recherché (ex: poussette, siege auto, robot tondeuse)",
    marque="Marque obligatoire (ex: cybex, bugaboo, stokke)",
    ville="Ville (optionnel)",
    rayon_km="Rayon en km (défaut: 20)",
    prix_max="Prix maximum en euros (0 = aucun filtre)",
    prix_min="Seuil pépite en euros (0 = désactivé)",
    particuliers_seulement="Ne montrer que les annonces de particuliers",
    filtrage_strict="Exige que les mots-clés importants soient présents dans l'annonce",
)
@app_commands.choices(etat=CONDITION_CHOICES)
async def tester(
    interaction: discord.Interaction,
    mots_cles: str,
    marque: str = "",
    ville: str = "",
    rayon_km: int = 20,
    prix_max: int = 0,
    prix_min: int = 0,
    particuliers_seulement: bool = False,
    filtrage_strict: bool = True,
    etat: app_commands.Choice[str] = None,
):
    await interaction.response.defer(ephemeral=True)
    mots_cles = normalize_text(mots_cles)
    marque = normalize_text(marque)
    ville = normalize_text(ville)

    if not mots_cles:
        await interaction.followup.send(
            "❌ Les mots-clés ne peuvent pas être vides.",
            ephemeral=True,
        )
        return

    if rayon_km <= 0:
        await interaction.followup.send(
            "❌ Le rayon doit être supérieur à 0 km.",
            ephemeral=True,
        )
        return

    if prix_max < 0 or prix_min < 0 or (prix_max and prix_min > prix_max):
        await interaction.followup.send(
            "❌ Vérifiez les prix : ils doivent être positifs, et le seuil pépite ne peut pas dépasser le prix max.",
            ephemeral=True,
        )
        return

    cfg = {
        "max_price": prix_max or None,
        "min_price": prix_min,
        "condition": etat.value if etat and etat.value != "all" else None,
        "keywords": mots_cles,
        "marque": marque,
        "filtrage_strict": filtrage_strict,
        "mots_obligatoires": keyword_tokens(mots_cles),
    }

    def run_simulate():
        try:
            from lbc import Client, Sort
            client = Client()
            params = {"text": f"{mots_cles} {marque}".strip()}
            if prix_max > 0:
                params["price"] = [0, prix_max]
            if particuliers_seulement:
                params["owner_type"] = lbc.OwnerType.PRIVATE
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
        title=f"🧪 Test — `{mots_cles}`" + (f" / `{marque}`" if marque else ""),
        description=f"📍 {location_info}\n📋 **{total} annonce(s)** trouvée(s) sur Leboncoin en ce moment.",
        color=discord.Color.orange()
    )
    for ad in result:
        reason = get_filter_reason(ad, cfg)
        status = f"🚫 Filtrée : {reason}" if reason else "✅ Alerte possible"
        if not reason and is_bargain_ad(ad, cfg):
            status = "🚨 Pépite possible"
        embed.add_field(
            name=_ad_field(ad, "subject", "title", default="Annonce")[:50],
            value=f"💶 {_ad_field(ad, 'price', default='?')} € — {status}\n[Voir l'annonce]({_ad_field(ad, 'url', default='https://www.leboncoin.fr')})",
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
    channel, channel_error = get_alert_channel()
    if not channel:
        logger.error("[Bot] %s", channel_error)
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

    ad_url = _ad_field(ad, "url", default=None)
    view = AutobuyView(ad_url) if ad_url else None

    future = asyncio.run_coroutine_threadsafe(
        channel.send(embed=embed, view=view),
        bot.loop,
    )

    def _log_send_result(done):
        try:
            done.result()
        except discord.Forbidden:
            logger.exception(
                "[%s] Alerte non envoyée: permission Discord refusée.",
                search_name,
            )
        except discord.HTTPException:
            logger.exception("[%s] Alerte non envoyée: erreur HTTP Discord.", search_name)
        except Exception:
            logger.exception("[%s] Alerte non envoyée.", search_name)

    future.add_done_callback(_log_send_result)


# ─────────────────────────────────────────────
# Start
# ─────────────────────────────────────────────

def start_bot():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ DISCORD_TOKEN manquant dans les variables d'environnement.")
        return
    bot.run(token)
