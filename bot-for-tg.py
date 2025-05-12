import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import boto3
from botocore.exceptions import BotoCoreError, ClientError

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загрузка конфигурации из переменных окружения
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')  # Токен вашего бота
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_S3_BUCKET = os.getenv('AWS_S3_BUCKET')

# Ограничение Telegram на размер файла для бота
MAX_TELEGRAM_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2 ГБ

# Инициализация бота и диспетчера
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(bot)

# Инициализация клиента S3
s3_client = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

@dp.message_handler(commands=['send'])
async def cmd_send(message: types.Message):
    """
    Команда /send <путь_к_файлу>
    Если файл <= 2ГБ, отправляется напрямую через Telegram.
    Если больше, загружает в S3 и присылает ссылку.
    """
    args = message.get_args()
    if not args:
        await message.reply("Использование: /send <путь_к_файлу>")
        return

    file_path = args.strip()
    if not os.path.isfile(file_path):
        await message.reply(f"Файл не найден: {file_path}")
        return

    file_size = os.path.getsize(file_path)
    logger.info(f"Отправка файла: {file_path}, размер: {file_size}")

    # Отправка через Telegram, если размер <= 2 ГБ
    if file_size <= MAX_TELEGRAM_FILE_SIZE:
        try:
            await message.answer_document(open(file_path, 'rb'))
            logger.info("Файл отправлен через Telegram")
        except Exception as e:
            logger.error(f"Ошибка при отправке файла через Telegram: {e}")
            await message.reply("Не удалось отправить файл через Telegram.")
    else:
        # Загрузка в S3
        try:
            file_name = os.path.basename(file_path)
            s3_key = f"uploads/{file_name}"
            s3_client.upload_file(file_path, AWS_S3_BUCKET, s3_key)
            # Генерация presigned URL (доступен 1 час)
            presigned_url = s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': AWS_S3_BUCKET, 'Key': s3_key},
                ExpiresIn=3600
            )
            logger.info(f"Файл загружен в S3: s3://{AWS_S3_BUCKET}/{s3_key}")

            # Отправка ссылки пользователю
            keyboard = InlineKeyboardMarkup().add(
                InlineKeyboardButton("Скачать файл", url=presigned_url)
            )
            await message.reply("Файл слишком большой для отправки через Telegram. Предлагаю скачать его по ссылке:", reply_markup=keyboard)
        except (BotoCoreError, ClientError) as e:
            logger.error(f"Ошибка при загрузке в S3: {e}")
            await message.reply("Не удалось загрузить файл во внешнее хранилище.")

if __name__ == '__main__':
    # Запуск бота
    executor.start_polling(dp, skip_updates=True)
