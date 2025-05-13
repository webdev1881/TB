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
Ты — помощник в изучении русского языка. Твоя задача — помогать пользователям 
улучшать их письменный и разговорный русский. Ты можешь:
1. Объяснять грамматические правила
2. Проверять и исправлять тексты
3. Предлагать синонимы и альтернативные выражения
4. Отвечать на вопросы о русской культуре и литературе
5. Помогать с переводами на русский язык

Всегда отвечай на русском языке, даже если пользователь пишет на другом языке.
Будь дружелюбным, терпеливым и подробным в своих объяснениях.
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
        "Привет! Я бот, который поможет вам улучшить ваш русский язык. "
        "Просто напишите мне сообщение, и я постараюсь помочь вам с грамматикой, "
        "переводом или любыми другими вопросами о русском языке.\n\n"
        "Я также могу анализировать голосовые сообщения и текст на изображениях!"
    )

@dp.message(Command("help"))
async def send_help(message: types.Message):
    """Обработчик команды /help"""
    help_text = """
Я могу помочь вам с русским языком! Вот что я умею:

/start - Начать разговор
/help - Показать это сообщение
/clear - Очистить историю нашего разговора

Просто напишите мне:
- Текст для проверки грамматики и пунктуации
- Вопрос о русской грамматике или лексике
- Предложение для перевода на русский
- Вопрос о русской культуре или литературе

Дополнительные возможности:
- Отправьте мне голосовое сообщение, и я его расшифрую
- Отправьте мне изображение с текстом, и я извлеку из него текст

Я всегда отвечаю на русском языке!
    """
    await message.answer(help_text)

@dp.message(Command("clear"))
async def clear_history(message: types.Message):
    """Очистка истории сообщений"""
    user_id = message.from_user.id
    user_contexts[user_id] = []
    await message.answer("История разговора очищена!")

async def process_text_with_claude(user_id, text_content):
    """Обработка текста с помощью Claude API"""
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
            text=f"Распознанный текст: {text}\n\nТеперь анализирую..."
        )
        
        # Обрабатываем распознанный текст с помощью Claude
        claude_response = await process_text_with_claude(user_id, text)
        
        # Удаляем сообщение "Анализирую..."
        await bot.delete_message(chat_id=message.chat.id, message_id=waiting_msg.message_id)
        
        # Отправляем ответ пользователю
        await message.answer(
            f"Распознанный текст: <b>{text}</b>\n\n{claude_response}", 
            parse_mode=ParseMode.HTML
        )
        
    except sr.UnknownValueError:
        await bot.delete_message(chat_id=message.chat.id, message_id=waiting_msg.message_id)
        await message.answer("Не удалось распознать речь. Пожалуйста, попробуйте еще раз.")
    except sr.RequestError as e:
        await bot.delete_message(chat_id=message.chat.id, message_id=waiting_msg.message_id)
        await message.answer(f"Ошибка сервиса распознавания речи: {e}")
    except Exception as e:
        logging.error(f"Ошибка при обработке голосового сообщения: {e}")
        await bot.delete_message(chat_id=message.chat.id, message_id=waiting_msg.message_id)
        await message.answer(f"Произошла ошибка при обработке голосового сообщения. Пожалуйста, попробуйте позже.")

@dp.message(F.photo)
async def process_photo_message(message: types.Message):
    """Обработка изображений"""
    user_id = message.from_user.id
    
    # Создаем ждущее сообщение
    waiting_msg = await message.answer("Распознаю текст на изображении...")
    
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
            await message.answer("На изображении не удалось распознать текст. Попробуйте другое изображение.")
            return
        
        # Обновляем статус
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=waiting_msg.message_id,
            text=f"Распознанный текст: {text}\n\nТеперь анализирую..."
        )
        
        # Обрабатываем распознанный текст с помощью Claude
        claude_response = await process_text_with_claude(user_id, text)
        
        # Удаляем сообщение "Анализирую..."
        await bot.delete_message(chat_id=message.chat.id, message_id=waiting_msg.message_id)
        
        # Отправляем ответ пользователю
        await message.answer(
            f"Распознанный текст: <b>{text}</b>\n\n{claude_response}", 
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logging.error(f"Ошибка при обработке изображения: {e}")
        await bot.delete_message(chat_id=message.chat.id, message_id=waiting_msg.message_id)
        await message.answer(f"Произошла ошибка при распознавании текста на изображении. Пожалуйста, попробуйте позже.")

async def main():
    # Запуск бота
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())