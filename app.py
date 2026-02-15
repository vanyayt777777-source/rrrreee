from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid, PhoneNumberInvalid
import asyncio
import os
import uuid
from functools import wraps

app = Flask(__name__)
app.secret_key = 'dev-monkey-secret-key-2025'
CORS(app)

# Создаем папку для сессий
os.makedirs('sessions', exist_ok=True)

# Хранилище активных клиентов (в реальном проекте используйте БД)
active_clients = {}

# API данные
API_ID = 32480523
API_HASH = '147839735c9fa4e83451209e9b55cfc5'

def async_route(f):
    """Декоратор для асинхронных маршрутов"""
    @wraps(f)
    def wrapped(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapped

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/send-code', methods=['POST'])
@async_route
async def send_code():
    """Отправка кода подтверждения"""
    data = request.json
    phone = data.get('phone')
    
    if not phone:
        return jsonify({'error': 'Телефон обязателен'}), 400
    
    try:
        # Создаем уникальное имя сессии
        session_name = f"sessions/{phone.replace('+', '')}_{uuid.uuid4().hex[:8]}"
        
        # Создаем клиента
        client = Client(
            session_name,
            api_id=API_ID,
            api_hash=API_HASH,
            phone_number=phone,
            workdir='.'
        )
        
        # Подключаемся и запрашиваем код
        await client.connect()
        sent_code = await client.send_code(phone)
        
        # Сохраняем клиента и данные для подтверждения
        active_clients[phone] = {
            'client': client,
            'phone_code_hash': sent_code.phone_code_hash,
            'session_name': session_name
        }
        
        return jsonify({
            'success': True,
            'message': 'Код отправлен',
            'phone_code_hash': sent_code.phone_code_hash
        })
        
    except PhoneNumberInvalid:
        return jsonify({'error': 'Неверный номер телефона'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/verify-code', methods=['POST'])
@async_route
async def verify_code():
    """Подтверждение кода и вход"""
    data = request.json
    phone = data.get('phone')
    code = data.get('code')
    password = data.get('password', '')  # 2FA пароль если есть
    
    if not phone or not code:
        return jsonify({'error': 'Телефон и код обязательны'}), 400
    
    client_data = active_clients.get(phone)
    if not client_data:
        return jsonify({'error': 'Сначала отправьте код'}), 400
    
    client = client_data['client']
    
    try:
        # Пытаемся войти с кодом
        await client.sign_in(
            phone_number=phone,
            phone_code_hash=client_data['phone_code_hash'],
            phone_code=code
        )
        
        # Получаем информацию о пользователе
        me = await client.get_me()
        
        return jsonify({
            'success': True,
            'message': 'Вход выполнен успешно',
            'user': {
                'id': me.id,
                'first_name': me.first_name,
                'last_name': me.last_name,
                'username': me.username,
                'phone': me.phone_number
            }
        })
        
    except SessionPasswordNeeded:
        # Требуется 2FA пароль
        if password:
            await client.check_password(password)
            me = await client.get_me()
            return jsonify({
                'success': True,
                'message': 'Вход выполнен с 2FA',
                'user': {
                    'id': me.id,
                    'first_name': me.first_name,
                    'last_name': me.last_name,
                    'username': me.username,
                    'phone': me.phone_number
                }
            })
        else:
            return jsonify({
                'need_password': True,
                'message': 'Требуется пароль двухфакторной аутентификации'
            }), 401
            
    except PhoneCodeInvalid:
        return jsonify({'error': 'Неверный код подтверждения'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/chats', methods=['GET'])
@async_route
async def get_chats():
    """Получение списка чатов"""
    phone = request.args.get('phone')
    
    if not phone:
        return jsonify({'error': 'Телефон обязателен'}), 400
    
    client_data = active_clients.get(phone)
    if not client_data:
        return jsonify({'error': 'Аккаунт не авторизован'}), 401
    
    client = client_data['client']
    
    try:
        chats = []
        # Получаем диалоги (чаты)
        async for dialog in client.get_dialogs():
            chat = dialog.chat
            
            # Определяем тип чата и имя
            if chat.type == "private":
                name = f"{chat.first_name or ''} {chat.last_name or ''}".strip()
                if not name:
                    name = "Пользователь"
                chat_type = "👤 Личный"
            elif chat.type == "group":
                name = chat.title or "Группа"
                chat_type = "👥 Группа"
            elif chat.type == "supergroup":
                name = chat.title or "Супергруппа"
                chat_type = "📢 Супергруппа"
            elif chat.type == "channel":
                name = chat.title or "Канал"
                chat_type = "📺 Канал"
            else:
                name = "Чат"
                chat_type = "💬 Другое"
            
            # Получаем последнее сообщение для превью
            last_message = ""
            if dialog.top_message:
                last_message = dialog.top_message.text or "[Медиа]"
                if len(last_message) > 50:
                    last_message = last_message[:50] + "..."
            
            chats.append({
                'id': str(chat.id),
                'name': name,
                'type': chat_type,
                'unread_count': dialog.unread_messages_count,
                'last_message': last_message,
                'photo': None  # В реальном проекте можно добавить фото
            })
        
        # Сортируем по активности (сначала с непрочитанными)
        chats.sort(key=lambda x: x['unread_count'], reverse=True)
        
        return jsonify({
            'success': True,
            'chats': chats[:50]  # Ограничиваем 50 чатами
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/send-message', methods=['POST'])
@async_route
async def send_message():
    """Отправка сообщения в чат"""
    data = request.json
    phone = data.get('phone')
    chat_id = data.get('chat_id')
    message = data.get('message')
    
    if not all([phone, chat_id, message]):
        return jsonify({'error': 'Все поля обязательны'}), 400
    
    client_data = active_clients.get(phone)
    if not client_data:
        return jsonify({'error': 'Аккаунт не авторизован'}), 401
    
    client = client_data['client']
    
    try:
        # Отправляем сообщение
        sent_message = await client.send_message(
            chat_id=int(chat_id),
            text=message
        )
        
        return jsonify({
            'success': True,
            'message': 'Сообщение отправлено',
            'message_id': sent_message.id
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/broadcast', methods=['POST'])
@async_route
async def broadcast():
    """Массовая рассылка по выбранным чатам"""
    data = request.json
    phone = data.get('phone')
    chat_ids = data.get('chat_ids', [])
    message = data.get('message')
    delay = float(data.get('delay', 3))
    
    if not phone or not chat_ids or not message:
        return jsonify({'error': 'Все поля обязательны'}), 400
    
    if len(chat_ids) > 20:
        return jsonify({'error': 'Максимум 20 чатов'}), 400
    
    client_data = active_clients.get(phone)
    if not client_data:
        return jsonify({'error': 'Аккаунт не авторизован'}), 401
    
    client = client_data['client']
    
    try:
        results = []
        for i, chat_id in enumerate(chat_ids):
            try:
                # Отправляем сообщение
                sent = await client.send_message(
                    chat_id=int(chat_id),
                    text=message
                )
                results.append({
                    'chat_id': chat_id,
                    'success': True,
                    'message_id': sent.id
                })
                
                # Задержка между сообщениями
                if i < len(chat_ids) - 1:
                    await asyncio.sleep(delay)
                    
            except Exception as e:
                results.append({
                    'chat_id': chat_id,
                    'success': False,
                    'error': str(e)
                })
        
        return jsonify({
            'success': True,
            'results': results,
            'total': len(results),
            'successful': sum(1 for r in results if r['success'])
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/logout', methods=['POST'])
@async_route
async def logout():
    """Выход из аккаунта"""
    data = request.json
    phone = data.get('phone')
    
    if not phone:
        return jsonify({'error': 'Телефон обязателен'}), 400
    
    client_data = active_clients.pop(phone, None)
    if client_data:
        client = client_data['client']
        try:
            await client.stop()
            # Удаляем файл сессии
            session_file = f"{client_data['session_name']}.session"
            if os.path.exists(session_file):
                os.remove(session_file)
        except:
            pass
    
    return jsonify({'success': True, 'message': 'Выход выполнен'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
