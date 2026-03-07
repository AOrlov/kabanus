import logging

from src import config, logging_utils
from src.bot.app import build_application
from src.bot.reaction_service import ReactionState
from src.bot.runtime import BotRuntime
from src.provider_factory import build_provider

logging_utils.configure_bootstrap()
settings = config.get_settings()
logging_utils.configure_logging(settings)

logger = logging.getLogger(__name__)
model_provider = build_provider()


def build_runtime() -> BotRuntime:
    return BotRuntime(
        model_provider=model_provider,
        logger=logger,
        get_settings=config.get_settings,
    )


def main() -> None:
    runtime = build_runtime()
    app = build_application(runtime, ReactionState())
    logger.info("Bot started with features: %s", runtime.get_settings().features)
    app.run_polling()


if __name__ == "__main__":
    main()
