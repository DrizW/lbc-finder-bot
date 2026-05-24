from searcher import Searcher
from config import CONFIG

from bot import start_bot

def main() -> None:
    searcher = Searcher(searches=CONFIG)
    searcher.start()
    start_bot()


if __name__ == "__main__":
    main()
