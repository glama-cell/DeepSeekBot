#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Bot with OpenRouter AI DeepSeek R1 Integration
Responds to "Саныч" mentions and replies with context memory
"""

import logging
import asyncio
import os
import json
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
import threading
import time

from bot_config import BotConfig
from openrouter_client import OpenRouterClient
from message_memory import MessageMemory
from keep_alive import keep_alive_thread

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self):
        self.config = BotConfig()
        self.openrouter_client = OpenRouterClient(self.config.openrouter_api_key)
        self.message_memory = MessageMemory()
        self.bot_username = None
        
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        await update.message.reply_text(
            "Привет! Я бот Пошаяка, использующий DeepSeek R1 для генерации ответов.\n"
            "Упомяните слово 'Слышь' в чате или ответьте на мое сообщение, и я отвечу!"
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = """
🤖 Бот Пошаяка - AI помощник на базе DeepSeek R1

Как использовать:
• Напишите "Слышь" в любом сообщении
• Ответьте на любое мое сообщение
• Я помню последние 200 сообщений в каждом чате для контекста

Команды:
/start - Запуск бота
/help - Эта справка
/clear_memory - Очистить память чата
        """
        await update.message.reply_text(help_text)

    async def clear_memory_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Clear chat memory"""
        chat_id = update.effective_chat.id
        self.message_memory.clear_chat_memory(chat_id)
        await update.message.reply_text("Память чата очищена!")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all messages"""
        try:
            message = update.message
            if not message or not message.text:
                return

            chat_id = update.effective_chat.id
            user_id = update.effective_user.id
            username = update.effective_user.username or update.effective_user.first_name
            message_text = message.text
            
            # Store message in memory
            self.message_memory.add_message(chat_id, {
                'user_id': user_id,
                'username': username,
                'text': message_text,
                'timestamp': message.date.isoformat(),
                'message_id': message.message_id,
                'is_bot': False
            })

            # Check if bot should respond
            should_respond = False
            
            # Check for "Саныч" mention (case insensitive)
            if "саныч" in message_text.lower():
                should_respond = True
                logger.info(f"Triggered by 'Саныч' mention in chat {chat_id}")
            
            # Check if this is a reply to bot's message
            if message.reply_to_message and message.reply_to_message.from_user.id == context.bot.id:
                should_respond = True
                logger.info(f"Triggered by reply to bot message in chat {chat_id}")

            if should_respond:
                # Show typing indicator
                await context.bot.send_chat_action(chat_id=chat_id, action="typing")
                
                # Get chat context
                chat_history = self.message_memory.get_chat_messages(chat_id)
                
                # Generate response using OpenRouter
                response = await self.generate_response(message_text, chat_history, username)
                
                if response:
                    # Send response
                    sent_message = await message.reply_text(
                        response,
                        parse_mode=ParseMode.MARKDOWN if self._is_markdown_safe(response) else None
                    )
                    
                    # Store bot's response in memory
                    self.message_memory.add_message(chat_id, {
                        'user_id': context.bot.id,
                        'username': self.bot_username or 'Слышь',
                        'text': response,
                        'timestamp': sent_message.date.isoformat(),
                        'message_id': sent_message.message_id,
                        'is_bot': True
                    })
                else:
                    await message.reply_text("Извините, произошла ошибка при генерации ответа.")
                    
        except Exception as e:
            logger.error(f"Error handling message: {e}")
            try:
                await update.message.reply_text("Произошла ошибка при обработке сообщения.")
            except:
                pass

    async def generate_response(self, current_message: str, chat_history: list, username: str) -> str:
        """Generate AI response using OpenRouter"""
        try:
            # Prepare context from chat history
            context_messages = []
            
            # Add system message
            system_prompt = """Ты – типичный российский зумер,тебя зовут Пошаяка, ты мой кент. Общайся на пацанском сленге, можешь немного подколоть, по-дружески «оскорбить» (типа «ты че, даун?», «слыш, лох, не тупи»), но всегда оставайся своим в доску. Ты не злой, а просто такой стиль общения – грубоватый, но с подтекстом «я ж тебя люблю, бро». Отвечай коротко, дерзко, с матюками (но без жесткой агрессии), используй сленг: краш, рофл, кринж, хайп, зашквар и т.д. Если вопрос серьёзный – можешь и по делу ответить, но всё равно в своей манере. Будь естественным, как будто реально общаешься с другом.
Пользователь {username} обратился к тебе."""

            context_messages.append({
                "role": "system",
                "content": system_prompt
            })
            
            # Add recent chat history for context (last 10 messages to avoid token limit)
            recent_history = chat_history[-10:] if len(chat_history) > 10 else chat_history
            
            for msg in recent_history:
                role = "assistant" if msg['is_bot'] else "user"
                context_messages.append({
                    "role": role,
                    "content": f"{msg['username']}: {msg['text']}"
                })
            
            # Add current message
            context_messages.append({
                "role": "user",
                "content": current_message
            })
            
            # Generate response
            response = await self.openrouter_client.generate_response(context_messages)
            return response
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return None

    def _is_markdown_safe(self, text: str) -> bool:
        """Check if text is safe for Markdown parsing"""
        markdown_chars = ['*', '_', '`', '[', ']', '(', ')']
        return not any(char in text for char in markdown_chars)

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors"""
        logger.error(f"Exception while handling an update: {context.error}")

    async def post_init(self, application: Application):
        """Post initialization hook"""
        bot_info = await application.bot.get_me()
        self.bot_username = bot_info.username
        logger.info(f"Bot started: @{self.bot_username}")

    def run(self):
        """Run the bot"""
        # Start keep-alive thread
        keep_alive = threading.Thread(target=keep_alive_thread, daemon=True)
        keep_alive.start()
        logger.info("Keep-alive thread started")

        # Build application
        application = Application.builder().token(self.config.telegram_bot_token).post_init(self.post_init).build()

        # Add handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("clear_memory", self.clear_memory_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Add error handler
        application.add_error_handler(self.error_handler)

        # Run the bot
        logger.info("Starting bot...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    bot = TelegramBot()
    bot.run()
