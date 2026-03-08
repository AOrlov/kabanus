import logging

from src import config, logging_utils
from src.bot import app as bot_app

logger = logging.getLogger(__name__)


def run() -> None:
    logging_utils.configure_bootstrap()
    settings = config.get_settings()
    logging_utils.configure_logging(settings)
    bot_app.run_polling()


if __name__ == "__main__":
    run()
