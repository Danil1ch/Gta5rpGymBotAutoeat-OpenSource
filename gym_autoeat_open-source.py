import cv2
import numpy as np
import time
import pyautogui
import mss
import keyboard
import threading
import tkinter as tk
from tkinter import Label, font
import os
import sys
import configparser

# --- ИМПОРТ ДЛЯ PYQT6 ---
from PyQt6.QtWidgets import (QApplication, QDialog, QLabel, QPushButton, 
                             QVBoxLayout, QHBoxLayout, QWidget, QLineEdit)
from PyQt6.QtGui import QIcon, QKeySequence
from PyQt6.QtCore import Qt, QTimer

# --- ГЛОБАЛЬНЫЕ СТИЛИ (Сохранены крупные размеры и стиль) ---
QSS_STYLE = """
QDialog {
    background-color: #2e2e2e; 
    color: #ffffff;
    font-family: Segoe UI, sans-serif;
}
QLabel {
    color: #ffffff;
    font-size: 14pt;
    margin: 5px;
}
QPushButton {
    background-color: #444444;
    color: #ffffff;
    border: 1px solid #555555;
    padding: 10px 20px;
    border-radius: 5px;
    font-size: 14pt;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #555555;
}
QPushButton[objectName="YesButton"] {
    background-color: #008800; 
}
QPushButton[objectName="NoButton"] {
    background-color: #880000; 
}
QLineEdit {
    background-color: #3e3e3e;
    color: #00ff00;
    border: 2px solid #555555;
    padding: 10px;
    border-radius: 5px;
    font-size: 24pt;
    font-weight: bold;
    text-align: center;
}
"""

# --- Скрытие консоли ---
if sys.platform == "win32":
    import ctypes
    kernel32 = ctypes.WinDLL('kernel32')
    user32 = ctypes.WinDLL('user32')
    hWnd = kernel32.GetConsoleWindow()
    if hWnd:
        user32.ShowWindow(hWnd, 0)

# --- ПУТИ И КОНФИГУРАЦИЯ (ИЗМЕНЕНО: Конфиг теперь в AppData\Local) ---

APP_NAME = "GymBot" # Имя папки для настроек внутри AppData/Local

def get_config_dir():
    """Возвращает путь к скрытой папке конфигурации в AppData/Local и создает ее."""
    if sys.platform == "win32":
        # Путь: C:\Users\Username\AppData\Local\GymBot
        local_appdata = os.path.join(os.path.expanduser('~'), 'AppData', 'Local', APP_NAME)
    else:
        # Для других систем (Linux/macOS) используем скрытую папку в Home
        local_appdata = os.path.join(os.path.expanduser('~'), f'.{APP_NAME}_config')
        
    os.makedirs(local_appdata, exist_ok=True)
    return local_appdata

def get_resource_dir():
    """Возвращает корневую директорию скрипта или EXE-файла для ресурсов (шаблона)."""
    if getattr(sys, 'frozen', False):
        # Если запущено как EXE (PyInstaller)
        return os.path.dirname(sys.executable)
    else:
        # Если запущено как Python-скрипт
        return os.path.dirname(os.path.abspath(__file__))

# SCRIPT_DIR используется ТОЛЬКО для ресурсов (end_approach.png)
SCRIPT_DIR = get_resource_dir() 

# CONFIG_FILE теперь использует скрытую папку
CONFIG_DIR = get_config_dir()
CONFIG_FILE = os.path.join(CONFIG_DIR, 'gym_config.ini')

# Настройки бота
ROI_X = 660 
ROI_Y = 300
ROI_W = 600
ROI_H = 500
END_REGION = (650, 1015, 620, 39)
END_THRESHOLD = 0.75
END_STABLE_TIME = 0.7
REST_TIME = 30
MIN_GAP = 8
MAX_GAP = 25
PRESS_COOLDOWN = 0.25
WHITE_LOWER = np.array([0, 0, 180])
WHITE_UPPER = np.array([180, 70, 255])
GREEN_LOWER = np.array([25, 40, 40])
GREEN_UPPER = np.array([95, 255, 255])
MIN_WHITE_RADIUS = 15
MIN_GREEN_RADIUS = 30
SMOOTHIE_COOLDOWN = 7.0 # 7 секунд между нажатиями смузи

# Глобальные переменные
is_running = False
is_paused = True
current_status = "ОЖИДАНИЕ"
last_space_time = 0
APPROACH_COUNT = 0
AUTO_EAT_ENABLED = False
EAT_KEY = None
MAX_APPROACHES = 30
FOOD_TYPE = 'bar' # 'bar' (батончики) или 'smoothie' (смузи)

# --- УНИВЕРСАЛЬНАЯ ФУНКЦИЯ ЗАГРУЗКИ ---
def load_image_any_path(path, grayscale=True):
    try:
        with open(path, 'rb') as f:
            img_bytes = bytearray(f.read())
        nparr = np.frombuffer(img_bytes, np.uint8)
        if grayscale:
            img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
        else:
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        return img
    except Exception:
        return None

# --- ЗАГРУЗКА ШАБЛОНА ---
def load_end_template():
    possible_names = ["end_approach.png", "end_approach.jpg", "end_approach.jpeg", "END_APPROACH.PNG"]
    for filename in possible_names:
        # Используем SCRIPT_DIR (путь к EXE) для поиска шаблона
        template_path = os.path.join(SCRIPT_DIR, filename) 
        if os.path.exists(template_path):
            template = load_image_any_path(template_path, grayscale=True)
            if template is not None:
                return template, True
    return None, False

END_TEMPLATE, TEMPLATE_LOADED = load_end_template()

# --- ФУНКЦИИ КОНФИГА ---
def load_config():
    global FOOD_TYPE
    config = configparser.ConfigParser()
    # Читаем из CONFIG_FILE (который теперь в AppData)
    config.read(CONFIG_FILE) 
    if config.has_section('AutoEat'):
        key = config.get('AutoEat', 'Key', fallback=None)
        FOOD_TYPE = config.get('AutoEat', 'FoodType', fallback='bar')
        return key
    return None

def save_config(key, food_type):
    config = configparser.ConfigParser()
    # Сначала читаем, чтобы сохранить остальные секции
    config.read(CONFIG_FILE) 
    # Сохраняем/обновляем секцию в CONFIG_FILE
    config['AutoEat'] = {'Key': key if key else '', 'FoodType': food_type}
    with open(CONFIG_FILE, 'w') as configfile:
        config.write(configfile)

# --- PYQT6 ДИАЛОГИ ---

class AskAutoEatDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Настройка Автоеды")
        self.setMinimumSize(450, 250)
        self.resize(450, 250)
        layout = QVBoxLayout()
        label = QLabel("Включить автоеду?")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        btn_layout = QHBoxLayout()
        btn_yes = QPushButton("✅ ДА")
        btn_yes.setObjectName("YesButton") 
        btn_yes.clicked.connect(self.accept)
        btn_no = QPushButton("❌ НЕТ")
        btn_no.setObjectName("NoButton")
        btn_no.clicked.connect(self.reject)
        btn_layout.addWidget(btn_yes)
        btn_layout.addWidget(btn_no)
        layout.addLayout(btn_layout)
        self.setLayout(layout)

class AskFoodTypeDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Выбор еды")
        self.setMinimumSize(500, 250)
        self.resize(500, 250)
        self.food_type = None
        layout = QVBoxLayout()
        label = QLabel("Что бот будет есть?")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        btn_layout = QHBoxLayout()
        btn_bar = QPushButton("Батончики ")
        btn_bar.clicked.connect(lambda: self.set_food_type('bar'))
        btn_bar.setObjectName("BarButton")
        btn_layout.addWidget(btn_bar)
        btn_smoothie = QPushButton("Смузи ")
        btn_smoothie.clicked.connect(lambda: self.set_food_type('smoothie'))
        btn_smoothie.setObjectName("SmoothieButton")
        btn_layout.addWidget(btn_smoothie)
        layout.addLayout(btn_layout)
        self.setLayout(layout)
    def set_food_type(self, type_name):
        self.food_type = type_name
        self.accept()

class AskChangeKeyDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Настройка Автоеды")
        self.setMinimumSize(550, 250)
        self.resize(550, 250)
        layout = QVBoxLayout()
        label = QLabel("Поменять кнопку для еды?")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        btn_layout = QHBoxLayout()
        btn_yes = QPushButton("✅ ПОМЕНЯТЬ")
        btn_yes.setObjectName("YesButton")
        btn_yes.clicked.connect(self.accept)
        btn_no = QPushButton("❌ ОСТАВИТЬ")
        btn_no.setObjectName("NoButton")
        btn_no.clicked.connect(self.reject)
        btn_layout.addWidget(btn_yes)
        btn_layout.addWidget(btn_no)
        layout.addLayout(btn_layout)
        self.setLayout(layout)

class RecordKeyDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Запись клавиши")
        self.setMinimumSize(500, 300) 
        self.resize(500, 300)
        self.eat_key_name = None
        layout = QVBoxLayout()
        label = QLabel("Нажмите кнопку еды:")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        self.key_display = QLineEdit()
        self.key_display.setPlaceholderText("ОЖИДАНИЕ НАЖАТИЯ...")
        self.key_display.setReadOnly(True)
        self.key_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.key_display)
        info = QLabel("(Принимает F-клавиши, цифры и другие символы)")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.setStyleSheet("font-size: 10pt; color: #aaaaaa;")
        layout.addWidget(info)
        self.setLayout(layout)
    def keyPressEvent(self, event):
        key = event.key()
        final_name = ""
        if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12:
            final_name = f"f{key - Qt.Key.Key_F1 + 1}"
        elif event.text():
            final_name = event.text().lower()
        if final_name and final_name not in ('shift', 'ctrl', 'alt'):
            self.eat_key_name = final_name
            self.key_display.setText(final_name.upper())
            QTimer.singleShot(700, self.accept)

# --- OVERLAY GUI (TKINTER) ---
class OverlayGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)
        self.root.geometry("+10+10")
        self.root.configure(bg='#0a0a0a')
        self.root.wm_attributes("-alpha", 0.9)
        
        frame = tk.Frame(self.root, bg='#0a0a0a', padx=15, pady=10)
        frame.pack()
        
        tk.Label(frame, text="Качалка", font=("Segoe UI", 11, "bold"), fg="#00ff00", bg='#0a0a0a').pack()
        
        self.status = tk.Label(frame, text=current_status, font=("Segoe UI", 10), fg="white", bg='#0a0a0a')
        self.status.pack(pady=5)
        
        self.keys = tk.Label(frame, text="F7-Start", font=("Segoe UI", 9), fg="#aaa", bg='#0a0a0a')
        self.keys.pack(pady=2)
        
        self.eat_info = tk.Label(frame, text=self.get_eat_text(), font=("Segoe UI", 8), fg="#aaa", bg='#0a0a0a')
        self.eat_info.pack(pady=2)

        tk.Frame(frame, height=1, width=150, bg='#333333').pack(pady=5)
        
        self.update_ui()
        self.root.mainloop()

    def get_eat_text(self):
        food_name = "Батончики" if FOOD_TYPE == 'bar' else "Смузи"
        if AUTO_EAT_ENABLED and EAT_KEY:
            return f"Автоеда: ВКЛ ({EAT_KEY.upper()}, {food_name}) | Подх: {APPROACH_COUNT}/{MAX_APPROACHES}"
        return "Автоеда: ОТКЛ"

    def update_ui(self):
        global current_status
        color = "#FFFFFF"
        if "РАБОТАЕТ" in current_status: color = "#00FF00"
        elif "ПАУЗА" in current_status: color = "#FFFF00"
        elif "ОТДЫХ" in current_status: color = "#00FFFF"
        elif "НАЖИМАЮ" in current_status or "ЕСТ" in current_status: color = "#FF9900"
        
        self.status.config(text=current_status, fg=color)
        
        keys_text = "F8 - Пауза | F9 - Выход" if is_running and not is_paused else "F7 - Запуск"
        self.keys.config(text=keys_text)
        self.eat_info.config(text=self.get_eat_text())
        
        self.root.after(200, self.update_ui)

# --- ГЛАВНАЯ ЛОГИКА БОТА ---

def handle_eating():
    """Выполняет логику поедания в зависимости от FOOD_TYPE."""
    global current_status, FOOD_TYPE, EAT_KEY
    
    if FOOD_TYPE == 'bar':
        current_status = f"ЕСТ БАТОНЧИК: {EAT_KEY.upper()}"
        pyautogui.press(EAT_KEY)
        time.sleep(1.0) 
        
    elif FOOD_TYPE == 'smoothie':
        for i in range(1, 6):
            current_status = f"ЕСТ СМУЗИ: {EAT_KEY.upper()} ({i}/5)"
            pyautogui.press(EAT_KEY)
            if i < 5:
                if not smart_sleep(SMOOTHIE_COOLDOWN):
                    return

def bot_thread():
    global current_status, is_paused, is_running, APPROACH_COUNT, last_space_time
    
    roi = {"top": ROI_Y, "left": ROI_X, "width": ROI_W, "height": ROI_H}
    
    with mss.mss() as sct:
        while True:
            if not is_running: break
            if is_paused:
                current_status = "ПАУЗА (F7)"
                time.sleep(0.1)
                continue
                
            # 1. НАЧАЛО НОВОГО ПОДХОДА
            current_status = "НАЖИМАЮ E"
            press_e()
            time.sleep(0.1)
            current_status = "РАБОТАЕТ"
            last_space_time = 0
            
            end_timer = None
            
            # 2. ЦИКЛ ПОДХОДА
            while not is_paused and is_running:
                img = np.array(sct.grab(roi))
                hsv = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGRA2BGR), cv2.COLOR_BGR2HSV)
                rg, rw = get_radii(hsv)
                
                t = time.time()
                if can_press_space(rg, rw, t):
                    pyautogui.press('space')
                    time.sleep(0.05)
                
                if check_end(sct):
                    if end_timer is None: end_timer = t
                    elif t - end_timer >= END_STABLE_TIME:
                        current_status = "ЗАВЕРШЕНО"
                        time.sleep(0.2)
                        break
                else:
                    end_timer = None
                    
                time.sleep(0.02)
                
            if is_paused: continue
            
            # 3. УВЕЛИЧИВАЕМ СЧЕТЧИК ПОДХОДОВ
            if is_running: APPROACH_COUNT += 1
            
            # 4. ПРОВЕРКА И ЕДА (Срабатывает СРАЗУ после подхода, до отдыха)
            if AUTO_EAT_ENABLED and APPROACH_COUNT >= MAX_APPROACHES:
                handle_eating()
                APPROACH_COUNT = 0
            
            # 5. ОТДЫХ
            for i in range(REST_TIME, 0, -1):
                current_status = f"ОТДЫХ: {i}"
                if not smart_sleep(1): break 

def press_e():
    keyboard.press('e'); time.sleep(0.05); keyboard.release('e')

def get_radii(img_hsv):
    mask_w = cv2.inRange(img_hsv, WHITE_LOWER, WHITE_UPPER)
    mask_g = cv2.inRange(img_hsv, GREEN_LOWER, GREEN_UPPER)
    
    rw = 0
    cnt_w, _ = cv2.findContours(mask_w, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnt_w:
        if cv2.contourArea(c) > 50:
            _, r = cv2.minEnclosingCircle(c)
            if r > rw: rw = r
            
    rg = 0
    cnt_g, _ = cv2.findContours(mask_g, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnt_g:
        if cv2.contourArea(c) > 100:
            _, r = cv2.minEnclosingCircle(c)
            if r > rg: rg = r
            
    return rg, rw

def can_press_space(rg, rw, t):
    global last_space_time
    if t - last_space_time < PRESS_COOLDOWN: return False
    if rw < MIN_WHITE_RADIUS or rg < MIN_GREEN_RADIUS: return False
    if rw >= rg: return False
    diff = rg - rw
    if not (MIN_GAP <= diff <= MAX_GAP): return False
    last_space_time = t
    return True

def check_end(sct):
    if END_TEMPLATE is None: return False
    # Используем END_REGION для захвата конкретной области
    img = np.array(sct.grab({"top": END_REGION[1], "left": END_REGION[0], "width": END_REGION[2], "height": END_REGION[3]}))
    gray = cv2.cvtColor(img[:,:,:3], cv2.COLOR_BGR2GRAY)
    res = cv2.matchTemplate(gray, END_TEMPLATE, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(res)
    return max_val >= END_THRESHOLD

def smart_sleep(sec):
    global is_paused, is_running
    for _ in range(int(sec * 10)):
        if not is_running or is_paused: return False
        time.sleep(0.1)
    return True

def key_listener():
    global is_running, is_paused, current_status
    while True:
        if keyboard.is_pressed('f7'):
            if not is_running:
                is_running = True; is_paused = False
                threading.Thread(target=bot_thread, daemon=True).start()
            else: is_paused = False
            time.sleep(0.3)
        if keyboard.is_pressed('f8'):
            is_paused = True; time.sleep(0.3)
        if keyboard.is_pressed('f9'):
            is_running = False; is_paused = True
            current_status = "ВЫХОД"; time.sleep(1)
            os._exit(0)
        time.sleep(0.05)

# --- STARTUP ---
def configure():
    global AUTO_EAT_ENABLED, EAT_KEY, FOOD_TYPE
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS_STYLE)
    
    # 1. Загрузка конфигурации (Обновляет FOOD_TYPE)
    key = load_config()
    
    # 2. Спрашиваем, включать ли автоеду
    if AskAutoEatDialog().exec() == QDialog.DialogCode.Rejected:
        AUTO_EAT_ENABLED = False
        return
        
    AUTO_EAT_ENABLED = True

    # 3. Спрашиваем, что есть
    food_dlg = AskFoodTypeDialog()
    if food_dlg.exec() == QDialog.DialogCode.Accepted:
        FOOD_TYPE = food_dlg.food_type
    else:
        AUTO_EAT_ENABLED = False
        return
    
    # 4. Проверяем, нужно ли менять кнопку
    if key:
        change_dlg = AskChangeKeyDialog()
        if change_dlg.exec() == QDialog.DialogCode.Rejected:
            EAT_KEY = key
            save_config(EAT_KEY, FOOD_TYPE) 
            return
            
    # 5. Записываем новую кнопку
    key_dlg = RecordKeyDialog()
    if key_dlg.exec() == QDialog.DialogCode.Accepted and key_dlg.eat_key_name:
        EAT_KEY = key_dlg.eat_key_name
        save_config(EAT_KEY, FOOD_TYPE) 
    else:
        AUTO_EAT_ENABLED = False

if __name__ == "__main__":
    configure()
    threading.Thread(target=key_listener, daemon=True).start()
    OverlayGUI()