from model import Search, Parameters
import lbc

from .handler import handle

CONFIG = [
    Search(
        name="Poussette Cybex",
        parameters=Parameters(
            text="poussette cybex",
        ),
        delay=60,  # Check every 1 minute for better reactivity
        handler=handle,
    ),
]
