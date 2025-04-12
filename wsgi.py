#!/usr/bin/env python3
"""
WSGI-файл для запуска приложения на продакшн-сервере
Используйте с gunicorn: gunicorn -w 4 -k gevent wsgi:app
"""

from app import app

if __name__ == "__main__":
    app.run() 