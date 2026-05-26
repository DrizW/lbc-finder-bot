# lbc-finder
[![GitHub license](https://img.shields.io/github/license/etienne-hd/lbc?style=for-the-badge)](https://github.com/etienne-hd/lbc/blob/master/LICENSE)

**Stay notified when new ads appear on Leboncoin**

This fork is configured from Discord slash commands. Searches are saved in
`data/settings.json`, so there is no built-in "Paris" search in the runtime code.
*lbc-finder is not affiliated with, endorsed by, or in any way associated with Leboncoin or its services. Use at your own risk.*

This project uses [lbc](https://github.com/etienne-hd/lbc), an unofficial library to interact with Leboncoin API.

## Features
* Advanced Search (text, category, price, location, square, etc.)
* Proxy Support for anonymity and bypassing rate limits
* Custom Logger with log file
* Configurable search interval (delay)
* Handler function triggered on new ads for full customization
* Multiple simultaneous searches with threading
* Easy integration with notifications (Discord, Telegram, email…) via handler

## Installation

Required **Python 3.10+**
1. **Clone the repository**
    ```bash
    git clone https://github.com/DrizW/lbc-finder-bot.git
    cd lbc-finder-bot
    ```
2. **Install dependencies**
    ```bash
    pip install .
    ```

    With **uv**:
    ```bash
    uv sync
    ```

## Docker

You can run **lbc-finder** using Docker without installing Python locally.

### Build locally

Build this fork locally before deployment so the Discord commands and LXC fixes are included:

```bash
docker build -t lbc-finder .
```

### Run the container

```bash
docker run -d \
  --name lbc-finder \
  --env-file .env \
  -v lbc_data:/app/data \
  lbc-finder
```

### Volumes

| Path in container | Description                                                                                         |
| ----------------- | --------------------------------------------------------------------------------------------------- |
| `/app/config`     | Optional `requirements.txt` for additional Python libraries |
| `/app/data`       | Persistent storage for searches, stats, detected ads and logs |

Example:

```bash
-v $(pwd)/config:/app/config
```

Searches created with `/ajouter-niche` are stored in `/app/data/settings.json`.

### LXC / Proxmox

For a Proxmox LXC, keep one persistent data directory and point the bot to it:

```env
DISCORD_TOKEN=your_discord_bot_token
DISCORD_CHANNEL_ID=your_alert_channel_id
LBC_DATA_DIR=/opt/lbc-finder/data
```

After deploy, run `/diagnostic` to confirm the bot reads the expected
`settings.json`, then run `/alerte-test` to confirm Discord delivery.

> **Extra Python libraries:**
> If your configuration requires additional Python packages, create a `requirements.txt` file inside your `config/` folder.
> The container startup script will automatically install all listed packages before running **lbc-finder**:

```sh
#!/bin/sh
if [ -e config/requirements.txt ]
then
    uv add -r config/requirements.txt
fi

exec "$@"
```

This way, you can extend the container with any Python library you need without modifying the Docker image itself.


## Configuration
Searches are managed from Discord. The bot does not load a hard-coded default niche.

Runtime files are stored in `data/` by default:

| File | Description |
| ---- | ----------- |
| `data/settings.json` | Niches created with `/ajouter-niche` |
| `data/stats.json` | Compteurs de recherches et d'alertes |
| `data/id.json` | Already seen Leboncoin ad IDs |
| `data/logs/` | Warning/error logs |

The bot only loads niches from `data/settings.json` by default. Old
`settings.json` files next to the Python code are ignored to avoid stale demo
searches being loaded after deployment.

You can override these paths with environment variables:

| Variable | Description |
| -------- | ----------- |
| `LBC_DATA_DIR` | Directory used for runtime files |
| `LBC_SETTINGS_FILE` | Full path to the searches JSON file |
| `LBC_STATS_FILE` | Full path to the stats JSON file |

### Discord Commands

| Command | Description |
| ------- | ----------- |
| `/ajouter-niche` | Ajoute ou met à jour une niche avec mots-clés, prix, ville, rayon, état, type de vendeur et filtrage strict |
| `/supprimer-niche` | Supprime une niche |
| `/vider-niches` | Supprime toutes les niches configurées |
| `/diagnostic` | Affiche les chemins utilisés, les recherches actives et le salon Discord |
| `/alerte-test` | Envoie une alerte de test dans le salon configuré |
| `/pause` | Met une niche en pause sans la supprimer |
| `/reprendre` | Relance une niche mise en pause |
| `/niches` | Liste les niches configurées et leur statut |
| `/statistiques` | Affiche les annonces trouvées, filtrées et alertées |
| `/tester` | Teste une recherche sans la lancer, avec les mêmes filtres locaux que les alertes |

Le champ `marque` est optionnel mais recommandé. Pour une niche comme
`mots_cles: poussette` et `marque: cybex`, le bot filtre localement les annonces
qui ne contiennent pas `cybex` dans leur titre, description ou attributs, même si
Leboncoin les renvoie dans les résultats.

Le bouton des alertes ouvre l'annonce Leboncoin officielle. Il ne tente pas
d'ouvrir directement une page de paiement, car les liens d'achat immédiat ne sont
pas publics/stables et peuvent renvoyer une page 404.

### Search Parameters

All available parameters are documented in the [lbc](https://github.com/etienne-hd/lbc) repository.

### Delay

Each active niche is checked every 60 seconds.

### Handler

This function is called whenever a new ad appears.
It must accept two parameters:

* the `Ad` object
* the name (label) of the search (e.g. **"Porsche 944"**)

```python
def handle(ad: lbc.Ad, search_name: str) -> None:
    ...
```
You can find example handlers in the [examples](examples/) folder.

### Proxy

You can configure a proxy, here is an example:

```python
from lbc import Proxy
from model import Search

proxy = Proxy(
    host="127.0.0.1",
    port=9444,
    username="etienne",
    password="123456"
)

Search(
    name=...,
    parameters=...,
    delay=...,
    handler=...,
    proxy=proxy
)
```

## Usage
To run **lbc-finder**, simply start the `main.py` file:
```bash
python main.py
```

## License

This project is licensed under the MIT License.

## Support

<a href="https://www.buymeacoffee.com/etienneh" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;" ></a>

You can reach out to me on [Telegram](https://t.me/etienne_hd) or [Discord](https://discord.com/users/1153975318990827552) if you're looking for custom scraping services.
