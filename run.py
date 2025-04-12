#!/usr/bin/env python3
# Файл для запуска приложения на локальном сервере

import os
from app import app

if __name__ == "__main__":
    # Получение порта из переменных окружения для совместимости с облачными платформами
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, threaded=True, debug=True) 