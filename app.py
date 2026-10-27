"""
Telegram Last Seen Bulk Checker (local web tool)
Run:  python app.py   ->  http://127.0.0.1:5000
"""
import asyncio, json, os, random, threading, time, uuid
from flask import Flask, Response, jsonify, render_template, request
from telethon import TelegramClient, errors, types
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE, "config.json")
SESSION_FILE = os.path.join(BASE, "tg_session")

app = Flask(__name__)

# ---- password protection (REQUIRED when public) ----
APP_USER = os.environ.get("APP_USER", "admin")
APP_PASSWORD = os.environ.get("APP_PASSWORD")  # set this on the server!

@app.before_request
def require_login():
    if not APP_PASSWORD:
        return  # local use only
    a = request.authorization
    if not a or a.username != APP_USER or a.password != APP_PASSWORD:
        return Response("Login required", 401, {"WWW-Authenticate": 'Basic realm="TG Checker"'})

# ---- background asyncio loop (Telethon needs one) ----
loop = asyncio.new_event_loop()
threading.Thread(target=loop.run_forever, daemon=True).start()

def run(coro, timeout=None):
    return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout)

client = None
login_state = {"phone": None, "hash": None}
jobs = {}

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}

async def get_client():
    global client
    cfg = load_config()
    if not cfg.get("api_id"):
        return None
    if client is None:
        client = TelegramClient(SESSION_FILE, int(cfg["api_id"]), cfg["api_hash"])
    if not client.is_connected():
        await client.connect()
    return client

def status_label(status):
    if isinstance(status, types.UserStatusOnline):
        return "online", "Online now"
    if isinstance(status, types.UserStatusOffline):
        w = status.was_online.strftime("%Y-%m-%d %H:%M UTC")
        age = time.time() - status.was_online.timestamp()
        bucket = "recently" if age < 3 * 86400 else "week" if age < 8 * 86400 else "month" if age < 32 * 86400 else "long"
        return bucket, f"Exact: {w}"
    if isinstance(status, types.UserStatusRecently):
        return "recently", "Recently (last ~3 days)"
    if isinstance(status, types.UserStatusLastWeek):
        return "week", "Within a week"
    if isinstance(status, types.UserStatusLastMonth):
        return "month", "Within a month"
    return "long", "Long time ago / hidden"

async def lookup(c, item):
    item = item.strip()
    is_phone = item.startswith("+") or (item.replace(" ", "").isdigit() and len(item) >= 7)
    if is_phone:
        phone = "+" + "".join(ch for ch in item if ch.isdigit())
        res = await c(ImportContactsRequest([types.InputPhoneContact(0, phone, "tmp", "")]))
        if not res.users:
            return None
        user = res.users[0]
        try:
            await c(DeleteContactsRequest([user]))  # remove temp contact again
        except Exception:
            pass
        return user
    name = item.replace("https://t.me/", "").replace("t.me/", "").lstrip("@")
    ent = await c.get_entity(name)
    return ent if isinstance(ent, types.User) else None

async def job_worker(job_id, items, min_d, max_d):
    job = jobs[job_id]
    c = await get_client()
    for i, item in enumerate(items):
        if job["cancel"]:
            break
        row = {"input": item, "name": "", "username": "", "bucket": "error", "label": ""}
        try:
            user = await lookup(c, item)
            if user is None:
                row["label"] = "Not found / not a user"
            else:
                row["name"] = " ".join(filter(None, [user.first_name, user.last_name]))
                row["username"] = user.username or ""
                if user.bot:
                    row["bucket"], row["label"] = "bot", "Bot"
                else:
                    row["bucket"], row["label"] = status_label(user.status)
        except errors.FloodWaitError as e:
            if e.seconds <= 120:
                await asyncio.sleep(e.seconds + 1)
                items.insert(i + 1, item)  # retry this one
                row["label"] = f"Flood wait {e.seconds}s, retrying"
            else:
                row["label"] = f"Flood wait {e.seconds}s - stopped"
                job["results"].append(row)
                job["error"] = f"Telegram asked to wait {e.seconds}s. Try again later with a smaller list."
                break
        except (errors.UsernameNotOccupiedError, errors.UsernameInvalidError, ValueError):
            row["label"] = "Not found"
        except Exception as e:
            row["label"] = f"Error: {type(e).__name__}"
        job["results"].append(row)
        job["done"] = len(job["results"])
        await asyncio.sleep(random.uniform(min_d, max_d))
    job["finished"] = True

# ---------------- routes ----------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/state")
def state():
    cfg = load_config()
    async def _s():
        c = await get_client()
        return bool(c and await c.is_user_authorized())
    return jsonify(has_config=bool(cfg.get("api_id")), authorized=run(_s()) if cfg.get("api_id") else False)

@app.route("/api/config", methods=["POST"])
def config():
    global client
    d = request.json
    with open(CONFIG_FILE, "w") as f:
        json.dump({"api_id": str(d["api_id"]).strip(), "api_hash": d["api_hash"].strip()}, f)
    client = None
    return jsonify(ok=True)

@app.route("/api/send_code", methods=["POST"])
def send_code():
    phone = request.json["phone"].strip()
    async def _s():
        c = await get_client()
        r = await c.send_code_request(phone)
        login_state.update(phone=phone, hash=r.phone_code_hash)
    try:
        run(_s())
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400

@app.route("/api/verify", methods=["POST"])
def verify():
    d = request.json
    async def _v():
        c = await get_client()
        try:
            await c.sign_in(login_state["phone"], d["code"].strip(), phone_code_hash=login_state["hash"])
        except errors.SessionPasswordNeededError:
            if not d.get("password"):
                return "need_password"
            await c.sign_in(password=d["password"])
        return "ok"
    try:
        r = run(_v())
        return jsonify(ok=r == "ok", need_password=r == "need_password")
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400

@app.route("/api/logout", methods=["POST"])
def logout():
    global client
    async def _l():
        c = await get_client()
        if c:
            await c.log_out()
    try:
        run(_l())
    except Exception:
        pass
    client = None
    return jsonify(ok=True)

@app.route("/api/check", methods=["POST"])
def check():
    d = request.json
    items = [x.strip() for x in d["items"] if x.strip()][:500]
    if not items:
        return jsonify(ok=False, error="List is empty"), 400
    job_id = uuid.uuid4().hex[:8]
    jobs[job_id] = {"results": [], "done": 0, "total": len(items), "finished": False, "cancel": False, "error": None}
    min_d = max(1.0, float(d.get("delay", 2)))
    asyncio.run_coroutine_threadsafe(job_worker(job_id, items, min_d, min_d + 1.5), loop)
    return jsonify(ok=True, job=job_id)

@app.route("/api/job/<job_id>")
def job(job_id):
    j = jobs.get(job_id)
    return jsonify(j) if j else (jsonify(error="no such job"), 404)

@app.route("/api/cancel/<job_id>", methods=["POST"])
def cancel(job_id):
    if job_id in jobs:
        jobs[job_id]["cancel"] = True
    return jsonify(ok=True)

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)), debug=False)
