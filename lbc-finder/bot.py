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
from model import Search, Parameters
from sources import get_source
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


def parse_sources(value: str | list[str] | None) -> list[str]:
    if isinstance(value, list):
        raw_sources = value
    else:
        raw_sources = str(value or "leboncoin").split(",")
    sources = []
    for source in raw_sources:
        normalized = normalize_for_match(source).strip()
        if normalized in {"lbc", "leboncoin"}:
            normalized = "leboncoin"
        if normalized and normalized not in sources:
            sources.append(normalized)
    return sources or ["leboncoin"]


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


def _ad_brand_values(ad: lbc.Ad) -> list[str]:
    values = []
    brand_keys = {"brand", "marque", "make", "manufacturer", "fabricant"}
    for source_name in ("attributes", "options"):
        source = getattr(ad, source_name, None)
        if isinstance(source, dict):
            for key, value in source.items():
                if normalize_for_match(key) in brand_keys and value is not None:
                    values.append(str(value))
        elif isinstance(source, list):
            for item in source:
                if not isinstance(item, dict):
                    continue
                key = normalize_for_match(
                    item.get("key") or item.get("name") or item.get("id") or ""
                )
                if key not in brand_keys:
                    continue
                value = item.get("value") or item.get("values")
                if isinstance(value, list):
                    values.extend(str(part) for part in value if part is not None)
                elif value is not None:
                    values.append(str(value))
    return values


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

    brand_tokens = keyword_tokens(brand)
    if not brand_tokens:
        return None

    structured_brands = _ad_brand_values(ad)
    if structured_brands:
        for value in structured_brands:
            normalized_value = normalize_for_match(value)
            if all(token in normalized_value for token in brand_tokens):
                return None
        return brand

    searchable = _ad_match_text(ad)
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

    return Search(
        name=name,
        parameters=Parameters(**_search_parameters_kwargs(name, cfg)),
        delay=60,
        handler=handle,
        sources=parse_sources(cfg.get("sources")),
    )


def _search_parameters_kwargs(name: str, cfg: dict) -> dict:
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

    return params_kwargs


def _format_ad_location(ad) -> str:
    location = _ad_field(ad, "location", default="")
    if not location:
        return "Localisation non précisée"
    for attr in ("city_label", "city", "zipcode", "department_name", "region_name"):
        value = getattr(location, attr, None)
        if value:
            return str(value)
    if isinstance(location, dict):
        for key in ("city_label", "city", "zipcode", "department_name", "region_name"):
            if location.get(key):
                return str(location[key])
    return str(location)


def _parse_ad_datetime(ad):
    value = _ad_field(ad, "index_date", "published_at", "created_at", default=None)
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(value, datetime.time.min)
    if isinstance(value, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(value)
        except (OSError, ValueError):
            return None

    raw = str(value).strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        return datetime.datetime.fromisoformat(normalized)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(raw[: len(fmt)], fmt)
        except ValueError:
            continue
    return None


def _is_today_or_unknown(ad) -> bool:
    published = _parse_ad_datetime(ad)
    if published is None:
        return True
    if published.tzinfo is not None:
        published = published.astimezone().replace(tzinfo=None)
    return published.date() == datetime.datetime.now().date()


def _ad_date_label(ad) -> str:
    published = _parse_ad_datetime(ad)
    if published is None:
        return "date non précisée"
    return published.strftime("%d/%m/%Y %H:%M")


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

MATCH_MODE_CHOICES = [
    app_commands.Choice(name="Équilibré", value="equilibre"),
    app_commands.Choice(name="Large", value="large"),
    app_commands.Choice(name="Strict", value="strict"),
]

MATCH_MODE_LABELS = {
    "large": "Large",
    "equilibre": "Équilibré",
    "strict": "Strict",
}

MATCH_MODE_HEAT_SCORES = {
    "large": 0,
    "equilibre": 35,
    "strict": 55,
}


def normalize_match_mode(mode: app_commands.Choice[str] | str | None) -> str:
    if isinstance(mode, app_commands.Choice):
        value = mode.value
    else:
        value = mode
    return value if value in MATCH_MODE_LABELS else "equilibre"


def required_tokens_for_mode(keywords: str, mode: str) -> list[str]:
    tokens = keyword_tokens(keywords)
    if mode == "large":
        return []
    if mode == "strict":
        return tokens
    return tokens[:4]


async def configured_niche_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    needle = normalize_for_match(current)
    choices = []
    for name, cfg in load_settings().items():
        if not isinstance(cfg, dict):
            continue
        if needle and needle not in normalize_for_match(name):
            continue
        choices.append(app_commands.Choice(name=name[:100], value=name))
        if len(choices) >= 25:
            break
    return choices


def delete_configured_niche(niche: str) -> tuple[bool, str]:
    settings = load_settings()
    if niche not in settings:
        return False, f"❌ La niche `{niche}` est introuvable."

    del settings[niche]
    save_settings(settings)
    logger.info("[%s] Niche supprimée.", niche)

    if _searcher is not None:
        _searcher.remove_search_thread(niche)

    return True, f"🗑️ Niche **{niche}** supprimée."


@bot.tree.command(
    name="ajouter-niche",
    description="Ajoute une niche de recherche simple ou précise"
)
@app_commands.describe(
    niche="Nom court de la niche (ex: Poussette Cybex, Plaque induction)",
    mots_cles="Ce que tu veux surveiller (ex: cybex priam, plaque induction, iphone 14)",
    prix_max="Budget maximum en euros (0 = aucun plafond)",
    marque="Marque obligatoire si tu veux verrouiller une marque",
    mode="Large = plus d'alertes, Équilibré = recommandé, Strict = plus sélectif",
    prix_min="Seuil pépite en euros (0 = désactivé)",
    ville="Ville pour la recherche géolocalisée (laisser vide = France entière)",
    rayon_km="Rayon en km autour de la ville (défaut: 20)",
    particuliers_seulement="Ne montrer que les annonces de particuliers",
    sources="Sources à surveiller séparées par virgule: leboncoin, ebay",
)
@app_commands.choices(etat=CONDITION_CHOICES, mode=MATCH_MODE_CHOICES)
async def ajouterniche(
    interaction: discord.Interaction,
    niche: str,
    mots_cles: str,
    prix_max: int = 0,
    marque: str = "",
    mode: app_commands.Choice[str] = None,
    prix_min: int = 0,
    ville: str = "",
    rayon_km: int = 20,
    particuliers_seulement: bool = False,
    sources: str = "leboncoin",
    etat: app_commands.Choice[str] = None,
):
    await interaction.response.defer(ephemeral=True)
    niche = normalize_text(niche)
    mots_cles = normalize_text(mots_cles)
    marque = normalize_text(marque)
    ville = normalize_text(ville)
    source_names = parse_sources(sources)
    mode_value = normalize_match_mode(mode)
    required_tokens = required_tokens_for_mode(mots_cles, mode_value)

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

    if prix_max < 0:
        await interaction.followup.send(
            "❌ Le budget maximum ne peut pas être négatif.",
            ephemeral=True
        )
        return

    if prix_min < 0:
        await interaction.followup.send(
            "❌ Le seuil pépite ne peut pas être négatif.",
            ephemeral=True
        )
        return

    if prix_max and prix_min > prix_max:
        await interaction.followup.send(
            "❌ Le seuil pépite doit être inférieur ou égal au budget maximum.",
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
        "max_price": prix_max or None,
        "min_price": prix_min,
        "mode_match": mode_value,
        "min_heat_score": MATCH_MODE_HEAT_SCORES[mode_value],
        "city": ville,
        "lat": None,
        "lng": None,
        "radius_km": rayon_km,
        "owner_type": "private" if particuliers_seulement else "all",
        "condition": etat.value if etat and etat.value != "all" else None,
        "filtrage_strict": mode_value != "large",
        "mots_obligatoires": required_tokens,
        "sources": source_names,
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
            and existing.get("max_price") == (prix_max or None)
            and existing.get("mode_match", "equilibre") == mode_value
            and parse_sources(existing.get("sources")) == source_names
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
        "[%s] Niche enregistrée: mots_cles=%r marque=%r prix_max=%s seuil_pepite=%s ville=%r rayon=%s vendeur=%s etat=%s sources=%s",
        niche,
        mots_cles,
        marque or "non définie",
        prix_max or "aucun",
        prix_min,
        ville or "France entière",
        rayon_km,
        entry["owner_type"],
        entry["condition"] or "all",
        ",".join(source_names),
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
    extras.append(f"🎯 Mode : `{MATCH_MODE_LABELS[mode_value]}`")
    if required_tokens:
        extras.append(f"🧩 Mots exigés : `{', '.join(required_tokens)}`")
    extras.append(f"🌐 Sources : `{', '.join(source_names)}`")
    budget_line = (
        f"💶 Budget max : `{prix_max} €`\n"
        if prix_max
        else "💶 Budget max : `aucun`\n"
    )

    await interaction.followup.send(
        f"✅ Niche **{niche}** ajoutée !\n"
        f"🔍 Mots-clés : `{mots_cles}`\n"
        + (f"🏷️ Marque : `{marque}`\n" if marque else "")
        + f"🌐 Sources : `{', '.join(source_names)}`\n"
        + budget_line
        + f"📍 Localisation : {location_info}"
        + (("\n" + "\n".join(extras)) if extras else ""),
        ephemeral=True
    )


@bot.tree.command(name="supprimer-une-niche", description="Supprime une seule niche configurée")
@app_commands.describe(niche="Nom de la niche à supprimer")
@app_commands.autocomplete(niche=configured_niche_autocomplete)
async def supprimeruneniche(interaction: discord.Interaction, niche: str):
    _, message = delete_configured_niche(niche)
    await interaction.response.send_message(message, ephemeral=True)


@bot.tree.command(name="supprimer-niche", description="Alias: supprime une seule niche")
@app_commands.describe(niche="Nom de la niche à supprimer")
@app_commands.autocomplete(niche=configured_niche_autocomplete)
async def supprimerniche(interaction: discord.Interaction, niche: str):
    _, message = delete_configured_niche(niche)
    await interaction.response.send_message(message, ephemeral=True)


@bot.tree.command(name="retirer-niche", description="Alias: retire une seule niche")
@app_commands.describe(niche="Nom de la niche à retirer")
@app_commands.autocomplete(niche=configured_niche_autocomplete)
async def retirerniche(interaction: discord.Interaction, niche: str):
    _, message = delete_configured_niche(niche)
    await interaction.response.send_message(message, ephemeral=True)


@bot.tree.command(name="vider-niches", description="Supprime toutes les niches configurées")
async def viderlesniches(interaction: discord.Interaction):
    settings = load_settings()
    stopped_threads = []

    if _searcher is not None:
        stopped_threads = _searcher.remove_all_search_threads()

    save_settings({})
    logger.info(
        "Toutes les niches ont été supprimées. Threads stoppés: %s",
        ", ".join(stopped_threads) if stopped_threads else "aucun",
    )
    details = (
        f"\nThreads arrêtés : `{', '.join(stopped_threads)}`"
        if stopped_threads
        else ""
    )
    await interaction.response.send_message(
        "🧹 Toutes les niches ont été supprimées. "
        "Vous pouvez repartir avec `/ajouter-niche`."
        + details,
        ephemeral=True
    )


@bot.tree.command(name="pause", description="Met une niche en pause")
@app_commands.describe(niche="Nom de la niche à mettre en pause")
@app_commands.autocomplete(niche=configured_niche_autocomplete)
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
@app_commands.autocomplete(niche=configured_niche_autocomplete)
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
        extras.append(f"🌐 Sources : {', '.join(parse_sources(cfg.get('sources')))}")
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
                f"**Sources :** `{', '.join(parse_sources(cfg.get('sources')))}`\n"
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


@bot.tree.command(
    name="annonces-du-jour",
    description="Affiche les annonces vues aujourd'hui pour une niche configurée",
)
@app_commands.describe(
    niche="Niche à consulter",
    limite="Nombre maximum d'annonces à afficher",
)
@app_commands.autocomplete(niche=configured_niche_autocomplete)
async def annoncesdujour(
    interaction: discord.Interaction,
    niche: str,
    limite: int = 10,
):
    await interaction.response.defer(ephemeral=True)
    settings = load_settings()
    cfg = settings.get(niche)
    if not isinstance(cfg, dict):
        await interaction.followup.send(
            f"❌ La niche `{niche}` est introuvable.",
            ephemeral=True,
        )
        return

    limite = max(1, min(20, limite))

    def run_lookup():
        from config.handler import _raw_listing_from_ad, _search_intent_reason

        search = Search(
            name=niche,
            parameters=Parameters(**_search_parameters_kwargs(niche, cfg)),
            delay=60,
            handler=lambda _ad, _name: None,
            sources=parse_sources(cfg.get("sources")),
        )
        rows = []
        errors = []
        for source_name in search.sources or ["leboncoin"]:
            source = get_source(source_name)
            if source is None:
                errors.append(f"source inconnue: {source_name}")
                continue
            try:
                ads = source.search(search)
            except Exception as exc:
                logger.exception("[%s] Erreur annonces-du-jour source %s", niche, source_name)
                errors.append(f"{source_name}: {exc}")
                continue

            for ad in ads:
                if not _is_today_or_unknown(ad):
                    continue
                reason = get_filter_reason(ad, cfg)
                if not reason:
                    raw = _raw_listing_from_ad(ad)
                    reason = _search_intent_reason(raw, cfg)
                status = f"Filtrée: {reason}" if reason else "Candidate"
                rows.append((source_name, ad, status))
                if len(rows) >= limite:
                    return rows, errors
        return rows, errors

    rows, errors = await asyncio.get_event_loop().run_in_executor(None, run_lookup)

    location = (
        f"{cfg.get('city')} ({cfg.get('radius_km', 20)} km)"
        if cfg.get("city")
        else "France entière"
    )
    embed = discord.Embed(
        title=f"Annonces du jour - {niche}",
        description=(
            f"Mots-clés : `{cfg.get('keywords', niche)}`\n"
            f"Marque : `{cfg.get('marque') or '—'}`\n"
            f"Zone : {location}\n"
            f"Sources : `{', '.join(parse_sources(cfg.get('sources')))}`"
        ),
        color=discord.Color.blurple(),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )

    if not rows:
        detail = "\n".join(errors) if errors else "Aucune annonce du jour trouvée sur cette niche."
        embed.add_field(name="Résultat", value=detail[:1000], inline=False)
    else:
        for source_name, ad, status in rows:
            title = _ad_field(ad, "subject", "title", default="Annonce")[:80]
            price = _ad_field(ad, "price", default="?")
            url = _ad_field(ad, "url", default="")
            value = (
                f"Prix : `{price} €`\n"
                f"Statut : `{status}`\n"
                f"Date : `{_ad_date_label(ad)}`\n"
                f"Lieu : `{_format_ad_location(ad)}`\n"
                f"Source : `{source_name}`"
            )
            if url:
                value += f"\n[Voir l'annonce]({url})"
            embed.add_field(name=title, value=value[:1000], inline=False)
        if errors:
            embed.set_footer(text="Certaines sources ont renvoyé une erreur: " + " | ".join(errors)[:150])

    await interaction.followup.send(embed=embed, ephemeral=True)


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
    mode="Large = plus de résultats, Équilibré = recommandé, Strict = plus sélectif",
    ville="Ville (optionnel)",
    rayon_km="Rayon en km (défaut: 20)",
    prix_max="Prix maximum en euros (0 = aucun filtre)",
    prix_min="Seuil pépite en euros (0 = désactivé)",
    particuliers_seulement="Ne montrer que les annonces de particuliers",
    sources="Sources à tester séparées par virgule: leboncoin, ebay",
)
@app_commands.choices(etat=CONDITION_CHOICES, mode=MATCH_MODE_CHOICES)
async def tester(
    interaction: discord.Interaction,
    mots_cles: str,
    marque: str = "",
    mode: app_commands.Choice[str] = None,
    ville: str = "",
    rayon_km: int = 20,
    prix_max: int = 0,
    prix_min: int = 0,
    particuliers_seulement: bool = False,
    sources: str = "leboncoin",
    etat: app_commands.Choice[str] = None,
):
    await interaction.response.defer(ephemeral=True)
    mots_cles = normalize_text(mots_cles)
    marque = normalize_text(marque)
    ville = normalize_text(ville)
    source_names = parse_sources(sources)
    mode_value = normalize_match_mode(mode)
    required_tokens = required_tokens_for_mode(mots_cles, mode_value)

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
        "mode_match": mode_value,
        "filtrage_strict": mode_value != "large",
        "mots_obligatoires": required_tokens,
        "sources": source_names,
    }

    def run_simulate():
        try:
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
            simulated_search = Search(
                name="simulation",
                parameters=Parameters(**params),
                delay=60,
                handler=lambda _ad, _name: None,
                sources=source_names,
            )
            ads = []
            for source_name in source_names:
                source = get_source(source_name)
                if source is None:
                    continue
                ads.extend(source.search(simulated_search))
            return len(ads), ads[:3]
        except Exception as e:
            return None, str(e)

    total, result = await asyncio.get_event_loop().run_in_executor(None, run_simulate)

    if total is None:
        await interaction.followup.send(f"❌ Erreur lors de la simulation : `{result}`", ephemeral=True)
        return

    location_info = f"autour de **{ville}** ({rayon_km} km)" if ville else "**France entière**"
    embed = discord.Embed(
        title=f"🧪 Test — `{mots_cles}`" + (f" / `{marque}`" if marque else ""),
        description=(
            f"📍 {location_info}\n"
            f"🌐 Sources : **{', '.join(source_names)}**\n"
            f"🎯 Mode : **{MATCH_MODE_LABELS[mode_value]}**\n"
            f"📋 **{total} annonce(s)** trouvée(s)."
        ),
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
    source_name = _ad_field(ad, "source", default="leboncoin")
    embed.add_field(name="🌐 Source", value=str(source_name), inline=True)

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


def _product_context_label(opportunity) -> str:
    analysis = opportunity.analysis
    raw = opportunity.raw
    return " ".join(
        part
        for part in [
            analysis.detected_brand,
            analysis.detected_model,
            analysis.detected_product_type,
        ]
        if part
    ) or raw.title or "votre annonce"


def _generic_checks(opportunity) -> list[str]:
    analysis = opportunity.analysis
    product_type = normalize_for_match(analysis.detected_product_type)

    if analysis.risk_flags:
        return analysis.risk_flags
    if "console" in product_type:
        return [
            "vérifier que la console s'allume",
            "tester les manettes et les ports",
            "demander si le compte est dissocié",
            "confirmer les accessoires inclus",
        ]
    if "smartphone" in product_type or "telephone" in product_type:
        return [
            "vérifier blocage iCloud/Google",
            "contrôler batterie et écran",
            "demander facture ou preuve d'achat",
            "tester charge, son et appareil photo",
        ]
    if "aspirateur" in product_type:
        return [
            "tester l'aspiration",
            "vérifier batterie et chargeur",
            "contrôler brosses et filtres",
            "demander les accessoires inclus",
        ]
    if "induction" in product_type or "cuisson" in product_type:
        return [
            "vérifier que toutes les zones chauffent",
            "contrôler fissures ou rayures profondes",
            "demander référence exacte et dimensions",
            "confirmer disponibilité du câble ou branchement",
        ]
    if "poussette" in product_type:
        return [
            "vérifier pliage et verrouillage",
            "contrôler roues et freins",
            "vérifier textile et accessoires",
            "demander facture si disponible",
        ]
    return [
        "vérifier l'état réel sur place",
        "demander si tout fonctionne correctement",
        "confirmer les accessoires inclus",
        "demander facture ou preuve d'achat si disponible",
    ]


def _seller_message(opportunity) -> str:
    product = _product_context_label(opportunity)
    return (
        f"Bonjour, votre {product} est-il toujours disponible ?\n"
        "Est-ce que tout fonctionne correctement et y a-t-il des défauts à signaler ? "
        "Je peux me déplacer rapidement si tout est OK."
    )


def send_opportunity_alert_threadsafe(opportunity, search_name: str, niche_name: str | None = None):
    channel, channel_error = get_alert_channel()
    if not channel:
        logger.error("[Bot] %s", channel_error)
        return

    raw = opportunity.raw
    analysis = opportunity.analysis
    market = opportunity.market
    margin = opportunity.margin
    title = (
        f"🔥🔥 {opportunity.heat_score}/100 — {opportunity.heat_label}"
        if opportunity.heat_score >= 85
        else f"🔥 {opportunity.heat_score}/100 — {opportunity.heat_label}"
    )
    product = " ".join(
        part
        for part in [analysis.detected_brand, analysis.detected_model]
        if part
    ) or raw.title

    embed = discord.Embed(
        title=title,
        url=raw.url,
        color=discord.Color.red() if opportunity.heat_score >= 85 else discord.Color.gold(),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    embed.add_field(name="Produit détecté", value=product, inline=False)
    embed.add_field(name="Recherche configurée", value=search_name, inline=True)
    embed.add_field(name="Famille détectée", value=niche_name or "recherche libre", inline=True)
    embed.add_field(name="Prix annonce", value=f"{raw.price} €", inline=True)
    embed.add_field(
        name="Prix médian observé",
        value=f"{market.median} €" if market.median else "insuffisant",
        inline=True,
    )
    embed.add_field(
        name="Comparables",
        value=str(market.comparable_count),
        inline=True,
    )
    embed.add_field(
        name="Revente réaliste",
        value=(
            f"{margin.resale_price_low} à {margin.resale_price_high} €"
            if margin.resale_price_low and margin.resale_price_high
            else "à confirmer"
        ),
        inline=True,
    )
    embed.add_field(
        name="Marge estimée",
        value=(
            f"{margin.estimated_margin_low} à {margin.estimated_margin_high} €"
            if margin.estimated_margin_low is not None
            and margin.estimated_margin_high is not None
            else "à confirmer"
        ),
        inline=True,
    )
    embed.add_field(
        name="État",
        value=analysis.detected_condition or "non détecté",
        inline=True,
    )
    embed.add_field(
        name="Accessoires",
        value=", ".join(analysis.detected_accessories) or "non détectés",
        inline=False,
    )
    embed.add_field(name="Localisation", value=raw.location or "non précisée", inline=True)
    embed.add_field(name="Source", value=raw.platform, inline=True)
    embed.add_field(
        name="Pourquoi c'est intéressant",
        value="\n".join(f"- {reason}" for reason in opportunity.reasons) or "- Score suffisant",
        inline=False,
    )
    checks = _generic_checks(opportunity)
    embed.add_field(
        name="Points à vérifier",
        value="\n".join(f"- {risk}" for risk in checks),
        inline=False,
    )
    embed.add_field(
        name="Message vendeur suggéré",
        value=_seller_message(opportunity),
        inline=False,
    )
    if raw.image_urls:
        embed.set_thumbnail(url=raw.image_urls[0])

    view = AutobuyView(raw.url) if raw.url else None
    future = asyncio.run_coroutine_threadsafe(
        channel.send(embed=embed, view=view),
        bot.loop,
    )
    future.add_done_callback(lambda done: done.exception())


# ─────────────────────────────────────────────
# Start
# ─────────────────────────────────────────────

def start_bot():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ DISCORD_TOKEN manquant dans les variables d'environnement.")
        return
    bot.run(token)
