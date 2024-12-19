import sqlite3
from proxy_checker_gui import setup_database, save_to_database  # Подключаем функции из proxy_checker_gui.py

def test_database_setup():
    # Тест на создание базы данных и таблицы
    setup_database()
    conn = sqlite3.connect("proxies.db")  # Открываем базу данных
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='proxies';")
    table_exists = cursor.fetchone()
    conn.close()
    assert table_exists is not None  # Убеждаемся, что таблица создана

def test_save_to_database():
    # Тест на запись данных в базу
    setup_database()  # Убеждаемся, что база данных настроена
    save_to_database("192.168.0.1:8080", "TestCountry")  # Добавляем запись
    conn = sqlite3.connect("proxies.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM proxies WHERE ip_port='192.168.0.1:8080';")
    result = cursor.fetchone()
    conn.close()
    assert result is not None  # Проверяем, что запись существует
    assert result[1] == "192.168.0.1:8080"  # Проверяем корректность IP
    assert result[2] == "TestCountry"  # Проверяем корректность страны
