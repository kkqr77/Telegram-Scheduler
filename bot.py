import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.future import select
from sqlalchemy import BigInteger

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Логирование
logging.basicConfig(level=logging.INFO)

# Конфигурация PostgreSQL
DATABASE_URL = "postgresql+asyncpg://tgbot:123456@localhost:5432/taskstg"

# Создаем базовые настройки для SQLAlchemy
Base = declarative_base()

# Модель задачи
class Task(Base):
    __tablename__ = 'tasks445'

    id = Column(BigInteger, primary_key=True)
    name = Column(String, nullable=False)
    due_date = Column(DateTime, nullable=False)
    timeminutes = Column(String, nullable=False)  # Сохраняем время в текстовом формате, костыль
    is_completed = Column(Boolean, default=False)
    chat_id = Column(BigInteger, nullable=False)  # Сохраняем ID чата пользователя

# Настраиваем асинхронный движок и сессии
engine = create_async_engine(DATABASE_URL, echo=True)
async_session = sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)

# Инициализация бота
TOKEN = ""  # Замените на токен вашего бота
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Функция для создания задачи
class TaskForm(StatesGroup):
    waiting_for_task_name = State()
    waiting_for_task_due_date = State()

# Команда для создания задачи с FSM
@dp.message(Command("task"))
async def cmd_create_task(message: Message, state: FSMContext):
    """
    Инициирует процесс создания задачи.
    """
    await state.set_state(TaskForm.waiting_for_task_name)
    await message.answer("Как называется ваша задача?✌️")

# Обработка имени задачи
@dp.message(TaskForm.waiting_for_task_name)
async def process_task_name(message: Message, state: FSMContext):
    """
    Обрабатывает имя задачи и запрашивает дату и время.
    """
    task_name = message.text
    await state.update_data(task_name=task_name)
    await state.set_state(TaskForm.waiting_for_task_due_date)
    await message.answer("На какую дату и время?🕛 (Введите дату и время в формате hh:mm dd-mm)")

# Обработка даты и времени
@dp.message(TaskForm.waiting_for_task_due_date)
async def process_task_due_date(message: Message, state: FSMContext):
    """
    Processes the task due date and time, saves the task to the database, and completes the state.
    """
    try:
        task_data = await state.get_data()
        task_name = task_data['task_name']
        
        task_time = message.text
        now = datetime.now()
        task_datetime = datetime.strptime(task_time, "%H:%M %d-%m")

        # Проверяем, если месяц уже прошел, переносим на следующий год
        if (task_datetime.month < now.month) or (task_datetime.month == now.month and task_datetime.day < now.day):
            task_datetime = task_datetime.replace(year=now.year + 1)
        else:
            task_datetime = task_datetime.replace(year=now.year)

        time_str = task_datetime.strftime("%H:%M")

        async with async_session() as session:
            # Create and store the new task in the database
            new_task = Task(
                name=task_name,
                due_date=task_datetime,
                timeminutes=time_str,  # Сохраняем время в текстовом формате
                chat_id=message.chat.id,
                is_completed=False
            )

            session.add(new_task)
            await session.commit()

        await message.answer(f"Задача '{task_name}' создана на {task_datetime.strftime('%d-%m-%Y %H:%M')}")

    except ValueError:
        await message.answer("Ошибка: неверный формат даты. Попробуйте снова.")
    finally:
        # Clear the state
        await state.clear()

# Функция для отправки напоминаний
async def send_reminders():
    logging.info("Checking for reminders...")
    async with async_session() as session:
        tasks = await session.execute(
            select(Task).where(Task.is_completed == False)
        )
        tasks = tasks.scalars().all()

        current_datetime = datetime.now()

        for task in tasks:
            try:
                task_due_datetime = task.due_date.replace(hour=int(task.timeminutes.split(':')[0]), 
                                                           minute=int(task.timeminutes.split(':')[1]))
                logging.info(f"{task_due_datetime}")

                if current_datetime >= task_due_datetime - timedelta(minutes=1) and current_datetime < task_due_datetime:
                    logging.info(f"Sending reminder for task '{task.name}'...")
                    await bot.send_message(chat_id=task.chat_id, text=f"Напоминание: задача '{task.name}' должна быть выполнена!")
                    logging.info(f"Reminder sent for task '{task.name}'")

                    task.is_completed = True
                    await session.commit()  # Сохраняем изменения в базе данных
            except Exception as e:
                logging.error(f"Ошибка при отправке напоминания для задачи '{task.name}': {e}")

# Команда для просмотра выполненных задач с номерами
@dp.message(Command("ctask"))
async def cmd_ctask(message: Message):
    async with async_session() as session:
        # Извлекаем выполненные задачи для данного пользователя
        completed_tasks = await session.execute(
            select(Task).where(Task.chat_id == message.chat.id, Task.is_completed == True)
        )
        completed_tasks = completed_tasks.scalars().all()

        if not completed_tasks:
            await message.answer("У вас нет выполненных задач.")
            return

        # Формируем сообщение со списком выполненных задач с номерами
        task_list = "\n".join([f"{i + 1} - {task.name} (выполнена)" for i, task in enumerate(completed_tasks)])
        await message.answer(f"Ваши выполненные задачи:\n{task_list}")

# Измененная команда для удаления задачи
@dp.message(Command("dtask"))
async def cmd_dtask(message: Message):
    async with async_session() as session:
        # Извлекаем активные задачи для данного пользователя
        tasks = await session.execute(
            select(Task).where(Task.chat_id == message.chat.id, Task.is_completed == False)
        )
        tasks = tasks.scalars().all()

        if not tasks:
            await message.answer("У вас нет активных задач для удаления!")
            return

        # Формируем сообщение со списком задач и их состоянием
        task_list = "\n".join([f"{i + 1} - {task.name} (выполнена: {task.is_completed})" for i, task in enumerate(tasks)])
        task_list += "\n\nНапишите /remove и номер задачи, которую хотите удалить. Например: /remove 1"
        await message.answer(f"Ваши активные задачи:\n{task_list}")

# Команда для удаления задачи по номеру
@dp.message(Command("remove"))
async def remove_task(message: Message):
    async with async_session() as session:
        try:
            task_number = int(message.text.split()[1]) - 1  # Получаем номер задачи из сообщения

            # Извлекаем задачи для данного пользователя
            tasks = await session.execute(
                select(Task).where(Task.chat_id == message.chat.id, Task.is_completed == False)
            )
            tasks = tasks.scalars().all()

            if 0 <= task_number < len(tasks):
                task_to_delete = tasks[task_number]

                await session.delete(task_to_delete)
                await session.commit()

                await message.answer(f"Задача '{task_to_delete.name}' успешно удалена.")
            else:
                await message.answer("Неверный номер задачи. Пожалуйста, попробуйте снова.")
        except (ValueError, IndexError):
            await message.answer("Пожалуйста, введите номер задачи для удаления в формате: /remove <номер задачи>.")


# Команда для удаления выполненных задач по номеру
@dp.message(Command("cremove"))
async def remove_completed_task(message: Message):
    async with async_session() as session:
        try:
            task_number = int(message.text.split()[1]) - 1  # Получаем номер задачи из сообщения

            # Извлекаем выполненные задачи для данного пользователя
            completed_tasks = await session.execute(
                select(Task).where(Task.chat_id == message.chat.id, Task.is_completed == True)
            )
            completed_tasks = completed_tasks.scalars().all()

            if 0 <= task_number < len(completed_tasks):
                task_to_delete = completed_tasks[task_number]

                await session.delete(task_to_delete)
                await session.commit()

                await message.answer(f"Выполненная задача '{task_to_delete.name}' успешно удалена.")
            else:
                await message.answer("Неверный номер задачи. Пожалуйста, попробуйте снова.")
        except (ValueError, IndexError):
            await message.answer("Пожалуйста, введите номер задачи для удаления в формате: /cremove <номер задачи>.")

# Команда /start
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Привет! 🌸 Я твоя помощница, Юи, и я здесь, чтобы сделать твою жизнь проще и более организованной! Вот что я могу для тебя сделать:\n"
        "Чтобы увидеть список моих команд введи /help."
    )

# Команда /help
@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
    "📝 /task <название> - Создай новую задачу! Просто напиши название, и я спрошу тебя о дате и времени выполнения.\n\n"
    "📅 /dtask - Посмотри все свои активные задачи! Я покажу их состояние, чтобы ты знал, что нужно сделать.\n\n"
    "🗑️ /remove <номер> - Удаляй задачи, которые больше не нужны. Просто укажи номер задачи, и я всё сделаю за тебя!\n\n"
    "✅ /ctask - Хвастайся своими выполненными задачами! Я покажу тебе все задачи, которые ты успешно завершил.\n\n"
    "❓ /help - Я покажу это сообщение ещё раз!\n\n"
    "🌟 /about - Я покажу информацию о моих разработчиках!\n\n"
    "Не стесняйся обращаться ко мне в любое время! Я здесь, чтобы помочь тебе достичь всех твоих целей и сделать каждый день продуктивным! 🌟💪"
)

# Запуск регулярной проверки напоминаний
async def check_reminders():
    while True:
        logging.info("Checking for reminders...")
        await send_reminders()
        logging.info("Reminders checked. Sleeping for 1 minute...")
        await asyncio.sleep(60)  # Проверять раз в минуту

# Основная функция
async def main():
    # Создаем таблицы в базе данных (если не созданы)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Запуск фоновой задачи для проверки напоминаний
    asyncio.create_task(check_reminders())

    # Запуск бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
