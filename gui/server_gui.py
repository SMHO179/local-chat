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
    QListWidget,
    QSplitter,
    QGroupBox,
    QFormLayout,
    QStatusBar,
)


class ServerWorker(QThread):
    client_connected = pyqtSignal(str, str)
    client_disconnected = pyqtSignal(str)
    message_received = pyqtSignal(str)
    log_message = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, host: str, port: int):
        super().__init__()
        self.host = host
        self.port = port
        self.running = False
        self.server_socket = None
        self.clients = []
        self.names = []

    def run(self):
        self.running = True
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen()
            self.server_socket.settimeout(1.0)
            self.log_message.emit(f"Server listening on {self.host}:{self.port}")

            while self.running:
                try:
                    client, address = self.server_socket.accept()
                except socket.timeout:
                    continue

                try:
                    client.send(b"NICK")
                    name = client.recv(1024).decode()
                except Exception:
                    client.close()
                    continue

                self.clients.append(client)
                self.names.append(name)

                self.client_connected.emit(name, f"{address[0]}:{address[1]}")
                self.broadcast(f"[*] {name} joined the chat.".encode())

                thread = threading.Thread(target=self.handle, args=(client,), daemon=True)
                thread.start()

        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            self.cleanup()

    def handle(self, client):
        while self.running:
            try:
                message = client.recv(1024)
                if not message:
                    raise ConnectionError
                self.broadcast(message)
                self.message_received.emit(message.decode())
            except Exception:
                index = self.clients.index(client)
                self.clients.remove(client)
                name = self.names.pop(index)
                client.close()
                self.client_disconnected.emit(name)
                self.broadcast(f"[*] {name} left the chat.".encode())
                break

    def broadcast(self, message):
        for client in self.clients[:]:
            try:
                client.send(message)
            except Exception:
                pass

    def stop(self):
        self.running = False
        self.cleanup()

    def cleanup(self):
        for client in self.clients:
            try:
                client.close()
            except Exception:
                pass
        self.clients.clear()
        self.names.clear()
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None


class ServerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chat Server")
        self.setMinimumSize(700, 500)
        self.worker = None
        self.init_ui()

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        config_group = QGroupBox("Server Configuration")
        config_layout = QFormLayout()
        self.host_input = QLineEdit("127.0.0.1")
        self.port_input = QLineEdit("5555")
        self.start_btn = QPushButton("Start Server")
        self.start_btn.clicked.connect(self.toggle_server)
        config_layout.addRow("Host:", self.host_input)
        config_layout.addRow("Port:", self.port_input)
        config_layout.addRow(self.start_btn)
        config_group.setLayout(config_layout)
        layout.addWidget(config_group)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        clients_group = QGroupBox("Connected Clients")
        clients_layout = QVBoxLayout()
        self.client_list = QListWidget()
        clients_layout.addWidget(self.client_list)
        clients_group.setLayout(clients_layout)
        splitter.addWidget(clients_group)

        log_group = QGroupBox("Chat Log")
        log_layout = QVBoxLayout()
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        log_layout.addWidget(self.log_display)
        log_group.setLayout(log_layout)
        splitter.addWidget(log_group)

        splitter.setSizes([250, 450])
        layout.addWidget(splitter)

        self.statusBar().showMessage("Server stopped")

    def toggle_server(self):
        if self.worker and self.worker.running:
            self.stop_server()
        else:
            self.start_server()

    def start_server(self):
        host = self.host_input.text().strip()
        try:
            port = int(self.port_input.text().strip())
        except ValueError:
            self.log_display.append("Invalid port number.")
            return

        self.worker = ServerWorker(host, port)
        self.worker.log_message.connect(self.log_display.append)
        self.worker.error_occurred.connect(self.on_error)
        self.worker.client_connected.connect(self.on_client_connected)
        self.worker.client_disconnected.connect(self.on_client_disconnected)
        self.worker.message_received.connect(self.on_message)
        self.worker.start()

        self.start_btn.setText("Stop Server")
        self.host_input.setEnabled(False)
        self.port_input.setEnabled(False)
        self.statusBar().showMessage("Server running")

    def stop_server(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait(2000)
            self.worker = None
        self.client_list.clear()
        self.start_btn.setText("Start Server")
        self.host_input.setEnabled(True)
        self.port_input.setEnabled(True)
        self.statusBar().showMessage("Server stopped")
        self.log_display.append("Server stopped.")

    def on_client_connected(self, name, addr):
        self.client_list.addItem(f"{name} ({addr})")
        self.log_display.append(f"[+] {name} connected from {addr}")

    def on_client_disconnected(self, name):
        for i in range(self.client_list.count()):
            if name in self.client_list.item(i).text():
                self.client_list.takeItem(i)
                break
        self.log_display.append(f"[-] {name} disconnected")

    def on_message(self, message):
        self.log_display.append(message)

    def on_error(self, error):
        self.log_display.append(f"Error: {error}")
        self.stop_server()

    def closeEvent(self, event):
        if self.worker:
            self.worker.stop()
            self.worker.wait(2000)
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = ServerWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
