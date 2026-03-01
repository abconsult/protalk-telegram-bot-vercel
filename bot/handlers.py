import os
import asyncio
import logging
import traceback
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import LabeledPrice, PreCheckoutQuery, CallbackQuery, BufferedInputFile, InlineQueryResultCachedPhoto
from aiogram.utils.deep_linking import create_start_link

from bot.config import ADMIN_ID, OCCASIONS, STYLES, FONTS_LIST, PACKAGES, YUKASSA_TOKEN, MAX_CUSTOM_TEXT_LENGTH
from bot.database import (
    kv, credits_key, get_credits, set_user_state, get_user_state,
    add_credits, pending_key, pop_pending, save_pending,
    record_new_user, get_total_users, get_total_generations, 
    get_total_revenue, record_payment, get_all_users, is_user_exists,
    get_postcards
)
from bot.keyboards import (
    build_occasion_keyboard, build_style_keyboard,
    build_font_keyboard, build_packages_keyboard, build_text_mode_keyboard
)
from bot.services import generate_postcard

logger = logging.getLogger(__name__)

# Referral config
REFERRAL_BONUS_INVITER = 2
REFERRAL_BONUS_INVITEE = 1

# State tracking (addressee is no longer needed)
DEFAULT_STATE = {"occasion": None, "style": None, "font": None, "text_mode": None}

def register_handlers(dp: Dispatcher, bot: Bot):
    
    # ---------------- ADMIN PANEL ----------------

    @dp.message(Command("stats"))
    async def admin_stats(message: types.Message):
        if message.chat.id != ADMIN_ID:
            return
            
        users = get_total_users()
        generations = get_total_generations()
        revenue = get_total_revenue()
        
        text = (
            f"📊 <b>Статистика проекта:</b>\n\n"
            f"👥 Всего пользователей: <b>{users}</b>\n"
            f"🖼 Сгенерировано открыток: <b>{generations}</b>\n"
            f"💰 Общая выручка: <b>{revenue} руб.</b>"
        )
        await message.answer(text, parse_mode="HTML")

    @dp.message(Command("broadcast"))
    async def admin_broadcast(message: types.Message):
        if message.chat.id != ADMIN_ID:
            return
            
        text_to_send = message.text.replace("/broadcast", "").strip()
        if not text_to_send:
            await message.answer("Использование: `/broadcast Ваш текст для рассылки`", parse_mode="Markdown")
            return
            
        users = get_all_users()
        if not users:
            await message.answer("В базе нет пользователей для рассылки.")
            return

        await message.answer(f"⏳ Начинаю рассылку для {len(users)} пользователей...")
        
        success, failed = 0, 0
        for uid in users:
            try:
                await bot.send_message(uid, text_to_send)
                success += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                failed += 1
                logger.warning(f"Failed to send broadcast to {uid}: {e}")
                
        await message.answer(f"✅ <b>Рассылка завершена!</b>\n\nУспешно: {success}\nОшибок (заблокировали бота): {failed}", parse_mode="HTML")

    @dp.message(Command("reset"))
    async def reset_credits(message: types.Message):
        if message.chat.id != ADMIN_ID:
            return
        kv.delete(credits_key(message.chat.id))
        await message.answer("🔄 Счетчик сброшен! Теперь снова доступно 3 бесплатные открытки.")

    @dp.message(Command("clear_state"))
    async def clear_user_state(message: types.Message):
        chat_id = message.chat.id
        set_user_state(chat_id, DEFAULT_STATE.copy())
        await message.answer("🧹 Состояние очищено. Начните заново с /start")

    # ---------------- INLINE MODE ----------------
    
    @dp.inline_query()
    async def inline_query_handler(inline_query: types.InlineQuery):
        name = inline_query.query.strip()
        user_id = inline_query.from_user.id
        
        postcards = get_postcards(user_id)
        if not postcards:
            # User has no postcards saved yet
            await inline_query.answer(
                results=[],
                cache_time=1,
                is_personal=True,
                switch_pm_text="✨ Создать открытку",
                switch_pm_parameter="create"
            )
            return

        results = []
        for idx, pc in enumerate(postcards):
            caption_text = pc.get("caption", "")
            
            # Form the final caption depending on if a name was typed
            if name:
                # e.g., "Маша, от всей души поздравляю..."
                first_letter = caption_text[0].lower() if caption_text else ""
                rest = caption_text[1:] if len(caption_text) > 1 else ""
                final_caption = f"{name}, {first_letter}{rest}"
            else:
                # Just show how it will look
                final_caption = f"..., {caption_text}"
            
            results.append(
                InlineQueryResultCachedPhoto(
                    id=str(idx),
                    photo_file_id=pc['file_id'],
                    caption=final_caption
                )
            )
        
        await inline_query.answer(
            results,
            cache_time=1,
            is_personal=True,
            switch_pm_text="➕ Создать ещё",
            switch_pm_parameter="create"
        )


    # ---------------- USER FLOW ----------------

    @dp.message(CommandStart())
    async def start(message: types.Message):
        chat_id = message.chat.id
        
        args = message.text.split()
        referral_text = ""
        
        if not is_user_exists(chat_id):
            record_new_user(chat_id)
            
            if len(args) > 1 and args[1].isdigit():
                inviter_id = int(args[1])
                if inviter_id != chat_id:
                    add_credits(chat_id, REFERRAL_BONUS_INVITEE)
                    referral_text = f"🎉 <b>Вы перешли по приглашению!</b>\nВам начислен дополнительный <b>+{REFERRAL_BONUS_INVITEE} кредит</b>.\n\n"
                    
                    try:
                        add_credits(inviter_id, REFERRAL_BONUS_INVITER)
                        await bot.send_message(
                            inviter_id, 
                            f"🎁 <b>По вашей ссылке зарегистрировался друг!</b>\nВам начислено <b>+{REFERRAL_BONUS_INVITER} кредита</b>.", 
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.error(f"Failed to notify inviter {inviter_id}: {e}")
        
        set_user_state(chat_id, DEFAULT_STATE.copy())
        credits = get_credits(chat_id)
        
        welcome_text = (
            f"Привет! Я делаю поздравления с ИИ 😃🙌🏼\n\n"
            f"{referral_text}"
            f"🎁 Вам доступно <b>{credits}</b> бесплатных открыток.\n"
            f"Выберите повод:"
        )
        await message.answer(welcome_text, reply_markup=build_occasion_keyboard(), parse_mode="HTML")

    @dp.message(Command("referral"))
    async def get_referral_link(message: types.Message):
        chat_id = message.chat.id
        link = await create_start_link(bot, str(chat_id), encode=False)
        
        text = (
            f"🤝 <b>Приглашайте друзей и получайте бесплатные открытки!</b>\n\n"
            f"За каждого нового друга, который запустит бота по вашей ссылке, "
            f"вы получите <b>+{REFERRAL_BONUS_INVITER} кредита</b>, "
            f"а ваш друг — <b>+{REFERRAL_BONUS_INVITEE} бонусный кредит</b>.\n\n"
            f"Ваша ссылка для приглашений:\n{link}"
        )
        await message.answer(text, parse_mode="HTML")

    @dp.message(Command("balance"))
    async def balance(message: types.Message):
        chat_id = message.chat.id
        credits = get_credits(chat_id)
        await message.answer(
            f"Осталось кредитов: <b>{credits}</b>\n\n"
            f"💡 Получить бесплатные кредиты можно пригласив друзей через команду /referral",
            parse_mode="HTML"
        )

    @dp.message(F.text.in_(OCCASIONS))
    async def choose_occasion(message: types.Message):
        chat_id = message.chat.id
        
        if message.text == "✏️ Свой повод":
            st = {
                "occasion": "WAITING_CUSTOM_OCCASION",
                "style": None,
                "font": None,
                "text_mode": None,
            }
            set_user_state(chat_id, st)
            await message.answer("Пожалуйста, напишите свой повод (например: День программиста, Годовщина знакомства):", reply_markup=types.ReplyKeyboardRemove())
            return

        st = {
            "occasion": message.text,
            "style": None,
            "font": None,
            "text_mode": None,
        }
        set_user_state(chat_id, st)
        await message.answer("Теперь выберите стиль:", reply_markup=build_style_keyboard())

    @dp.message(F.text.in_(STYLES))
    async def choose_style(message: types.Message):
        try:
            logger.info(f"===> user selected style: {message.text}")
            chat_id = message.chat.id
            st = get_user_state(chat_id)
            logger.info(f"===> current state: {st}")
            
            if not st.get("occasion") or st.get("occasion") == "WAITING_CUSTOM_OCCASION":
                logger.info("===> returning to choose occasion")
                await message.answer("Сначала выберите повод:", reply_markup=build_occasion_keyboard())
                return
                
            st["style"] = message.text
            st["font"] = None
            st["text_mode"] = None
            
            logger.info(f"===> saving state: {st}")
            set_user_state(chat_id, st)
            logger.info("===> state saved successfully")

            logger.info("===> sending keyboard")
            await message.answer("Отлично! Теперь выберите шрифт для надписи:", reply_markup=build_font_keyboard())
            logger.info("===> keyboard sent")
            
        except Exception as e:
            logger.error(f"CRITICAL ERROR in choose_style: {e}")
            logger.error(traceback.format_exc())
            try:
                await message.answer(f"Произошла системная ошибка: {str(e)[:50]}. Напишите /start.")
            except:
                pass

    @dp.message(F.text.in_(FONTS_LIST))
    async def choose_font(message: types.Message):
        chat_id = message.chat.id
        st = get_user_state(chat_id)

        if not st.get("style"):
            await message.answer("Сначала выберите стиль:", reply_markup=build_style_keyboard())
            return

        st["font"] = message.text
        st["text_mode"] = None
        set_user_state(chat_id, st)
        
        await message.answer("Как напишем поздравление?", reply_markup=build_text_mode_keyboard())

    @dp.message(F.text.in_(["✨ Сгенерировать ИИ", "✏️ Написать свой текст"]))
    async def choose_text_mode(message: types.Message):
        chat_id = message.chat.id
        st = get_user_state(chat_id)

        if not st.get("font"):
            await message.answer("Сначала выберите шрифт:", reply_markup=build_font_keyboard())
            return

        mode = "ai" if message.text == "✨ Сгенерировать ИИ" else "custom"
        st["text_mode"] = mode
        set_user_state(chat_id, st)

        # Ask for text instructions based on mode
        if mode == "ai":
            prompt = "Напишите коротко, для кого это поздравление и какие есть пожелания (например: для мамы от сына, крепкого здоровья и счастья):"
        else:
            prompt = (
                "Напишите свой текст поздравления.\n"
                "❗️ <b>ВАЖНО:</b> Не пишите имя адресата в начале. Начните сразу с сути (желательно с маленькой буквы).\n"
                "Имя будет подставлено автоматически при отправке открытки."
            )
        
        await message.answer(prompt, reply_markup=types.ReplyKeyboardRemove(), parse_mode="HTML")

    @dp.callback_query(F.data.startswith("buy:"))
    async def buy_package(query: CallbackQuery):
        chat_id = query.message.chat.id
        _, n_str = query.data.split(":")
        n = int(n_str)

        if n not in PACKAGES:
            await query.answer("Неверный пакет", show_alert=True)
            return

        pending = kv.get(pending_key(chat_id))
        if not pending:
            await query.answer("Нет активного запроса. Начните с /start", show_alert=True)
            return

        pkg = PACKAGES[n]
        payload = f"pkg:{n}:{chat_id}"

        await query.answer()

        await bot.send_invoice(
            chat_id=chat_id,
            title=pkg["label"],
            description=f"Покупка {n} кредитов на генерацию открыток.",
            payload=payload,
            provider_token=YUKASSA_TOKEN,
            currency="RUB",
            prices=[LabeledPrice(label=pkg["label"], amount=pkg["amount"])],
        )

    @dp.pre_checkout_query()
    async def pre_checkout(q: PreCheckoutQuery):
        await q.answer(ok=True)

    @dp.message(F.successful_payment)
    async def paid(message: types.Message):
        chat_id = message.chat.id
        invoice_payload = message.successful_payment.invoice_payload

        try:
            prefix, n_str, _ = invoice_payload.split(":")
            if prefix != "pkg":
                raise ValueError("bad payload")
            n = int(n_str)
            if n not in PACKAGES:
                raise ValueError("unknown package")
        except Exception:
            await message.answer("Оплата прошла, но пакет не распознан. Напишите /start.")
            return

        record_payment(PACKAGES[n]["rub"])

        new_credits = add_credits(chat_id, n)
        await message.answer(f"✅ Оплата успешна! Начислено {n} кредитов. Теперь доступно: {new_credits}")

        pending = pop_pending(chat_id)
        if pending:
            await generate_postcard(chat_id, message, pending, bot)
        else:
            await message.answer("Выберите повод для новой открытки:", reply_markup=build_occasion_keyboard())

    @dp.message()
    async def text_input_and_route(message: types.Message):
        chat_id = message.chat.id
        st = get_user_state(chat_id)
        
        text_input = message.text.strip()
        if not text_input:
            await message.answer("Пожалуйста, отправьте текст.")
            return
            
        # Optional: General text length limit to prevent abuse
        if len(text_input) > 500:
            await message.answer("Текст слишком длинный. Пожалуйста, сделайте его короче (максимум 500 символов).")
            return
            
        # 1. Waiting for custom occasion text
        if st.get("occasion") == "WAITING_CUSTOM_OCCASION":
            if len(text_input) > 50:
                await message.answer("Название повода слишком длинное. Пожалуйста, уложитесь в 50 символов.")
                return
            st["occasion"] = f"✏️ {text_input}"
            set_user_state(chat_id, st)
            await message.answer("Отлично! Теперь выберите стиль:", reply_markup=build_style_keyboard())
            return

        # 2. Check if we are missing required state
        if not st.get("occasion") or not st.get("style") or not st.get("font") or not st.get("text_mode"):
            await message.answer("Давайте начнём заново: выберите повод.", reply_markup=build_occasion_keyboard())
            return

        # 3. Handle Greeting Text Input (both AI and custom mode)
        if st["text_mode"] == "custom" and len(text_input) > MAX_CUSTOM_TEXT_LENGTH:
            await message.answer(
                f"Текст слишком длинный ({len(text_input)} символов). "
                f"Пожалуйста, уложитесь в {MAX_CUSTOM_TEXT_LENGTH} символов."
            )
            return

        payload = {
            "occasion": st["occasion"],
            "style": st["style"],
            "font": st["font"],
            "text_mode": st["text_mode"],
            "text_input": text_input,   # used for both AI hint or full custom text
        }
        
        set_user_state(chat_id, DEFAULT_STATE.copy())

        credits = get_credits(chat_id)
        if credits > 0:
            await generate_postcard(chat_id, message, payload, bot)
        else:
            save_pending(chat_id, payload)
            await message.answer(
                "У вас закончились бесплатные открытки.\n"
                "Выберите пакет для продолжения или пригласите друга через /referral:",
                reply_markup=build_packages_keyboard()
            )
