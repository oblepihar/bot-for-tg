import os
import logging
import time
import random
import string
import json
import sys
import shutil
import platform
import traceback

from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import InputFile
import aiohttp
import asyncio
from datetime import datetime
from typing import Optional, Union, Dict, Any, List

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
YANDEX_DISK_TOKEN = os.getenv('YANDEX_DISK_TOKEN')
YANDEX_DISK_PATH = 'telegram_uploads'
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("telegram_yadisk_bot")
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(bot)


def generate_random_filename(extension: str = "txt", length: int = 8) -> str:
    random_string = ''.join(random.choices(string.ascii_letters + string.digits, k=length))
    filename = f"{random_string}.{extension}"
    logger.debug(f"Сгенерировано имя файла: {filename}")
    return filename


def ensure_directory_exists(path: str):
    if not os.path.exists(path):
        logger.info(f"Создаю директорию: {path}")
        os.makedirs(path)


def get_current_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def log_exception(prefix: str, exc: Exception):
    logger.error(f"{prefix}: {str(exc)}")
    traceback.print_exc()


def safe_remove(path: str):
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.info(f"Удален временный файл: {path}")
    except Exception as e:
        log_exception("Ошибка удаления файла", e)


def is_supported_file(filename: str) -> bool:
    return any(filename.endswith(ext) for ext in [".txt", ".pdf", ".docx", ".jpg", ".png", ".zip"])


class YandexDiskClient:
    BASE_URL = 'https://cloud-api.yandex.net:443/v1/disk'

    def __init__(self, token: str):
        self.token = token
        self.headers = {'Authorization': f'OAuth {token}'}

    async def create_folder(self, path: str):
        url = f'{self.BASE_URL}/resources'
        params = {'path': path}
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.put(url, params=params) as resp:
                if resp.status == 201:
                    logger.info(f"Папка создана: {path}")
                elif resp.status == 409:
                    logger.info(f"Папка уже существует: {path}")
                else:
                    text = await resp.text()
                    log_exception("Ошибка создания папки", Exception(text))

    async def get_upload_url(self, path: str) -> Optional[str]:
        url = f'{self.BASE_URL}/resources/upload'
        params = {'path': path, 'overwrite': 'true'}
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('href')
                else:
                    logger.warning(f"Ошибка получения upload_url: {resp.status}")
                    return None

    async def upload_file(self, local_path: str, disk_path: str):
        upload_url = await self.get_upload_url(disk_path)
        if not upload_url:
            logger.error("URL для загрузки не получен.")
            return

        async with aiohttp.ClientSession() as session:
            with open(local_path, 'rb') as f:
                async with session.put(upload_url, data=f) as resp:
                    if resp.status != 201:
                        text = await resp.text()
                        log_exception("Ошибка загрузки файла", Exception(text))

    async def get_public_link(self, path: str) -> Optional[str]:
        url = f'{self.BASE_URL}/resources/publish'
        params = {'path': path}
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.put(url, params=params) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    return data.get('public_url')
                else:
                    text = await resp.text()
                    log_exception("Ошибка получения публичной ссылки", Exception(text))
                    return None


yadisk = YandexDiskClient(YANDEX_DISK_TOKEN)


async def initialize_yadisk():
    logger.info("Инициализация: создание корневой папки на Яндекс.Диске...")
    await yadisk.create_folder(YANDEX_DISK_PATH)


loop = asyncio.get_event_loop()
loop.run_until_complete(initialize_yadisk())


@dp.message_handler(commands=['start', 'help'])
async def send_welcome(message: types.Message):
    logger.info(f"Получена команда от пользователя {message.from_user.id}")
    await message.reply(
        "👋 Привет!\n"
        "Я — бот, который поможет тебе загрузить документы на Яндекс.Диск и получить ссылку для скачивания.\n"
        "📎 Отправь мне файл — я всё сделаю сам!\n"
        "🔗 Максимальный размер одного файла: 2 ГБ."
    )


@dp.message_handler(content_types=types.ContentType.DOCUMENT)
async def handle_document(message: types.Message):
    logger.info(f"Получен документ от пользователя {message.from_user.id}")

    file_id = message.document.file_id
    file_name = message.document.file_name or generate_random_filename()
    file_path_local = f"/tmp/{file_name}"
    file_path_disk = f"{YANDEX_DISK_PATH}/{file_name}"

    try:
        await download_file_locally(file_id, file_path_local)
        await yadisk.create_folder(YANDEX_DISK_PATH)
        await yadisk.upload_file(file_path_local, file_path_disk)
        public_url = await yadisk.get_public_link(file_path_disk)
        if public_url:
            await message.reply(f"✅ Файл загружен на Яндекс.Диск!\n🔗 Ссылка: {public_url}")
        else:
            await message.reply("⚠️ Не удалось получить ссылку на файл. Попробуйте позже.")
    except Exception as e:
        log_exception("Обработка документа", e)
        await message.reply("❌ Произошла ошибка во время обработки файла.")
    finally:
        safe_remove(file_path_local)


async def download_file_locally(file_id: str, destination: str):
    try:
        logger.info(f"Начинаю загрузку файла {file_id} в {destination}")
        await bot.download_file_by_id(file_id, destination=destination)
        logger.info(f"Файл успешно сохранён локально: {destination}")
    except Exception as e:
        log_exception("Ошибка локальной загрузки", e)
        raise


@dp.message_handler(content_types=types.ContentType.PHOTO)
async def handle_photo(message: types.Message):
    await message.reply("📸 Картинки пока не поддерживаются. Отправь файл в виде документа.")


@dp.message_handler(content_types=types.ContentType.AUDIO)
async def handle_audio(message: types.Message):
    await message.reply("🎵 Аудио пока не поддерживаются. Отправь файл в виде документа.")


@dp.message_handler(content_types=types.ContentType.VIDEO)
async def handle_video(message: types.Message):
    await message.reply("🎥 Видео пока не поддерживаются. Отправь файл в виде документа.")


@dp.message_handler()
async def fallback_message(message: types.Message):
    await message.reply("🤖 Отправь файл в виде документа, чтобы я загрузил его на Яндекс.Диск!")


def main():
    logger.info("🚀 Бот запущен! Ожидание сообщений...")
    executor.start_polling(dp, skip_updates=True)


if __name__ == '__main__':
    main()
