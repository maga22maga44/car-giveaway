from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file
import os
import json
from datetime import datetime, timedelta
import requests
import io
import xlsxwriter
from werkzeug.middleware.proxy_fix import ProxyFix
from functools import lru_cache
import threading

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24))
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000  # 1 год для статических файлов

# Настройка для работы за прокси-сервером
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

# Путь к файлу данных
DATA_FILE = os.environ.get('DATA_FILE', os.path.join(os.path.dirname(__file__), 'participants.json'))

# Добавляем блокировку для безопасной работы с файлом данных при конкурентном доступе
data_lock = threading.Lock()

# Создаем файл, если он не существует
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump([], f)

# Список допустимых городов и районов
ALLOWED_CITIES = [
    # Основные города
    'махачкала', 'каспийск',
    
    # Районы Махачкалы
    'кировский район', 'ленинский район', 'советский район',
    
    # Посёлки городского типа Кировского района
    'ленинкент', 'семендер', 'сулак', 'шамхал',
    
    # Сёла Кировского района
    'богатырёвка', 'красноармейское', 'остров чечень', 'шамхал-термен',
    
    # Посёлки и сёла Ленинского района
    'новый кяхулай', 'новый хушет', 'талги',
    
    # Посёлки Советского района
    'альбурикент', 'кяхулай', 'тарки',
    
    # Микрорайоны и районы
    '5-й посёлок', '5 посёлок',
    
    # Дополнительные микрорайоны и кварталы
    'каменный карьер', 'афган-городок', 'кемпинг', 'кирпичный', 
    'ккоз', 'тау', 'центральный', 'южный', 'рекреационная зона', 'финский квартал',
    
    # Пригородные районы
    'турали'
]

# Для тестирования на хостинге - разрешаем все города, если установлена переменная окружения
if os.environ.get('ALLOW_ALL_LOCATIONS') == 'true':
    def check_location_allowed(city):
        return True
else:
    def check_location_allowed(city):
        return city in ALLOWED_CITIES

# Кэш для данных о местоположении по IP
ip_location_cache = {}

# Время жизни кэша местоположения (1 час)
IP_CACHE_TTL = 3600

@lru_cache(maxsize=128)
def get_location_from_ip(ip_address):
    """Получение информации о местоположении по IP-адресу"""
    # Проверяем кэш
    current_time = datetime.now().timestamp()
    if ip_address in ip_location_cache:
        cache_entry = ip_location_cache[ip_address]
        if current_time - cache_entry['timestamp'] < IP_CACHE_TTL:
            return cache_entry['data']
    
    try:
        response = requests.get(f"http://ip-api.com/json/{ip_address}", timeout=3)
        data = response.json()
        if data.get('status') == 'success':
            result = {
                'city': data.get('city', '').lower(),
                'region': data.get('regionName', ''),
                'country': data.get('country', '')
            }
            # Сохраняем в кэш
            ip_location_cache[ip_address] = {
                'data': result,
                'timestamp': current_time
            }
            return result
        return None
    except Exception as e:
        print(f"Ошибка при определении местоположения: {e}")
        return None

@lru_cache(maxsize=128)
def get_location_from_coordinates(lat, lng):
    """Получение информации о местоположении по координатам"""
    try:
        response = requests.get(
            f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lng}&zoom=18&addressdetails=1",
            headers={'User-Agent': 'CarRaffle/1.0'},
            timeout=3
        )
        data = response.json()
        if 'address' in data:
            city = data['address'].get('city', '').lower()
            if not city:
                city = data['address'].get('town', '').lower()
            if not city:
                city = data['address'].get('village', '').lower()
            
            return {
                'city': city,
                'region': data['address'].get('state', ''),
                'country': data['address'].get('country', '')
            }
        return None
    except Exception as e:
        print(f"Ошибка при определении местоположения по координатам: {e}")
        return None

# Кэш для участников с временем жизни
participants_cache = {
    'data': None,
    'timestamp': 0
}
PARTICIPANTS_CACHE_TTL = 60  # 60 секунд

def load_participants():
    """Загрузка данных участников из файла с кэшированием"""
    global participants_cache
    current_time = datetime.now().timestamp()
    
    # Если есть актуальные данные в кэше, возвращаем их
    if participants_cache['data'] is not None and current_time - participants_cache['timestamp'] < PARTICIPANTS_CACHE_TTL:
        return participants_cache['data']
    
    # Иначе загружаем из файла
    with data_lock:
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                participants = json.load(f)
                # Обновляем кэш
                participants_cache['data'] = participants
                participants_cache['timestamp'] = current_time
                return participants
        except:
            return []

def save_participant(participant_data):
    """Сохранение данных участника в файл"""
    with data_lock:
        participants = load_participants()
        participants.append(participant_data)
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(participants, f, ensure_ascii=False, indent=4)
        
        # Обновляем кэш
        participants_cache['data'] = participants
        participants_cache['timestamp'] = datetime.now().timestamp()

def is_phone_registered(phone):
    """Проверка, зарегистрирован ли уже данный номер телефона"""
    participants = load_participants()
    # Нормализуем телефон для сравнения (удаляем все, кроме цифр)
    normalized_phone = ''.join(filter(str.isdigit, phone))
    
    for participant in participants:
        normalized_participant_phone = ''.join(filter(str.isdigit, participant['phone']))
        if normalized_participant_phone == normalized_phone:
            return True
    return False

@app.route('/')
def index():
    """Главная страница с формой регистрации"""
    return render_template('index.html')

@app.route('/check-coordinates')
def check_coordinates():
    """Проверка местоположения пользователя по координатам"""
    lat = request.args.get('lat')
    lng = request.args.get('lng')
    
    if not lat or not lng:
        return jsonify({"status": "error", "message": "Не указаны координаты"})
    
    location = get_location_from_coordinates(lat, lng)
    if not location:
        return jsonify({"status": "error", "message": "Не удалось определить местоположение по координатам"})
    
    city = location.get('city', '').lower()
    allowed = check_location_allowed(city)
    
    return jsonify({
        "status": "success", 
        "allowed": allowed,
        "city": city
    })

@app.route('/check-location')
def check_location():
    """Проверка местоположения пользователя по IP"""
    ip_address = request.remote_addr
    
    # Для локальной разработки используем внешний IP
    if ip_address == '127.0.0.1':
        # Для тестирования можно использовать любой публичный IP из Махачкалы
        # Это только для разработки
        return jsonify({"status": "success", "allowed": True, "city": "махачкала (тестовый режим)"})
    
    location = get_location_from_ip(ip_address)
    if not location:
        return jsonify({"status": "error", "message": "Не удалось определить местоположение"})
    
    city = location.get('city', '').lower()
    allowed = check_location_allowed(city)
    
    return jsonify({
        "status": "success", 
        "allowed": allowed,
        "city": city
    })

@app.route('/check-phone')
def check_phone():
    """Проверка существования номера телефона в базе данных"""
    phone = request.args.get('phone')
    
    if not phone:
        return jsonify({"exists": False})
    
    # Проверяем, зарегистрирован ли уже данный номер телефона
    if is_phone_registered(phone):
        return jsonify({
            "exists": True, 
            "message": "Этот номер телефона уже зарегистрирован в розыгрыше. Регистрация возможна только один раз."
        })
    
    return jsonify({"exists": False})

@app.route('/register', methods=['POST'])
def register():
    """Регистрация участника"""
    # Проверка на AJAX-запрос
    is_ajax_request = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    
    # Получение данных из формы
    full_name = request.form.get('full_name')
    phone = request.form.get('phone')
    age = request.form.get('age')
    gender = request.form.get('gender')
    
    # Валидация данных
    if not full_name or not phone or not age or not gender:
        if is_ajax_request:
            return jsonify({'success': False, 'message': 'Пожалуйста, заполните все поля формы!'}), 400
        flash('Пожалуйста, заполните все поля формы!', 'danger')
        return redirect(url_for('index'))
    
    # Проверка, зарегистрирован ли уже данный номер телефона
    if is_phone_registered(phone):
        if is_ajax_request:
            return jsonify({'success': False, 'message': 'Этот номер телефона уже зарегистрирован в розыгрыше. Регистрация возможна только один раз.'}), 400
        flash('Этот номер телефона уже зарегистрирован в розыгрыше. Регистрация возможна только один раз.', 'danger')
        return redirect(url_for('index'))
    
    # Получение координат
    latitude = request.form.get('latitude')
    longitude = request.form.get('longitude')
    
    # Проверка местоположения по координатам, если они предоставлены
    location = None
    is_allowed = False
    
    # Если установлена переменная окружения, то разрешаем всем
    if os.environ.get('ALLOW_ALL_LOCATIONS') == 'true':
        is_allowed = True
    else:
        if latitude and longitude:
            location = get_location_from_coordinates(latitude, longitude)
            if location and check_location_allowed(location.get('city', '').lower()):
                is_allowed = True
        
        # Если координаты не предоставлены или не удалось определить местоположение,
        # пробуем определить по IP
        if not is_allowed:
            ip_address = request.remote_addr
            if ip_address == '127.0.0.1':  # Для локальной разработки
                is_allowed = True
            else:
                ip_location = get_location_from_ip(ip_address)
                if ip_location and check_location_allowed(ip_location.get('city', '').lower()):
                    is_allowed = True
                    location = ip_location
    
    # Если пользователь не из разрешенного города
    if not is_allowed:
        if is_ajax_request:
            return jsonify({'success': False, 'message': 'К сожалению, вы не можете участвовать в розыгрыше. Розыгрыш доступен только для жителей Махачкалы и Каспийска.'}), 400
        return redirect(url_for('index'))
    
    # Создание записи об участнике
    participant = {
        'full_name': full_name,
        'phone': phone,
        'age': age,
        'gender': gender,
        'ip_address': request.remote_addr,
        'location': location,
        'coordinates': {
            'latitude': latitude,
            'longitude': longitude,
            'city': location.get('city', '') if location else None
        } if latitude and longitude else None,
        'registration_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    # Сохранение данных участника
    save_participant(participant)
    
    # Получаем общее количество участников для определения номера
    participants = load_participants()
    participant_number = len(participants)
    
    # Возвращаем разные ответы в зависимости от типа запроса
    if is_ajax_request:
        return jsonify({
            'success': True, 
            'message': 'Вы успешно зарегистрированы для участия в розыгрыше!',
            'participant_number': participant_number
        })
    
    # Перенаправление на страницу успеха
    flash('Вы успешно зарегистрированы для участия в розыгрыше!', 'success')
    return redirect(url_for('success'))

@app.route('/success')
def success():
    """Страница успешной регистрации"""
    return render_template('success.html')

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    """Административная панель"""
    # В реальном проекте здесь должна быть надежная авторизация
    if request.method == 'POST':
        password = request.form.get('password')
        secure_password = "kvdarit_avto35"  # Новый пароль администратора
        if password == secure_password:  # Безопасный пароль с комбинацией букв, цифр и специальных символов
            session['admin'] = True
        else:
            flash('Неверный пароль!', 'danger')
    
    if session.get('admin'):
        participants = load_participants()
        return render_template('admin.html', participants=participants)
    else:
        return render_template('admin_login.html')

@app.route('/delete-participants', methods=['POST'])
def delete_participants():
    # Проверка, что пользователь является администратором
    if not session.get('admin'):
        return jsonify({'success': False, 'message': 'Доступ запрещен'}), 403
    
    try:
        # Очистка файла participants.json
        with data_lock:
            with open(DATA_FILE, 'w') as f:
                json.dump([], f)
            
            # Обновляем кэш
            participants_cache['data'] = []
            participants_cache['timestamp'] = datetime.now().timestamp()
            
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/delete-participant/<int:index>', methods=['POST'])
def delete_participant(index):
    # Проверка, что пользователь является администратором
    if not session.get('admin'):
        return jsonify({'success': False, 'message': 'Доступ запрещен'}), 403
    
    try:
        # Загрузка списка участников
        with data_lock:
            participants = load_participants()
            
            # Проверка валидности индекса
            if index < 0 or index >= len(participants):
                return jsonify({'success': False, 'message': 'Участник не найден'}), 404
            
            # Удаление участника
            del participants[index]
            
            # Сохранение обновленного списка
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(participants, f, ensure_ascii=False, indent=4)
            
            # Обновляем кэш
            participants_cache['data'] = participants
            participants_cache['timestamp'] = datetime.now().timestamp()
                
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/export-to-excel', methods=['GET'])
def export_to_excel():
    """Генерация Excel-файла с данными участников"""
    # Проверка, что пользователь является администратором
    if not session.get('admin'):
        flash('Доступ запрещен. Пожалуйста, войдите как администратор.', 'danger')
        return redirect(url_for('admin'))
    
    try:
        # Загрузка данных участников
        participants = load_participants()
        
        # Создание объекта для записи Excel-файла
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet('Участники')
        
        # Форматирование
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#007bff',
            'font_color': 'white',
            'border': 1
        })
        
        cell_format = workbook.add_format({
            'border': 1
        })
        
        # Установка ширины столбцов
        worksheet.set_column('A:A', 25)  # Имя
        worksheet.set_column('B:B', 20)  # Телефон
        worksheet.set_column('C:C', 10)  # Возраст
        worksheet.set_column('D:D', 15)  # Пол
        worksheet.set_column('E:E', 20)  # Город
        worksheet.set_column('F:F', 20)  # Регион
        worksheet.set_column('G:G', 20)  # Страна
        worksheet.set_column('H:H', 25)  # Время регистрации
        worksheet.set_column('I:I', 30)  # Координаты
        worksheet.set_column('J:J', 20)  # IP-адрес
        
        # Заголовки столбцов
        headers = [
            'Имя', 'Телефон', 'Возраст', 'Пол', 'Город', 'Регион', 'Страна', 
            'Время регистрации', 'Координаты', 'IP-адрес'
        ]
        
        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_format)
        
        # Заполнение данными
        for i, participant in enumerate(participants):
            row = i + 1
            
            # Безопасное извлечение данных
            full_name = str(participant.get('full_name', ''))
            phone = str(participant.get('phone', ''))
            age = str(participant.get('age', ''))
            gender = 'Мужской' if str(participant.get('gender', '')) == 'male' else 'Женский'
            
            # Безопасное извлечение данных о местоположении
            city = ''
            region = ''
            country = ''
            
            # Получение города из координат (если они есть)
            coordinates = participant.get('coordinates', {})
            if coordinates and isinstance(coordinates, dict):
                city_from_coords = coordinates.get('city', '')
                if city_from_coords:
                    city = city_from_coords
            
            # Если город не определен из координат, пробуем получить его из location
            if not city:
                location = participant.get('location', {})
                if location and isinstance(location, dict):
                    city = location.get('city', '')
                    region = location.get('region', '')
                    country = location.get('country', '')
            
            # Форматирование координат
            coords = ''
            if coordinates and isinstance(coordinates, dict):
                lat = coordinates.get('latitude', '')
                lng = coordinates.get('longitude', '')
                if lat and lng:
                    coords = f"{lat}, {lng}"
            
            # IP-адрес
            ip_address = str(participant.get('ip_address', ''))
            
            # Время регистрации
            reg_time = str(participant.get('registration_time', ''))
            
            # Капитализация строк
            if city:
                city = city.capitalize()
            if region:
                region = region.capitalize()
            if country:
                country = country.capitalize()
            
            # Данные для записи
            data = [
                full_name,
                phone,
                age,
                gender,
                city,
                region,
                country,
                reg_time,
                coords,
                ip_address
            ]
            
            # Запись данных в Excel
            for col, value in enumerate(data):
                worksheet.write(row, col, value, cell_format)
        
        # Закрытие и возврат Excel-файла
        workbook.close()
        output.seek(0)
        
        # Формирование имени файла с текущей датой
        current_date = datetime.now().strftime('%Y-%m-%d')
        filename = f'participants_{current_date}.xlsx'
        
        return send_file(
            output, 
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 
            as_attachment=True, 
            download_name=filename
        )
    except Exception as e:
        import traceback
        print(traceback.format_exc())  # Печать полного трейсбека ошибки в консоль
        flash(f'Ошибка при создании Excel-файла: {str(e)}', 'danger')
        return redirect(url_for('admin'))

# Добавляем настройку для сжатия ответов
@app.after_request
def add_header(response):
    # Кэширование статических файлов
    if 'Cache-Control' not in response.headers:
        if request.path.startswith('/static/'):
            # Кэшировать статические файлы на 1 год
            response.headers['Cache-Control'] = 'public, max-age=31536000'
        else:
            # Не кэшировать HTML-страницы
            response.headers['Cache-Control'] = 'no-store'
    return response

if __name__ == '__main__':
    # Для продакшена используйте WSGI-сервер (gunicorn или uwsgi)
    # gunicorn -w 4 -b 0.0.0.0:5000 app:app
    app.run(debug=False, host='0.0.0.0') 