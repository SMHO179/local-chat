import socket
import threading

HOST = "127.0.0.1"
PORT = 5555

name = input("Username: ")

client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect((HOST, PORT))


def receive():
    while True:
        try:
            message = client.recv(1024).decode()

            if message == "NICK":
                client.send(name.encode())
            else:
                print(message)
        except:
            print("Disconnected.")
            client.close()
            break


def write():
    while True:
        text = input()
        message = f"{name}: {text}"
        client.send(message.encode())


threading.Thread(target=receive, daemon=True).start()
threading.Thread(target=write).start()
