# Config is now fully dynamic — searches are managed via Discord commands:
#   /addsearch  — ajouter une niche
#   /delsearch  — supprimer une niche
#   /listsearches — lister les niches actives
#
# This file is kept for import compatibility only.

from .handler import handle  # noqa: F401

CONFIG = []  # Empty — loaded dynamically from settings.json at startup
