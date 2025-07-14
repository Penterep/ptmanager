import argparse
import json
import socket
import sys
import os
import time
import threading
import queue

from ptlibs import ptjsonlib

class BurpSocketListener:
    def __init__(self, daemon, config, port, data_callback=None):
        print(f"Starting listener on port: {port}")
        self.host = '127.0.0.1'  # Localhost
        self.port = port #56651
        self.server_socket = None
        self.client_connection = None
        self.client_address = None
        self.daemon = daemon
        self.config = config

        self.domain_guid_map = {}  # domain -> guid

        # Start the server socket
        self.start_server_socket()

        # Start the listening thread to accept connections
        self.listen_thread = threading.Thread(target=self.listen_for_client)
        self.listen_thread.start()

        self.data_callback = data_callback

        self.burpsuite_data_queue = queue.Queue()

        self.processing_thread = threading.Thread(target=self.process_incoming_burpsuite_data, daemon=True)
        self.processing_thread.start()

    def process_incoming_burpsuite_data(self):
        """Process incoming BurpSuite data in a dedicated thread."""
        while True:
            if not self.domain_guid_map:
                self.clear_burp_queue()
            else:
                self.process_burp_data()

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
                data = self.receive_full_data(self.client_connection) # receive from extension
                if data:
                    # Full data. Sends json to que
                    self.burpsuite_data_queue.put(data)
                    #if self.data_callback:
                        #self.data_callback(data)
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
            chunk = conn.recv(4096)
            if not chunk:
                return None  # klient ukončil spojení

            buffer += chunk.decode('utf-8')

            while delimiter in buffer:
                raw_message, buffer = buffer.split(delimiter, 1)
                message = raw_message.strip()

                try:
                    print("OK", message)
                    return json.loads(message)
                except json.JSONDecodeError as e:
                    #print(f"[ERROR] Failed to parse JSON: {e}", "MESSAGE:", message)
                    # Just a fragment, expecting more..
                    buffer = message + delimiter + buffer
                    break  # break out of inner while, recv more data

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

    def send_domain_to_burp_scope(self, domain):
        try:
            scope_data = {"action": "add_scope", "domain": domain}
            self.send_data_to_client(scope_data)
        except Exception as e:
            print(f"Error sending scope update to Burp: {e}")

    def clear_burp_queue(self):
        """Clear BurpSuite queue if domain_guid_map is empty."""
        while True:
            try:
                self.burpsuite_data_queue.get_nowait()
            except queue.Empty:
                break

    def process_burp_data(self):
        """Process BurpSuite data."""
        try:
            burp_data = self.burpsuite_data_queue.get_nowait()
            domain = burp_data.pop("domain", None)
            guid = self.domain_guid_map.get(domain)
            self.handle_burp_data_with_guid(burp_data, guid)
        except queue.Empty:
            pass

    def handle_burp_data_with_guid(self, data, guid):
        """Handle Burp data and forward it to the API."""
        data["satid"] = self.config.get_satid()
        data["guid"]  = guid

        time.sleep(1)

        response = self.daemon.send_to_api("result-proxy", data)

        try:
            res_data = response.json()
            if res_data.get("success"):
                self.send_data_to_client(res_data.get("data"))
        except:
            return

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