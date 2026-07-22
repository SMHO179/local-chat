import socket
import threading

HOST = "127.0.0.1"
PORT = 5555

clients = []
names = []


def broadcast(message):
    for client in clients:
        client.send(message)


def handle(client):
    while True:
        try:
            message = client.recv(1024)
            if not message:
                raise ConnectionError
            broadcast(message)
        except:
            index = clients.index(client)
            clients.remove(client)
            name = names.pop(index)
            client.close()
            broadcast(f"[*] {name} left the chat.".encode())
            break


server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((HOST, PORT))
server.listen()

print(f"Server listening on {HOST}:{PORT}")

while True:
    client, address = server.accept()

    client.send(b"NICK")
    name = client.recv(1024).decode()

    clients.append(client)
    names.append(name)

    print(f"{name} connected from {address}")

    broadcast(f"[*] {name} joined the chat.".encode())

    thread = threading.Thread(target=handle, args=(client,))
    thread.start()
