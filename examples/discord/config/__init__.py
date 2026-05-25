from model import Search, Parameters
import lbc

from .handler import handle

location = lbc.City(
    lat=44.837789,
    lng=-0.57918,
    radius=20_000,  # 20 km
    city="Bordeaux",
)

CONFIG = [
    Search(
        name="Porsche 944 Bordeaux",
        parameters=Parameters(
            text="Porsche 944",
            locations=[location],
            category=lbc.Category.VEHICULES_VOITURES,
            price=[0, 25_000],
        ),
        delay=60 * 5,  # Check every 5 minutes
        handler=handle,
    ),
]
