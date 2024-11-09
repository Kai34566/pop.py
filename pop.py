import telebot
from telebot import types
import random
from random import shuffle
import asyncio
import logging
import time
import threading


notification_timers = {}


logging.basicConfig(level=logging.INFO)

bot = telebot.TeleBot("7526419069:AAFpc9Is0TzP_0GQsYhvYmHA6dyWvvQ9O8w")

# Словарь со всеми чатами и игроками в этих чатах
chat_list = {}
game_tasks = {}
registration_timers = {}
game_start_timers = {}
# Словарь для хранения времени последнего нажатия кнопки каждым игроком
vote_timestamps = {}
next_players = {}
registration_lock = threading.Lock()

player_profiles = {}
sent_messages = {}

is_night = False

class Game:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.players = {}
        self.dead_last_words = {}  # Инициализация словаря для последних слов убитых игроков
        self.dead = None
        self.sheriff_check = None
        self.sheriff_shoot = None
        self.sheriff_id = None
        self.sergeant_id = None
        self.doc_target = None
        self.vote_counts = {}
        self.confirm_votes = {'yes': 0, 'no': 0, 'voted': {}}
        self.game_running = False
        self.button_id = None
        self.dList_id = None
        self.shList_id = None
        self.docList_id = None
        self.mafia_votes = {}
        self.mafia_voting_message_id = None
        self.don_id = None
        self.lucky_id = None
        self.vote_message_id = None
        self.hobo_id = None  # ID Бомжа
        self.hobo_target = None  # Цель Бомжа
        self.hobo_visitors = []  # Посетители цели Бомжа
        self.suicide_bomber_id = None  # ID Смертника
        self.suicide_hanged = False  # Переменная для отслеживания повешенного самоубийцы
        self.all_dead_players = []
        self.lover_id = None
        self.lover_target_id = None
        self.previous_lover_target_id = None
        self.last_sheriff_menu_id = None
        self.lawyer_id = None
        self.lawyer_target = None
        self.maniac_id = None
        self.maniac_target = None

    def update_player_list(self):
        players_list = ", ".join([player['name'] for player in self.players.values()])
        return players_list

    def remove_player(chat, player_id, killed_by=None):
     if player_id in chat.players:
        dead_player = chat.players.pop(player_id)  # Удаляем игрока из текущего списка игроков

        clickable_name = f"[{dead_player['name']}](tg://user?id={player_id})"
        
        # Сохраняем информацию об убитом игроке в список убитых
        chat.all_dead_players.append(f"{clickable_name} - {dead_player['role']}")

        # Если игрок был убит ночью (мафией или Комиссаром), отправляем сообщение
        if killed_by == 'night':
            bot.send_message(player_id, "Тебя убили :( Можешь написать здесь своё последнее сообщение.", parse_mode='Markdown')
            chat.dead_last_words[player_id] = dead_player['name']  # Сохраняем имя игрока для последнего сообщения

def change_role(player_id, player_dict, new_role, text, game):
    player_dict[player_id]['role'] = new_role
    player_dict[player_id]['action_taken'] = False
    player_dict[player_id]['skipped_actions'] = 0
    try:
        bot.send_message(player_id, text)
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение игроку {player_id}: {e}")
    if new_role == '🤵🏻‍♂️ Дон':
        player_dict[player_id]['don'] = True
    else:
        player_dict[player_id]['don'] = False
    if new_role == '💣 Смертник':
        game.suicide_bomber_id = player_id
    logging.info(f"Игрок {player_dict[player_id]['name']} назначен на роль {new_role}")

def list_btn(player_dict, user_id, player_role, text, action_type, message_id=None):
    players_btn = types.InlineKeyboardMarkup()

    for key, val in player_dict.items():
        # Логируем текущую роль каждого игрока
        logging.info(f"Текущая роль игрока: {val['role']} (ID: {key})")
        logging.info(f"Обработка игрока: {val['name']} (ID: {key}) - Роль: {val['role']}")

        # Условие для доктора, чтобы не лечить себя дважды
        if player_role == 'доктор' and key == user_id:
            logging.info(f"Доктор {val['name']} - self_healed: {val.get('self_healed', False)}")
            if val.get('self_healed', False):
                logging.info(f"Доктор {val['name']} уже лечил себя, не добавляем в список.")
                continue
            else:
                logging.info(f"Доктор {val['name']} еще не лечил себя, добавляем в список.")
                players_btn.add(types.InlineKeyboardButton(val['name'], callback_data=f'{key}_{action_type}'))
                continue

        # Условие для адвоката, чтобы он не выбирал мертвых игроков и самого себя
        if player_role == '👨🏼‍💼 Адвокат' and (key == user_id or val['role'] == 'dead'):
            logging.info(f"Адвокат не может выбрать мертвого игрока или самого себя.")
            continue

        # Убираем мафию и дона из списка для мафии и дона
        if player_role in ['мафия', 'don']:
            logging.info(f"Текущая роль {player_role}, проверяем игрока {val['name']} с ролью {val['role']}")
            if val['role'] in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон']:
                logging.info(f"Игрок {val['name']} (Мафия или Дон) исключен из списка выбора.")
                continue  # Пропускаем союзников

        # Добавление остальных игроков в список
        if key != user_id and val['role'] != 'dead':
            players_btn.add(types.InlineKeyboardButton(val['name'], callback_data=f'{key}_{action_type}'))

    logging.info(f"Редактирование сообщения с кнопками для {player_role}.")

    if message_id:
        try:
            bot.edit_message_text(chat_id=user_id, message_id=message_id, text=text, reply_markup=players_btn)
        except Exception as e:
            logging.error(f"Ошибка при редактировании сообщения: {e}")
    else:
        try:
            msg = bot.send_message(user_id, text, reply_markup=players_btn)
            logging.info(f"Сообщение с кнопками отправлено, message_id: {msg.message_id}")
            return msg.message_id
        except Exception as e:
            logging.error(f"Ошибка при отправке сообщения с кнопками: {e}")


def registration_message(players):
    if players:
        player_names = [f"[{player['name']}](tg://user?id={player_id})" for player_id, player in players.items()]
        player_list = ', '.join(player_names)
        return f"*Ведётся набор в игру*\n{player_list}\n_{len(player_names)} участников_"
    else:
        return "*Ведётся набор в игру*\n_участников нет_"

# Формирование сообщения с живыми игроками
def night_message(players):
    # Сортируем игроков по номеру перед выводом
    sorted_players = sorted(players.items(), key=lambda item: item[1]['number'])
    living_players = [f"{player['number']}. [{player['name']}](tg://user?id={player_id})" for player_id, player in sorted_players if player['role'] != 'dead']
    player_list = '\n'.join(living_players)
    return f"*Живые игроки:*\n{player_list}\n\n_Спать осталось 45 сек._\n"

def day_message(players):
    # Сортируем игроков по номеру перед выводом
    sorted_players = sorted(players.items(), key=lambda item: item[1]['number'])
    
    # Список живых игроков
    living_players = [f"{player['number']}. [{player['name']}](tg://user?id={player_id})"
                      for player_id, player in sorted_players if player['role'] != 'dead']
    player_list = '\n'.join(living_players)
    
    # Подсчёт ролей среди живых игроков
    roles = [player['role'] for player_id, player in sorted_players if player['role'] != 'dead']
    
    # Категоризация ролей
    peaceful_roles = ['👨🏼‍⚕️ Доктор', '🧙‍♂️ Бомж', '🕵🏼 Комиссар Каттани', '🤞 Счастливчик', '💣 Смертник', '💃🏼 Любовница', '👮🏼 Сержант', '👨🏼 Мирный житель']
    mafia_roles = ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон', '👨🏼‍💼 Адвокат']
    maniac_roles = ['🔪 Маньяк', '🤦‍♂️ Самоубийца']

    # Подсчет количества ролей среди живых
    role_counts = {}
    for role in roles:
        if role not in role_counts:
            role_counts[role] = 1
        else:
            role_counts[role] += 1

    # Формирование строк с ролями и количеством игроков
    result_lines = []

    # Обработка мирных ролей
    peaceful_list = [f"{role} ({count})" if count > 1 else role for role, count in role_counts.items() if role in peaceful_roles]
    peaceful_count = sum(role_counts[role] for role in peaceful_roles if role in role_counts)
    if peaceful_list:
        result_lines.append(f"👨🏼 {peaceful_count}: {', '.join(peaceful_list)}")

    # Обработка мафиозных ролей
    mafia_list = [f"{role} ({count})" if count > 1 else role for role, count in role_counts.items() if role in mafia_roles]
    mafia_count = sum(role_counts[role] for role in mafia_roles if role in role_counts)
    if mafia_list:
        result_lines.append(f"🤵🏼 {mafia_count}: {', '.join(mafia_list)}")

    # Обработка маньяков и самоубийц
    maniac_list = [f"{role} ({count})" if count > 1 else role for role, count in role_counts.items() if role in maniac_roles]
    maniac_count = sum(role_counts[role] for role in maniac_roles if role in role_counts)
    if maniac_list:
        result_lines.append(f"🤵🏻‍♂️ {maniac_count}: {', '.join(maniac_list)}")

    # Формирование финального текста
    return (f"*Живые игроки:*\n{player_list}\n\n"
            f"*Из них*:\n" + '\n'.join(result_lines) + 
            f"\n\n👥 Всего: *{len(living_players)}*\n\n"
            "Теперь пришло время обсудить сегодняшние события, пытаясь выяснить причины и последствия...")
    
def players_alive(player_dict, phase):
    if phase == "registration":
        return registration_message(player_dict)
    elif phase == "night":
        return night_message(player_dict)
    elif phase == "day":
        return day_message(player_dict)

def emoji(role):
    emojis = {
        'мафия': '🤵🏻',
        'Комиссар Каттани': '🕵🏼️‍♂️',
        'мирный житель': '👨🏼',
        'доктор': '👨🏼‍⚕️'
    }
    return emojis.get(role, '')

def voice_handler(chat_id):
    global chat_list
    chat = chat_list[chat_id]
    players = chat.players
    votes = []
    for player_id, player in players.items():
        if 'voice' in player:
            votes.append(player['voice'])
            del player['voice']
    if votes:
        dead_id = max(set(votes), key=votes.count)
        dead = players.pop(dead_id)
        return dead

def send_message_to_mafia(chat, message):
    for player_id, player in chat.players.items():
        if player['role'] in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон']:
            bot.send_message(player_id, message, parse_mode='Markdown')

def notify_mafia(chat, sender_name, message, sender_id):
    for player_id, player in chat.players.items():
        if player['role'] in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон'] and player_id != sender_id:
            role = 'Дон' if chat.players[sender_id]['role'] == '🤵🏻‍♂️ Дон' else 'Мафия'
            bot.send_message(player_id, f"*{role} {sender_name}:*\n{message}", parse_mode='Markdown')
        if player['role'] == '👨🏼‍💼 Адвокат':
            if chat.players[sender_id]['role'] == '🤵🏻‍♂️ Дон':
                bot.send_message(player_id, f"🤵🏻‍♂️ Дон ???:\n{message}")
            else:
                bot.send_message(player_id, f"🤵🏻 Мафия ???:\n{message}")

def notify_mafia_and_don(chat):
    mafia_and_don_list = []
    # Создаем копию списка игроков, чтобы избежать изменения размера словаря во время итерации
    players_copy = list(chat.players.items())
    
    for player_id, player in players_copy:
        if player['role'] == '🤵🏻‍♂️ Дон':
            mafia_and_don_list.append(f"[{player['name']}](tg://user?id={player_id}) - 🤵🏻‍♂️ *Дон*")
        elif player['role'] == '🤵🏻 Мафия':
            mafia_and_don_list.append(f"[{player['name']}](tg://user?id={player_id}) - 🤵🏻 *Мафия*")
    
    message = "*Запоминай своих саратников*:\n" + "\n".join(mafia_and_don_list)
    
    for player_id, player in players_copy:
        if player['role'] in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон']:
            bot.send_message(player_id, message, parse_mode='Markdown')

def notify_twenty_nine_seconds_left(chat_id):
    global registration_timers
    if chat_id in registration_timers:
        del registration_timers[chat_id]  # Удаляем таймер из словаря, если он сработал
    if chat_id in chat_list:
        chat = chat_list[chat_id]
        if not chat.game_running and chat.button_id:
            join_btn = types.InlineKeyboardMarkup()
            bot_username = bot.get_me().username
            join_url = f'https://t.me/{bot_username}?start=join_{chat_id}'
            item1 = types.InlineKeyboardButton('🤵🏻 Присоединиться', url=join_url)
            join_btn.add(item1)
            bot.send_message(chat_id, '⏰ Регистрация закончится через *29 сек.*', reply_markup=join_btn, parse_mode="Markdown")

def notify_one_minute_left(chat_id):
    global registration_timers
    if chat_id in registration_timers:
        del registration_timers[chat_id]  # Удаляем таймер из словаря, если он сработал
    if chat_id in chat_list:
        chat = chat_list[chat_id]
        if not chat.game_running and chat.button_id:
            join_btn = types.InlineKeyboardMarkup()
            bot_username = bot.get_me().username
            join_url = f'https://t.me/{bot_username}?start=join_{chat_id}'
            item1 = types.InlineKeyboardButton('🤵🏻 Присоединиться', url=join_url)
            join_btn.add(item1)
            bot.send_message(chat_id, '⏰ Регистрация закончится через *59 сек.*', reply_markup=join_btn, parse_mode="Markdown")
            
            # Запускаем таймер на уведомление за 29 секунд
            notification_timers[chat_id] = threading.Timer(30.0, lambda: notify_twenty_nine_seconds_left(chat_id))
            notification_timers[chat_id].start()

def start_game_with_delay(chat_id):
    global notification_timers, game_start_timers

    if chat_id in chat_list:
        chat = chat_list[chat_id]
        if chat.game_running:  # Проверяем, начата ли игра
            # Если игра начата, отменяем таймер уведомления
            if chat_id in notification_timers:
                notification_timers[chat_id].cancel()
                del notification_timers[chat_id]
            # Отменяем таймер старта игры
            if chat_id in game_start_timers:
                game_start_timers[chat_id].cancel()
                del game_start_timers[chat_id]
            return

        if chat.button_id:
            bot.delete_message(chat_id, chat.button_id)
            chat.button_id = None

        # Отменяем таймер уведомления, если он существует
        if chat_id in notification_timers:
            notification_timers[chat_id].cancel()
            del notification_timers[chat_id]

        # Отменяем таймер старта игры, если он существует
        if chat_id in game_start_timers:
            game_start_timers[chat_id].cancel()
            del game_start_timers[chat_id]

        _start_game(chat_id)

def reset_registration(chat_id):
    global notification_timers, game_start_timers
    chat = chat_list.get(chat_id)

    # Удаляем текущее сообщение о регистрации
    if chat and chat.button_id:
        bot.delete_message(chat_id, chat.button_id)
        chat.button_id = None

    # Очищаем список игроков
    if chat:
        chat.players.clear()
        chat.game_running = False  # Обнуляем состояние игры

    # Отменяем таймер уведомления, если он существует
    if chat_id in notification_timers:
        notification_timers[chat_id].cancel()
        del notification_timers[chat_id]

    # Отменяем таймер старта игры, если он существует
    if chat_id in game_start_timers:
        game_start_timers[chat_id].cancel()
        del game_start_timers[chat_id]

def add_player(chat, user_id, user_name, player_number):
    # Создаем профиль игрока при присоединении
    get_or_create_profile(user_id, user_name)
    
    chat.players[user_id] = {'name': user_name, 'role': 'ждет', 'skipped_actions': 0, 'status': 'alive', 'number': player_number}

def confirm_vote(chat_id, player_id, player_name, confirm_votes, player_list):
    # Проверяем, было ли уже отправлено сообщение для этого игрока
    if player_id in sent_messages:
        logging.info(f"Сообщение подтверждения для {player_name} уже отправлено.")
        return sent_messages[player_id], f"Вы точно хотите повесить {player_name}?"

    confirm_markup = types.InlineKeyboardMarkup(row_width=2)  # Устанавливаем две кнопки в строке
    confirm_markup.add(
        types.InlineKeyboardButton(f"👍🏼 {confirm_votes['yes']}", callback_data=f"confirm_{player_id}_yes"),
        types.InlineKeyboardButton(f"👎🏼 {confirm_votes['no']}", callback_data=f"confirm_{player_id}_no")
    )

    # Создаем кликабельную ссылку на игрока
    player_link = f"[{player_name}](tg://user?id={player_id})"
    
    # Используем кликабельную ссылку в сообщении
    msg = bot.send_message(chat_id, f"Вы точно хотите повесить {player_link}?", reply_markup=confirm_markup, parse_mode="Markdown")
    
    logging.info(f"Сообщение подтверждения голосования отправлено с message_id: {msg.message_id}")
    
    # Сохраняем message_id в sent_messages
    sent_messages[player_id] = msg.message_id
    
    return msg.message_id, f"Вы точно хотите повесить {player_link}?"
    
def end_day_voting(chat):
    if not chat.vote_counts:  # Если нет голосов
        bot.send_message(chat.chat_id, "*Голосование завершено*\nМнения жителей разошлись...\nРазошлись и сами жители,\nтак никого и не повесив...", parse_mode="Markdown")
        reset_voting(chat)  # Сброс голосования

        # Сбрасываем блокировку голосования у всех игроков
        for player in chat.players.values():
            player['voting_blocked'] = False
        
        if check_game_end(chat, time.time()):
            return False  # Игра завершена
        return False  # Немедленно продолжаем игру

    max_votes = max(chat.vote_counts.values(), default=0)
    potential_victims = [player_id for player_id, votes in chat.vote_counts.items() if votes == max_votes]

    # Проверка, если большинство проголосовало за "Пропустить"
    if 'skip' in chat.vote_counts and chat.vote_counts['skip'] == max_votes:
        bot.send_message(chat.chat_id, "*Голосование завершено*\n🚷 Жители города решили\nникого не повесить...", parse_mode="Markdown")
        reset_voting(chat)

        # Сбрасываем блокировку голосования у всех игроков
        for player in chat.players.values():
            player['voting_blocked'] = False
        
        if check_game_end(chat, time.time()):
            return False  # Игра завершена
        return False  # Продолжаем игру без ожидания

    if len(potential_victims) == 1 and max_votes > 0:
        player_id = potential_victims[0]
        if player_id in chat.players:  # Проверка, что игрок существует
            
            # Проверка, не вышел ли игрок из игры
            if chat.players[player_id].get('status') == 'left':
                player_name = chat.players[player_id]['name']
                clickable_name = f"[{player_name}](tg://user?id={player_id})"
                bot.send_message(chat.chat_id, f"*Голосование завершено*\n😵 Игрок {clickable_name} не дождавшись суда, сам вынес себе приговор 😭", parse_mode="Markdown")
                chat.remove_player(player_id)
                reset_voting(chat)

                # Сбрасываем блокировку голосования у всех игроков
                for player in chat.players.values():
                    player['voting_blocked'] = False
                
                if check_game_end(chat, time.time()):
                    return False  # Игра завершена
                return False  # Немедленно продолжаем игру
            
            # Продолжаем, если игрок не покинул игру
            player_name = chat.players[player_id]['name']
            chat.confirm_votes['player_id'] = player_id  # Сохраняем player_id для подтверждения голосования
            chat.vote_message_id, chat.vote_message_text = confirm_vote(chat.chat_id, player_id, player_name, chat.confirm_votes, chat.players)  # Отправляем подтверждающее голосование
            return True  # Ждем подтверждения голосования
        else:
            logging.error(f"Игрок с id {player_id} не найден в chat.players")
            reset_voting(chat)

            # Сбрасываем блокировку голосования у всех игроков
            for player in chat.players.values():
                player['voting_blocked'] = False
                
            return False  # Немедленно продолжаем игру
    else:
        # Если голоса равны или нет результата, выводим сообщение и немедленно продолжаем игру
        bot.send_message(chat.chat_id, "*Голосование завершено*\nМнения жителей разошлись...\nРазошлись и сами жители,\nтак никого и не повесив...", parse_mode="Markdown")
        reset_voting(chat)  # Сброс голосования

        # Сбрасываем блокировку голосования у всех игроков
        for player in chat.players.values():
            player['voting_blocked'] = False
        
        if check_game_end(chat, time.time()):
            return False  # Игра завершена
        return False  # Продолжаем игру без ожидания

def handle_confirm_vote(chat):
    yes_votes = chat.confirm_votes['yes']
    no_votes = chat.confirm_votes['no']

    # Обрабатываем только если идет подтверждающее голосование
    if yes_votes == no_votes:
        # Если подтверждающее голосование завершилось равными голосами, выводим результат и продолжаем игру
        send_voting_results(chat, yes_votes, no_votes)
        disable_vote_buttons(chat)  # Удаляем кнопки
    elif yes_votes > no_votes:
        # Если больше голосов "за", игрок казнен
        dead_id = chat.confirm_votes['player_id']
        if dead_id in chat.players:
            dead = chat.players[dead_id]
            disable_vote_buttons(chat)
            # Передаем информацию о казненном игроке и его роли
            send_voting_results(chat, yes_votes, no_votes, dead['name'], dead['role'])  

            chat.remove_player(dead_id)
            
            # Проверка, был ли этот игрок Доном
            if dead['role'] == '🤵🏻‍♂️ Дон':
                check_and_transfer_don_role(chat)

            # Проверка, был ли этот игрок Комиссаром
            if dead['role'] == '🕵🏼 Комиссар Каттани':
                check_and_transfer_sheriff_role(chat)

        else:
            logging.error(f"Игрок с id {dead_id} не найден в chat.players")
    else:
        # Если больше голосов "против", игрок не казнен
        disable_vote_buttons(chat)
        send_voting_results(chat, yes_votes, no_votes)

    reset_voting(chat)  # Сбрасываем голосование после подтверждения

def disable_vote_buttons(chat):
    try:
        if chat.vote_message_id:
            logging.info(f"Попытка удаления кнопок голосования с message_id: {chat.vote_message_id}")
            # Удаляем кнопки
            updated_text = f"{chat.vote_message_text}\n\n_Голосование завершено_"
            bot.edit_message_text(chat_id=chat.chat_id, message_id=chat.vote_message_id, text=updated_text, parse_mode="Markdown")
            
            bot.edit_message_reply_markup(chat_id=chat.chat_id, message_id=chat.vote_message_id, reply_markup=None)
        else:
            logging.error("vote_message_id не установлен.")
    except Exception as e:
        logging.error(f"Не удалось заблокировать кнопки для голосования: {e}")

def send_voting_results(chat, yes_votes, no_votes, player_name=None, player_role=None):
    if yes_votes > no_votes:
        # Делаем имя игрока кликабельным
        player_link = f"[{player_name}](tg://user?id={chat.confirm_votes['player_id']})"
        result_text = (f"*Результаты голосования:*\n"
                       f"👍🏼 {yes_votes} | 👎🏼 {no_votes}\n\n"
                       f"_Сегодня был повешен_ {player_link}\n"
                       f"Он был {player_role}..")
        
        # Отправляем сообщение в чат с результатами голосования
        bot.send_message(chat.chat_id, result_text, parse_mode="Markdown")
        
        # Отправляем личное сообщение повешенному игроку
        bot.send_message(chat.confirm_votes['player_id'], "*Тебя казнили на дневном собрании :(*", parse_mode="Markdown")
    else:
        result_text = (f"*Результаты голосования:*\n"
                       f"👍🏼 {yes_votes} | 👎🏼 {no_votes}\n\n"
                       f"Мнения жителей разошлись...\n"
                       f"Разошлись и сами жители, так\n"
                       f"никого и не повесив...")
        
        # Отправляем сообщение в чат с результатами голосования
        bot.send_message(chat.chat_id, result_text, parse_mode="Markdown")

def send_sheriff_menu(chat, sheriff_id, callback_query=None, message_id=None):
    if not is_night:
        if callback_query:
            # Отвечаем всплывающим уведомлением, если действие пытаются выполнить не ночью
            bot.answer_callback_query(callback_query.id, "Действия  доступны только ночью.", show_alert=True)
        return

    sheriff_menu = types.InlineKeyboardMarkup()
    sheriff_menu.add(types.InlineKeyboardButton('🔍 Проверять', callback_data=f'{sheriff_id}_check'))
    sheriff_menu.add(types.InlineKeyboardButton('🔫 Стрелять', callback_data=f'{sheriff_id}_shoot'))

    new_text = "Выбери своё действие в эту ночь"

    if message_id:
        bot.edit_message_text(chat_id=sheriff_id, message_id=message_id, text=new_text, reply_markup=sheriff_menu)
    else:
        msg = bot.send_message(sheriff_id, new_text, reply_markup=sheriff_menu)
        chat.last_sheriff_menu_id = msg.message_id  # Сохраняем идентификатор последнего меню

def reset_voting(chat):
    # Очищаем все переменные, связанные с голосованием
    chat.vote_counts.clear()
    chat.confirm_votes = {'yes': 0, 'no': 0, 'voted': {}}
    chat.vote_message_id = None
    chat.vote_counts['skip'] = 0
    
    # Сбрасываем флаг голосования у каждого игрока
    for player in chat.players.values():
        player['has_voted'] = False

    # Сбрасываем отправленные сообщения
    sent_messages.clear()  # Очищаем словарь sent_messages

def handle_night_action(callback_query, chat, player_role):
    player_id = callback_query.from_user.id
    player = chat.players.get(player_id)

    if not is_night:
        bot.answer_callback_query(callback_query.id, text="Это действие доступно только ночью.")
        return False
    
    # Проверка, совершил ли Комиссар уже проверку или стрельбу
    if player_role == '🕵🏼 Комиссар Каттани' and (chat.sheriff_check or chat.sheriff_shoot):
        bot.answer_callback_query(callback_query.id, text="Вы уже сделали свой выбор этой ночью.")
        bot.delete_message(player_id, callback_query.message.message_id)
        return False

    if player.get('action_taken', False):
        bot.answer_callback_query(callback_query.id, text="Вы уже сделали свой выбор этой ночью.")
        bot.delete_message(player_id, callback_query.message.message_id)
        return False

    player['action_taken'] = True  # Отмечаем, что действие совершено
    return True


def check_and_transfer_don_role(chat):
    if chat.don_id not in chat.players or chat.players[chat.don_id]['role'] == 'dead':
        # Дон мертв, проверяем, есть ли еще мафия
        alive_mafia = [player_id for player_id, player in chat.players.items() if player['role'] == '🤵🏻 Мафия']
        if alive_mafia:
            new_don_id = alive_mafia[0]
            change_role(new_don_id, chat.players, '🤵🏻‍♂️ Дон', 'Теперь ты Дон!', chat)
            chat.don_id = new_don_id
            bot.send_message(chat.chat_id, "🤵🏻 *Мафия* унаследовала роль 🤵🏻‍♂️ *Дон*", parse_mode="Markdown")
        else:
            logging.info("Все мафиози мертвы, роль Дона не передана.")

def check_game_end(chat, game_start_time):
    # Считаем количество живых мафиози, Дона, адвоката и маньяка
    mafia_count = len([p for p in chat.players.values() if p['role'] in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон'] and p['status'] != 'dead'])
    lawyer_count = len([p for p in chat.players.values() if p['role'] == '👨🏼‍💼 Адвокат' and p['status'] != 'dead'])
    maniac_count = len([p for p in chat.players.values() if p['role'] == '🔪 Маньяк' and p['status'] != 'dead'])
    non_mafia_count = len([p for p in chat.players.values() if p['role'] not in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон', '👨🏼‍💼 Адвокат', '🔪 Маньяк'] and p['status'] != 'dead'])
    
    total_mafia_team = mafia_count + lawyer_count

    # Проверка, был ли линчеван самоубийца
    suicide_player = [p for p in chat.players.values() if p['role'] == '🤦‍♂️ Самоубийца' and p['status'] == 'lynched']
    
    # 1. Победа самоубийцы, если его линчевали
    if suicide_player:
        winning_team = "Самоубийца"
        winners = [f"[{v['name']}](tg://user?id={k}) - {v['role']}" for k, v in chat.players.items() if v['role'] == '🤦‍♂️ Самоубийца' and v['status'] == 'lynched']
    
    # 2. Победа маньяка, если он остался единственным живым игроком
    elif maniac_count == 1 and len([p for p in chat.players.values() if p['status'] != 'dead']) == 1:
        winning_team = "Маньяк"
        winners = [f"[{v['name']}](tg://user?id={k}) - {v['role']}" for k, v in chat.players.items() if v['role'] == '🔪 Маньяк' and v['status'] != 'dead']
    
    # 3. Победа маньяка, если он остался с одним игроком
    elif maniac_count == 1 and len(chat.players) - maniac_count == 1:
        winning_team = "Маньяк"
        winners = [f"[{v['name']}](tg://user?id={k}) - {v['role']}" for k, v in chat.players.items() if v['role'] == '🔪 Маньяк' and v['status'] != 'dead']
    
    # 4. Победа мирных жителей, если все мафиози, Дон и маньяк мертвы
    elif mafia_count == 0 and maniac_count == 0:  
        winning_team = "Мирные жители"
        winners = [f"[{v['name']}](tg://user?id={k}) - {v['role']}" for k, v in chat.players.items() if v['role'] not in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон', '👨🏼‍💼 Адвокат', '🔪 Маньяк'] and v['status'] != 'dead']
    
    # 5. Победа мафии, если Дон остался единственным живым игроком
    elif mafia_count == 1 and total_mafia_team == 1 and len([p for p in chat.players.values() if p['status'] != 'dead']) == 1:
        winning_team = "Мафия"
        winners = [f"[{v['name']}](tg://user?id={k}) - {v['role']}" for k, v in chat.players.items() if v['role'] == '🤵🏻‍♂️ Дон' and v['status'] != 'dead']
    
    # 6. Победа мафии, если количество мафии и адвоката больше или равно числу не-мафиози
    elif (total_mafia_team == 1 and non_mafia_count == 1) or \
         (total_mafia_team == 2 and non_mafia_count == 1) or \
         (total_mafia_team == 3 and non_mafia_count == 2) or \
         (total_mafia_team == 4 and non_mafia_count == 2) or \
         (total_mafia_team == 5 and non_mafia_count == 3):
        winning_team = "Мафия"
        winners = [f"[{v['name']}](tg://user?id={k}) - {v['role']}" for k, v in chat.players.items() if v['role'] in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон', '👨🏼‍💼 Адвокат'] and v['status'] != 'dead']
    
    # Если ни одно из условий не выполнено, игра продолжается
    else:
        return False  # Игра продолжается

    # Распределение выигрыша среди победителей
    for player_id, player in chat.players.items():
        if f"[{player['name']}](tg://user?id={player_id}) - {player['role']}" in winners:
            # Начисление 20 евро победителям
            player_profiles[player_id]['euro'] += 10
            bot.send_message(player_id, "*Игра окончена*!\nВы получили 10 💶", parse_mode="Markdown")
    
    # Если самоубийца выиграл
    if suicide_player:
        for player_id, player in chat.players.items():
            if player['role'] == '🤦‍♂️ Самоубийца' and player['status'] == 'lynched':
                bot.send_message(player_id, "Ты выиграл, как самоубийца! 💶 20")
    
    # Формируем список проигравших и отправляем им сообщение о проигрыше
    winners_ids = [k for k, v in chat.players.items() if f"[{v['name']}](tg://user?id={k}) - {v['role']}" in winners]
    remaining_players = [f"[{v['name']}](tg://user?id={k}) - {v['role']}" for k, v in chat.players.items() if k not in winners_ids and v['status'] not in ['dead', 'left']]

    # Добавляем вышедших игроков
    remaining_players.extend([f"[{v['name']}](tg://user?id={k}) - {v['role']}" for k, v in chat.players.items() if v['status'] == 'left'])

    # Добавляем убитых игроков за игру
    all_dead_players = []
    for player in chat.all_dead_players:
        if isinstance(player, dict):
            all_dead_players.append(f"[{player['name']}](tg://user?id={player['user_id']}) - {player['role']}")
        else:
            all_dead_players.append(player)

    # Отправляем проигравшим сообщение
    for player_id in chat.players:
        if player_id not in winners_ids and chat.players[player_id]['status'] != 'left':
            bot.send_message(player_id, "*Игра окончена!*\nВы получили 0 💶", parse_mode="Markdown")

    # Отправляем сообщение с предложением подписаться на новостной канал
    news_btn = types.InlineKeyboardMarkup()
    news_btn.add(types.InlineKeyboardButton("📰 Подписаться", url="https://t.me/+rJAbQVV5_lU4NjJi"))
    bot.send_message(chat.chat_id, '*Канал игровых новостей*\n@FrenemyMafiaNews\n\nПодпишитесь, что бы быть в курсе всех обновлений игры', reply_markup=news_btn, parse_mode="Markdown")

    time.sleep(4)
    
    # Подсчитываем время игры
    game_duration = time.time() - game_start_time
    minutes = int(game_duration // 60)
    seconds = int(game_duration % 60)

    # Формируем сообщение с результатами
    result_text = (f"*Игра окончена! 🙂*\n"
                   f"Победили: *{winning_team}*\n\n"
                   f"*Победители:*\n" + "\n".join(winners) + "\n\n"
                   f"*Остальные участники:*\n" + "\n".join(remaining_players + all_dead_players) + "\n\n"
                   f"⏰ Игра длилась: {minutes} мин. {seconds} сек.")

    bot.send_message(chat.chat_id, result_text, parse_mode="Markdown")


    # Отправляем сообщение всем убитым игрокам
    for dead_player in chat.all_dead_players:
        if isinstance(dead_player, dict):
            player_id = dead_player['user_id']
        elif isinstance(dead_player, str):
            player_id = int(dead_player.split('=')[1].split(')')[0])
        
        try:
            bot.send_message(player_id, "*Игра окончена*!\nВы получили 0 💶", parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение убитому игроку {player_id}: {e}")

    # Сброс игры
    reset_game(chat)

    reset_roles(chat)
    send_profiles_to_channel()
    return True  # Игра окончена

def reset_game(chat):
    chat.players.clear()  # Очищаем список игроков
    chat.dead = None
    chat.sheriff_check = None
    chat.sheriff_shoot = None
    chat.sheriff_id = None
    chat.doc_target = None
    chat.vote_counts.clear()
    chat.confirm_votes = {'yes': 0, 'no': 0, 'voted': {}}
    chat.game_running = False
    chat.button_id = None
    chat.dList_id = None
    chat.shList_id = None
    chat.docList_id = None
    chat.mafia_votes.clear()
    chat.mafia_voting_message_id = None
    chat.don_id = None
    chat.lucky_id = None
    chat.vote_message_id = None
    chat.hobo_id = None
    chat.hobo_target = None
    chat.hobo_visitors.clear()
    chat.suicide_bomber_id = None  # Сбрасываем ID смертника
    chat.suicide_hanged = False  # Сбрасываем статус самоубийцы
    chat.lover_id = None  # Сбрасываем роль любовницы
    chat.lover_target_id = None  # Сбрасываем цель любовницы
    chat.previous_lover_target_id = None  # Сбрасываем предыдущую цель любовницы
    chat.lawyer_id = None  # Сбрасываем ID адвоката
    chat.lawyer_target = None  # Сбрасываем цель адвоката
    chat.sergeant_id = None  # Сбрасываем ID сержанта
    chat.maniac_id = None  # Сбрасываем ID маньяка
    chat.maniac_target = None  # Сбрасываем цель маньяка
    logging.info(f"Игра сброшена в чате {chat.chat_id}")

def reset_roles(chat):
    """
    Сбрасывает роли и параметры всех игроков в чате.
    """
    for player_id, player in chat.players.items():
        player['role'] = 'ждет'  # Возвращаем всех игроков в состояние ожидания
        player['status'] = 'alive'  # Сбрасываем статус игрока на живой
        player['skipped_actions'] = 0  # Сбрасываем количество пропущенных действий
        player['self_healed'] = False  # Сбрасываем статус самовосстановления для доктора
        player['voting_blocked'] = False  # Сбрасываем блокировку голосования для любовницы
        player['healed_from_lover'] = False  # Сбрасываем флаг лечения от любовницы
        player['action_taken'] = False  # Сбрасываем флаг того, что игрок совершил действие ночью
        player['lucky_escape'] = False  # Сбрасываем флаг "счастливчика", если он спас себя

    # Сбрасываем специфические роли
    chat.don_id = None
    chat.sheriff_id = None
    chat.sergeant_id = None
    chat.doc_target = None
    chat.vote_counts.clear()
    chat.confirm_votes = {'yes': 0, 'no': 0, 'voted': {}}
    chat.game_running = False
    chat.button_id = None
    chat.dList_id = None
    chat.shList_id = None
    chat.docList_id = None
    chat.mafia_votes.clear()
    chat.mafia_voting_message_id = None
    chat.hobo_id = None
    chat.hobo_target = None
    chat.hobo_visitors.clear()  # Очищаем список посетителей цели Бомжа
    chat.suicide_bomber_id = None
    chat.suicide_hanged = False
    chat.all_dead_players.clear()
    chat.lover_id = None
    chat.lover_target_id = None
    chat.previous_lover_target_id = None
    chat.last_sheriff_menu_id = None
    chat.lawyer_id = None
    chat.lawyer_target = None
    chat.maniac_id = None
    chat.maniac_target = None
    chat.lucky_id = None  # Сбрасываем ID "Счастливчика"
    chat.vote_message_id = None
    chat.dead_last_words.clear()  # Сбрасываем последние слова убитых игроков

    logging.info("Все роли и параметры игроков сброшены.")

def escape_markdown(text):
    escape_chars = r'\*_`['
    return ''.join(f'\\{char}' if char in escape_chars else char for char in text)

def check_and_transfer_sheriff_role(chat):
    if chat.sheriff_id not in chat.players or chat.players[chat.sheriff_id]['role'] == 'dead':
        # Комиссар мертв, проверяем, есть ли сержант
        if chat.sergeant_id and chat.sergeant_id in chat.players and chat.players[chat.sergeant_id]['role'] != 'dead':
            new_sheriff_id = chat.sergeant_id
            change_role(new_sheriff_id, chat.players, '🕵🏼 Комиссар Каттани', 'Теперь ты Комиссар Каттани!', chat)
            chat.sheriff_id = new_sheriff_id
            chat.sergeant_id = None  # Теперь сержант становится Комиссаром, и роль сержанта больше не нужна
            bot.send_message(chat.chat_id, "👮🏼 *Сержант* унаследовал роль 🕵🏼 * Комиссар Каттани*", parse_mode="Markdown")
        else:
            logging.info("Нет сержанта для передачи роли Комиссара.")

def notify_police(chat):
    police_members = []
    if chat.sheriff_id and chat.sheriff_id in chat.players and chat.players[chat.sheriff_id]['role'] == '🕵🏼 Комиссар Каттани':
        sheriff_name = chat.players[chat.sheriff_id]['name']
        police_members.append(f"[{sheriff_name}](tg://user?id={chat.sheriff_id}) - 🕵🏼 * Комиссар Каттани*")
    if chat.sergeant_id and chat.sergeant_id in chat.players and chat.players[chat.sergeant_id]['role'] == '👮🏼 Сержант':
        sergeant_name = chat.players[chat.sergeant_id]['name']
        police_members.append(f"[{sergeant_name}](tg://user?id={chat.sergeant_id}) - 👮🏼 *Сержант*")

    message = "🚨 *Состав полиции:*\n" + "\n".join(police_members)

    for player_id in [chat.sheriff_id, chat.sergeant_id]:
        if player_id in chat.players:
            bot.send_message(player_id, message, parse_mode='Markdown')

def process_deaths(chat, killed_by_mafia, killed_by_sheriff, killed_by_bomber=None, killed_by_maniac=None):
    combined_message = ""
    deaths = {}  # Храним информацию о том, кто убил кого

    # Проверка и группировка по целям:
    if killed_by_mafia:
        victim_id, victim = killed_by_mafia
        deaths[victim_id] = {'victim': victim, 'roles': ['🤵🏻‍♂️ Дон']}

    if killed_by_sheriff:
        victim_id, victim = killed_by_sheriff
        if victim_id in deaths:
            deaths[victim_id]['roles'].append('🕵🏼 Комиссар Каттани')
        else:
            deaths[victim_id] = {'victim': victim, 'roles': ['🕵🏼 Комиссар Каттани']}

    if killed_by_maniac:
        victim_id, victim = killed_by_maniac
        if victim_id in deaths:
            deaths[victim_id]['roles'].append('🔪 Маньяк')
        else:
            deaths[victim_id] = {'victim': victim, 'roles': ['🔪 Маньяк']}

    # Добавляем проверку на пропуски действий (Сон)
    for player_id, player in chat.players.items():
        if player['role'] != 'dead' and player.get('skipped_actions', 0) >= 2:
            # Если игрока уже посетили другие роли, добавляем "Сон" к списку ролей
            if player_id in deaths:
                deaths[player_id]['roles'].append('💤 Сон')
            else:
                deaths[player_id] = {'victim': player, 'roles': ['💤 Сон']}

    # Обрабатываем смерти, выводим сообщения для каждого убитого
    for victim_id, death_info in deaths.items():
        victim = death_info['victim']
        roles_involved = death_info['roles']

        # Игнорируем щит, если одной из причин смерти был "Сон"
        if '💤 Сон' not in roles_involved:
            # Проверка наличия щита у игрока
            if victim_id in player_profiles and player_profiles[victim_id]['shield'] > 0:
                player_profiles[victim_id]['shield'] -= 1  # Уменьшаем количество щитов на 1
                roles_failed = ", ".join(roles_involved)
                bot.send_message(chat.chat_id, f"🪽 Кто-то из игроков потратил щит\n*{roles_failed}* не смог убить его", parse_mode="Markdown")
                bot.send_message(victim_id, "⚔️ Тебя пытались убить, но щит спас тебя!")
                continue

        # Игнорируем лечение доктора, если одной из причин смерти был "Сон"
        if '💤 Сон' not in roles_involved and chat.doc_target and chat.doc_target == victim_id:
            roles_failed = ", ".join(roles_involved)
            bot.send_message(chat.chat_id, f'👨🏼‍⚕️ *Доктор* кого-то спас этой ночью\n*{roles_failed}* не смог его убить', parse_mode="Markdown")
            bot.send_message(chat.doc_target, '👨🏼‍⚕️ *Доктор* вылечил тебя!', parse_mode="Markdown")
            continue

        # Проверка Смертника: если он убит, забирает с собой убийцу
        if victim['role'] == '💣 Смертник':
            for killer_role in roles_involved:
                if killer_role in ['🤵🏻‍♂️ Дон', '🕵🏼 Комиссар Каттани', '🔪 Маньяк']:
                    if killer_role == '🤵🏻‍♂️ Дон' and chat.don_id:
                        don_player_link = f"[{chat.players[chat.don_id]['name']}](tg://user?id={chat.don_id})"
                        combined_message += f"Сегодня был жестоко убит 🤵🏻‍♂️ *Дон* {don_player_link}...\nХодят слухи, что у него был визит от 💣 *Смертник*\n\n"
                        chat.remove_player(chat.don_id, killed_by='night')

                    if killer_role == '🕵🏼 Комиссар Каттани' and chat.sheriff_id:
                        sheriff_player_link = f"[{chat.players[chat.sheriff_id]['name']}](tg://user?id={chat.sheriff_id})"
                        combined_message += f"Сегодня был жестоко убит 🕵🏼 *Комиссар Каттани* {sheriff_player_link}...\nХодят слухи, что у него был визит от 💣 *Смертник*\n\n"
                        chat.remove_player(chat.sheriff_id, killed_by='night')

                    if killer_role == '🔪 Маньяк' and chat.maniac_id:
                        maniac_player_link = f"[{chat.players[chat.maniac_id]['name']}](tg://user?id={chat.maniac_id})"
                        combined_message += f"Сегодня был жестоко убит 🔪 *Маньяк* {maniac_player_link}...\nХодят слухи, что у него был визит от 💣 *Смертник*\n\n"
                        chat.remove_player(chat.maniac_id, killed_by='night')

        # Формируем сообщение о смерти
        victim_link = f"[{victim['name']}](tg://user?id={victim_id})"
        role_list = ", ".join(roles_involved)
        combined_message += f"Сегодня был жестоко убит *{victim['role']}* {victim_link}...\n"
        combined_message += f"Ходят слухи, что у него был визит от *{role_list}*\n\n"

        # Удаление игрока из игры
        chat.remove_player(victim_id, killed_by='night')

    # Выводим финальное сообщение с результатами ночи
    if combined_message:
        bot.send_message(chat.chat_id, combined_message, parse_mode="Markdown")
    else:
        # Если никого не убили, выводим сообщение
        bot.send_message(chat.chat_id, "_🤷 Странно, этой ночью все остались в живых..._", parse_mode="Markdown")

    # Теперь выполняем передачу ролей после всех убийств
    check_and_transfer_don_role(chat)
    check_and_transfer_sheriff_role(chat)

def process_night_actions(chat):
    for player_id, player in chat.players.items():
        if player['role'] != 'dead' and not player_made_action(player_id):
            player_profiles[player_id]['skipped_actions'] += 1
        else:
            player_profiles[player_id]['skipped_actions'] = 0  # Сбрасываем счетчик, если игрок выполнил действие


def get_or_create_profile(user_id, user_name):
    # Проверяем, существует ли профиль в словаре
    profile = player_profiles.get(user_id)
    
    if not profile:
        # Если профиля нет, создаем новый
        profile = {
            'id': user_id,
            'name': user_name,
            'euro': 0,  # Например, стартовый баланс
            'coins': 0,
            'shield': 0,
            'fake_docs': 0  # Инициализируем fake_docs значением 0
        }
        # Сохраняем профиль в словаре
        player_profiles[user_id] = profile
    else:
        # Убедимся, что профиль содержит все необходимые ключи
        if 'fake_docs' not in profile:
            profile['fake_docs'] = 0
        if 'shield' not in profile:
            profile['shield'] = 0
        if 'coins' not in profile:
            profile['coins'] = 0

    return profile

def send_profiles_to_channel():
    # Замените на ID вашего канала
    channel_id = '@Hjoxbednxi'

    if not player_profiles:
        print("❌ Нет доступных данных о профилях.")
        return

    for user_id, profile in player_profiles.items():
        # Формируем сообщение с данными каждого профиля с экранированием специальных символов
        profile_data = (
            f"/give {profile.get('id', 'Отсутствует')} euro {profile.get('euro', '0')} "
            f"shield {profile.get('shield', '0')} fake\\_docs {profile.get('fake_docs', '0')} "
            f"coins {profile.get('coins', '0')}"
        )

        try:
            # Отправляем данные каждого профиля отдельно в канал
            bot.send_message(channel_id, profile_data, parse_mode="MarkdownV2")
            time.sleep(5)  # Задержка на 5 секунд
        except Exception as e:
            logging.error(f"Ошибка отправки данных профиля в канал: {e}")
            return

    print("✅ Данные профилей отправлены в канал.")

def process_mafia_action(chat):
    mafia_victim = None
    if chat.mafia_votes and not chat.dead:
        vote_counts = {}
        for voter_id, victim_id in chat.mafia_votes.items():
            if voter_id == chat.don_id:
                vote_counts[victim_id] = vote_counts.get(victim_id, 0) + 3  # Голос Дона считается за 3
            else:
                vote_counts[victim_id] = vote_counts.get(victim_id, 0) + 1  # Голоса обычных мафиози

        # Находим максимальное количество голосов
        max_votes = max(vote_counts.values(), default=0)
        possible_victims = [victim for victim, votes in vote_counts.items() if votes == max_votes]

        # Если несколько жертв с одинаковым количеством голосов
        if len(possible_victims) > 1:
            if chat.don_id in chat.mafia_votes:
                # Если Дон проголосовал, приоритет его выбору
                mafia_victim = chat.mafia_votes[chat.don_id]
            else:
                # Если Дон не проголосовал
                send_message_to_mafia(chat, "*Голосование завершено.*\nСемья не смогла выбрать жертву.")
                return None  # Если Дона нет, голосование провалено
        else:
            # Если есть один явный лидер по голосам
            mafia_victim = possible_victims[0]

        # Отправляем сообщение о результате голосования
        if mafia_victim and mafia_victim in chat.players:
            # Экранируем специальные символы в имени жертвы для Markdown
            mafia_victim_name = chat.players[mafia_victim]['name'].replace('_', '\\_').replace('*', '\\*').replace('[', '\\[')
            send_message_to_mafia(chat, f"*Голосование завершено*\nМафия выбрала жертву: {mafia_victim_name}")
            bot.send_message(chat.chat_id, "🤵🏻 *Мафия* выбрала жертву...", parse_mode="Markdown")

            # Проверка на блокировку Дона или другие условия
            if chat.don_id and chat.players[chat.don_id].get('voting_blocked', False):
                mafia_victim = None  # Блокируем убийство мафией
            else:
                chat.dead = (mafia_victim, chat.players[mafia_victim])
        else:
            send_message_to_mafia(chat, "*Голосование завершено.*\nСемья не смогла выбрать жертву.")
    else:
        send_message_to_mafia(chat, "*Голосование завершено.*\nСемья не смогла выбрать жертву.")

    chat.mafia_votes.clear()
    return mafia_victim


@bot.message_handler(commands=['start'])
def start_message(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if message.chat.type == 'private':
        # Логика для приватного чата
        user_name = message.from_user.first_name if message.from_user.first_name else "Пользователь"
        
        get_or_create_profile(user_id, user_name)
        
        text = message.text

        # Проверяем, есть ли параметр после команды /start
        if len(text.split()) > 1:
            param = text.split()[1]
            if param.startswith("join_"):
                game_chat_id = int(param.split('_')[1])
                chat = chat_list.get(game_chat_id)
                if chat:
                    try:
                        # Проверка прав пользователя в группе
                        chat_member = bot.get_chat_member(game_chat_id, user_id)

                        # Проверка, может ли пользователь отправлять сообщения
                        if chat_member.status in ['member', 'administrator', 'creator'] and (chat_member.can_send_messages is None or chat_member.can_send_messages):
                            if chat.game_running:
                                bot.send_message(user_id, "🚫 Не удалось присоединиться, игра уже началась!")
                            elif not chat.button_id:
                                bot.send_message(user_id, "🚫 Не удалось присоединиться, игра не запущена.")
                            elif user_id not in chat.players:
                                user_name = message.from_user.first_name
                                chat.players[user_id] = {'name': user_name, 'role': 'ждет', 'skipped_actions': 0}
                                bot.send_message(user_id, f"🎲 Вы присоединились в чате {bot.get_chat(game_chat_id).title}")

                                # Обновляем сообщение о регистрации игроков
                                new_text = players_alive(chat.players, "registration")
                                new_markup = types.InlineKeyboardMarkup([[types.InlineKeyboardButton('🤵🏻 Присоединиться', url=f'https://t.me/{bot.get_me().username}?start=join_{game_chat_id}')]])

                                try:
                                    bot.edit_message_text(chat_id=game_chat_id, message_id=chat.button_id, text=new_text, reply_markup=new_markup, parse_mode="Markdown")
                                except Exception as e:
                                    logging.error(f"Ошибка обновления сообщения: {e}")
                                
                                # Проверяем количество зарегистрированных игроков
                                if len(chat.players) >= 20:
                                    _start_game(game_chat_id)
                            else:
                                bot.send_message(user_id, "✅ Вы уже в игре! :)")
                        else:
                            bot.send_message(user_id, "🚫 Вы не можете присоединиться к игре, так как у вас нет прав на отправку сообщений в группе.")
                    except Exception as e:
                        logging.error(f"Ошибка при проверке прав доступа: {e}")
                        bot.send_message(user_id, "Произошла ошибка при попытке присоединиться к игре.")
                return

        # Клавиатура для других действий, если команда /start без параметров
        keyboard = types.InlineKeyboardMarkup()
        join_chat_btn = types.InlineKeyboardButton('Войти в чат', callback_data='join_chat')
        keyboard.add(join_chat_btn)
        
        news_btn = types.InlineKeyboardButton('📰 Новости', url='t.me/FrenemyMafiaNews')
        keyboard.add(news_btn)

        bot_username = bot.get_me().username
        add_to_group_url = f'https://t.me/{bot_username}?startgroup=bot_command'
        add_to_group_btn = types.InlineKeyboardButton('🤵🏽 Добавить игру в свой чат', url=add_to_group_url)
        keyboard.add(add_to_group_btn)

        bot.send_message(chat_id, '*Привет!*\nЯ бот-ведущий для игры в 🤵🏻 *Мафию.*\nДобавь меня в чат, назначь администратором и начни играть бесплатно', reply_markup=keyboard, parse_mode="Markdown")

    elif message.chat.type in ['group', 'supergroup']:
        # Логика для запуска игры в группе
        user_id = message.from_user.id

        bot.delete_message(chat_id, message.message_id)

        # Проверка, является ли пользователь администратором
        chat_member = bot.get_chat_member(chat_id, user_id)
        if chat_member.status not in ['administrator', 'creator']:
            return

        _start_game(chat_id)


def _start_game(chat_id):
    global notification_timers

    if chat_id not in chat_list:
        bot.send_message(chat_id, 'Сначала создайте игру с помощью команды /game.')
        return

    chat = chat_list[chat_id]
    if chat.game_running:
        bot.send_message(chat_id, 'Игра уже начата.')
        return

    if len(chat.players) < 4:
        bot.send_message(chat_id, '*Недостаточно игроков для начала игры...*', parse_mode="Markdown")
        reset_registration(chat_id)
        return

    # Удаляем сообщение о регистрации перед началом игры
    if chat.button_id:
        bot.delete_message(chat_id, chat.button_id)
        chat.button_id = None

    # Отменяем таймер уведомления, если он установлен
    if chat_id in notification_timers:
        notification_timers[chat_id].cancel()
        del notification_timers[chat_id]

    # Отменяем таймер старта игры, если он установлен
    if chat_id in game_start_timers:
        game_start_timers[chat_id].cancel()
        del game_start_timers[chat_id]

    # Устанавливаем флаг, что игра запущена
    chat.game_running = True

    # Инициализируем время начала игры
    chat.game_start_time = time.time()

    bot.send_message(chat_id, '*Игра начинается!*\n\n👤 Идет выдача ролей...', parse_mode="Markdown")

    players_list = list(chat.players.items())
    shuffle(players_list)

    num_players = len(players_list)
    num_mafias = max(1, (num_players // 3))  # Минимум одна мафия
    mafia_assigned = 0

    # Установим статус alive для всех игроков перед началом игр
    numbers = list(range(1, num_players + 1))
    shuffle(numbers)
    for i, (player_id, player_info) in enumerate(players_list):
        player_info['status'] = 'alive'
        player_info['number'] = numbers[i]  # Присваиваем случайный уникальный номер
    # Назначение Дона
    logging.info(f"Назначение Дона: {players_list[0][1]['name']}")
    change_role(players_list[0][0], chat.players, '🤵🏻‍♂️ Дон', 'Ты — 🤵🏻‍♂️ Дон!\n\nТебе решать кто не проснётся этой ночью...', chat)
    chat.don_id = players_list[0][0]
    mafia_assigned += 1

    # Назначение мафии
    for i in range(1, num_players):
        if mafia_assigned < num_mafias:
            logging.info(f"Назначение Мафии: {players_list[i][1]['name']}")
            change_role(players_list[i][0], chat.players, '🤵🏻 Мафия', 'Ты — 🤵🏻 Мафия!\n\nВаша цель - следить за указанием главаря мафии (Дон) и остаться в живых', chat)
            mafia_assigned += 1

    roles_assigned = mafia_assigned + 1  # Учитывая Дона

    # Назначение доктора при 4 и более игроках
    if roles_assigned < num_players and num_players >= 4:
        logging.info(f"Назначение Доктора: {players_list[roles_assigned][1]['name']}")
        change_role(players_list[roles_assigned][0], chat.players, '👨🏼‍⚕️ Доктор', 'Ты — 👨🏼‍⚕️ Доктор!\n\nТебе решать кого спасти этой ночью...', chat)
        roles_assigned += 1

    # Назначение Самоубийцы при 4 и более игроках
    if roles_assigned < num_players and num_players >= 30:
        logging.info(f"Назначение Самоубийцы: {players_list[roles_assigned][1]['name']}")
        change_role(players_list[roles_assigned][0], chat.players, '🤦‍♂️ Самоубийца', 'Ты — 🤦‍♂️ Самоубийца!\n\nТвоя задача - быть повешенным на городском собрании! :)', chat)
        chat.suicide_bomber_id = players_list[roles_assigned][0]
        roles_assigned += 1

    # Назначение бомжа при 5 и более игроках
    if roles_assigned < num_players and num_players >= 5:
        logging.info(f"Назначение Бомжа: {players_list[roles_assigned][1]['name']}")
        change_role(players_list[roles_assigned][0], chat.players, '🧙‍♂️ Бомж', 'Ты — 🧙‍♂️ Бомж!\n\nТы можешь зайти за бутылкой к любому игроку и стать свидетелем убийства.', chat)
        chat.hobo_id = players_list[roles_assigned][0]
        roles_assigned += 1

    # Назначение Комиссара при 6 и более игроках
    if roles_assigned < num_players and num_players >= 6:
        logging.info(f"Назначение Комиссара: {players_list[roles_assigned][1]['name']}")
        change_role(players_list[roles_assigned][0], chat.players, '🕵🏼 Комиссар Каттани', 'Ты — 🕵🏼 Комиссар Каттани!\n\nГлавный городской защитник и гроза мафии. Твоя задача - находить мафию и исключать во время голосования.', chat)
        chat.sheriff_id = players_list[roles_assigned][0]
        roles_assigned += 1

    # Назначение счастливчика при 7 и более игроках
    if roles_assigned < num_players and num_players >= 8:
        logging.info(f"Назначение Счастливчика: {players_list[roles_assigned][1]['name']}")
        change_role(players_list[roles_assigned][0], chat.players, '🤞 Счастливчик', 'Ты — 🤞 Счастливчик!\n\nТвоя задача вычислить мафию и на городском собрании повесить засранцев. Если повезёт, при покушении ты останешься жив.', chat)
        chat.lucky_id = players_list[roles_assigned][0]
        roles_assigned += 1

    # Назначение смертника при 12 и более игроках
    if roles_assigned < num_players and num_players >= 12:
        logging.info(f"Назначение Смертника: {players_list[roles_assigned][1]['name']}")
        change_role(players_list[roles_assigned][0], chat.players, '💣 Смертник', 'Ты — 💣 Смертник!\n\nДнём и ночью ты обычный мирный житель, но если тебя попытаются убить, то ты сможешь выбрать кого из игроков забрать с собой в могилу', chat)
        chat.suicide_bomber_id = players_list[roles_assigned][0]
        roles_assigned += 1

    # Назначение Любовницы
    if roles_assigned < num_players and num_players >= 7:
        logging.info(f"Назначение Любовницы: {players_list[roles_assigned][1]['name']}")
        change_role(players_list[roles_assigned][0], chat.players, '💃🏼 Любовница', 'Ты — 💃 Любовница!\n\nПроводит ночь с одним из жителей городка, мешая ему при этом на одну ночь убить кого-то и говорить на дневном собрании.', chat)
        chat.lover_id = players_list[roles_assigned][0]
        roles_assigned += 1

    if roles_assigned < num_players and num_players >= 16:  # Адвокат появляется при 5 и более игроках
        logging.info(f"Назначение Адвоката: {players_list[roles_assigned][1]['name']}")
        change_role(players_list[roles_assigned][0], chat.players, '👨🏼‍💼 Адвокат', 'Ты — 👨🏼‍💼 Адвокат!\n\nТвоя задача - ночью выбирать кого защищать. Если ты выберешь Мафию, то Комиссар не сможет распознать её и покажет роль Мирного Жителя. Твоя задача - предугадать выбор комиссара и скрыть Мафию от его проверок.', chat)
        roles_assigned += 1

    if roles_assigned < num_players and num_players >= 13:  # Сержант назначается, если игроков 5 и более
        logging.info(f"Назначение Сержанта: {players_list[roles_assigned][1]['name']}")
        change_role(players_list[roles_assigned][0], chat.players, '👮🏼 Сержант', 'Ты — 👮🏼 Сержант!\n\nПомощник комиссара Каттани. Он будет информировать тебя о своих действиях и держать в курсе событий. Если комиссар погибнет - ты займёшь его место.', chat)
        chat.sergeant_id = players_list[roles_assigned][0]
        roles_assigned += 1

    # Назначение маньяка при 6 и более игроках
    if roles_assigned < num_players and num_players >= 16:
        logging.info(f"Назначение Маньяка: {players_list[roles_assigned][1]['name']}")
        change_role(players_list[roles_assigned][0], chat.players, '🔪 Маньяк', 'Ты — 🔪 Маньяк!\n\nВыступает сам за себя, каждую ночь убивая одного из жителей города. Может победить, только если останется один.', chat)
        chat.maniac_id = players_list[roles_assigned][0]
        roles_assigned += 1

    # Назначение оставшихся ролей как мирных жителей
    for i in range(roles_assigned, num_players):
        logging.info(f"Назначение Мирного жителя: {players_list[i][1]['name']}")
        change_role(players_list[i][0], chat.players, '👨🏼 Мирный житель', 'Ты — 👨🏼 Мирный житель!\n\nТвоя задача найти мафию и повесить на дневном голосовании.', chat)

    # Проверка, чтобы никто не остался с ролью "ждет"
    for player_id, player_info in chat.players.items():
        if player_info['role'] == 'ждет':
            logging.error(f"Игрок {player_info['name']} остался без роли!")
            change_role(player_id, chat.players, '👨🏼 Мирный житель', 'Ты — 👨🏼 Мирный житель!\n\nТвоя задача найти мафию и повесить на дневном голосовании.', chat)

    # Запуск основного игрового цикла
    asyncio.run(game_cycle(chat_id))
    
@bot.callback_query_handler(func=lambda call: call.data == 'join_chat')
def join_chat_callback(call):
    chat_id = call.message.chat.id
    message_id = call.message.message_id

    bot.answer_callback_query(call.id, "Выберите чат")
    # Создаем клавиатуру для кнопки "🛠️ Тестовый"
    test_button = types.InlineKeyboardMarkup()
    test_btn = types.InlineKeyboardButton('🎲 Frenemy Mafia Chat', url='https://t.me/FrenemyMafiaChat')
    test_button.add(test_btn)

    # Отправляем сообщение с кнопкой "🛠️ Тестовый"
    bot.send_message(chat_id, '*Список чатов*', reply_markup=test_button, parse_mode="Markdown")

@bot.message_handler(commands=['game'])
def create_game(message):
    chat_id = message.chat.id

    # Проверяем, что команда вызвана в групповом чате
    if message.chat.type not in ['group', 'supergroup']:
        bot.reply_to(message, "Эту команду можно использовать только в групповом чате.")
        return

    if chat_id not in chat_list:
        chat_list[chat_id] = Game(chat_id)

    bot.delete_message(chat_id, message.message_id)

    chat = chat_list[chat_id]

    if chat.game_running or chat.button_id:
        # Игнорируем команду и удаляем сообщение, если игра уже начата или регистрация уже открыта
        bot.delete_message(chat_id, message.message_id)
        return

    # Используем блокировку, чтобы предотвратить одновременное нажатие
    with registration_lock:
        if chat.button_id:
            # Если регистрация уже была начата, игнорируем дальнейшие действия
            return

        join_btn = types.InlineKeyboardMarkup()
        bot_username = bot.get_me().username
        join_url = f'https://t.me/{bot_username}?start=join_{chat_id}'
        item1 = types.InlineKeyboardButton('🤵🏻 Присоединиться', url=join_url)
        join_btn.add(item1)

        # Отправляем начальное сообщение о наборе
        msg_text = registration_message(chat.players)
        msg = bot.send_message(chat_id, msg_text, reply_markup=join_btn, parse_mode="Markdown")
        chat.button_id = msg.message_id

        bot.pin_chat_message(chat_id, msg.message_id)

        # Уведомляем игроков о начале регистрации
        notify_game_start(chat)  # <-- Здесь вызываем функцию для уведомления всех игроков

        # Запускаем таймер на 1 минуту для уведомления и на 2 минуты для начала игры
        notification_timers[chat_id] = threading.Timer(60.0, lambda: notify_one_minute_left(chat_id))
        game_start_timers[chat_id] = threading.Timer(120.0, lambda: start_game_with_delay(chat_id))

        notification_timers[chat_id].start()
        game_start_timers[chat_id].start()


def escape_markdown(text):
    # Экранируем специальные символы Markdown
    specials = r'\_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{char}' if char in specials else char for char in text)

@bot.message_handler(commands=['profile'])
def handle_profile(message):
    if message.chat.type == 'private':
        user_id = message.from_user.id  # Получаем ID пользователя
        user_name = message.from_user.first_name
        show_profile(message, user_id=user_id, user_name=user_name)

def show_profile(message, user_id, message_id=None, user_name=None):
    if not user_name:
        user_name = message.from_user.first_name

    profile = get_or_create_profile(user_id, user_name)

    # Формируем сообщение профиля с экранированными символами
    profile_text = f"*Ваш профиль*\n\n" \
                   f"👤 {escape_markdown(profile['name'])}\n🪪 ID: {user_id}\n\n" \
                   f"💶 *Евро*: {profile['euro']}\n" \
                   f"🪙 *Монета*: {profile['coins']}\n\n" \
                   f"⚔️ *Щит*: {profile['shield']}\n" \
                   f"📁 *Документы*: {profile['fake_docs']}\n\n"

    markup = types.InlineKeyboardMarkup()
    shop_btn = types.InlineKeyboardButton("🛒 Магазин", callback_data="shop")
    buy_coins_btn = types.InlineKeyboardButton("Купить 🪙", callback_data="buy_coins")
    markup.add(shop_btn, buy_coins_btn)

    if message_id:
        bot.edit_message_text(chat_id=message.chat.id, message_id=message_id, text=profile_text, reply_markup=markup, parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, profile_text, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data in ['shop', 'buy_coins', 'buy_shield', 'buy_fake_docs', 'back_to_profile'])
def handle_shop_actions(call):
    user_id = call.from_user.id
    user_name = call.from_user.first_name
    profile = get_or_create_profile(user_id, user_name)

    if not profile:
        bot.answer_callback_query(call.id, "Профиль не найден.", show_alert=True)
        return

    if call.data == "shop":
        # Магазин с предметами, с экранированием символов
        shop_text = f"💶 _Баланс_: {escape_markdown(str(profile['euro']))}\n" \
                    f"🪙 *Монета*: {escape_markdown(str(profile['coins']))}\n\n" \
                    f"⚔️ *Щит* (💶 150)\n_Спасет вас один раз от смерти._\n\n" \
                    f"📁 *Поддельные документы* (💶 200)\n_Комиссар увидит вас как мирного жителя._"
        
        markup = types.InlineKeyboardMarkup()
        buy_shield_btn = types.InlineKeyboardButton("⚔️ Щит - 💶 150", callback_data="buy_shield")
        buy_docs_btn = types.InlineKeyboardButton("📁 Поддельные документы - 💶 200", callback_data="buy_fake_docs")
        back_btn = types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_profile")
        markup.add(buy_shield_btn, buy_docs_btn)
        markup.add(back_btn)
        
        bot.edit_message_text(shop_text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif call.data == "buy_shield":
        if profile['euro'] >= 150:
            profile['euro'] -= 150
            profile['shield'] += 1
            # Сохраняем изменения сразу после покупки
            player_profiles[user_id] = profile

            # Обновляем профиль сразу после покупки, чтобы корректно отобразить изменения
            purchase_text = f"*Вы успешно купили щит!*\n\n💶 _Баланс_: {escape_markdown(str(profile['euro']))}\n🪙 *Монета:* {escape_markdown(str(profile['coins']))}\n⚔️ *Щитов:* {escape_markdown(str(profile['shield']))}\n📁 *Поддельные документы:* {escape_markdown(str(profile['fake_docs']))}"
            bot.answer_callback_query(call.id, "✅ Вы успешно купили ⚔️ Щит", show_alert=True)
            
            markup = types.InlineKeyboardMarkup()
            back_btn = types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_profile")
            markup.add(back_btn)
            
            # После покупки обновляем сообщение
            bot.edit_message_text(purchase_text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Недостаточно средств для покупки", show_alert=True)

    elif call.data == "buy_fake_docs":
        if profile['euro'] >= 200:
            profile['euro'] -= 200
            profile['fake_docs'] += 1
            # Сохраняем изменения в глобальном профиле сразу после покупки
            player_profiles[user_id] = profile

            # Обновляем профиль сразу после покупки
            purchase_text = f"*Вы успешно купили поддельные документы!*\n\n💶 _Баланс:_ {escape_markdown(str(profile['euro']))}\n🪙 *Монета:* {escape_markdown(str(profile['coins']))}\n⚔️ *Щитов:* {escape_markdown(str(profile['shield']))}\n📁 *Поддельные документы:* {escape_markdown(str(profile['fake_docs']))}"
            bot.answer_callback_query(call.id, "✅ Вы успешно купили Поддельные Документы!", show_alert=True)
            
            markup = types.InlineKeyboardMarkup()
            back_btn = types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_profile")
            markup.add(back_btn)
            
            # После покупки обновляем сообщение
            bot.edit_message_text(purchase_text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Недостаточно средств для покупки", show_alert=True)

    elif call.data == "back_to_profile":
        # При возврате к профилю обновляем информацию из глобального словаря
        profile = player_profiles[user_id]  # Обновляем профиль из глобального словаря
        show_profile(call.message, message_id=call.message.message_id, user_id=user_id, user_name=user_name)

@bot.message_handler(commands=['help'])
def send_help(message):
    # Проверяем, что сообщение отправлено в личном чате с ботом
    if message.chat.type == 'private':
        bot.send_message(message.chat.id, "⚙️ *Есть ошибки*⁉️\nВсе вопросы и ошибки, можете писать здесь 👇\n@RealMafiaDiscussion", parse_mode="Markdown")

@bot.message_handler(commands=['stop'])
def stop_game(message):
    global game_tasks, registration_timers

    chat_id = message.chat.id
    user_id = message.from_user.id

    bot.delete_message(chat_id, message.message_id)

    # Проверяем, что пользователь является администратором
    chat_member = bot.get_chat_member(chat_id, user_id)
    if chat_member.status not in ['administrator', 'creator']:
        return


    # Проверяем, идет ли регистрация или игра запущена
    chat = chat_list.get(chat_id)
    if not chat or (not chat.game_running and not chat.button_id):
        # Если ни регистрация, ни игра не начата, не делаем ничего
        return

    # Остановка таймера регистрации, если он существует
    if chat_id in registration_timers:
        registration_timers[chat_id].cancel()
        del registration_timers[chat_id]

    # Завершение игры, если она началась
    if chat_id in game_tasks:
        game_tasks[chat_id].cancel()  # Останавливаем цикл игры
        del game_tasks[chat_id]

    if chat.game_running:
        chat.game_running = False
        bot.send_message(chat_id, "🚫 *Игра остановлена\nадминистратором!*", parse_mode="Markdown")
        reset_game(chat)  # Сбрасываем игру
        reset_roles(chat)
    else:
        reset_registration(chat_id)  # Сбрасываем регистрацию, если игра не началась
        bot.send_message(chat_id, "*🚫 Регистрация отменена\nадминистратором*", parse_mode="Markdown")


@bot.message_handler(commands=['time'])
def stop_registration_timer(message):
    global notification_timers, game_start_timers
    chat_id = message.chat.id
    user_id = message.from_user.id

    bot.delete_message(chat_id, message.message_id)

    # Проверяем, что пользователь является администратором
    chat_member = bot.get_chat_member(chat_id, user_id)
    if chat_member.status not in ['administrator', 'creator']:
        return

    # Проверяем наличие таймеров и останавливаем их
    timers_stopped = False

    if chat_id in notification_timers:
        notification_timers[chat_id].cancel()
        del notification_timers[chat_id]
        timers_stopped = True

    if chat_id in game_start_timers:
        game_start_timers[chat_id].cancel()
        del game_start_timers[chat_id]
        timers_stopped = True

    # Если был остановлен хотя бы один таймер, выводим сообщение
    if timers_stopped:
        bot.send_message(chat_id, "*Таймер автоматического старта игры отключен.*\nЗапустите игру вручную через команду /start.", parse_mode="Markdown")


# Команда /next для отправки уведомления о новой регистрации в чате
@bot.message_handler(commands=['next'])
def next_message(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    chat_title = bot.get_chat(chat_id).title

    bot.delete_message(chat_id, message.message_id)

    if chat_id not in next_players:
        next_players[chat_id] = []

    # Добавляем игрока в список тех, кто нажал "next"
    if user_id not in next_players[chat_id]:
        next_players[chat_id].append(user_id)

    # Отправляем уведомление в личные сообщения игрока
    bot.send_message(user_id, f"🔔 Вам придёт оповещение о новой регистрации в чате *{chat_title}*", parse_mode="Markdown")

def notify_game_start(chat):
    chat_title = bot.get_chat(chat.chat_id).title
    if chat.chat_id in next_players:
        for player_id in next_players[chat.chat_id]:
            try:
                join_btn = types.InlineKeyboardMarkup()
                bot_username = bot.get_me().username
                join_url = f'https://t.me/{bot_username}?start=join_{chat.chat_id}'
                item1 = types.InlineKeyboardButton('🤵🏻 Присоединиться', url=join_url)
                join_btn.add(item1)

                # Отправляем сообщение о начале регистрации
                bot.send_message(player_id, f"👑 В чате *{chat_title}* начата регистрация на новую игру!", reply_markup=join_btn, parse_mode="Markdown")
            except Exception as e:
                logging.error(f"Ошибка при отправке уведомления о старте игры игроку {player_id}: {e}")

        next_players[chat.chat_id] = []

@bot.message_handler(commands=['leave'])
def leave_game(message):
    user_id = message.from_user.id
    game_chat_id = message.chat.id  # Получаем идентификатор чата
    
    # Удаляем сообщение с командой
    try:
        bot.delete_message(chat_id=game_chat_id, message_id=message.message_id)
    except Exception as e:
        logging.error(f"Не удалось удалить сообщение: {e}")

    chat = chat_list.get(game_chat_id)
    
    if chat and not chat.game_running and user_id in chat.players:
        # Удаляем игрока из списка
        chat.players.pop(user_id)
        bot.send_message(user_id, "👾 Вы вышли из игры.")
        
        # Обновляем сообщение о регистрации с кнопкой присоединиться
        new_msg_text = registration_message(chat.players)
        
        # Создаем новую клавиатуру с кнопкой "Присоединиться"
        new_markup = types.InlineKeyboardMarkup([[types.InlineKeyboardButton('🤵🏻 Присоединиться', url=f'https://t.me/{bot.get_me().username}?start=join_{game_chat_id}')]])
        
        try:
            bot.edit_message_text(chat_id=game_chat_id, message_id=chat.button_id, text=new_msg_text, reply_markup=new_markup, parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Ошибка обновления сообщения: {e}")
    else:
        bot.send_message(user_id, "🚫 Вы не зарегистрированы в этой игре\nили игра уже началась.")


@bot.message_handler(commands=['give'])
def give_items(message):
    # ID пользователя, который имеет право выполнять команду
    allowed_user_id = 6265990443  # Замените на ваш user_id

    # Проверяем, что команду выполняет авторизованный пользователь
    if message.from_user.id != allowed_user_id:
        bot.reply_to(message, "❌ У вас нет прав для выполнения этой команды.")
        return

    # Получаем аргументы команды
    command_args = message.text.split()

    # Проверяем, что переданы правильные аргументы
    if len(command_args) < 4 or (len(command_args) - 2) % 2 != 0:
        bot.reply_to(message, "❌ Неправильный формат команды. Используйте: /give <user_id> <item1> <amount1> [<item2> <amount2> ...]")
        return

    try:
        # Извлекаем user_id игрока
        target_user_id = int(command_args[1])

        # Проверяем, существует ли профиль игрока
        if target_user_id not in player_profiles:
            # Если профиль не существует, создаем новый профиль с именем пользователя
            try:
                # Попытка получить информацию о пользователе
                user_info = bot.get_chat(target_user_id)
                username = user_info.username or user_info.first_name
            except Exception as e:
                # Если не удалось получить имя пользователя, используем 'Неизвестный'
                username = "Неизвестный"

            # Создаем профиль с начальными значениями
            player_profiles[target_user_id] = {
                'id': target_user_id,
                'name': username,
                'euro': 0,
                'shield': 0,
                'fake_docs': 0,
                'coins': 0
            }
            bot.reply_to(message, f"🆕 Профиль пользователя с именем {username} и ID {target_user_id} создан.")

        # Обрабатываем пары item-amount из команды
        response = []
        for i in range(2, len(command_args), 2):
            item_type = command_args[i].lower()
            try:
                amount = int(command_args[i + 1])
            except ValueError:
                bot.reply_to(message, f"❌ Неправильный формат количества для {item_type}. Используйте целое число.")
                return

            # Обновляем значения профиля игрока в зависимости от item_type
            if item_type in player_profiles[target_user_id]:
                player_profiles[target_user_id][item_type] += amount
                response.append(f"✅ {item_type.capitalize()}: {amount}")
            else:
                response.append(f"❌ Неправильный тип предмета: {item_type}")

        # Отправляем итоговое сообщение с результатами
        bot.reply_to(message, f"Результаты для игрока {target_user_id}:\n" + "\n".join(response))

    except ValueError:
        bot.reply_to(message, "❌ Неправильный формат user_id. Используйте числовое значение.")

@bot.message_handler(commands=['check'])
def check_profiles(message):
    chat_id = message.chat.id

    try:
        send_profiles_to_channel()
        bot.send_message(chat_id, "✅ Данные профилей отправлены в канал.")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Ошибка при отправке данных профилей в канал: {e}")
    

bot_username = "@RealMafiaTestBot"

def all_night_actions_taken(chat):
    for player in chat.players.values():
        # Проверяем только живых игроков с активными ролями
        if player['role'] in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон', '🕵🏼 Комиссар Каттани', '👨🏼‍⚕️ Доктор', '🧙‍♂️ Бомж', '💃🏼 Любовница', '👨🏼‍💼 Адвокат', '🔪 Маньяк'] and player['role'] != 'dead':
            # Если игрок заблокирован или не выполнил действие, возвращаем False
            if player.get('voting_blocked', False) or not player.get('action_taken', False):
                return False
    return True

# Обновленный код для функции game_cycle
async def game_cycle(chat_id):
    global chat_list, is_night, is_voting_time, game_tasks
    chat = chat_list[chat_id]
    game_start_time = time.time()

    day_count = 1

    try:
        while chat.game_running:  # Основной цикл игры
            if not chat.game_running:
                break
            await asyncio.sleep(3)

            if not chat.game_running:
                break

            # Начало ночи
            is_night = True
            is_voting_time = False  # Убедимся, что голосование неактивно ночью

            # Сохраняем предыдущую цель любовницы перед сбросом
            chat.previous_lover_target_id = chat.lover_target_id  # Перенос текущей цели в предыдущую

            # Сброс всех выборов перед началом ночи
            chat.dead = None
            chat.sheriff_check = None
            chat.sheriff_shoot = None
            chat.doc_target = None
            chat.mafia_votes.clear()
            chat.hobo_target = None
            chat.hobo_visitors.clear()
            chat.lover_target_id = None  # Сброс цели любовницы
            chat.shList_id = None
            chat.lawyer_target = None
            chat.maniac_target# Сброс цели адвоката

            dead_id = None

            # Сбрасываем флаг action_taken у всех игроков перед новой ночью
            for player in chat.players.values():
                player['action_taken'] = False

            if not chat.game_running:
                break

            players_alive_text = players_alive(chat.players, "night")

            # Создание кнопки для личного сообщения бота
            bot_username = bot.get_me().username
            private_message_url = f'https://t.me/{bot_username}'
            private_message_btn = types.InlineKeyboardMarkup()
            private_message_btn.add(types.InlineKeyboardButton('Перейти к боту', url=private_message_url))

            # Отправляем сообщение с кнопкой и списком живых игроков
            bot.send_photo(chat_id, 'https://t.me/Hjoxbednxi/66', caption='🌙 *Наступает ночь*\nНа улицы города выходят лишь самые отважные и бесстрашные.\nУтром попробуем сосчитать их головы...', parse_mode="Markdown", reply_markup=private_message_btn)
            bot.send_message(chat_id=chat_id, text=players_alive_text, parse_mode="Markdown", reply_markup=private_message_btn)

            notify_mafia_and_don(chat)
            
            notify_police(chat)  # Уведомляем полицейских о составе

            if not chat.game_running:
                break

            # Отправляем новые кнопки выбора для ночных ролей
            for player_id, player in chat.players.items():
                if not chat.game_running:
                    break

                if player['role'] in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон']:
                    list_btn(chat.players, player_id, 'мафия', 'Кого будем устранять?', 'м')

                elif player['role'] == '🕵🏼 Комиссар Каттани':
                    send_sheriff_menu(chat, player_id)

                elif player['role'] == '👨🏼‍⚕️ Доктор':
                    list_btn(chat.players, player_id, 'доктор', 'Кого будем лечить?', 'д')

                elif player['role'] == '🧙‍♂️ Бомж':
                    list_btn(chat.players, player_id, 'бомж', 'К кому пойдешь за бутылкой?', 'б')

                elif player['role'] == '💃🏼 Любовница':
                    players_btn = types.InlineKeyboardMarkup()
                    for key, val in chat.players.items():
                        if key != player_id and val['role'] != 'dead' and (chat.previous_lover_target_id is None or key != chat.previous_lover_target_id):
                            players_btn.add(types.InlineKeyboardButton(val['name'], callback_data=f'{key}_л'))

                    bot.send_message(player_id, "С кем будешь проводить ночь?", reply_markup=players_btn)

                elif player['role'] == '👨🏼‍💼 Адвокат':
                    list_btn(chat.players, player_id, 'адвокат', 'Кого будешь защищать?', 'а')

                # Отправляем кнопки выбора для Маньяка
                elif player['role'] == '🔪 Маньяк':
                    list_btn(chat.players, player_id, 'маньяк', 'Кого будешь убивать?', 'мк')


            start_time = time.time()
            while time.time() - start_time < 30:
                if all_night_actions_taken(chat):
                    break
                await asyncio.sleep(2)

            if not chat.game_running:
                break

            is_night = False

            # Обработка действий любовницы
            don_blocked = False
            lover_target_healed = False
            if chat.lover_target_id and chat.lover_target_id in chat.players:
                lover_target = chat.players[chat.lover_target_id]
                bot.send_message(chat.lover_target_id, '"Ты со мною забудь обо всём...", - пела 💃🏼 Любовница', parse_mode="Markdown")

                if chat.doc_target == chat.lover_target_id:
                    bot.send_message(chat.lover_target_id, "💃🏼 *Любовница* хотела замолкнуть тебя, но увидела, что 👨🏼‍⚕️ *Доктор* у тебя и ушла!", parse_mode="Markdown")
                    lover_target_healed = True  # Устанавливаем флаг, что цель любовницы была вылечена
                else:

                # Устанавливаем флаг блокировки голосования
                    lover_target['voting_blocked'] = True

                # Отправляем сообщение игроку, что голосовать он не сможет

                    if lover_target['role'] == '🤵🏻‍♂️ Дон':
                        don_blocked = True  # Блокируем убийство мафией
                    elif lover_target['role'] == '🕵🏼 Комиссар Каттани':
                        chat.sheriff_check = None  # Блокируем проверку Комиссара
                        chat.sheriff_shoot = None  # Блокируем выстрел Комиссара
                    elif lover_target['role'] == '👨🏼‍⚕️ Доктор':
                        chat.doc_target = None  # Блокируем лечение доктора
                    elif lover_target['role'] == '🧙‍♂️ Бомж':
                        chat.hobo_visitors.clear()  # Блокируем проверку бомжа
                    elif lover_target['role'] == '👨🏼‍💼 Адвокат':
                        chat.lawyer_target = None  # Блокируем действие адвоката

                    elif lover_target['role'] == '🔪 Маньяк':  # Добавляем блокировку для маньяка
                        chat.maniac_target = None  # Блокируем действие маньяка

            if lover_target_healed:
                lover_target['voting_blocked'] = False
                lover_target['healed_from_lover'] = True  # Устанавливаем флаг лечения жертвы любовницы

            # Обработка результата действия адвоката
            lawyer_target = None
            if chat.lawyer_id and chat.lawyer_id in chat.players:
                lawyer_target = chat.players[chat.lawyer_id].get('lawyer_target')

            # Обрабатываем действия Маньяка
            killed_by_maniac = None
            if chat.maniac_target and chat.maniac_target in chat.players:
                killed_by_maniac = (chat.maniac_target, chat.players[chat.maniac_target])
                chat.maniac_target = None

            # Пример обработки действия мафии
            mafia_victim = process_mafia_action(chat)

            if not chat.game_running:
                break

            # Обработка результатов действий бомжа
            if chat.hobo_id and chat.hobo_target:
                hobo_target = chat.hobo_target
                if hobo_target in chat.players:  # Проверка существования hobo_target
                    hobo_target_name = chat.players[hobo_target]['name']
                    hobo_visitors = []

                    bot.send_message(hobo_target, f'🧙🏼‍♂️ *Бомж* выпросил у тебя бутылку этой ночью', parse_mode="Markdown")

                    # Если мафия выбрала ту же цель, что и Бомж
                    if chat.dead and chat.dead[0] == hobo_target:
                        don_id = chat.don_id
                        if don_id in chat.players:
                            don_name = chat.players[don_id]['name']
                            hobo_visitors.append(don_name)

                    # Если Комиссар выбрал ту же цель для проверки или стрельбы
                    if chat.sheriff_check == hobo_target or chat.sheriff_shoot == hobo_target:
                        sheriff_id = chat.sheriff_id
                        if sheriff_id in chat.players:
                            sheriff_name = chat.players[sheriff_id]['name']
                            hobo_visitors.append(sheriff_name)

                    # Если Доктор выбрал ту же цель для лечения
                    if chat.doc_target == hobo_target:
                        doc_id = next((pid for pid, p in chat.players.items() if p['role'] == '👨🏼‍⚕️ Доктор'), None)
                        if doc_id and doc_id in chat.players:
                            doc_name = chat.players[doc_id]['name']
                            hobo_visitors.append(doc_name)

                    if chat.maniac_target == hobo_target:
                        maniac_id = chat.maniac_id
                        if maniac_id in chat.players:
                            maniac_name = chat.players[maniac_id]['name']
                            hobo_visitors.append(maniac_name)

                    if chat.lover_target_id == hobo_target:
                        lover_id = chat.lover_id
                        if lover_id in chat.players:
                            lover_name = chat.players[lover_id]['name']
                            hobo_visitors.append(lover_name)

                    # Формируем сообщение для Бомжа
                    if hobo_visitors:
                        visitors_names = ', '.join(hobo_visitors)
                        bot.send_message(chat.hobo_id, f'Ночью ты пришёл за бутылкой к {hobo_target_name} и увидел там {visitors_names}.')
                    else:
                        bot.send_message(chat.hobo_id, f'Ты выпросил бутылку у {hobo_target_name} и ушел обратно на улицу. Ничего подозрительного не произошло.')
                else:
                    bot.send_message(chat.hobo_id, 'Ты никого не встретил этой ночью.')

            if not chat.game_running:
                break

            # Удаление игроков, пропустивших действия
            to_remove = []
            for player_id, player in chat.players.items():
                if not chat.game_running:
                    break
                if player['role'] not in ['👨🏼 Мирный житель', '🤞 Счастливчик', '💣 Смертник', '👮🏼 Сержант'] and not player.get('action_taken', False):
                    player['skipped_actions'] += 1
                    if player['skipped_actions'] >= 2:
                        to_remove.append(player_id)
                else:
                    player['action_taken'] = False
                    player['skipped_actions'] = 0

            bot.send_photo(chat_id, 'https://t.me/Hjoxbednxi/67', caption=f'🌤️ *День {day_count}*\nВзошло солнце и высушило кровь, пролитую вчера вечером на асфальте...', parse_mode="Markdown")

            await asyncio.sleep(4)

            if not chat.game_running:
                break

            # Обработка убийств
            killed_by_mafia = chat.dead  # Жертва мафии
            killed_by_sheriff = None
            killed_by_bomber = None# Жертва Комиссара


            if chat.sheriff_shoot and chat.sheriff_shoot in chat.players:
               shooted_player = chat.players[chat.sheriff_shoot]
               killed_by_sheriff = (chat.sheriff_shoot, chat.players[chat.sheriff_shoot])
               chat.sheriff_shoot = None

            process_deaths(chat, killed_by_mafia, killed_by_sheriff, killed_by_bomber, killed_by_maniac)

            if not chat.game_running:
                break

            logging.info(f"Цель Комиссара: {chat.sheriff_check}, Цель адвоката: {chat.lawyer_target}")

            # Проверка, показывается ли Комиссару "мирный житель"
            if chat.lawyer_target and chat.sheriff_check and chat.lawyer_target == chat.sheriff_check:
                checked_player = chat.players[chat.sheriff_check]
                bot.send_message(chat.sheriff_id, f"Ты выяснил, что {checked_player['name']} - 👨🏼 Мирный житель.")
                bot.send_message(chat.sheriff_check, '🕵🏼  *Комиссар Каттани* навестил тебя, но адвокат показал, что ты мирный житель.', parse_mode="Markdown")
                if chat.sergeant_id and chat.sergeant_id in chat.players:
                    sergeant_message = f"🕵🏼  Комиссар Каттани проверил {checked_player['name']}, его роль - 👨🏼 Мирный житель."
                    bot.send_message(chat.sergeant_id, sergeant_message)
            else:
                if chat.sheriff_check and chat.sheriff_check in chat.players:
                    checked_player = chat.players[chat.sheriff_check]

                    if 'fake_docs' not in checked_player:
                        checked_player['fake_docs'] = 0  # Если ключ отсутствует, инициализируем его
                        
                    if checked_player['fake_docs'] > 0:
                        bot.send_message(chat.sheriff_id, f"Ты выяснил, что {checked_player['name']} - 👨🏼 Мирный житель (фальшивые документы).")
                        bot.send_message(chat.sheriff_check, '🕵🏼  *Комиссар Каттани* навестил тебя, но ты показал фальшивые документы.', parse_mode="Markdown")
                        checked_player['fake_docs'] -= 1
                    else:
                        bot.send_message(chat.sheriff_id, f"Ты выяснил, что {checked_player['name']} - {checked_player['role']}.")
                        bot.send_message(chat.sheriff_check, '🕵🏼 *Комиссар Каттани* решил навестить тебя.', parse_mode="Markdown")
                    if chat.sergeant_id and chat.sergeant_id in chat.players:
                        sergeant_message = f"🕵🏼 Комиссар Каттани проверил {checked_player['name']}, его роль - {checked_player['role']}."
                        bot.send_message(chat.sergeant_id, sergeant_message)

            if check_game_end(chat, game_start_time):
                break  # Если игра закончена, выходим из цикла

            players_alive_text = players_alive(chat.players, "day")
            msg = bot.send_message(chat_id=chat_id, text=players_alive_text, parse_mode="Markdown")
            chat.button_id = msg.message_id

            chat.dead = None
            chat.sheriff_check = None

            await asyncio.sleep(30)

            if not chat.game_running:
                break

            # Начало голосования днем
            is_voting_time = True  # Включаем время голосования
            chat.vote_counts.clear()  # Сброс голосов перед началом нового голосования
            vote_msg = bot.send_message(chat.chat_id, '*Пришло время определить и наказать виноватых*\nГолосование продлится 45 секунд', reply_markup=types.InlineKeyboardMarkup([
                [types.InlineKeyboardButton('🗳 Голосование', url=f'https://t.me/{bot.get_me().username}')]
            ]), parse_mode="Markdown")
            chat.vote_message_id = vote_msg.message_id

            lover_target_healed = chat.doc_target == chat.lover_target_id

            for player_id in chat.players:
                if not chat.game_running:
                    break
                if player_id != chat.lover_target_id or lover_target_healed:  # Не отправляем сообщение жертве любовницы
                    try:
                        bot.send_message(player_id, '*Пришло время искать виноватых!*\nКого ты хочешь повесить?', reply_markup=types.InlineKeyboardMarkup(
                            [[types.InlineKeyboardButton(chat.players[pid]['name'], callback_data=f"{pid}_vote")] for pid in chat.players if pid != player_id] +
                            [[types.InlineKeyboardButton('🚷 Пропустить', callback_data='skip_vote')]]
                        ), parse_mode="Markdown")
                    except Exception as e:
                        logging.error(f"Не удалось отправить сообщение игроку {player_id}: {e}")

            if not chat.game_running:
                break

            vote_end_time = time.time() + 45
            while time.time() < vote_end_time:
                if not chat.game_running:
                    break
                if all(player.get('has_voted', False) for player in chat.players.values()):
                    break
                await asyncio.sleep(5)

            if not chat.game_running:
                break

            # Обрабатываем результат голосования
            should_continue = end_day_voting(chat)

            # Если игра не должна продолжаться после голосования
            if not should_continue:
                reset_voting(chat)
                day_count += 1
                continue

            is_voting_time = False  # Отключаем время голосования

            if check_game_end(chat, game_start_time):
                break  # Если игра закончена, выходим из цикла

            await asyncio.sleep(30)

            if not chat.game_running:
                break

            # Вызываем обработку подтверждающего голосования
            handle_confirm_vote(chat)

            chat.confirm_votes = {'yes': 0, 'no': 0, 'voted': {}}
            await asyncio.sleep(2)

            chat.vote_counts.clear()
            for player in chat.players.values():
                if not chat.game_running:
                    break
                player['has_voted'] = False

            # Сброс блокировки голосования в конце дня
            for player in chat.players.values():
                player['voting_blocked'] = False  # Разблокируем голосование для всех игроков

            if check_game_end(chat, game_start_time):
                break  # Если игра закончена, выходим из цикла

            day_count += 1

    except asyncio.CancelledError:
        logging.info(f"Игра в чате {chat_id} была принудительно остановлена.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('join_'))
def join_game(call):
    chat_id = int(call.data.split('_')[1])
    chat = chat_list.get(chat_id)
    user_id = call.from_user.id
    user_name = call.from_user.first_name

    if chat and not chat.game_running and chat.button_id:
        if user_id not in chat.players:
            add_player(chat, user_id, user_name)
            bot.answer_callback_query(call.id, text="Вы присоединились к игре!")

            # Обновляем сообщение о наборе
            new_msg_text = registration_message(chat.players)
            
            # Проверяем, изменился ли текст перед обновлением сообщения
            if new_msg_text != call.message.text:
                try:
                    bot.edit_message_text(chat_id=chat_id, message_id=chat.button_id, text=new_msg_text, reply_markup=call.message.reply_markup, parse_mode="Markdown")
                except Exception as e:
                    logging.error(f"Ошибка обновления сообщения: {e}")
            
            # Проверяем количество игроков
            if len(chat.players) >= 20:
                _start_game(chat_id)  # Запускаем игру, если зарегистрировалось достаточное количество игроков
        else:
            bot.answer_callback_query(call.id, text="Вы уже зарегистрированы в этой игре.")
    else:
        bot.answer_callback_query(call.id, text="Ошибка: игра уже началась или регистрация не открыта.")

@bot.callback_query_handler(func=lambda call: call.data == 'skip_vote')
def skip_vote_handler(call):
    global chat_list, is_voting_time

    from_id = call.from_user.id
    chat = None
    for c_id, c in chat_list.items():
        if from_id in c.players:
            chat = c
            chat_id = c_id
            break

    if not chat:
        bot.answer_callback_query(call.id, text="⛔️ ты не в игре.")
        return

    if not is_voting_time:  
        bot.answer_callback_query(call.id, text="Голосование сейчас недоступно.")
        return

    if 'vote_counts' not in chat.__dict__:
        chat.vote_counts = {}

    if not chat.players[from_id].get('has_voted', False):
        chat.vote_counts['skip'] = chat.vote_counts.get('skip', 0) + 1
        chat.players[from_id]['has_voted'] = True
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Ты выбрал(а) пропустить голосование")
        voter_link = f"[{chat.players[from_id]['name']}](tg://user?id={from_id})"
        bot.send_message(chat_id, f"🚷 {voter_link} предлагает никого не вешать", parse_mode="Markdown")

    if all(player.get('has_voted', False) for player in chat.players.values()):
        end_day_voting(chat)


@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    global chat_list, is_voting_time, vote_timestamps, is_night  # Добавлено is_night для отслеживания ночной/дневной фазы
    from_id = call.from_user.id
    current_time = time.time()

    chat = None
    for c_id, c in chat_list.items():
        if from_id in c.players:
            chat = c
            chat_id = c_id
            break

    if not chat:
        bot.answer_callback_query(call.id, text="⛔️ ты не в игре.")
        return

    player = chat.players.get(from_id)

    if player['role'] == 'dead':
        bot.answer_callback_query(call.id, text="⛔️ ты мертв!")
        return

    if chat.confirm_votes.get('player_id') == from_id:
        return

    # Проверка блокировки голосования, если игрока выбрала любовница
    if player.get('voting_blocked', False) and not player.get('healed_from_lover', False):
        bot.answer_callback_query(call.id, text="💃🏼 Ты со мною забудь обо всём... ")
        return

    # Проверка, нажимал ли игрок кнопку недавно
    if from_id in vote_timestamps:
        last_vote_time = vote_timestamps[from_id]
        if current_time - last_vote_time < 1:
            bot.answer_callback_query(call.id, text="Голос принят!")  # Интервал в 3 секунды
            return  # Просто игнорируем нажатие

    # Обновляем время последнего нажатия
    vote_timestamps[from_id] = current_time

    try:
        logging.info(f"Получены данные: {call.data}")
        data_parts = call.data.split('_')

        if len(data_parts) < 2:
            logging.error(f"Недостаточно данных в callback_data: {call.data}")
            return

        action = data_parts[0]
        role = data_parts[1]

        if action in ['yes', 'no']:
            if from_id == chat.confirm_votes['player_id']:
                bot.answer_callback_query(call.id, text="Ты не можешь голосовать.")
                return
            time.sleep(1.5)

        # Проверка, что действия Комиссара доступны только ночью
        if role == '🕵🏼 Комиссар Каттани':
            if not is_night:  # Если сейчас не ночь
                bot.answer_callback_query(call.id, text="Действия  доступны только ночью.")
                return

            # Проверка, совершил ли Комиссар уже действие
            if chat.players[from_id].get('action_taken', False):
                bot.answer_callback_query(call.id, text="Вы уже сделали выбор этой ночью.")
                return

        # Обработка голосования
        if call.data.startswith('confirm'):
            player_id = int(data_parts[1])
            vote_confirmation = data_parts[2]

            if from_id in chat.confirm_votes['voted']:
                previous_vote = chat.confirm_votes['voted'][from_id]
                if previous_vote == 'yes':
                    chat.confirm_votes['yes'] -= 1
                elif previous_vote == 'no':
                    chat.confirm_votes['no'] -= 1

            chat.confirm_votes['voted'][from_id] = vote_confirmation

            if vote_confirmation == 'yes':
                chat.confirm_votes['yes'] += 1
            elif vote_confirmation == 'no':
                chat.confirm_votes['no'] += 1

            confirm_markup = types.InlineKeyboardMarkup()
            confirm_markup.add(
                types.InlineKeyboardButton(f"👍🏼 {chat.confirm_votes['yes']}", callback_data=f"confirm_{player_id}_yes"),
                types.InlineKeyboardButton(f"👎🏼 {chat.confirm_votes['no']}", callback_data=f"confirm_{player_id}_no")
            )

            # Проверяем, изменилась ли разметка перед обновлением
            current_markup = call.message.reply_markup
            new_markup_data = confirm_markup.to_dict()
            current_markup_data = current_markup.to_dict() if current_markup else None

            if new_markup_data != current_markup_data:
                try:
                    bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=confirm_markup)
                except Exception as e:
                    logging.error(f"Ошибка при обновлении клавиатуры голосования: {e}")
            else:
                logging.info("Клавиатура уже актуальна, обновление не требуется.")

            bot.answer_callback_query(call.id, text="Голос принят!")

            alive_players_count = len([p for p in chat.players.values() if p['role'] != 'dead' and p['status'] == 'alive' and p != chat.confirm_votes['player_id']])
            if chat.confirm_votes['yes'] + chat.confirm_votes['no'] == alive_players_count:
                disable_vote_buttons(chat)
                send_voting_results(chat, chat.players[player_id]['name'], chat.confirm_votes['yes'], chat.confirm_votes['no'])

        else:
            action = data_parts[1]

            # Обработка действий, которые требуют числового значения в первой части данных
            if action in ['ш', 'с', 'м', 'мк', 'д', 'б', 'л', 'а', 'vote']:
                try:
                    target_id = int(data_parts[0])  # Пробуем преобразовать в число
                except ValueError:
                    logging.error(f"Невозможно преобразовать данные в число: {data_parts[0]}")
                    return

                player_role = chat.players[from_id]['role']

                # Обработка действий для Комиссара, мафии, адвоката и других ролей
                if player_role == '🕵🏼 Комиссар Каттани' and action == 'ш':
                    if not is_night:  # Если сейчас не ночь
                        bot.answer_callback_query(call.id, text="Действия  доступны только ночью.")
                        return# Комиссар проверяет игрока
                    if chat.players[from_id].get('action_taken', False):  # Проверяем, сделал ли уже Комиссар действие
                        bot.answer_callback_query(call.id, text="Вы уже сделали выбор этой ночью.")
                        return

                    chat.sheriff_check = target_id
                    chat.players[from_id]['action_taken'] = True  # Отмечаем, что Комиссар сделал действие
                    if chat.last_sheriff_menu_id:
                        try:
                            bot.edit_message_text(chat_id=from_id, message_id=chat.last_sheriff_menu_id, text=f"Ты пошёл проверять {chat.players[target_id]['name']}")
                        except Exception as e:
                            logging.error(f"Ошибка при обновлении последнего меню Комиссара: {e}")

                    bot.send_message(chat.chat_id, f"🕵🏼 *Комиссар Каттани* ушел искать злодеев...", parse_mode="Markdown")

                    # Отключаем кнопки после выбора
                    bot.edit_message_reply_markup(chat_id=from_id, message_id=chat.last_sheriff_menu_id, reply_markup=None)

                    # Уведомляем сержанта
                    if chat.sergeant_id and chat.sergeant_id in chat.players:
                        sergeant_message = f"🕵🏼 Комиссар Каттани {chat.players[from_id]['name']} отправился проверять {chat.players[target_id]['name']}."
                        bot.send_message(chat.sergeant_id, sergeant_message)

                elif player_role == '🕵🏼 Комиссар Каттани' and action == 'с':
                    if not is_night:  # Если сейчас не ночь
                        bot.answer_callback_query(call.id, text="Действия Комиссара доступны только ночью.")
                        return
                        # Комиссар стреляет в игрока
                    if chat.players[from_id].get('action_taken', False):  # Проверяем, сделал ли уже Комиссар действие
                        bot.answer_callback_query(call.id, text="Вы уже сделали выбор этой ночью.")
                        return

                    chat.sheriff_shoot = target_id
                    chat.players[from_id]['action_taken'] = True  # Отмечаем, что Комиссар сделал действие
                    if chat.last_sheriff_menu_id:
                        try:
                            bot.edit_message_text(chat_id=from_id, message_id=chat.last_sheriff_menu_id, text=f"Ты пошёл убивать {chat.players[target_id]['name']}")
                        except Exception as e:
                            logging.error(f"Ошибка при обновлении последнего меню Комиссара: {e}")

                    bot.send_message(chat.chat_id, f"🕵🏼 *Комиссар Каттани* зарядил свой пистолет...", parse_mode="Markdown")

                    # Отключаем кнопки после выбора
                    bot.edit_message_reply_markup(chat_id=from_id, message_id=chat.last_sheriff_menu_id, reply_markup=None)

                    # Уведомляем сержанта
                    if chat.sergeant_id and chat.sergeant_id in chat.players:
                        sergeant_message = f"🕵🏼 Комиссар Каттани {chat.players[from_id]['name']} стреляет в {chat.players[target_id]['name']}."
                        bot.send_message(chat.sergeant_id, sergeant_message)

                elif player_role in ['🤵🏻 Мафия', '🤵🏻‍♂️ Дон'] and action == 'м':  # Мафия или Дон выбирает жертву
                    if not handle_night_action(call, chat, player_role):
                        return

                    if target_id not in chat.players or chat.players[target_id]['role'] == 'dead':
                        bot.answer_callback_query(call.id, "Цель недоступна.")
                        return

                    victim_name = chat.players[target_id]['name']
                    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"Ты проголосвал за {victim_name}")

                    if from_id not in chat.mafia_votes:
                        chat.mafia_votes[from_id] = target_id
                        voter_name = chat.players[from_id]['name']
        
                        if player_role == '🤵🏻‍♂️ Дон':
                            send_message_to_mafia(chat, f"🤵🏻‍♂️ *Дон* [{voter_name}](tg://user?id={from_id}) проголосовал за {victim_name}")
                            for player_id, player in chat.players.items():
                                if player['role'] == '👨🏼‍💼 Адвокат':
                                    bot.send_message(player_id, f"🤵🏻‍♂️ Дон ??? проголосовал за {victim_name}")
                        else:
                            send_message_to_mafia(chat, f"🤵🏻 Мафия [{voter_name}](tg://user?id={from_id}) проголосовал(а) за {victim_name}")
                            for player_id, player in chat.players.items():
                                if player['role'] == '👨🏼‍💼 Адвокат':
                                    bot.send_message(player_id, f"🤵🏻 Мафия ??? проголосовал за {victim_name}")
                    else:
                        bot.answer_callback_query(call.id, "Вы уже проголосовали.")

                elif player_role == '👨🏼‍⚕️ Доктор' and action == 'д':  # Доктор выбирает цель для лечения
                    if not handle_night_action(call, chat, player_role):
                        return

                    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"Ты выбрал лечить {chat.players[target_id]['name']}")
                    
                    if target_id == from_id:
                        if player.get('self_healed', False):  
                            bot.answer_callback_query(call.id, text="Вы уже лечили себя, выберите другого игрока.")
                            return
                        else:
                            player['self_healed'] = True  
                    
                    chat.doc_target = target_id
                    bot.send_message(chat.chat_id, " 👨🏼‍⚕️ *Доктор* выехал спасать жизни...", parse_mode="Markdown")

                elif player_role == '🧙‍♂️ Бомж' and action == 'б':  # Бомж выбирает цель
                    if not handle_night_action(call, chat, player_role):
                        return
                    chat.hobo_target = target_id
                    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"Ты ушел за бутылкой к {chat.players[chat.hobo_target]['name']}")
                    bot.send_message(chat.chat_id, f"🧙‍♂️ *Бомж* пошел к кому-то за бутылкой…", parse_mode="Markdown")

                elif player_role == '💃🏼 Любовница' and action == 'л':
                    if not handle_night_action(call, chat, player_role):
                        return
                    chat.previous_lover_target_id = chat.lover_target_id
                    chat.lover_target_id = target_id
                    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"Ты отправилась спать с {chat.players[chat.lover_target_id]['name']}")
                    bot.send_message(chat.chat_id, "💃🏼 *Любовница* уже ждёт кого-то в гости...", parse_mode="Markdown")
                    logging.info(f"Предыдущая цель любовницы обновлена: {chat.previous_lover_target_id}")
                    logging.info(f"Текущая цель любовницы: {chat.lover_target_id}")

                elif player_role == '👨🏼‍💼 Адвокат' and action == 'а':  # Адвокат выбирает цель
                    if not handle_night_action(call, chat, player_role):
                        return
                    chat.lawyer_target = target_id
                    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"Ты выбрал защищать {chat.players[chat.lawyer_target]['name']}")
                    bot.send_message(chat.chat_id, "👨🏼‍💼 *Адвокат* ищет клиента для защиты...", parse_mode="Markdown")

                elif player_role == '🔪 Маньяк' and action == 'мк':  # Маньяк выбирает жертву
                    if not handle_night_action(call, chat, player_role):
                        return
                    chat.maniac_target = target_id
                    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"Ты выбрал убить {chat.players[chat.maniac_target]['name']}")
                    bot.send_message(chat.chat_id, "🔪 *Маньяк* вышел на охоту...", parse_mode="Markdown")

                elif action == 'vote':  # Голосование
                    if not is_voting_time:  
                        bot.answer_callback_query(call.id, text="Голосование сейчас недоступно.")
                        return

                    if 'vote_counts' not in chat.__dict__:
                        chat.vote_counts = {}

                    if not chat.players[from_id].get('has_voted', False):
                        victim_name = chat.players[target_id]['name']
                        chat.vote_counts[target_id] = chat.vote_counts.get(target_id, 0) + 1
                        chat.players[from_id]['has_voted'] = True
                        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"Ты выбрал(а) {victim_name}")
                        voter_link = f"[{chat.players[from_id]['name']}](tg://user?id={from_id})"
                        target_link = f"[{chat.players[target_id]['name']}](tg://user?id={target_id})"

                        bot.send_message(chat_id, f"{voter_link} проголосовал(а) за {target_link}", parse_mode="Markdown")

                    if all(player.get('has_voted', False) for player in chat.players.values()):
                        end_day_voting(chat)

            # Обработка действий "Проверять" и "Стрелять" для Комиссара
            elif action == 'check':
                if not is_night:  # Если сейчас не ночь
                    bot.answer_callback_query(call.id, text="Действия  доступны только ночью.")
                    return# Комиссар выбирает проверку
                if chat.players[from_id].get('action_taken', False):  # Проверяем, сделал ли уже Комиссар действие
                        bot.answer_callback_query(call.id, text="Вы уже сделали выбор этой ночью.")
                        return
                list_btn(chat.players, from_id, '🕵🏼 Комиссар Каттани', 'Кого будем проверять?', 'ш', message_id=chat.last_sheriff_menu_id)

            elif action == 'shoot':
                if not is_night:  # Если сейчас не ночь
                    bot.answer_callback_query(call.id, text="Действия  доступны только ночью.")
                    return# Комиссар выбирает стрельбу
                if chat.players[from_id].get('action_taken', False):  # Проверяем, сделал ли уже Комиссар действие
                        bot.answer_callback_query(call.id, text="Вы уже сделали выбор этой ночью.")
                        return
                list_btn(chat.players, from_id, '🕵🏼 Комиссар Каттани', 'Кого будем стрелять?', 'с', message_id=chat.last_sheriff_menu_id)

    except Exception as e:
        logging.error(f"Ошибка в callback_handler: {e}")

@bot.message_handler(func=lambda message: message.chat.type == 'private')
def handle_private_message(message):
    user_id = message.from_user.id
    chat = next((chat for chat in chat_list.values() if user_id in chat.players or user_id in chat.dead_last_words), None)

    if chat:
        if not chat.game_running:
            logging.info(f"Игра завершена, игнорируем сообщение от {user_id}")
            return

        # Если игрок мертв и может отправить последние слова
        if user_id in chat.dead_last_words:
            player_name = chat.dead_last_words.pop(user_id)
            last_words = message.text
            if last_words:
                player_link = f"[{player_name}](tg://user?id={user_id})"
                bot.send_message(chat.chat_id, f"Кто-то из жителей слышал, как {player_link} кричал перед смертью:\n_{last_words}_", parse_mode="Markdown")
                bot.send_message(user_id, "*Сообщение принято и отправлено в чат.*", parse_mode='Markdown')
            return

        # Пересылка сообщений между Комиссаром и Сержантом только ночью
        if is_night:
            if user_id == chat.sheriff_id and chat.sergeant_id in chat.players:
                bot.send_message(chat.sergeant_id, f"🕵🏼 *Комиссар {chat.players[user_id]['name']}*:\n{message.text}", parse_mode='Markdown')
            elif user_id == chat.sergeant_id and chat.sheriff_id in chat.players:
                bot.send_message(chat.sheriff_id, f"👮🏼 *Сержант {chat.players[user_id]['name']}*:\n{message.text}", parse_mode='Markdown')
            # Пересылка сообщений между мафией и Доном только ночью
            elif chat.players[user_id]['role'] in ['🤵🏻‍♂️ Дон', '🤵🏻 Мафия']:
                notify_mafia(chat, chat.players[user_id]['name'], message.text, user_id)

@bot.message_handler(content_types=['text', 'sticker', 'photo', 'video', 'document', 'audio', 'voice', 'animation'])
def handle_message(message):
    global is_night
    chat_id = message.chat.id
    user_id = message.from_user.id

    chat = chat_list.get(chat_id)
    if chat:
        if chat.game_running:
            chat_member = bot.get_chat_member(chat_id, user_id)
            is_admin = chat_member.status in ['administrator', 'creator']

            # Определяем тип сообщения
            message_type = message.content_type
            logging.info(f"Получено сообщение от {user_id} типа: {message_type}")

            if is_night:
                # Ночью удаляем все сообщения, кроме сообщений администраторов, начинающихся с '!'
                if not (is_admin and message_type == 'text' and message.text.startswith('!')):
                    try:
                        logging.info(f"Попытка удаления сообщения ночью от {user_id}: {message_type}")
                        bot.delete_message(chat_id, message.message_id)
                    except Exception as e:
                        logging.error(f"Ошибка при удалении сообщения от {user_id}: {e}")
                else:
                    logging.info(f"Сообщение ночью сохранено от {user_id} (админ с '!'): {message.text if message_type == 'text' else message_type}")
            else:
                # Днём удаляем сообщения от убитых, незарегистрированных игроков или жертвы любовницы (если не была вылечена), кроме сообщений администраторов с '!'
                player = chat.players.get(user_id, {})
                if ((user_id not in chat.players or player.get('role') == 'dead') or 
                    (user_id == chat.lover_target_id and not player.get('healed_from_lover', False))) and \
                    not (is_admin and message_type == 'text' and message.text.startswith('!')):
                    try:
                        logging.info(f"Попытка удаления сообщения днём от {user_id}: {message_type}")
                        bot.delete_message(chat_id, message.message_id)
                    except Exception as e:
                        logging.error(f"Ошибка при удалении сообщения от {user_id}: {e}")
                else:
                    logging.info(f"Сообщение днём сохранено от {user_id}: {message.text if message_type == 'text' else message_type}")

bot.infinity_polling()
