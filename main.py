import os
import requests
import json
import time
import subprocess
import getpass
from github import Github

def upload_to_github(username, token, repo_name, local_path):
    """Загружает проект на GitHub"""
    print("Загрузка проекта на GitHub...")
    
    # Аутентификация в GitHub
    g = Github(token)
    user = g.get_user()
    
    # Проверка существования репозитория или создание нового
    try:
        repo = user.get_repo(repo_name)
        print(f"Репозиторий {repo_name} уже существует")
    except:
        repo = user.create_repo(repo_name, description="Сайт розыгрыша автомобиля", private=False)
        print(f"Создан новый репозиторий: {repo_name}")
    
    # Подготовка .gitignore файла для исключения ненужных файлов
    gitignore_path = os.path.join(local_path, '.gitignore')
    if not os.path.exists(gitignore_path):
        with open(gitignore_path, 'w', encoding='utf-8') as f:
            f.write("__pycache__/\n*.py[cod]\n*$py.class\nvenv/\nenv/\n.env\n*.log\n")
    
    # Инициализация и настройка Git
    os.chdir(local_path)
    commands = [
        ["git", "init"],
        ["git", "config", "user.name", username],
        ["git", "config", "user.email", f"{username}@users.noreply.github.com"],
        ["git", "add", "."],
        ["git", "commit", "-m", "Первичная загрузка сайта розыгрыша автомобиля"],
        ["git", "branch", "-M", "main"],
        ["git", "remote", "add", "origin", f"https://{token}@github.com/{username}/{repo_name}.git"],
        ["git", "push", "-u", "origin", "main"]
    ]
    
    for cmd in commands:
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Ошибка при выполнении команды {cmd}: {e}")
            return None
    
    return repo.html_url

def deploy_to_render(github_url, api_key):
    """Развертывает Flask-проект на Render.com"""
    print("Развертывание проекта на Render.com...")
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # Настройка для Python/Flask приложения
    payload = {
        "type": "web_service",
        "name": "car-giveaway",
        "repo": github_url,
        "branch": "main",
        "buildCommand": "pip install -r requirements.txt",
        "startCommand": "gunicorn wsgi:app",
        "envVars": [
            {
                "key": "PYTHON_VERSION",
                "value": "3.9.0"
            },
            {
                "key": "SECRET_KEY",
                "value": os.urandom(24).hex()
            }
        ],
        "plan": "free"
    }
    
    response = requests.post(
        "https://api.render.com/v1/services",
        headers=headers,
        data=json.dumps(payload)
    )
    
    if response.status_code == 200 or response.status_code == 201:
        service_data = response.json()
        service_id = service_data.get("id")
        service_url = service_data.get("serviceDetails", {}).get("url")
        
        # Ожидание завершения деплоя
        print("Ожидание развертывания...")
        for _ in range(20):  # Максимум 10 минут ожидания
            time.sleep(30)
            status_response = requests.get(
                f"https://api.render.com/v1/services/{service_id}",
                headers=headers
            )
            status_data = status_response.json()
            status = status_data.get("status")
            
            if status == "live":
                return service_url
        
        return f"Деплой не завершен за отведенное время. Проверьте статус вручную: https://dashboard.render.com/"
    else:
        error_msg = response.json().get("error", "Неизвестная ошибка")
        print(f"Ошибка при создании сервиса: {error_msg}")
        return None

def main():
    print("=== Загрузка и деплой сайта розыгрыша автомобиля ===")
    
    # Сбор учетных данных
    username = input("Введите ваше имя пользователя GitHub: ")
    token = getpass.getpass("Введите личный токен доступа GitHub: ")
    repo_name = input("Введите имя репозитория (по умолчанию: car-giveaway): ") or "car-giveaway"
    
    # Получаем фактический путь к текущей директории
    current_dir = os.getcwd()
    local_path_input = input(f"Введите путь к папке проекта (по умолчанию: {current_dir}): ")
    local_path = local_path_input if local_path_input.strip() else current_dir
    
    render_api_key = getpass.getpass("Введите API ключ Render.com: ")
    
    # Проверка наличия PyGithub
    try:
        import github
    except ImportError:
        print("Установка необходимых зависимостей...")
        subprocess.run(["pip", "install", "PyGithub"], check=True)
    
    # Загрузка на GitHub
    github_url = upload_to_github(username, token, repo_name, local_path)
    if not github_url:
        print("Не удалось загрузить проект на GitHub")
        return
    
    print(f"Проект успешно загружен на GitHub: {github_url}")
    
    # Деплой на Render
    render_url = deploy_to_render(github_url, render_api_key)
    if not render_url:
        print(f"Не удалось развернуть проект. Попробуйте сделать это вручную через панель Render.com")
        return
    
    print("\n=== Результаты ===")
    print(f"GitHub репозиторий: {github_url}")
    print(f"URL вашего сайта: {render_url}")
    print(f"Админ-панель доступна по адресу: {render_url}/admin")
    print("Логин: admin")
    print("Пароль: kvdarit_avto35")
    print("\nВАЖНО: База данных участников хранится на сервере Render. Если вы хотите перенести существующих участников,")
    print("вам нужно обновить файл participants.json в репозитории GitHub.")

if __name__ == "__main__":
    main()
