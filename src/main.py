import logging

from src import logging_utils
from src.bot import app as bot_app

logger = logging.getLogger(__name__)


def run() -> None:
    logging_utils.configure_bootstrap()
    bot_app.run()


if __name__ == "__main__":
    run()
