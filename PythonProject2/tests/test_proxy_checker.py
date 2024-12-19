from proxy_checker_gui import check_proxy  # Импортируем функцию проверки прокси
from unittest.mock import patch  # Импортируем библиотеку для мока

@patch("requests.get")  # Мокаем функцию requests.get
def test_check_proxy_http(mock_get):
    # Устанавливаем поведение мока для успешного подключения
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"origin": "8.8.8.8"}

    # Проверяем результат
    result = check_proxy("8.8.8.8:8080", "http")
    assert "is working" in result  # Проверяем, что прокси определён как рабочий

@patch("requests.get")
def test_check_proxy_invalid(mock_get):
    # Мокаем ошибку соединения
    mock_get.side_effect = Exception("Connection failed")

    # Проверяем результат для невалидного прокси
    result = check_proxy("invalid:port", "http")
    assert "failed" in result  # Проверяем, что ошибка обработана корректно
