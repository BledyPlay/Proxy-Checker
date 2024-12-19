import sys
import os
import socket
import requests
import sqlite3
import logging
from concurrent.futures import ThreadPoolExecutor
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QPushButton, QVBoxLayout, QHBoxLayout, QWidget, QTextEdit,
    QFileDialog, QLabel, QComboBox, QProgressBar, QMessageBox, QStackedWidget
)
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QFont, QPixmap
import socks
import shutil
import tempfile
from collections import defaultdict
from bs4 import BeautifulSoup

logging.basicConfig(
    filename="proxy_checker.log",
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
# === SQLite Database Setup ===
DB_NAME = "proxies.db"
def setup_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS proxies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ip_port TEXT NOT NULL,
        country TEXT NOT NULL
    )''')
    conn.commit()
    conn.close()

def save_to_database(ip_port, country):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO proxies (ip_port, country) VALUES (?, ?)", (ip_port, country))
        conn.commit()
        conn.close()
        logging.info(f"Saved to database: {ip_port} | {country}")
    except sqlite3.Error as e:
        logging.error(f"Failed to save {ip_port} to database: {e}")

class ProxySearchThread(QThread):
    progress = pyqtSignal(str)
    progress_count = pyqtSignal(int, int)
    completed = pyqtSignal(list)
    stop_signal = False

    def __init__(self, protocol):
        super().__init__()
        self.protocol = protocol

    def run(self):
        try:
            proxies = self.fetch_proxies_from_internet()
            if not self.stop_signal:
                self.completed.emit(proxies)
        except Exception as e:
            self.progress.emit(f"Error in thread execution: {str(e)}")

    def stop(self):
        self.stop_signal = True

    def fetch_proxies_from_internet(self):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36"
        }
        search_query = f"free {self.protocol} proxy list"
        search_url = f"https://www.google.com/search?q={search_query.replace(' ', '+')}"
        proxies = []

        try:
            response = requests.get(search_url, headers=headers, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                links = [a["href"] for a in soup.find_all("a", href=True) if "http" in a["href"]]

                total_links = len(links)
                for index, link in enumerate(links, start=1):
                    if self.stop_signal:
                        break
                    try:
                        resp = requests.get(link, headers=headers, timeout=10)
                        if resp.status_code == 200:
                            proxies.extend(resp.text.strip().split("\n"))
                            self.progress.emit(f"Fetched proxies from {link}")
                    except Exception as e:
                        self.progress.emit(f"Failed to fetch from {link}: {str(e)}")
                    self.progress_count.emit(index, total_links)
        except requests.RequestException as e:
            self.progress.emit(f"Failed to perform dynamic search: {str(e)}")
        except Exception as e:
            self.progress.emit(f"Unexpected error: {str(e)}")

        return proxies

def check_proxy(proxy, protocol):
    logging.debug(f"Checking proxy: {proxy} with protocol: {protocol}")
    try:
        ip, port = proxy.split(":")
        port = int(port)

        if protocol == "http":
            proxies = {"http": f"http://{proxy}", "https": f"http://{proxy}"}
            try:
                response = requests.get("https://httpbin.org/ip", proxies=proxies, timeout=5)
                if response.status_code == 200:
                    country = get_country_by_ip(ip)
                    save_to_database(proxy, country)
                    logging.info(f"{proxy} is working | Country: {country}")
                    return f"{proxy} is working | Country: {country}"
            except Exception as e:
                logging.error(f"{proxy} HTTP check failed: {e}")
                return f"{proxy} failed: {e}"

        elif protocol in ["socks4", "socks5"]:
            try:
                socks.set_default_proxy(
                    socks.SOCKS4 if protocol == "socks4" else socks.SOCKS5, ip, port
                )
                socket.socket = socks.socksocket
                sock = socket.create_connection(("httpbin.org", 80), timeout=5)
                sock.close()
                country = get_country_by_ip(ip)
                save_to_database(proxy, country)
                logging.info(f"{proxy} is working | Country: {country}")
                return f"{proxy} is working | Country: {country}"
            except Exception as e:
                logging.error(f"{proxy} SOCKS check failed: {e}")
                return f"{proxy} failed: {e}"

    except ValueError:
        logging.error(f"{proxy} has invalid format")
        return f"{proxy} failed: Invalid format"
    except Exception as e:
        logging.critical(f"Unexpected error with {proxy}: {e}")
        return f"{proxy} failed: {e}"

def process_file(file_path, protocol, progress_signal=None, progress_count_signal=None):
    logging.info(f"Processing proxy file: {file_path} with protocol: {protocol}")
    with open(file_path, "r") as file:
        proxies = [line.strip() for line in file.readlines() if line.strip()]

    total_proxies = len(proxies)
    results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(check_proxy, proxy, protocol) for proxy in proxies]
        for i, future in enumerate(futures):
            try:
                result = future.result(timeout=5)  # Добавьте таймаут для потоков
                results.append(result)
                if progress_signal:
                    progress_signal.emit(result)
                if progress_count_signal:
                    progress_count_signal.emit(i + 1, total_proxies)
            except Exception as e:
                logging.error(f"Error while checking proxy: {e}")
                results.append(f"Error checking proxy: {e}")
    return results

def get_country_by_ip(ip):
    try:
        response = requests.get(f"http://ip-api.com/json/{ip}", timeout=5)
        data = response.json()
        return data.get("country", "Unknown")
    except Exception:
        return "Unknown"

def clean_temp_files():
    temp_dir = tempfile.gettempdir()
    try:
        shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception as e:
        print(f"Failed to clean temporary files: {e}")
def sort_proxies_by_country(proxies):
    """
    Сортировка прокси по названию страны.
    """
    sorted_proxies = defaultdict(list)
    for proxy in proxies:
        ip = proxy.split(":")[0]
        country = get_country_by_ip(ip)  # Используем уже существующую функцию get_country_by_ip
        sorted_proxies[country].append(proxy)

    sorted_list = []
    for country in sorted(sorted_proxies.keys()):
        sorted_list.extend(sorted_proxies[country])
    return sorted_list
def save_sorted_proxies(file_path, proxies):
    """
    Сохранение отсортированных прокси в файл.
    """
    try:
        with open(file_path, "w") as file:
            for proxy in proxies:
                file.write(proxy + "\n")
        logging.info(f"Отсортированные прокси сохранены в {file_path}")
    except Exception as e:
        logging.error(f"Ошибка при сохранении прокси в файл: {e}")

class MainMenu(QWidget):
    def __init__(self, stacked_widget):
        super().__init__()
        self.stacked_widget = stacked_widget
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignCenter)

        self.background = QLabel(self)
        pixmap = QPixmap(r"A:\\PythonProject2\\background.png")
        if not pixmap.isNull():
            self.background.setPixmap(pixmap)
            self.background.setScaledContents(True)
        else:
            self.background.setStyleSheet("background-color: black;")
        self.background.setGeometry(0, 0, self.width(), self.height())

        self.title_label = QLabel("Proxy Checker", self)
        self.title_label.setFont(QFont("Arial", 24, QFont.Bold))
        self.title_label.setStyleSheet("color: white; text-align: center;")
        self.title_label.setAlignment(Qt.AlignCenter)

        self.start_button = QPushButton("Start", self)
        self.start_button.setStyleSheet(
            "background-color: #333; color: white; padding: 15px; border: 1px solid white; border-radius: 10px; font-size: 26px;"
        )
        self.start_button.setFixedHeight(60)
        self.start_button.setFixedWidth(200)
        self.start_button.clicked.connect(self.go_to_checker)

        self.start_online_button = QPushButton("Start Online", self)
        self.start_online_button.setStyleSheet(
            "background-color: #333; color: white; padding: 15px; border: 1px solid white; border-radius: 10px; font-size: 26px;"
        )
        self.start_online_button.setFixedHeight(60)
        self.start_online_button.setFixedWidth(200)
        self.start_online_button.clicked.connect(self.go_to_online_checker)

        self.exit_button = QPushButton("Exit", self)
        self.exit_button.setStyleSheet(
            "background-color: #333; color: white; padding: 15px; border: 1px solid white; border-radius: 10px; font-size: 26px;"
        )
        self.exit_button.setFixedHeight(60)
        self.exit_button.setFixedWidth(200)
        self.exit_button.clicked.connect(self.close_application)

        layout.addWidget(self.title_label)
        layout.addSpacing(20)
        layout.addWidget(self.start_button, alignment=Qt.AlignCenter)
        layout.addWidget(self.start_online_button, alignment=Qt.AlignCenter)
        layout.addWidget(self.exit_button, alignment=Qt.AlignCenter)

        self.setLayout(layout)

    def resizeEvent(self, event):
        self.background.setGeometry(0, 0, self.width(), self.height())

    def go_to_checker(self):
        self.stacked_widget.setCurrentIndex(1)

    def go_to_online_checker(self):
        self.stacked_widget.setCurrentIndex(2)

    def close_application(self):
        QApplication.quit()

class ProxyCheckerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Proxy Checker")
        self.resize(938, 669)
        self.setStyleSheet("border: 2px solid #333; background-color: #222;")
        self.stacked_widget = QStackedWidget()

        self.main_menu = MainMenu(self.stacked_widget)
        self.proxy_checker = ProxyCheckerWidget(self.stacked_widget)
        self.online_proxy_checker = OnlineProxyCheckerWidget(self.stacked_widget)

        self.stacked_widget.addWidget(self.main_menu)
        self.stacked_widget.addWidget(self.proxy_checker)
        self.stacked_widget.addWidget(self.online_proxy_checker)

        self.setCentralWidget(self.stacked_widget)

class ProxyCheckerWidget(QWidget):
    def __init__(self, stacked_widget):
        super().__init__()
        self.stacked_widget = stacked_widget
        self.working_proxies = []
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignCenter)

        self.background = QLabel(self)
        pixmap = QPixmap(r"A:\\PythonProject2\\background.png")
        if not pixmap.isNull():
            self.background.setPixmap(pixmap)
            self.background.setScaledContents(True)
            self.background.setStyleSheet("opacity: 0.3;")
        else:
            self.background.setStyleSheet("background-color: black;")
        self.background.setGeometry(0, 0, self.width(), self.height())

        self.label = QLabel("Select proxy protocol:")
        self.label.setFont(QFont("Arial", 12))
        self.label.setStyleSheet("color: silver;")
        layout.addWidget(self.label)

        self.protocol_combo = QComboBox()
        self.protocol_combo.addItems(["http", "socks4", "socks5"])
        self.protocol_combo.setStyleSheet("padding: 5px; border-radius: 8px; border: 1px solid #CCCCCC; background-color: #333; color: silver;")
        layout.addWidget(self.protocol_combo)

        self.file_button = QPushButton("Load Proxy File")
        self.file_button.setStyleSheet("background-color: #333; color: white; padding: 10px; border-radius: 8px; border: 1px solid white;")
        self.file_button.clicked.connect(self.load_file)
        layout.addWidget(self.file_button)

        self.check_button = QPushButton("Check Proxies")
        self.check_button.setStyleSheet("background-color: #333; color: white; padding: 10px; border-radius: 8px; border: 1px solid white;")
        self.check_button.clicked.connect(self.start_checking)
        layout.addWidget(self.check_button)

        self.download_button = QPushButton("Download Working Proxies")
        self.download_button.setStyleSheet("background-color: #333; color: white; padding: 10px; border-radius: 8px; border: 1px solid white;")
        self.download_button.clicked.connect(self.download_working_proxies)
        self.download_button.setEnabled(False)
        layout.addWidget(self.download_button)

        self.result_box = QTextEdit()
        self.result_box.setReadOnly(True)
        self.result_box.setStyleSheet("border: 1px solid #CCCCCC; border-radius: 8px; padding: 5px; background-color: rgba(34, 34, 34, 0.7); color: white;")
        layout.addWidget(self.result_box)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("QProgressBar {border: 1px solid #CCCCCC; border-radius: 8px; height: 20px; background-color: #333;} QProgressBar::chunk {background-color: #666; border-radius: 8px;}")
        layout.addWidget(self.progress_bar)

        self.back_to_menu_button = QPushButton("Back to Menu")
        self.back_to_menu_button.setStyleSheet("background-color: #333; color: white; padding: 10px; border-radius: 8px; border: 1px solid white;")
        self.back_to_menu_button.clicked.connect(self.go_to_menu)
        layout.addWidget(self.back_to_menu_button)

        self.setLayout(layout)

    def resizeEvent(self, event):
        self.background.setGeometry(0, 0, self.width(), self.height())

    def load_file(self):
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Proxy File", "", "Text Files (*.txt)", options=options)
        if file_path:
            self.proxy_file = file_path
            self.result_box.append(f"Loaded proxy file: {file_path}")

    def start_checking(self):
        if hasattr(self, 'proxy_file') and os.path.exists(self.proxy_file):
            protocol = self.protocol_combo.currentText()
            self.result_box.append("Starting proxy check...")
            self.progress_bar.setValue(0)

            self.thread = ProxyCheckerThread(self.proxy_file, protocol)
            self.thread.progress.connect(self.update_results)
            self.thread.completed.connect(self.save_working_proxies)
            self.thread.progress_count.connect(self.update_progress_bar)
            self.thread.start()
        else:
            self.result_box.append("No valid proxy file loaded.")

    def update_results(self, result):
        self.result_box.append(result)

    def update_progress_bar(self, current, total):
        progress = int((current / total) * 100)
        self.progress_bar.setValue(progress)

    def save_working_proxies(self, results):
        self.working_proxies = [result.split(" ")[0] for result in results if "is working" in result]
        self.result_box.append(f"\nFound {len(self.working_proxies)} working proxies.")
        self.download_button.setEnabled(True)

    def download_working_proxies(self):
        if self.working_proxies:
            sorted_proxies = sort_proxies_by_country(self.working_proxies)
            options = QFileDialog.Options()
            save_path, _ = QFileDialog.getSaveFileName(self, "Save Sorted Proxies", "sorted_proxies.txt", "Text Files (*.txt)", options=options)
            if save_path:
                save_sorted_proxies(save_path, sorted_proxies)
                QMessageBox.information(self, "Success", f"Sorted proxies saved to {save_path}")

    def go_to_menu(self):
        self.stacked_widget.setCurrentIndex(0)
class ProxyCheckerThread(QThread):
    progress = pyqtSignal(str)
    progress_count = pyqtSignal(int, int)
    completed = pyqtSignal(list)

    def __init__(self, file_path, protocol):
        super().__init__()
        self.file_path = file_path
        self.protocol = protocol

    def run(self):
        try:
            results = process_file(self.file_path, self.protocol, self.progress, self.progress_count)
            self.completed.emit(results)
        except Exception as e:
            self.progress.emit(f"Ошибка: {str(e)}")

class OnlineProxyCheckerWidget(QWidget):
    def __init__(self, stacked_widget):
        super().__init__()
        self.stacked_widget = stacked_widget
        self.working_proxies = []
        self.search_thread = None
        self.check_thread = None
        self.initUI()

    def initUI(self):
        # Установка фонового изображения
        self.background = QLabel(self)
        pixmap = QPixmap(r"A:\\PythonProject2\\background.png")  # Обновите путь, если необходимо
        if not pixmap.isNull():
            self.background.setPixmap(pixmap)
            self.background.setScaledContents(True)
        else:
            self.background.setStyleSheet("background-color: black;")
        self.background.setGeometry(0, 0, self.width(), self.height())

        # Настройка основного интерфейса
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignCenter)

        self.label = QLabel("Select proxy protocol:")
        self.label.setFont(QFont("Arial", 12))
        self.label.setStyleSheet("color: silver;")
        layout.addWidget(self.label)

        self.protocol_combo = QComboBox()
        self.protocol_combo.addItems(["http", "socks4", "socks5"])
        self.protocol_combo.setStyleSheet(
            "padding: 5px; border-radius: 8px; border: 1px solid #CCCCCC; background-color: #333; color: silver;"
        )
        layout.addWidget(self.protocol_combo)

        self.search_button = QPushButton("Search Proxies")
        self.search_button.setStyleSheet(
            "background-color: #333; color: white; padding: 10px; border-radius: 8px; border: 1px solid white;"
        )
        self.search_button.clicked.connect(self.start_search)
        layout.addWidget(self.search_button)

        self.stop_button = QPushButton("Stop Search")
        self.stop_button.setStyleSheet(
            "background-color: #333; color: white; padding: 10px; border-radius: 8px; border: 1px solid white;"
        )
        self.stop_button.clicked.connect(self.stop_search)
        layout.addWidget(self.stop_button)

        self.check_button = QPushButton("Check Proxies")
        self.check_button.setStyleSheet(
            "background-color: #333; color: white; padding: 10px; border-radius: 8px; border: 1px solid white;"
        )
        self.check_button.clicked.connect(self.start_checking)
        layout.addWidget(self.check_button)

        self.download_button = QPushButton("Download Proxies")
        self.download_button.setStyleSheet(
            "background-color: #333; color: white; padding: 10px; border-radius: 8px; border: 1px solid white;"
        )
        self.download_button.clicked.connect(self.download_proxies)
        self.download_button.setEnabled(False)
        layout.addWidget(self.download_button)

        self.result_box = QTextEdit()
        self.result_box.setReadOnly(True)
        self.result_box.setStyleSheet(
            """
            border: 1px solid #CCCCCC; 
            border-radius: 8px; 
            padding: 5px; 
            background-color: rgba(34, 34, 34, 0.7); /* Adjust transparency to match the style */
            color: white;
            """
        )
        layout.addWidget(self.result_box)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(
            """
            QProgressBar {
                border: 1px solid #CCCCCC; 
                border-radius: 8px; 
                height: 20px; 
                background-color: #333;
            }
            QProgressBar::chunk {
                background-color: #666; 
                border-radius: 8px;
            }
            """
        )
        layout.addWidget(self.progress_bar)

        self.back_to_menu_button = QPushButton("Back to Menu")
        self.back_to_menu_button.setStyleSheet(
            "background-color: #333; color: white; padding: 10px; border-radius: 8px; border: 1px solid white;"
        )
        self.back_to_menu_button.clicked.connect(self.go_to_menu)
        layout.addWidget(self.back_to_menu_button)

        self.setLayout(layout)
        self.background.lower()  # Убедитесь, что фон находится позади всех виджетов

    def resizeEvent(self, event):
        # Автоматическая подгонка фона под размер окна
        self.background.setGeometry(0, 0, self.width(), self.height())

    def start_search(self):
        protocol = self.protocol_combo.currentText()
        self.search_thread = ProxySearchThread(protocol)
        self.search_thread.progress.connect(self.update_results)
        self.search_thread.completed.connect(self.save_proxies)
        self.search_thread.start()

    def stop_search(self):
        if self.search_thread:
            self.search_thread.stop()

    def start_checking(self):
        proxies = self.result_box.toPlainText().split("\n")
        protocol = self.protocol_combo.currentText()
        if proxies:
            self.progress_bar.setValue(0)
            self.check_thread = ProxyCheckerThread("\n".join(proxies), protocol)
            self.check_thread.progress.connect(self.update_results)
            self.check_thread.completed.connect(self.save_working_proxies)
            self.check_thread.progress_count.connect(self.update_progress_bar)
            self.check_thread.start()

    def update_results(self, result):
        self.result_box.append(result)

    def update_progress_bar(self, current, total):
        progress = int((current / total) * 100)
        self.progress_bar.setValue(progress)

    def save_proxies(self, proxies):
        self.result_box.append(f"\nFound {len(proxies)} proxies.")

    def save_working_proxies(self, results):
        self.working_proxies = [
            result.split(" ")[0] for result in results if "is working" in result
        ]
        self.result_box.append(f"\nFound {len(self.working_proxies)} working proxies.")
        self.download_button.setEnabled(True)

    def download_proxies(self):
        if self.working_proxies:
            sorted_proxies = sort_proxies_by_country(self.working_proxies)
            options = QFileDialog.Options()
            save_path, _ = QFileDialog.getSaveFileName(
                self, "Save Proxies", "sorted_proxies.txt", "Text Files (*.txt)", options=options
            )
            if save_path:
                save_sorted_proxies(save_path, sorted_proxies)
                QMessageBox.information(self, "Success", f"Proxies saved to {save_path}")

    def go_to_menu(self):
        self.stacked_widget.setCurrentIndex(0)

if __name__ == "__main__":
    setup_database()  # Setup database before launching the app
    app = QApplication(sys.argv)
    mainWin = ProxyCheckerApp()
    mainWin.show()
    sys.exit(app.exec_())

