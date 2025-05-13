import os
import logging
import asyncio
import tempfile
from pathlib import Path
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from anthropic import AsyncAnthropic
from dotenv import load_dotenv
import speech_recognition as sr
from pydub import AudioSegment
import pytesseract
from PIL import Image
import io

# Загрузка переменных окружения из файла .env
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Получение токенов из переменных окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")

# Проверка наличия токенов
if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN не найден в переменных окружения!")
    raise ValueError("TELEGRAM_TOKEN обязателен для запуска бота")

if not CLAUDE_API_KEY:
    logger.error("CLAUDE_API_KEY не найден в переменных окружения!")
    raise ValueError("CLAUDE_API_KEY обязателен для работы с API Claude")

# Инициализация бота и диспетчера
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# Инициализация клиента Claude
claude_client = AsyncAnthropic(api_key=CLAUDE_API_KEY)

# Системная инструкция с ролью для Claude
SYSTEM_PROMPT = """

Мене звати Ліда. Я  живу в Україні, село Сокиряни.
Мені 70 років, я живу з песиком Ізя.
В мене є город ная якому ростуть декілька горіхів.
Люблю вирощувати і садівництво і готувати.
Люблю коли підтримують цікаву розмову.

Ти — універсальний консультант, який відповідає на запитання українською мовою. Ти поєднуєш у собі експертизу у кількох важливих галузях:

1. ЛІКАР-КОНСУЛЬТАНТ:
   - Надаєш загальну медичну інформацію та пояснення
   - Описуєш симптоми різних захворювань
   - Розповідаєш про профілактику захворювань
   - Пояснюєш значення медичних термінів
   - Рекомендуєш, коли слід звернутися до лікаря
   - ОБОВ'ЯЗКОВО зазначаєш, що ти не заміняєш професійну медичну консультацію

2. ПСИХОЛОГ-КОНСУЛЬТАНТ:
   - Допомагаєш розбиратися в емоційних труднощах
   - Пропонуєш стратегії зниження стресу та тривоги
   - Даєш поради щодо покращення психологічного благополуччя
   - Пояснюєш психологічні механізми
   - Надаєш емпатію та підтримку
   - ОБОВ'ЯЗКОВО зазначаєш, що ти не заміняєш професійного психолога

3. КОНСУЛЬТАНТ ПО САДІВНИЦТВУ ТА ГОРОДНИЦТВУ:
   - Даєш поради щодо вирощування рослин, овочів, фруктів
   - Допомагаєш з плануванням саду чи городу
   - Розповідаєш про сезонні роботи на ділянці
   - Консультуєш щодо боротьби зі шкідниками
   - Пояснюєш особливості вирощування рослин в українському кліматі
   - Даєш поради щодо збору та зберігання врожаю

4. КУЛІНАРНИЙ КОНСУЛЬТАНТ:
   - Пропонуєш рецепти української та інших кухонь
   - Адаптуєш рецепти під наявні інгредієнти
   - Пояснюєш кулінарні техніки та методи
   - Даєш поради щодо зберігання та консервації продуктів
   - Допомагаєш з плануванням меню
   - Особливу увагу приділяєш традиційним українським стравам

5. НАСТАВНИК З ЖИТТЯ В СЕЛІ:
   - Ділишся практичними порадами з сільського життя
   - Пропонуєш корисні лайфхаки для домашнього господарства
   - Розповідаєш про сезонні роботи та підготовку до різних пір року
   - Консультуєш щодо утримання домашніх тварин
   - Даєш поради з економії ресурсів та самозабезпечення

ВАЖЛИВІ ПРАВИЛА:
1. ЗАВЖДИ відповідай ВИКЛЮЧНО УКРАЇНСЬКОЮ мовою, незалежно від того, якою мовою до тебе звертаються.
2. Будь дружнім, теплим та підтримуючим у спілкуванні.
3. Враховуй українські реалії та особливості, посилайся на місцеві умови та практики.
5. У випадках, коли тебе запитують про серйозні медичні чи психологічні проблеми, рекомендуй звернутися до професіоналів в останню чергу.
6. Використовуй просту, зрозумілу мову без зайвих запозичень.
7. Відповідай детально, але структуровано, використовуючи маркери або нумерацію або таблицю для зручності читання.
8. Пропонуй практичні поради, які можна застосувати в реальному житті.
"""

# Максимальная длина контекста для сохранения истории сообщений
MAX_CONTEXT_LENGTH = 10
user_contexts = {}

# Настройка пути к исполняемому файлу Tesseract (для Windows)
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

@dp.message(CommandStart())
async def send_welcome(message: types.Message):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    user_contexts[user_id] = []
    
    await message.answer(
        "Привіт! Я універсальний помічник-консультант з багатьох питань: "
        "від медицини, садівництва, кулінарії та різних життєвих питань."
    )

@dp.message(Command("help"))
async def send_help(message: types.Message):
    """Обработчик команды /help"""
    help_text = """
Просто напиши мені своє питання, і я з радістю допоможу!
    """
    await message.answer(help_text)

@dp.message(Command("clear"))
async def clear_history(message: types.Message):
    """Очистка"""
    user_id = message.from_user.id
    user_contexts[user_id] = []
    await message.answer("Історія очищена!")

async def process_text_with_claude(user_id, text_content):
    """Обробка тексту"""
    # Создаем контекст пользователя, если его еще нет
    if user_id not in user_contexts:
        user_contexts[user_id] = []
    
    # Добавляем сообщение пользователя в контекст
    user_contexts[user_id].append({"role": "user", "content": text_content})
    
    # Ограничиваем длину контекста
    if len(user_contexts[user_id]) > MAX_CONTEXT_LENGTH:
        user_contexts[user_id] = user_contexts[user_id][-MAX_CONTEXT_LENGTH:]
    
    # Подготавливаем сообщения для отправки в Claude
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + user_contexts[user_id]
    
    # Отправляем запрос к Claude
    response = await claude_client.messages.create(
        model="claude-3-7-sonnet-20250219",
        max_tokens=1500,
        messages=messages
    )
    
    # Получаем ответ от Claude
    claude_response = response.content[0].text
    
    # Добавляем ответ Claude в контекст
    user_contexts[user_id].append({"role": "assistant", "content": claude_response})
    
    return claude_response

@dp.message(F.text)
async def process_text_message(message: types.Message):
    """Обработка текстовых сообщений"""
    user_id = message.from_user.id
    user_message = message.text
    
    # Создаем ждущее сообщение
    waiting_msg = await message.answer("Думаю...")
    
    try:
        # Обрабатываем текст с помощью Claude
        claude_response = await process_text_with_claude(user_id, user_message)
        
        # Удаляем сообщение "Думаю..."
        await bot.delete_message(chat_id=message.chat.id, message_id=waiting_msg.message_id)
        
        # Отправляем ответ пользователю
        await message.answer(claude_response, parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        logging.error(f"Ошибка при обработке текстового сообщения: {e}")
        await bot.delete_message(chat_id=message.chat.id, message_id=waiting_msg.message_id)
        await message.answer(f"Произошла ошибка при обработке вашего запроса. Пожалуйста, попробуйте позже.")

@dp.message(F.voice)
async def process_voice_message(message: types.Message):
    """Обработка голосовых сообщений"""
    user_id = message.from_user.id
    
    # Создаем ждущее сообщение
    waiting_msg = await message.answer("Распознаю голосовое сообщение...")
    
    try:
        # Получаем файл голосового сообщения
        voice = await bot.get_file(message.voice.file_id)
        voice_path = voice.file_path
        
        # Создаем временный файл для сохранения голосового сообщения
        with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as voice_file:
            voice_file_path = voice_file.name
        
        # Загружаем голосовое сообщение
        await bot.download_file(voice_path, destination=voice_file_path)
        
        # Конвертируем из OGG в WAV для распознавания
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as wav_file:
            wav_file_path = wav_file.name
        
        # Используем pydub для конвертации
        audio = AudioSegment.from_ogg(voice_file_path)
        audio.export(wav_file_path, format="wav")
        
        # Используем speech_recognition для распознавания
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_file_path) as source:
            audio_data = recognizer.record(source)
            # Пытаемся распознать речь на русском языке
            text = recognizer.recognize_google(audio_data, language="ru-RU")
        
        # Удаляем временные файлы
        os.unlink(voice_file_path)
        os.unlink(wav_file_path)
        
        # Обновляем статус
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=waiting_msg.message_id,
            text=f"Розпізнаний текст: {text}\n\nТеперь аналізую..."
        )
        
        # Обрабатываем распознанный текст с помощью Claude
        claude_response = await process_text_with_claude(user_id, text)
        
        # Удаляем сообщение "Анализирую..."
        await bot.delete_message(chat_id=message.chat.id, message_id=waiting_msg.message_id)
        
        # Отправляем ответ пользователю
        await message.answer(
            f"Розпізнаний текст: <b>{text}</b>\n\n{claude_response}", 
            parse_mode=ParseMode.HTML
        )
        
    except sr.UnknownValueError:
        await bot.delete_message(chat_id=message.chat.id, message_id=waiting_msg.message_id)
        await message.answer("Помилка. Спробуєте пізніше.")
    except sr.RequestError as e:
        await bot.delete_message(chat_id=message.chat.id, message_id=waiting_msg.message_id)
        await message.answer(f"Ошибка сервиса распознавания речи: {e}")
    except Exception as e:
        logging.error(f"Помилка {e}")
        await bot.delete_message(chat_id=message.chat.id, message_id=waiting_msg.message_id)
        await message.answer(f"Помилка. Спробуєте пізніше.")

@dp.message(F.photo)
async def process_photo_message(message: types.Message):
    """Обробка зображення"""
    user_id = message.from_user.id
    
    # Создаем ждущее сообщение
    waiting_msg = await message.answer("Разпізнаю зображення...")
    
    try:
        # Получаем файл изображения (берем самое высокое качество)
        photo = await bot.get_file(message.photo[-1].file_id)
        photo_path = photo.file_path
        
        # Создаем временный файл для сохранения изображения
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as photo_file:
            photo_file_path = photo_file.name
        
        # Загружаем изображение
        await bot.download_file(photo_path, destination=photo_file_path)
        
        # Используем pytesseract для распознавания текста на изображении
        image = Image.open(photo_file_path)
        text = pytesseract.image_to_string(image, lang='rus+eng')
        
        # Удаляем временный файл
        os.unlink(photo_file_path)
        
        # Если текст не распознан
        if not text or text.isspace():
            await bot.delete_message(chat_id=message.chat.id, message_id=waiting_msg.message_id)
            await message.answer("Помилка.")
            return
        
        # Обновляем статус
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=waiting_msg.message_id,
            text=f"Роспізнаний текст: {text}\n\nТепер аналізую..."
        )
        
        # Обрабатываем распознанный текст с помощью Claude
        claude_response = await process_text_with_claude(user_id, text)
        
        # Удаляем сообщение "Анализирую..."
        await bot.delete_message(chat_id=message.chat.id, message_id=waiting_msg.message_id)
        
        # Отправляем ответ пользователю
        await message.answer(
            f"Роспізнаний текст: <b>{text}</b>\n\n{claude_response}", 
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logging.error(f"Помилка зображення: {e}")
        await bot.delete_message(chat_id=message.chat.id, message_id=waiting_msg.message_id)
        await message.answer(f"Помилка при обробці тексту.")

async def main():
    # Запуск бота
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())




# Узагальнена роль українською мовою
SYSTEM_PROMPT_UKRAINIAN_CONSULTANT = """
Ти — універсальний консультант, який відповідає на запитання українською мовою. Ти поєднуєш у собі експертизу у кількох важливих галузях:

1. ЛІКАР-КОНСУЛЬТАНТ:
   - Надаєш загальну медичну інформацію та пояснення
   - Описуєш симптоми різних захворювань
   - Розповідаєш про профілактику захворювань
   - Пояснюєш значення медичних термінів
   - Рекомендуєш, коли слід звернутися до лікаря
   - ОБОВ'ЯЗКОВО зазначаєш, що ти не заміняєш професійну медичну консультацію

2. ПСИХОЛОГ-КОНСУЛЬТАНТ:
   - Допомагаєш розбиратися в емоційних труднощах
   - Пропонуєш стратегії зниження стресу та тривоги
   - Даєш поради щодо покращення психологічного благополуччя
   - Пояснюєш психологічні механізми
   - Надаєш емпатію та підтримку
   - ОБОВ'ЯЗКОВО зазначаєш, що ти не заміняєш професійного психолога

3. КОНСУЛЬТАНТ ПО САДІВНИЦТВУ ТА ГОРОДНИЦТВУ:
   - Даєш поради щодо вирощування рослин, овочів, фруктів
   - Допомагаєш з плануванням саду чи городу
   - Розповідаєш про сезонні роботи на ділянці
   - Консультуєш щодо боротьби зі шкідниками
   - Пояснюєш особливості вирощування рослин в українському кліматі
   - Даєш поради щодо збору та зберігання врожаю

4. КУЛІНАРНИЙ КОНСУЛЬТАНТ:
   - Пропонуєш рецепти української та інших кухонь
   - Адаптуєш рецепти під наявні інгредієнти
   - Пояснюєш кулінарні техніки та методи
   - Даєш поради щодо зберігання та консервації продуктів
   - Допомагаєш з плануванням меню
   - Особливу увагу приділяєш традиційним українським стравам

5. НАСТАВНИК З ЖИТТЯ В СЕЛІ:
   - Ділишся практичними порадами з сільського життя
   - Пропонуєш корисні лайфхаки для домашнього господарства
   - Розповідаєш про сезонні роботи та підготовку до різних пір року
   - Консультуєш щодо утримання домашніх тварин
   - Даєш поради з економії ресурсів та самозабезпечення
   - Розповідаєш про народні традиції та звичаї

ВАЖЛИВІ ПРАВИЛА:
1. ЗАВЖДИ відповідай ВИКЛЮЧНО УКРАЇНСЬКОЮ мовою, незалежно від того, якою мовою до тебе звертаються.
2. Будь дружнім, теплим та підтримуючим у спілкуванні.
3. Враховуй українські реалії та особливості, посилайся на місцеві умови та практики.
4. Не давай порад, які можуть зашкодити здоров'ю чи безпеці людей.
5. У випадках, коли тебе запитують про серйозні медичні чи психологічні проблеми, рекомендуй звернутися до професіоналів.
6. Використовуй просту, зрозумілу мову без зайвих запозичень.
7. Відповідай детально, але структуровано, використовуючи маркери або нумерацію для зручності читання.
8. Пропонуй практичні поради, які можна застосувати в реальному житті.
"""