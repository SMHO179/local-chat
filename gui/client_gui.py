import sys
import socket
import threading

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QGroupBox,
    QFormLayout,
    QStatusBar,
)


class ClientWorker(QThread):
    message_received = pyqtSignal(str)
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, host: str, port: int, name: str):
        super().__init__()
        self.host = host
        self.port = port
        self.name = name
        self.running = False
        self.client_socket = None

    def run(self):
        self.running = True
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.connect((self.host, self.port))
            self.connected.emit()

            self.receive_loop()

        except Exception as e:
            if self.running:
                self.error_occurred.emit(str(e))
        finally:
            self.running = False
            if self.client_socket:
                try:
                    self.client_socket.close()
                except Exception:
                    pass
                self.client_socket = None
            self.disconnected.emit()

    def receive_loop(self):
        while self.running:
            try:
                message = self.client_socket.recv(1024).decode()
                if not message:
                    break

                if message == "NICK":
                    self.client_socket.send(self.name.encode())
                else:
                    self.message_received.emit(message)
            except Exception:
                break

    def send_message(self, text):
        if self.client_socket and self.running:
            try:
                message = f"{self.name}: {text}"
                self.client_socket.send(message.encode())
            except Exception:
                pass

    def stop(self):
        self.running = False
        if self.client_socket:
            try:
                self.client_socket.close()
            except Exception:
                pass
            self.client_socket = None


class ClientWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chat Client")
        self.setMinimumSize(600, 450)
        self.worker = None
        self.init_ui()

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        config_group = QGroupBox("Connection")
        config_layout = QFormLayout()
        self.host_input = QLineEdit("127.0.0.1")
        self.port_input = QLineEdit("5555")
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter your username")
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.toggle_connection)
        config_layout.addRow("Host:", self.host_input)
        config_layout.addRow("Port:", self.port_input)
        config_layout.addRow("Username:", self.name_input)
        config_layout.addRow(self.connect_btn)
        config_group.setLayout(config_layout)
        layout.addWidget(config_group)

        chat_group = QGroupBox("Chat")
        chat_layout = QVBoxLayout()
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        chat_layout.addWidget(self.chat_display)
        chat_group.setLayout(chat_layout)
        layout.addWidget(chat_group)

        input_group = QGroupBox("Message")
        input_layout = QHBoxLayout()
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText("Type a message...")
        self.message_input.returnPressed.connect(self.send_message)
        self.send_btn = QPushButton("Send")
        self.send_btn.setEnabled(False)
        self.send_btn.clicked.connect(self.send_message)
        input_layout.addWidget(self.message_input)
        input_layout.addWidget(self.send_btn)
        input_group.setLayout(input_layout)
        layout.addWidget(input_group)

        self.statusBar().showMessage("Disconnected")

    def toggle_connection(self):
        if self.worker and self.worker.running:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        name = self.name_input.text().strip()
        if not name:
            self.chat_display.append("Please enter a username.")
            return

        host = self.host_input.text().strip()
        try:
            port = int(self.port_input.text().strip())
        except ValueError:
            self.chat_display.append("Invalid port number.")
            return

        self.worker = ClientWorker(host, port, name)
        self.worker.message_received.connect(self.on_message)
        self.worker.connected.connect(self.on_connected)
        self.worker.disconnected.connect(self.on_disconnected)
        self.worker.error_occurred.connect(self.on_error)
        self.worker.start()

        self.connect_btn.setText("Disconnect")
        self.host_input.setEnabled(False)
        self.port_input.setEnabled(False)
        self.name_input.setEnabled(False)
        self.statusBar().showMessage("Connecting...")

    def disconnect(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait(2000)
            self.worker = None
        self.on_disconnected()

    def send_message(self):
        text = self.message_input.text().strip()
        if text and self.worker and self.worker.running:
            self.worker.send_message(text)
            self.message_input.clear()

    def on_connected(self):
        self.send_btn.setEnabled(True)
        self.message_input.setEnabled(True)
        self.statusBar().showMessage("Connected")
        self.chat_display.append("Connected to server.")

    def on_disconnected(self):
        self.send_btn.setEnabled(False)
        self.message_input.setEnabled(False)
        self.connect_btn.setText("Connect")
        self.host_input.setEnabled(True)
        self.port_input.setEnabled(True)
        self.name_input.setEnabled(True)
        self.statusBar().showMessage("Disconnected")

    def on_message(self, message):
        self.chat_display.append(message)

    def on_error(self, error):
        self.chat_display.append(f"Error: {error}")
        self.disconnect()

    def closeEvent(self, event):
        if self.worker:
            self.worker.stop()
            self.worker.wait(2000)
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = ClientWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
