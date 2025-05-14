import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import InputFile
from aiogram.utils import executor
import aiohttp
import asyncio
# Настройки
TELEGRAM_TOKEN = os.getenv('7754226231:AAHd1xY6TfhEKdy-NSDGZR-yeZqENr1Xzr8')  # Токен бота Telegram
YANDEX_DISK_TOKEN = os.getenv('YANDEX_DISK_TOKEN')  # OAuth-токен для Яндекс.Диск
YANDEX_DISK_PATH = 'telegram_uploads'  # Папка на Яндекс.Диске для загрузки
# Инициализация
logging.basicConfig(level=logging.INFO)
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(bot)


# Хелпер для Яндекс.Диска
class YandexDiskClient:
    BASE_URL = 'https://cloud-api.yandex.net:443/v1/disk'

    def __init__(self, token: str):
        self.headers = {'Authorization': f'OAuth {token}'}

    async def create_folder(self, path: str):
        url = f'{self.BASE_URL}/resources'
        params = {'path': path}
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.put(url, params=params) as resp:
                if resp.status not in (201, 409):  # 201 - создано, 409 - уже существует
                    text = await resp.text()
                    logging.error(f'Ошибка создания папки: {text}')

    async def get_upload_url(self, path: str) -> str:
        url = f'{self.BASE_URL}/resources/upload'
        params = {'path': path, 'overwrite': 'true'}
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(url, params=params) as resp:
                data = await resp.json()
                return data.get('href')

    async def upload_file(self, local_path: str, disk_path: str):
        # Получаем URL для загрузки
        upload_url = await self.get_upload_url(disk_path)
        # Загружаем файл
        async with aiohttp.ClientSession() as session:
            with open(local_path, 'rb') as f:
                async with session.put(upload_url, data=f) as resp:
                    if resp.status != 201:
                        text = await resp.text()
                        logging.error(f'Ошибка загрузки файла: {text}')

    async def get_public_link(self, path: str) -> str:
        url = f'{self.BASE_URL}/resources/publish'
        params = {'path': path}
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.put(url, params=params) as resp:
                data = await resp.json()
        return data.get('public_url')


# Инициализация клиента Яндекс.Диск
yadisk = YandexDiskClient(YANDEX_DISK_TOKEN)
# Создаем корневую папку
asyncio.get_event_loop().run_until_complete(yadisk.create_folder(YANDEX_DISK_PATH))


@dp.message_handler(commands=['start', 'help'])
async def send_welcome(message: types.Message):
    await message.reply(
        "Привет! Отправь файл боту, и я загружу его на Яндекс.Диск и пришлю тебе ссылку для скачивания. \n"
        "Максимальный размер одного файла — 2 ГБ."
    )


@dp.message_handler(content_types=types.ContentType.DOCUMENT)
async def handle_document(message: types.Message):
    # Скачиваем файл локально
    file_id = message.document.file_id
    file_name = message.document.file_name
    file_path = f"/tmp/{file_name}"
    await bot.download_file_by_id(file_id, destination=file_path)
    # Загружаем на Яндекс.Диск
    disk_file_path = f"{YANDEX_DISK_PATH}/{file_name}"
    await yadisk.create_folder(YANDEX_DISK_PATH)
    await yadisk.upload_file(file_path, disk_file_path)
    # Получаем публичную ссылку
    public_url = await yadisk.get_public_link(disk_file_path)
    # Отправляем ссылку пользователю
    if public_url:
        await message.reply(f"Файл загружен: {public_url}")
    else:
        await message.reply("Не удалось получить ссылку. Попробуйте позже.")
    # Удаляем локальный файл
    os.remove(file_path)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)