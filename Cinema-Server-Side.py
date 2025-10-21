#!/usr/bin/env python3
"""
cinema_server.py
Simple TCP JSON server for Cinema Ticket System.

Protocol:
- Client sends JSON objects terminated by newline '\n'.
- Server replies with a JSON object terminated by newline '\n'.
- Example request:
  {"action": "list_movies"}
  {"action": "sell", "movie_id": 1, "customer_name": "Ada", "number_of_tickets": 2}

Run:
    python cinema_server.py
"""

import sqlite3
import threading
import socket
import json
from datetime import datetime
from pathlib import Path
import traceback

HOST = "127.0.0.1"
PORT = 5000
DB_NAME = "cinema_server.db"
RECEIPT_DIR = Path("server_receipts")
RECEIPT_DIR.mkdir(exist_ok=True)


# ---- Database layer ----
def get_connection():
    return sqlite3.connect(DB_NAME, timeout=10, check_same_thread=False)


def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''
    CREATE TABLE IF NOT EXISTS movies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        cinema_room INTEGER,
        release_date TEXT,
        end_date TEXT,
        tickets_available INTEGER,
        ticket_price REAL
    )''')
    cur.execute('''
    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        movie_id INTEGER,
        customer_name TEXT,
        number_of_tickets INTEGER,
        total REAL,
        sale_time TEXT
    )''')
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM movies")
    if cur.fetchone()[0] == 0:
        sample = [
            ("The Matrix", 1, "2025-06-01", "2025-06-30", 100, 120.00),
            ("The One", 2, "2025-06-01", "2025-06-30", 100, 120.00),
            ("Mabiba", 3, "2025-06-01", "2025-06-30", 100, 180.00),
            ("Phoenix", 4, "2025-06-01", "2025-06-30", 100, 220.00),
            ("The Pump", 5, "2025-06-01", "2025-06-30", 100, 110.00),
        ]
        cur.executemany('''
            INSERT INTO movies (title, cinema_room, release_date, end_date, tickets_available, ticket_price)
            VALUES (?, ?, ?, ?, ?, ?)''', sample)
        conn.commit()
    conn.close()


# ---- Business logic handlers ----
def list_movies():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, title, cinema_room, release_date, end_date, tickets_available, ticket_price FROM movies")
    rows = cur.fetchall()
    conn.close()
    movies = []
    for r in rows:
        movies.append({
            "id": r[0],
            "title": r[1],
            "cinema_room": r[2],
            "release_date": r[3],
            "end_date": r[4],
            "tickets_available": r[5],
            "ticket_price": r[6]
        })
    return {"status": "ok", "movies": movies}


def add_movie(payload):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO movies (title, cinema_room, release_date, end_date, tickets_available, ticket_price)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (payload["title"], int(payload["cinema_room"]), payload.get("release_date", ""), payload.get("end_date", ""),
              int(payload["tickets_available"]), float(payload["ticket_price"])))
        conn.commit()
        conn.close()
        return {"status": "ok", "message": "Movie added"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def update_movie(payload):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('''
            UPDATE movies SET title=?, cinema_room=?, release_date=?, end_date=?, tickets_available=?, ticket_price=?
            WHERE id=?
        ''', (payload["title"], int(payload["cinema_room"]), payload.get("release_date",""), payload.get("end_date",""),
              int(payload["tickets_available"]), float(payload["ticket_price"]), int(payload["id"])))
        conn.commit()
        changed = cur.rowcount
        conn.close()
        if changed == 0:
            return {"status": "error", "message": "Movie id not found"}
        return {"status": "ok", "message": "Movie updated"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def delete_movie(payload):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM movies WHERE id=?", (int(payload["id"]),))
        conn.commit()
        changed = cur.rowcount
        conn.close()
        if changed == 0:
            return {"status": "error", "message": "Movie id not found"}
        return {"status": "ok", "message": "Movie deleted"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def sell_tickets(payload):
    try:
        movie_id = int(payload["movie_id"])
        name = payload["customer_name"]
        requested = int(payload["number_of_tickets"])
        if requested <= 0:
            return {"status": "error", "message": "Requested tickets must be > 0"}

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT tickets_available, ticket_price, title FROM movies WHERE id=?", (movie_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"status": "error", "message": "Movie not found"}
        available, price, title = row
        if requested > available:
            conn.close()
            return {"status": "error", "message": f"Not enough tickets (available {available})"}

        total = requested * price
        # insert sale
        cur.execute('''
            INSERT INTO sales (movie_id, customer_name, number_of_tickets, total, sale_time)
            VALUES (?, ?, ?, ?, ?)
        ''', (movie_id, name, requested, total, datetime.now().isoformat()))
        # decrement tickets
        cur.execute("UPDATE movies SET tickets_available = tickets_available - ? WHERE id=?", (requested, movie_id))
        conn.commit()
        conn.close()

        # create receipt file server-side
        receipt_name = RECEIPT_DIR / f"receipt_{datetime.now().strftime('%Y%m%d%H%M%S')}_{movie_id}.txt"
        with open(receipt_name, "w", encoding="utf-8") as f:
            f.write("CINEMA RECEIPT\n")
            f.write(f"Movie: {title}\n")
            f.write(f"Customer: {name}\n")
            f.write(f"Tickets: {requested}\n")
            f.write(f"Total: {total:.2f}\n")
            f.write(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        return {"status": "ok", "message": "Tickets sold", "sale": {"movie_id": movie_id, "title": title, "customer": name, "tickets": requested, "total": total}, "receipt": str(receipt_name)}
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


# ---- Request dispatcher ----
def handle_request(obj):
    action = obj.get("action")
    if action == "list_movies":
        return list_movies()
    if action == "add_movie":
        return add_movie(obj)
    if action == "update_movie":
        return update_movie(obj)
    if action == "delete_movie":
        return delete_movie(obj)
    if action == "sell":
        return sell_tickets(obj)
    return {"status": "error", "message": "Unknown action"}


# ---- Networking: JSON over TCP (newline-delimited) ----
def send_json(conn, obj):
    data = json.dumps(obj, ensure_ascii=False) + "\n"
    conn.sendall(data.encode("utf-8"))


def recv_json(conn):
    buffer = b""
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            if buffer:
                try:
                    return json.loads(buffer.decode("utf-8"))
                except:
                    return None
            return None
        buffer += chunk
        if b"\n" in buffer:
            line, rest = buffer.split(b"\n", 1)
            # Put rest back into a small internal buffer by using a socket-level hack is complicated.
            # For simplicity, handle single-request-per-connection model.
            try:
                return json.loads(line.decode("utf-8"))
            except:
                return None


def client_thread(conn, addr):
    try:
        req = recv_json(conn)
        if not req:
            send_json(conn, {"status": "error", "message": "Invalid or empty request"})
            return
        resp = handle_request(req)
        send_json(conn, resp)
    except Exception as e:
        traceback.print_exc()
        try:
            send_json(conn, {"status": "error", "message": str(e)})
        except:
            pass
    finally:
        try:
            conn.close()
        except:
            pass


def start_server():
    init_db()
    print(f"Server starting on {HOST}:{PORT} ...")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, PORT))
    s.listen(8)
    try:
        while True:
            conn, addr = s.accept()
            t = threading.Thread(target=client_thread, args=(conn, addr), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("Shutting down server.")
    finally:
        s.close()


if __name__ == "__main__":
    start_server()
