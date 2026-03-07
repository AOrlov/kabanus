from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from src.message_store import add_message, build_context

from src.bot.access import is_allowed, log_context, storage_id
from src.bot.addressing_service import (
    AddressingRequest,
    resolve_addressing_decision,
    resolve_reply_target_if_needed,
)
from src.bot.message_input_service import normalize_inbound_message
from src.bot.reaction_service import (
    REACTION_ALLOWED_LIST,
    REACTION_ALLOWED_SET,
    ReactionState,
    maybe_react as maybe_react_impl,
)
from src.bot.response_generation_service import (
    build_outgoing_text,
    build_prompt,
    generate_response_with_retries,
    log_prompt_if_debug,
)
from src.bot.response_service import send_ai_response
from src.bot.runtime import BotRuntime


def build_handle_addressed_message_handler(
    runtime: BotRuntime,
    reaction_state: ReactionState,
):
    async def handle_addressed_message(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        runtime.logger.debug(
            "handle_addressed_message called", extra=log_context(update)
        )
        settings = runtime.get_settings()
        if (
            not is_allowed(
                update,
                settings_getter=runtime.get_settings,
                logger=runtime.logger,
            )
            or not settings.features["message_handling"]
        ):
            return
        if not update.message or not update.effective_user or not update.effective_chat:
            return
        if update.effective_user.is_bot:
            return

        inbound = await normalize_inbound_message(
            update,
            context,
            model_provider=runtime.model_provider,
            logger=runtime.logger,
        )
        if inbound is None:
            return

        add_message(
            inbound.sender,
            inbound.text,
            is_bot=False,
            chat_id=inbound.storage_id,
            telegram_message_id=update.message.message_id,
            reply_to_telegram_message_id=inbound.reply_to_telegram_message_id,
        )

        await maybe_react_impl(
            update,
            inbound.text,
            state=reaction_state,
            settings_getter=runtime.get_settings,
            model_provider=runtime.model_provider,
            logger=runtime.logger,
            log_context_fn=log_context,
            storage_id_fn=storage_id,
            allowed_list=REACTION_ALLOWED_LIST,
            allowed_set=REACTION_ALLOWED_SET,
        )

        bot = await context.bot.get_me()
        decision = resolve_addressing_decision(
            update,
            request=AddressingRequest(
                text=inbound.text,
                is_transcribed_text=inbound.is_transcribed_text,
                bot_username=bot.username or "",
                bot_id=bot.id,
                aliases=settings.bot_aliases,
            ),
        )
        runtime.logger.debug(
            "Addressing decision",
            extra={
                **log_context(update),
                "mentioned_bot": decision.mentioned_bot,
                "replied_to_bot": decision.replied_to_bot,
                "replied_to_other_user": decision.replied_to_other_user,
                "triggered": decision.should_respond,
            },
        )

        if not decision.should_respond:
            if inbound.is_transcribed_text:
                await update.effective_chat.send_action(action=ChatAction.TYPING)
                await update.message.reply_text(inbound.text)
            return

        reply_target_context = await resolve_reply_target_if_needed(
            update,
            decision=decision,
            chat_id=inbound.storage_id,
            context=context,
            model_provider=runtime.model_provider,
        )
        if settings.debug_mode and reply_target_context is not None:
            runtime.logger.debug(
                "Resolved reply target context",
                extra={
                    **log_context(update),
                    "source": reply_target_context.get("source", ""),
                    "reply_target_preview": reply_target_context.get("text", "")[:256],
                },
            )

        await update.effective_chat.send_action(action=ChatAction.TYPING)
        context_text = build_context(
            chat_id=inbound.storage_id,
            latest_user_text=inbound.text,
            summarize_fn=runtime.model_provider.generate_low_cost,
        )
        prompt = build_prompt(
            context_text=context_text,
            sender=inbound.sender,
            latest_text=inbound.text,
            reply_target_context=reply_target_context,
        )
        log_prompt_if_debug(
            prompt=prompt,
            settings=settings,
            logger=runtime.logger,
            update=update,
        )

        response = await generate_response_with_retries(
            update,
            prompt=prompt,
            settings=settings,
            model_provider=runtime.model_provider,
            logger=runtime.logger,
        )
        if not response:
            return

        outgoing_text = build_outgoing_text(
            source_text=inbound.text,
            response_text=response,
            is_transcribed_text=inbound.is_transcribed_text,
        )
        await send_ai_response(
            update,
            outgoing_text,
            inbound.storage_id,
            settings_getter=runtime.get_settings,
            logger=runtime.logger,
            log_context_fn=log_context,
        )

    return handle_addressed_message
