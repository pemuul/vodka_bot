from aiogram import Bot, Dispatcher, Router, BaseMiddleware, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
import asyncio
import sql_mgt  # ваш модуль для работы с БД (get_user_async, create_user_async, update_user_async)

API_TOKEN = "ВАШ_ТОКЕН"

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
router = Router()


# ----------------------
# 1. Middleware, перехватывающее абсолютно все сообщения (outer)
# ----------------------
class AgePhoneCheckMiddleware(BaseMiddleware):
    """
    Перехватывает ВСЕ входящие Message и требует:
      1) Подтверждения возраста: age_18 = True в БД.
      2) Отправки номера телефона: phone != None в БД.
    Любое сообщение блокируется, пока хотя бы одно условие не выполнено.
    """

    async def __call__(self, handler, event: Message, data: dict) -> any:
        # Получаем запись пользователя из БД (или создаём, если её нет).
        user = await sql_mgt.get_user_async(event.chat.id)
        if not user:
            # Создаём “заглушку” в БД: age_18=False, phone=None
            await sql_mgt.create_user_async({
                "chat_id": event.chat.id,
                "age_18": False,
                "phone": None
            })
            user = await sql_mgt.get_user_async(event.chat.id)

        # 1) Проверяем, подтвердил ли пользователь, что ему есть 18 лет
        if not user.get("age_18", False):
            inline_kb_age = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Мне есть 18 лет",
                            callback_data="confirm_age"
                        )
                    ]
                ]
            )
            # Любое сообщение будет перехвачено и вместо этого придёт следующий ответ:
            await event.answer(
                "Прежде чем продолжить, подтвердите, что вам есть 18 лет:\n\n"
                "Нажмите кнопку ниже.",
                reply_markup=inline_kb_age
            )
            # НЕ вызываем handler(event, data) — блокируем дальнейшую обработку
            return

        # 2) Проверяем, есть ли у пользователя номер телефона в БД
        if not user.get("phone"):
            inline_kb_phone = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Поделиться номером телефона",
                            callback_data="start_phone_share"
                        )
                    ]
                ]
            )
            await event.answer(
                "Чтобы продолжить работу с ботом, необходимо поделиться номером телефона:\n\n"
                "Нажмите кнопку ниже.",
                reply_markup=inline_kb_phone
            )
            return  # Блокируем дальнейшую обработку

        # 3) Если и возраст подтверждён, и телефон есть — пропускаем событие дальше
        return await handler(event, data)


# Регистрируем middleware как "outer" для всех Message
dp.message.outer_middleware(AgePhoneCheckMiddleware())


# ----------------------
# 2. CallbackQuery-хендлер: пользователь нажал "Мне есть 18 лет"
# ----------------------
@router.callback_query(F.data == "confirm_age")
async def confirm_age_handler(call: CallbackQuery):
    """
    Сохраняем age_18=True в БД и редактируем исходное сообщение, убирая кнопку.
    """
    await sql_mgt.update_user_async(call.from_user.id, {"age_18": True})
    await call.answer("Возраст подтверждён", show_alert=False)

    # Убираем inline-кнопку из сообщения и показываем, что ок:
    try:
        await call.message.edit_text("✅ Вы подтвердили, что вам есть 18 лет.")
    except:
        pass  # Игнорируем ошибки редактирования, если сообщение уже изменено


# ----------------------
# 3. CallbackQuery-хендлер: пользователь нажал "Поделиться номером телефона"
# ----------------------
@router.callback_query(F.data == "start_phone_share")
async def start_phone_share_handler(call: CallbackQuery):
    """
    Редактируем сообщение (удаляем inline-кнопку) и отправляем новое с 
    ReplyKeyboard для запроса контакта.
    """
    await call.answer("Пожалуйста, поделитесь вашим номером телефона.", show_alert=False)

    # Редактируем исходное сообщение, убирая inline-кнопку
    try:
        await call.message.edit_text("📲 Пожалуйста, поделитесь вашим номером телефона.")
    except:
        pass

    # Отправляем сообщение с Reply-клавиатурой для запроса контакта
    reply_kb_contact = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="Отправить номер телефона",
                    request_contact=True
                )
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await call.message.answer(
        "Нажмите кнопку ниже, чтобы отправить контакт:",
        reply_markup=reply_kb_contact
    )


# ----------------------
# 4. Message-хендлер: пользователь отправил контакт (content_type=contact)
# ----------------------
@router.message(F.contact)
async def contact_handler(message: Message):
    """
    Сохраняем телефон в БД (phone) и убираем reply-клавиатуру.
    """
    phone_number = message.contact.phone_number
    await sql_mgt.update_user_async(message.from_user.id, {"phone": phone_number})

    # Убираем клавиатуру, возвращаем обычную
    await message.answer(
        "Спасибо! Ваш номер сохранён.",
        reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton(text="Отменить"))
    )


# ----------------------
# 5. Пример основной команды /menu
# ----------------------
@router.message(Command("menu"))
async def cmd_menu(message: Message):
    """
    Выполняется только если:
      1) age_18 == True
      2) phone != None
    (т.е. middleware уже пропустил это сообщение)
    """
    await message.answer(
        "📋 Главное меню:\n"
        "1) Опция A\n"
        "2) Опция B"
    )


# ----------------------
# 6. Запуск бота
# ----------------------
async def main():
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
