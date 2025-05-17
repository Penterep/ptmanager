import argparse
import json
import socket
import sys
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor

from ptlibs import ptjsonlib


class BurpSocketListener:
    def __init__(self, port, data_callback=None):
        print(f"Starting listener on port: {port}")
        self.data_callback = data_callback
        self.host = '127.0.0.1'  # Localhost
        self.port = port #56651
        self.server_socket = None
        self.client_connection = None
        self.client_address = None

        # Start the server socket
        self.start_server_socket()

        # Start the listening thread to accept connections
        self.listen_thread = threading.Thread(target=self.listen_for_client)
        self.listen_thread.start()

        self.data_callback = data_callback

    def start_server_socket(self):
        """Start the server socket to accept a single client."""
        while True:
            try:
                self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.server_socket.bind((self.host, self.port))
                self.server_socket.listen(1)  # Only accept one client
                print(f"Server listening on {self.host}:{self.port}")
                break
            except Exception as e:
                print(f"Bind failed: {e}")
                sys.exit(1)
                #continue

    def listen_for_client(self):
        """Listen for a client to connect and keep the connection open."""
        try:
            print("Waiting for client to connect...")
            # Zde bude server čekat na klienta, ale zůstane připojený.
            self.client_connection, self.client_address = self.server_socket.accept()
            print(f"Client connected from {self.client_address}")

            # Poslouchání pro data (při ztrátě spojení server čeká na nového klienta)
            self.listen_for_data()

        except Exception as e:
            print(f"Error accepting client connection: {e}")
            # Pokud dojde k chybě, server čeká na nové připojení

    def listen_for_data(self):
        """Listen for data from the connected client and print it."""
        while True:
            try:
                data = self.receive_full_data(self.client_connection)
                if data:
                    # Full data. Sends json to shared que
                    if self.data_callback:
                        self.data_callback(data)
                else:
                    print("Client disconnected, attempting to reconnect...")
                    self.client_connection.close()  # Zavře aktuální připojení
                    self.listen_for_client()  # Pokusí se o nové připojení
            except Exception as e:
                print(f"Error while receiving data: {e}")
                self.client_connection.close()
                self.listen_for_client()  # Pokusí se připojit znovu

    def receive_full_data(self, conn):
        buffer = ""
        delimiter = "__endS0ck3tMsg__"

        while True:
            chunk = conn.recv(1024).decode('utf-8')
            if not chunk:
                return None  # klient ukončil spojení

            buffer += chunk

            while delimiter in buffer:
                message, buffer = buffer.split(delimiter, 1)
                try:
                    return json.loads(message.strip())
                except json.JSONDecodeError as e:
                    print(f"[ERROR] Failed to parse JSON: {e}")
                    return None

    def send_data_to_client(self, data):
        """Send JSON data to the connected client (Burp plugin)."""
        if not self.client_connection:
            print("[WARN] No client connected. Cannot send data.")
            return

        try:
            message = json.dumps(data) + "__endS0ck3tMsg__"
            self.client_connection.sendall(message.encode('utf-8'))
            print("[INFO] Sent data to Burp plugin:", data)
        except Exception as e:
            print(f"[ERROR] Failed to send data to client: {e}")

def parse_args():
    parser = argparse.ArgumentParser(usage=f"burp_listener.py <options>")
    parser.add_argument("--port", type=int, required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    BurpSocketListener(port=args.port)
    while True:
        time.sleep(3)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nTerminated by user.")
        os._exit(1)