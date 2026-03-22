from flask import Flask, render_template, request, jsonify, send_file
import os
import psutil
import shutil
from datetime import datetime, timedelta
import platform
import string
import subprocess
import winreg
import json
import threading
import time
from collections import deque
import logging
from logging.handlers import RotatingFileHandler
import zipfile
import tempfile

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024  # 1GB

LOG_FOLDER = os.path.join(os.path.dirname(__file__), 'logs')
if not os.path.exists(LOG_FOLDER):
    os.makedirs(LOG_FOLDER)

log_file = os.path.join(LOG_FOLDER, 'server.log')
file_handler = RotatingFileHandler(log_file, maxBytes=10485760, backupCount=10, encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)

history_data = {
    'cpu': deque(maxlen=52560),
    'ram': deque(maxlen=52560),
    'timestamps': deque(maxlen=52560)
}

HISTORY_FILE = os.path.join(os.path.dirname(__file__), 'history.json')

def load_history():
    global history_data
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                history_data['cpu'] = deque(data.get('cpu', []), maxlen=52560)
                history_data['ram'] = deque(data.get('ram', []), maxlen=52560)
                history_data['timestamps'] = deque(data.get('timestamps', []), maxlen=52560)
    except Exception as e:
        app.logger.error(f"Ошибка загрузки истории: {e}")

def save_history():
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                'cpu': list(history_data['cpu']),
                'ram': list(history_data['ram']),
                'timestamps': list(history_data['timestamps'])
            }, f)
    except Exception as e:
        app.logger.error(f"Ошибка сохранения истории: {e}")

def record_history():
    while True:
        try:
            timestamp = datetime.now().isoformat()
            history_data['timestamps'].append(timestamp)
            history_data['cpu'].append(psutil.cpu_percent(interval=1))
            history_data['ram'].append(psutil.virtual_memory().percent)
            
            if len(history_data['timestamps']) % 10 == 0:
                save_history()
            
            time.sleep(600)
        except Exception as e:
            app.logger.error(f"Ошибка записи истории: {e}")
            time.sleep(600)

history_thread = threading.Thread(target=record_history, daemon=True)
history_thread.start()

def get_cpu_name():
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, 
                            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        cpu_name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
        winreg.CloseKey(key)
        if cpu_name:
            return cpu_name.strip()
    except:
        pass
    
    try:
        result = subprocess.run(['wmic', 'cpu', 'get', 'name'], 
                               capture_output=True, text=True, encoding='utf-8')
        lines = result.stdout.strip().split('\n')
        if len(lines) >= 2:
            name = lines[1].strip()
            if name and "Family" not in name:
                return name
    except:
        pass
    
    return platform.processor() or "Intel/AMD Processor"

def get_drives():
    drives = []
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if os.path.exists(drive):
            try:
                usage = psutil.disk_usage(drive)
                drives.append({
                    'name': drive,
                    'type': 'drive',
                    'size_formatted': format_bytes(usage.total),
                    'free_formatted': format_bytes(usage.free),
                    'percent': usage.percent
                })
            except:
                pass
    return drives

def format_bytes(bytes):
    if bytes == 0:
        return '0 B'
    sizes = ['B', 'KB', 'MB', 'GB', 'TB']
    i = 0
    while bytes >= 1024 and i < len(sizes) - 1:
        bytes /= 1024.0
        i += 1
    return f"{bytes:.1f} {sizes[i]}"

USERS = {
    'admin': 'admin123'
}

def check_auth(username, password):
    return USERS.get(username) == password

@app.before_request
def log_request():
    if request.path not in ['/api/history', '/api/system', '/api/current']:
        app.logger.info(f"Запрос: {request.method} {request.path}")

@app.route('/')
def index():
    auth = request.cookies.get('auth')
    if auth != 'true':
        return render_template('login.html')
    return render_template('dashboard.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if check_auth(username, password):
            app.logger.info(f"Успешный вход: {username}")
            resp = jsonify({'success': True})
            resp.set_cookie('auth', 'true')
            return resp
        app.logger.warning(f"Неудачная попытка входа: {username}")
        return jsonify({'success': False, 'error': 'Неверный логин или пароль'}), 401
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    resp = jsonify({'success': True})
    resp.set_cookie('auth', '', expires=0)
    return resp

@app.route('/api/history', methods=['GET'])
def get_history():
    period = request.args.get('period', '1h')
    
    period_config = {
        '1h': {'hours': 1, 'interval': 1},
        '24h': {'hours': 24, 'interval': 1},
        '1w': {'hours': 168, 'interval': 6},
        '1m': {'hours': 720, 'interval': 30},
        '1y': {'hours': 8760, 'interval': 360}
    }
    
    config = period_config.get(period, period_config['1h'])
    hours = config['hours']
    interval = config['interval']
    
    points_needed = hours * 6
    total_points = len(history_data['timestamps'])
    start_idx = max(0, total_points - points_needed)
    
    timestamps = list(history_data['timestamps'])[start_idx:]
    cpu_data = list(history_data['cpu'])[start_idx:]
    ram_data = list(history_data['ram'])[start_idx:]
    
    if interval > 1:
        timestamps = timestamps[::interval]
        cpu_data = cpu_data[::interval]
        ram_data = ram_data[::interval]
    
    return jsonify({
        'cpu': cpu_data,
        'ram': ram_data,
        'timestamps': timestamps
    })

@app.route('/api/drives', methods=['GET'])
def get_drives_list():
    return jsonify(get_drives())

@app.route('/api/files', methods=['GET'])
def list_files():
    path = request.args.get('path', '')
    
    if not path:
        return jsonify({
            'current_path': '',
            'is_root': True,
            'items': get_drives(),
            'parent_path': None
        })
    
    try:
        if not os.path.exists(path):
            return jsonify({'error': 'Путь не существует'}), 404
        
        if not os.path.isdir(path):
            return jsonify({'error': 'Это не директория'}), 400
        
        items = []
        for item in os.listdir(path):
            full_path = os.path.join(path, item)
            try:
                stat = os.stat(full_path)
                is_dir = os.path.isdir(full_path)
                
                items.append({
                    'name': item,
                    'path': full_path,
                    'type': 'directory' if is_dir else 'file',
                    'size': stat.st_size if not is_dir else 0,
                    'size_formatted': format_bytes(stat.st_size) if not is_dir else '',
                    'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                })
            except Exception as e:
                continue
        
        items.sort(key=lambda x: (x['type'] != 'directory', x['name'].lower()))
        
        parent_path = os.path.dirname(path)
        if parent_path == path or parent_path == '':
            parent_path = None
        
        return jsonify({
            'current_path': path,
            'is_root': False,
            'parent_path': parent_path,
            'items': items
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/upload', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'Файл не выбран'}), 400
        
        file = request.files['file']
        path = request.form.get('path', '')
        
        if file.filename == '':
            return jsonify({'error': 'Имя файла пусто'}), 400
        
        if not path:
            return jsonify({'error': 'Путь не указан'}), 400
        
        if not os.path.exists(path):
            return jsonify({'error': 'Директория не существует'}), 404
        
        if not os.path.isdir(path):
            return jsonify({'error': 'Указанный путь не является директорией'}), 400
        
        filename = file.filename
        full_path = os.path.join(path, filename)
        
        counter = 1
        name, ext = os.path.splitext(filename)
        while os.path.exists(full_path):
            full_path = os.path.join(path, f"{name}_{counter}{ext}")
            counter += 1
        
        file.save(full_path)
        app.logger.info(f"Загружен файл: {filename} -> {path}")
        
        return jsonify({'success': True, 'message': 'Файл загружен'})
            
    except Exception as e:
        app.logger.error(f"Ошибка загрузки: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/upload-folder', methods=['POST'])
def upload_folder():
    try:
        path = request.form.get('path', '')
        
        if not path:
            return jsonify({'error': 'Путь не указан'}), 400
        
        if not os.path.exists(path):
            return jsonify({'error': 'Директория не существует'}), 404
        
        if not os.path.isdir(path):
            return jsonify({'error': 'Указанный путь не является директорией'}), 400
        
        files = request.files.getlist('files[]')
        
        if not files or len(files) == 0:
            return jsonify({'error': 'Файлы не выбраны'}), 400
        
        success_count = 0
        error_count = 0
        
        for file in files:
            if file and file.filename:
                try:
                    relative_path = file.filename
                    full_path = os.path.join(path, relative_path)
                    
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    
                    counter = 1
                    name, ext = os.path.splitext(full_path)
                    while os.path.exists(full_path):
                        full_path = f"{name}_{counter}{ext}"
                        counter += 1
                    
                    file.save(full_path)
                    success_count += 1
                    
                except Exception as e:
                    app.logger.error(f"Ошибка сохранения {file.filename}: {e}")
                    error_count += 1
        
        app.logger.info(f"Загружена папка: {success_count} файлов, ошибок: {error_count} в {path}")
        
        return jsonify({
            'success': True,
            'message': f'Загружено файлов: {success_count}, ошибок: {error_count}'
        })
        
    except Exception as e:
        app.logger.error(f"Ошибка загрузки папки: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/download', methods=['GET'])
def download_file():
    file_path = request.args.get('path')
    
    if not file_path:
        return jsonify({'error': 'Путь не указан'}), 400
    
    if not os.path.exists(file_path):
        return jsonify({'error': 'Файл не найден'}), 404
    
    try:
        if os.path.isdir(file_path):
            temp_zip = tempfile.NamedTemporaryFile(suffix='.zip', delete=False)
            temp_zip.close()
            
            with zipfile.ZipFile(temp_zip.name, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(file_path):
                    for file in files:
                        file_full_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_full_path, os.path.dirname(file_path))
                        zipf.write(file_full_path, arcname)
            
            return send_file(
                temp_zip.name,
                as_attachment=True,
                download_name=f"{os.path.basename(file_path)}.zip",
                mimetype='application/zip'
            )
        else:
            return send_file(
                file_path,
                as_attachment=True,
                download_name=os.path.basename(file_path)
            )
    except Exception as e:
        app.logger.error(f"Ошибка скачивания {file_path}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/mkdir', methods=['POST'])
def create_directory():
    data = request.json
    path = data.get('path', '')
    dirname = data.get('dirname')
    
    if not path:
        return jsonify({'error': 'Путь не указан'}), 400
    
    if not dirname:
        return jsonify({'error': 'Имя папки обязательно'}), 400
    
    full_path = os.path.join(path, dirname)
    
    try:
        os.makedirs(full_path, exist_ok=True)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/delete', methods=['DELETE'])
def delete_item():
    data = request.json
    path = data.get('path')
    
    if not path:
        return jsonify({'error': 'Путь не указан'}), 400
    
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/rename', methods=['POST'])
def rename_item():
    data = request.json
    old_path = data.get('old_path')
    new_name = data.get('new_name')
    
    if not old_path or not new_name:
        return jsonify({'error': 'Не указан путь или новое имя'}), 400
    
    dir_path = os.path.dirname(old_path)
    new_path = os.path.join(dir_path, new_name)
    
    try:
        os.rename(old_path, new_path)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/system', methods=['GET'])
def system_info():
    try:
        cpu_percent = psutil.cpu_percent(interval=0.5)
        cpu_count_physical = psutil.cpu_count(logical=False)
        cpu_count_logical = psutil.cpu_count(logical=True)
        cpu_name = get_cpu_name()
        cpu_per_core = psutil.cpu_percent(percpu=True)
        
        ram = psutil.virtual_memory()
        
        disks = []
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks.append({
                    'mountpoint': part.mountpoint,
                    'total': usage.total,
                    'used': usage.used,
                    'free': usage.free,
                    'percent': usage.percent,
                    'total_formatted': format_bytes(usage.total),
                    'used_formatted': format_bytes(usage.used),
                    'free_formatted': format_bytes(usage.free)
                })
            except:
                pass
        
        net_io = psutil.net_io_counters()
        boot_time = datetime.fromtimestamp(psutil.boot_time()).strftime('%Y-%m-%d %H:%M:%S')
        
        return jsonify({
            'cpu': {
                'percent': cpu_percent,
                'physical_cores': cpu_count_physical,
                'logical_cores': cpu_count_logical,
                'name': cpu_name,
                'per_core': cpu_per_core
            },
            'memory': {
                'total': ram.total,
                'used': ram.used,
                'available': ram.available,
                'percent': ram.percent,
                'total_formatted': format_bytes(ram.total),
                'used_formatted': format_bytes(ram.used),
                'free_formatted': format_bytes(ram.available)
            },
            'disks': disks,
            'network': {
                'bytes_sent': net_io.bytes_sent,
                'bytes_recv': net_io.bytes_recv,
                'sent_formatted': format_bytes(net_io.bytes_sent),
                'recv_formatted': format_bytes(net_io.bytes_recv)
            },
            'system': {
                'hostname': platform.node(),
                'os': f"{platform.system()} {platform.release()}",
                'boot_time': boot_time,
                'python_version': platform.python_version()
            },
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    load_history()
    print("=" * 60)
    print("🏠 Home Server Manager запущен")
    print(f"📁 Логи сохраняются в: {LOG_FOLDER}")
    print("📈 История нагрузки: каждые 10 минут")
    print("📁 Поддержка загрузки папок")
    print("📁 Поддержка скачивания папок (ZIP)")
    print("Логин: admin | Пароль: admin123")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=True)