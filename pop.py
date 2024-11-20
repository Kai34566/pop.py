import telebot
from telebot.types import ChatPermissions
from datetime import datetime, timedelta

# Ваш токен бота
TOKEN = '7899444232:AAHWaBszb5IGER9LHxyWOu3yVTaKL6UmY6g'
bot = telebot.TeleBot(TOKEN)

def is_admin(chat_id, user_id):
    """Проверяет, является ли пользователь администратором в чате."""
    try:
        member = bot.get_chat_member(chat_id, user_id)
        return member.status in ['administrator', 'creator']
    except Exception as e:
        return False

@bot.message_handler(commands=['report'])
def report_message(message):
    try:
        # Проверяем, ответил ли пользователь на сообщение
        if not message.reply_to_message:
            bot.delete_message(message.chat.id, message.message_id)  # Удаляем команду
            return

        # Получаем список администраторов чата
        admins = bot.get_chat_administrators(message.chat.id)

        if not admins:
            bot.delete_message(message.chat.id, message.message_id)  # Удаляем команду
            return

        # Формируем текст уведомления
        reporter_name = f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip()
        reporter_mention = f"[{reporter_name}](tg://user?id={message.from_user.id})"
        report_text = f"⚠️ {reporter_mention} отправил репорт на следующее сообщение:"

        # Формируем ссылку на сообщение
        message_link = f"[Сообщение](tg://msg_id?{message.reply_to_message.message_id})"

        # Пересылаем сообщение всем администраторам с ссылкой
        for admin in admins:
            if admin.user.is_bot:
                continue  # Пропускаем ботов
            bot.send_message(
                chat_id=admin.user.id,
                text=f"{report_text}\n\n{message_link}",
                parse_mode="Markdown"
            )
            bot.forward_message(
                chat_id=admin.user.id,
                from_chat_id=message.chat.id,
                message_id=message.reply_to_message.message_id
            )

        bot.reply_to(message, "Спасибо за жалобу на сообщение!\nОтправлено уведомлений админам")
        bot.delete_message(message.chat.id, message.message_id)  # Удаляем команду
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {e}")

# Команды /mute и /ban из предыдущего кода
def process_action(message, action_type):
    try:
        if not is_admin(message.chat.id, message.from_user.id):
            bot.delete_message(message.chat.id, message.message_id)  # Удаляем команду
            return

        if message.reply_to_message:
            target_user = message.reply_to_message.from_user
        elif len(message.text.split()) >= 2:
            target_user_input = message.text.split()[1]
            target_user = bot.get_chat_member(message.chat.id, target_user_input).user
        else:
            bot.delete_message(message.chat.id, message.message_id)  # Удаляем команду
            return

        args = message.text.split()
        if len(args) < 3:
            until_date = None
            action_duration = "на ♾️ минут"
        else:
            time_arg = args[-2:]
            if len(time_arg) != 2 or not time_arg[0].isdigit()
                bot.delete_message(message.chat.id, message.message_id)  # Удаляем команду
                return

            time_value = int(time_arg[0])
            time_unit = time_arg[1].lower()
            if time_unit in ['minute', 'minutes']:
                minutes = time_value
            elif time_unit in ['hour', 'hours']:
                minutes = time_value * 60
            elif time_unit in ['day', 'days']:
                minutes = time_value * 60 * 24
            else:
                bot.delete_message(message.chat.id, message.message_id)  # Удаляем команду
                return

            until_date = datetime.now() + timedelta(minutes=minutes)
            action_duration = f"на {minutes} минут"

        if action_type == 'mute':
            permissions = ChatPermissions(can_send_messages=False)
            bot.restrict_chat_member(
                chat_id=message.chat.id,
                user_id=target_user.id,
                permissions=permissions,
                until_date=until_date
            )
        elif action_type == 'ban':
            bot.ban_chat_member(
                chat_id=message.chat.id,
                user_id=target_user.id,
                until_date=until_date
            )

        admin_name = f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip()
        target_name = f"{target_user.first_name or ''} {target_user.last_name or ''}".strip()

        bot.send_message(
            chat_id=message.chat.id,
            text=f"[{admin_name}](tg://user?id={message.from_user.id}) "
                 f"{'ограничил' if action_type == 'mute' else 'забанил'} пользователя [{target_name}](tg://user?id={target_user.id}) {action_duration}.",
            parse_mode="Markdown"
        )

        bot.delete_message(message.chat.id, message.message_id)  # Удаляем команду
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {e}")

@bot.message_handler(commands=['mute'])
def mute_user(message):
    process_action(message, 'mute')

@bot.message_handler(commands=['ban'])
def ban_user(message):
    process_action(message, 'ban')

# Запуск бота
bot.polling()
