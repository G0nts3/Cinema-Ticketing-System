import dearpygui.dearpygui as dpg
import socket
import json
import threading
import traceback
from pathlib import Path

HOST = "127.0.0.1"
PORT = 5000
TIMEOUT = 3  # seconds
RECEIPT_DIR = Path("client_receipts")
RECEIPT_DIR.mkdir(exist_ok=True)

# local cache
movies_cache = []

# ---- Networking helpers ----
def send_request(payload):
    """Send a JSON request and return parsed JSON response (or error dict)."""
    try:
        with socket.create_connection((HOST, PORT), timeout=TIMEOUT) as s:
            s.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            # receive until newline
            buffer = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buffer += chunk
                if b"\n" in buffer:
                    line, _ = buffer.split(b"\n", 1)
                    return json.loads(line.decode("utf-8"))
            if buffer:
                return json.loads(buffer.decode("utf-8"))
            return {"status": "error", "message": "No response"}
    except Exception as e:
        return {"status": "error", "message": f"Network error: {e}"}


# ---- UI actions ----
def refresh_movies():
    resp = send_request({"action": "list_movies"})
    if resp.get("status") == "ok":
        global movies_cache
        movies_cache = resp["movies"]
        combo_items = [f'{m["id"]}: {m["title"]} (avail {m["tickets_available"]})' for m in movies_cache]
        dpg.configure_item("movie_combo", items=combo_items)
        # refresh table rows
        dpg.delete_item("movies_table_rows", children_only=True)
        for m in movies_cache:
            row = dpg.add_table_row(parent="movies_table_rows")
            dpg.add_text(str(m["id"]), parent=row)
            dpg.add_text(m["title"], parent=row)
            dpg.add_text(str(m["cinema_room"]), parent=row)
            dpg.add_text(m["release_date"] or "", parent=row)
            dpg.add_text(m["end_date"] or "", parent=row)
            dpg.add_text(str(m["tickets_available"]), parent=row)
            dpg.add_text(f"{m['ticket_price']:.2f}", parent=row)
        dpg.set_value("status_text", "Movies refreshed.")
    else:
        dpg.set_value("status_text", f"Error: {resp.get('message')}")

def combo_changed(sender, app_data):
    if not app_data:
        return
    movie_id = int(app_data.split(":")[0])
    movie = next((m for m in movies_cache if m["id"] == movie_id), None)
    if movie:
        dpg.set_value("admin_title", movie["title"])
        dpg.set_value("admin_room", str(movie["cinema_room"]))
        dpg.set_value("admin_start", movie["release_date"] or "")
        dpg.set_value("admin_end", movie["end_date"] or "")
        dpg.set_value("admin_avail", str(movie["tickets_available"]))
        dpg.set_value("admin_price", f"{movie['ticket_price']:.2f}")

def buy_tickets():
    sel = dpg.get_value("movie_combo")
    if not sel:
        dpg.set_value("status_text", "Select a movie.")
        return
    try:
        movie_id = int(sel.split(":")[0])
        name = dpg.get_value("customer_name").strip()
        count = int(dpg.get_value("ticket_count"))
    except Exception:
        dpg.set_value("status_text", "Bad input.")
        return
    payload = {"action": "sell", "movie_id": movie_id, "customer_name": name, "number_of_tickets": count}
    resp = send_request(payload)
    if resp.get("status") == "ok":
        dpg.set_value("status_text", f"Success: {resp.get('message')}. Receipt saved on server: {resp.get('receipt')}")
        # Optionally save a small client-side copy of receipt
        sale = resp.get("sale")
        if sale:
            fn = RECEIPT_DIR / f"receipt_client_{movie_id}_{sale['tickets']}_{sale['customer'][:10]}.txt"
            with open(fn, "w", encoding="utf-8") as f:
                f.write("Client copy - receipt\n")
                f.write(str(sale))
        refresh_movies()
    else:
        dpg.set_value("status_text", f"Error: {resp.get('message')}")

def admin_add():
    try:
        payload = {
            "action": "add_movie",
            "title": dpg.get_value("admin_title").strip(),
            "cinema_room": int(dpg.get_value("admin_room")),
            "release_date": dpg.get_value("admin_start").strip(),
            "end_date": dpg.get_value("admin_end").strip(),
            "tickets_available": int(dpg.get_value("admin_avail")),
            "ticket_price": float(dpg.get_value("admin_price")),
        }
    except Exception:
        dpg.set_value("status_text", "Bad admin input.")
        return
    resp = send_request(payload)
    dpg.set_value("status_text", resp.get("message", "No response"))
    refresh_movies()

def admin_update():
    sel = dpg.get_value("movie_combo")
    if not sel:
        dpg.set_value("status_text", "Select a movie to update.")
        return
    try:
        payload = {
            "action": "update_movie",
            "id": int(sel.split(":")[0]),
            "title": dpg.get_value("admin_title").strip(),
            "cinema_room": int(dpg.get_value("admin_room")),
            "release_date": dpg.get_value("admin_start").strip(),
            "end_date": dpg.get_value("admin_end").strip(),
            "tickets_available": int(dpg.get_value("admin_avail")),
            "ticket_price": float(dpg.get_value("admin_price")),
        }
    except Exception:
        dpg.set_value("status_text", "Bad admin input.")
        return
    resp = send_request(payload)
    dpg.set_value("status_text", resp.get("message", "No response"))
    refresh_movies()

def admin_delete():
    sel = dpg.get_value("movie_combo")
    if not sel:
        dpg.set_value("status_text", "Select a movie to delete.")
        return
    payload = {"action": "delete_movie", "id": int(sel.split(":")[0])}
    resp = send_request(payload)
    dpg.set_value("status_text", resp.get("message", "No response"))
    refresh_movies()


# ---- GUI construction ----
def build_gui():
    dpg.create_context()
    dpg.create_viewport(title="Cinema Client (DearPyGui)", width=920, height=640)

    with dpg.window(label="Cinema Client", width=900, height=620):
        dpg.add_text("Cinema Ticket Client", bullet=False)
        dpg.add_separator()

        dpg.add_text("Select Movie:")
        dpg.add_combo(tag="movie_combo", items=[], width=480, callback=combo_changed)
        dpg.add_input_text(tag="customer_name", label="Customer Name", width=480)
        dpg.add_input_text(tag="ticket_count", label="Number of Tickets", default_value="1", width=200)
        dpg.add_button(label="Buy Tickets", callback=lambda s,a: buy_tickets(), width=160)
        dpg.add_spacing(count=1)
        dpg.add_text("", tag="status_text")

        dpg.add_separator()
        dpg.add_text("Available Movies:")
        with dpg.table(header_row=True, resizable=True, policy=dpg.mvTable_SizingStretchProp, width=880):
            dpg.add_table_column(label="ID", width=45)
            dpg.add_table_column(label="Title", width=200)
            dpg.add_table_column(label="Room", width=50)
            dpg.add_table_column(label="Start", width=100)
            dpg.add_table_column(label="End", width=100)
            dpg.add_table_column(label="Available", width=80)
            dpg.add_table_column(label="Price", width=75)
            with dpg.table_row(tag="movies_table_rows"):
                pass

        dpg.add_separator()
        dpg.add_text("Admin Panel")
        dpg.add_input_text(tag="admin_title", label="Title", width=480)
        dpg.add_input_text(tag="admin_room", label="Cinema Room (int)", width=200)
        dpg.add_input_text(tag="admin_start", label="Start Date (YYYY-MM-DD)", width=200)
        dpg.add_input_text(tag="admin_end", label="End Date (YYYY-MM-DD)", width=200)
        dpg.add_input_text(tag="admin_avail", label="Tickets Available (int)", width=200)
        dpg.add_input_text(tag="admin_price", label="Ticket Price (float)", width=200)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Add Movie", callback=lambda s,a: admin_add(), width=120)
            dpg.add_button(label="Update Movie", callback=lambda s,a: admin_update(), width=120)
            dpg.add_button(label="Delete Movie", callback=lambda s,a: admin_delete(), width=120)
            dpg.add_button(label="Refresh Movies", callback=lambda s,a: refresh_movies(), width=120)

        dpg.add_text(f"Client receipts folder: {RECEIPT_DIR.resolve()}")

    dpg.setup_dearpygui()
    dpg.show_viewport()
    # initial refresh (in background to avoid blocking GUI thread)
    threading.Thread(target=refresh_movies, daemon=True).start()
    dpg.start_dearpygui()
    dpg.destroy_context()


if __name__ == "__main__":
    try:
        build_gui()
    except Exception as e:
        print("GUI error:", e)
        traceback.print_exc()
