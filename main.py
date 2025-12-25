import telebot
from flask import Flask, request, jsonify
from threading import Thread
import sqlite3
import json
import time
import os

# ========== НАСТРОЙКИ ==========
TOKEN = os.environ.get("8426288768:AAHzFeW-Uqxga3dkKCfvZ9f4_9rrZy3t8xA")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)


# ========== БАЗА ДАННЫХ ==========
class Database:

    def __init__(self):
        self.conn = sqlite3.connect('users.db', check_same_thread=False)
        self.create_tables()

    def create_tables(self):
        # Пользователи
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                telegram_id INTEGER UNIQUE,
                website_token TEXT UNIQUE,
                is_linked BOOLEAN DEFAULT 0,
                created_at TIMESTAMP
            )
        ''')
        # Документы
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY,
                telegram_id INTEGER,
                doc_number TEXT,
                doc_title TEXT,
                doc_status TEXT,
                expiry_date TEXT,
                payment_date TEXT,
                external_url TEXT,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
            )
        ''')
        self.conn.commit()

    def add_user(self, telegram_id, website_token=None):
        """Добавить или обновить пользователя"""
        if website_token:
            self.conn.execute(
                '''
                INSERT OR REPLACE INTO users 
                (telegram_id, website_token, is_linked, created_at)
                VALUES (?, ?, 1, datetime('now'))
            ''', (telegram_id, website_token))
        else:
            self.conn.execute(
                '''
                INSERT OR IGNORE INTO users 
                (telegram_id, created_at)
                VALUES (?, datetime('now'))
            ''', (telegram_id, ))
        self.conn.commit()

    def link_user(self, telegram_id, website_token):
        """Привязать пользователя к сайту"""
        self.conn.execute(
            '''
            UPDATE users SET 
            website_token = ?, 
            is_linked = 1 
            WHERE telegram_id = ?
        ''', (website_token, telegram_id))
        self.conn.commit()

    def is_linked(self, telegram_id):
        """Проверка привязки"""
        result = self.conn.execute(
            'SELECT is_linked FROM users WHERE telegram_id = ?',
            (telegram_id, )).fetchone()
        return result[0] if result else False

    def get_user_token(self, telegram_id):
        """Получить токен пользователя"""
        result = self.conn.execute(
            'SELECT website_token FROM users WHERE telegram_id = ?',
            (telegram_id, )).fetchone()
        return result[0] if result else None

    def add_document(self, telegram_id, doc_data):
        """Добавить документ пользователю"""
        self.conn.execute(
            '''
            INSERT INTO documents 
            (telegram_id, doc_number, doc_title, doc_status, expiry_date, payment_date, external_url)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (telegram_id, doc_data.get('number'), doc_data.get('title'),
              doc_data.get('status'), doc_data.get('expiry_date'),
              doc_data.get('payment_date'), doc_data.get('url')))
        self.conn.commit()

    def get_user_documents(self, telegram_id):
        """Получить документы пользователя"""
        cursor = self.conn.execute(
            '''
            SELECT * FROM documents 
            WHERE telegram_id = ?
            ORDER BY expiry_date
        ''', (telegram_id, ))
        return cursor.fetchall()


# Создаем базу данных
db = Database()


# ========== FLASK API ДЛЯ САЙТА ==========
@app.route('/')
def home():
    return "📄 Document Assistant API - Работает на Railway!"


@app.route('/api/link', methods=['POST'])
def api_link():
    """API для привязки с сайта"""
    data = request.json
    website_token = data.get('token')
    telegram_id = data.get('telegram_id')

    if website_token and telegram_id:
        db.link_user(telegram_id, website_token)
        return jsonify({"status": "success", "message": "Аккаунт привязан"})
    return jsonify({"status": "error"})


@app.route('/api/send-document', methods=['POST'])
def api_send_document():
    """API для отправки документа с сайта"""
    data = request.json
    website_token = data.get('token')

    # Находим telegram_id по токену
    cursor = db.conn.execute(
        'SELECT telegram_id FROM users WHERE website_token = ?',
        (website_token, ))
    result = cursor.fetchone()

    if result:
        telegram_id = result[0]
        doc_data = {
            'number': data.get('number', 'Без номера'),
            'title': data.get('title', 'Документ'),
            'status': data.get('status', 'Новый'),
            'expiry_date': data.get('expiry_date'),
            'payment_date': data.get('payment_date'),
            'url': data.get('url', 'https://ваш-сайт.ру')
        }

        # Сохраняем документ
        db.add_document(telegram_id, doc_data)

        # Отправляем уведомление
        send_document_notification(telegram_id, doc_data)

        return jsonify({"status": "sent"})

    return jsonify({"status": "user_not_found"})


# ========== TELEGRAM БОТ ==========
def send_document_notification(telegram_id, doc_data):
    """Отправить уведомление о документе"""
    keyboard = telebot.types.InlineKeyboardMarkup()
    keyboard.row(
        telebot.types.InlineKeyboardButton("👀 Открыть на сайте",
                                           url=doc_data.get(
                                               'url', 'https://ваш-сайт.ру')),
        telebot.types.InlineKeyboardButton(
            "⏰ Отслеживать", callback_data=f"track_{doc_data['number']}"))
    keyboard.row(
        telebot.types.InlineKeyboardButton(
            "🗄️ Архивировать", callback_data=f"archive_{doc_data['number']}"))

    bot.send_message(telegram_id,
                     f"📄 *{doc_data['title']} {doc_data['number']}*\n"
                     f"Статус: {doc_data['status']}\n"
                     f"Дата: {doc_data.get('expiry_date', 'Не указана')}\n\n"
                     f"Что вы хотите сделать?",
                     reply_markup=keyboard,
                     parse_mode='Markdown')


def send_payment_reminder(telegram_id, doc_data):
    """Отправить напоминание об оплате"""
    keyboard = telebot.types.InlineKeyboardMarkup()
    keyboard.row(
        telebot.types.InlineKeyboardButton("✅ Оплачено", callback_data="paid"),
        telebot.types.InlineKeyboardButton("🔔 Напомнить позже",
                                           callback_data="remind_later"))
    keyboard.row(
        telebot.types.InlineKeyboardButton("👀 Открыть на сайте",
                                           url=doc_data.get(
                                               'url', 'https://ваш-сайт.ру')))

    bot.send_message(
        telegram_id, f"⏰ *НАПОМИНАНИЕ*\n"
        f"Срок оплаты по {doc_data['title']} {doc_data['number']}\n"
        f"истекает через 5 дней",
        reply_markup=keyboard,
        parse_mode='Markdown')


@bot.message_handler(commands=['start'])
def start_command(message):
    """Команда /start - начало работы"""
    telegram_id = message.chat.id
    db.add_user(telegram_id)  # Регистрируем пользователя

    # Проверяем привязку
    if db.is_linked(telegram_id):
        show_main_menu(message)
    else:
        show_link_instructions(message)


def show_link_instructions(message):
    """Показать инструкцию по привязке"""
    telegram_id = message.chat.id

    # Генерируем уникальный код для привязки
    import random
    link_code = f"LINK-{telegram_id}-{random.randint(1000, 9999)}"

    # Сохраняем код во временную базу
    db.conn.execute('UPDATE users SET website_token = ? WHERE telegram_id = ?',
                    (link_code, telegram_id))
    db.conn.commit()

    markup = telebot.types.InlineKeyboardMarkup()
    markup.row(
        telebot.types.InlineKeyboardButton(
            "🌐 Перейти на сайт для привязки",
            url=
            f"https://ваш-сайт.ру/link-telegram?code={link_code}&tid={telegram_id}"
        ))
    markup.row(
        telebot.types.InlineKeyboardButton("🔄 Проверить привязку",
                                           callback_data="check_link"))

    bot.send_message(telegram_id, f"🔗 *Привязка аккаунта к сайту*\n\n"
                     f"1. Ваш Telegram ID: `{telegram_id}`\n"
                     f"2. Код для привязки: `{link_code}`\n\n"
                     f"*Как привязать:*\n"
                     f"• Нажмите кнопку ниже\n"
                     f"• Или перейдите на сайт\n"
                     f"• Введите код в личном кабинете\n\n"
                     f"После привязки вы сможете:\n"
                     f"• Получать уведомления о документах\n"
                     f"• Видеть свои активные документы\n"
                     f"• Отслеживать сроки оплаты",
                     reply_markup=markup,
                     parse_mode='Markdown')


def show_main_menu(message):
    """Показать главное меню после привязки"""
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True,
                                               row_width=2)
    markup.row("📋 Мои документы", "⏰ Ближайшие события")
    markup.row("📄 Тест: Документ подписан", "💰 Тест: Напоминание об оплате")
    markup.row("🔄 Обновить", "⚙️ Настройки")

    bot.send_message(message.chat.id,
                     f"👋 Добро пожаловать, {message.from_user.first_name}!\n\n"
                     f"📄 *Ассистент документов готов к работе!*\n\n"
                     f"Вы можете:\n"
                     f"• Просматривать свои документы\n"
                     f"• Получать уведомления о статусах\n"
                     f"• Отслеживать сроки оплаты\n"
                     f"• Настраивать напоминания",
                     reply_markup=markup,
                     parse_mode='Markdown')


@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    """Обработка текстовых сообщений"""
    telegram_id = message.chat.id
    text = message.text

    # Проверяем привязку
    if not db.is_linked(telegram_id):
        bot.send_message(
            telegram_id, "⚠️ Сначала привяжите аккаунт к сайту!\n"
            "Используйте команду /start")
        return

    # Обработка команд меню
    if text == "📋 Мои документы":
        show_user_documents(telegram_id)

    elif text == "⏰ Ближайшие события":
        show_upcoming_events(telegram_id)

    elif text == "📄 Тест: Документ подписан":
        # Тест сценария А
        test_data = {
            'number': '24',
            'title': 'Договор услуг',
            'status': 'Подписан',
            'expiry_date': '25.12.2024',
            'url': 'https://ваш-сайт.ру/doc/24'
        }
        send_document_notification(telegram_id, test_data)

    elif text == "💰 Тест: Напоминание об оплате":
        # Тест сценария В
        test_data = {
            'number': '24',
            'title': 'Договор услуг',
            'url': 'https://ваш-сайт.ру/doc/24'
        }
        send_payment_reminder(telegram_id, test_data)

    elif text == "🔄 Обновить":
        bot.send_message(telegram_id, "✅ Данные обновлены!")
        show_user_documents(telegram_id)

    elif text == "⚙️ Настройки":
        show_settings(telegram_id)


def show_user_documents(telegram_id):
    """Показать документы пользователя"""
    documents = db.get_user_documents(telegram_id)

    if not documents:
        bot.send_message(
            telegram_id, "📭 У вас пока нет документов.\n"
            "Документы появятся здесь после их создания на сайте.")
        return

    message = "📋 *Ваши документы:*\n\n"
    for doc in documents:
        # doc: (id, telegram_id, number, title, status, expiry_date, payment_date, url)
        doc_id, _, number, title, status, expiry, payment, url = doc

        # Форматируем информацию
        expiry_info = f" | До: {expiry}" if expiry else ""
        payment_info = f" | Оплата: {payment}" if payment else ""

        message += f"• *{title} {number}*\n  Статус: {status}{expiry_info}{payment_info}\n\n"

    # Кнопки для каждого документа
    keyboard = telebot.types.InlineKeyboardMarkup()
    for doc in documents[:3]:  # Первые 3 документа
        _, _, number, title, _, _, _, url = doc
        keyboard.row(
            telebot.types.InlineKeyboardButton(
                f"👀 {title} {number}",
                url=url if url else "https://ваш-сайт.ру"))

    keyboard.row(
        telebot.types.InlineKeyboardButton("🔄 Обновить список",
                                           callback_data="refresh_docs"),
        telebot.types.InlineKeyboardButton("➕ Добавить документ",
                                           callback_data="add_doc"))

    bot.send_message(telegram_id,
                     message,
                     reply_markup=keyboard,
                     parse_mode='Markdown')


def show_upcoming_events(telegram_id):
    """Показать ближайшие события"""
    documents = db.get_user_documents(telegram_id)

    events = []
    for doc in documents:
        _, _, number, title, status, expiry, payment, _ = doc

        if expiry:
            events.append(f"• {title} {number} - истекает {expiry}")
        if payment:
            events.append(f"• {title} {number} - оплата до {payment}")

    if events:
        message = "⏰ *Ближайшие события:*\n\n" + "\n".join(
            events[:10])  # Первые 10 событий
    else:
        message = "✅ На ближайшее время событий нет."

    bot.send_message(telegram_id, message, parse_mode='Markdown')


def show_settings(telegram_id):
    """Показать настройки"""
    token = db.get_user_token(telegram_id)

    markup = telebot.types.InlineKeyboardMarkup()
    markup.row(
        telebot.types.InlineKeyboardButton("🔔 Вкл/Выкл уведомления",
                                           callback_data="toggle_notify"),
        telebot.types.InlineKeyboardButton("📅 Изменить время напоминаний",
                                           callback_data="change_time"))
    markup.row(
        telebot.types.InlineKeyboardButton("🔗 Показать код привязки",
                                           callback_data="show_token"),
        telebot.types.InlineKeyboardButton("❌ Отвязать аккаунт",
                                           callback_data="unlink"))

    bot.send_message(
        telegram_id, f"⚙️ *Настройки бота*\n\n"
        f"Текущий статус:\n"
        f"• Привязка: {'✅ Привязан' if token else '❌ Не привязан'}\n"
        f"• Токен: `{token if token else 'Не установлен'}`\n\n"
        f"Измените настройки:",
        reply_markup=markup,
        parse_mode='Markdown')


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    """Обработка нажатий на кнопки"""
    telegram_id = call.message.chat.id
    data = call.data

    if data == "check_link":
        if db.is_linked(telegram_id):
            bot.answer_callback_query(call.id, "✅ Аккаунт привязан!")
            show_main_menu(call.message)
        else:
            bot.answer_callback_query(call.id, "❌ Аккаунт еще не привязан")

    elif data.startswith("track_"):
        doc_number = data.replace("track_", "")
        bot.answer_callback_query(call.id,
                                  f"✅ Отслеживание включено для {doc_number}")
        bot.send_message(telegram_id,
                         f"Теперь я буду отслеживать документ {doc_number}")

    elif data.startswith("archive_"):
        doc_number = data.replace("archive_", "")
        bot.answer_callback_query(call.id,
                                  f"✅ Документ {doc_number} архивирован")
        bot.send_message(telegram_id,
                         f"Документ {doc_number} перемещен в архив")

    elif data == "paid":
        bot.answer_callback_query(call.id, "✅ Отметил как оплаченное")
        bot.send_message(telegram_id, "Статус оплаты обновлен")

    elif data == "remind_later":
        bot.answer_callback_query(call.id, "🔔 Напомню через 3 дня")
        bot.send_message(telegram_id, "Напоминание отложено на 3 дня")

    elif data == "refresh_docs":
        bot.answer_callback_query(call.id, "🔄 Обновляю...")
        show_user_documents(telegram_id)

    elif data == "show_token":
        token = db.get_user_token(telegram_id)
        bot.answer_callback_query(call.id, f"Токен: {token}")
        bot.send_message(telegram_id,
                         f"Ваш токен привязки: `{token}`",
                         parse_mode='Markdown')


# ========== ЗАПУСК ВСЕГО ==========
def run_flask():
    """Запуск Flask сервера"""
    port = int(os.environ.get("PORT", 3000))  # ✅ Railway сам назначает порт
    app.run(host='0.0.0.0', port=port)


if __name__ == '__main__':
    print("=" * 50)
    print("🚀 ЗАПУСКАЮ TELEGRAM БОТА НА RAILWAY")
    print("=" * 50)

    # Запускаем Flask в отдельном потоке
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    time.sleep(2)

    print("✅ Сервер запущен")
    print("🤖 Telegram бот запускается...")

    # Запускаем бота
    try:
        bot.polling(none_stop=True, interval=0, timeout=20)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        time.sleep(5)
