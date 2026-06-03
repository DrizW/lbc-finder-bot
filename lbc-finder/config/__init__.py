# Config is now fully dynamic — searches are managed via Discord commands:
#   /ajouter-niche  — ajouter une niche
#   /supprimer-niche  — supprimer une niche
#   /niches — lister les niches actives
#
# This file is kept for import compatibility only.

try:
    from .handler import handle  # noqa: F401
except ModuleNotFoundError:
    handle = None

CONFIG = []  # Empty — loaded dynamically from settings.json at startup
