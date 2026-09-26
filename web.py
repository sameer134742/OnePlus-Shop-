from flask import Flask, render_template, request, jsonify, send_from_directory, session, redirect
import os, sqlite3, secrets, string, re, base64
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = "oneplus-super-secret-change-this-2026"
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024

BRAND_NAME = "OnePlus Store"
UPI_ID     = "rajakhan7017503559@okicici"
UPI_NAME   = "Raja Khan"
SUPPORT    = "@BT_TIGER23"
DB_PATH    = os.path.join(os.path.dirname(__file__), "shop.db")
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ADMIN_USER = "admin"
ADMIN_PASS = "admin123"

APPS = {
    "starplus":  {"name": "Star Plus",            "icon": "★",  "color": "#a855f7", "img": "app_starplus.png"},
    "oneplus":   {"name": "OnePlus",              "icon": "1+", "color": "#eb0028", "img": "app_oneplus.png"},
    "sixty9":    {"name": "SIXTY-9 Loader",       "icon": "6️⃣", "color": "#dc2626", "img": "app_sixty9.png"},
    "admin":     {"name": "OnePlus Admin Server", "icon": "⚙️", "color": "#22c55e", "img": "app_fanloader.png"},
}

PLANS = {
    "5hr":    {"name": "5 Hours", "price": 50,  "old_price": 99,   "days": "5h", "emoji": "⏱️"},
    "1day":   {"name": "1 Day",   "price": 99,  "old_price": 199,  "days": 1,  "emoji": "⚡"},
    "3day":   {"name": "3 Days",  "price": 299, "old_price": 499,  "days": 3,  "emoji": "🔥", "tag": "POPULAR"},
    "7day":   {"name": "7 Days",  "price": 599, "old_price": 999,  "days": 7,  "emoji": "💫"},
    "1month": {"name": "1 Month", "price": 799, "old_price": 1499, "days": 30, "emoji": "💎", "tag": "BEST VALUE"},
}


def db():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    con = db(); c = con.cursor()
    try:
        c.execute("SELECT user_token FROM orders LIMIT 1")
    except:
        c.execute("DROP TABLE IF EXISTS orders")
        c.execute("DROP TABLE IF EXISTS keys")
        con.commit()

    c.execute("""CREATE TABLE IF NOT EXISTS keys(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        app TEXT, plan TEXT, key TEXT UNIQUE,
        used INTEGER DEFAULT 0, added_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        app TEXT, plan TEXT, price INTEGER,
        name TEXT, contact TEXT, utr TEXT UNIQUE,
        screenshot TEXT, risk_score INTEGER DEFAULT 0,
        risk_reason TEXT, status TEXT DEFAULT 'pending',
        key_given TEXT, created_at TEXT, approved_at TEXT,
        user_token TEXT, referred_by TEXT)""")
    con.commit(); con.close()


def admin_required(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("admin"):
            return redirect("/admin/login")
        return f(*a, **k)
    return w


def calc_risk(utr, name, contact, screenshot):
    score = 0; reasons = []
    if utr:
        fake_utrs = ["1234567890","0000000000","1111111111","123456789012",
                     "test","fake","abc123","123456789","9999999999","2222222222"]
        if utr.lower() in fake_utrs:
            score += 60; reasons.append("Fake UTR pattern")
        if len(set(utr)) <= 2:
            score += 40; reasons.append("Same digits repeat")
        if len(utr) < 12:
            score += 25; reasons.append("UTR chhota")
    if name:
        if len(name) < 3: score += 20; reasons.append("Naam chhota")
        if re.search(r'[^a-zA-Z\s\.\-]', name): score += 15; reasons.append("Ajeeb chars")
        if re.search(r'(asdf|qwer|zxcv|hjkl|test|fake|abc)', name.lower()):
            score += 30; reasons.append("Fake naam")
    if contact:
        if len(contact) < 5: score += 20; reasons.append("Contact chhota")
    if not screenshot: score += 30; reasons.append("Screenshot missing")
    return min(score, 100), " | ".join(reasons)


@app.route("/")
def home():
    return render_template("index.html", apps=APPS, plans=PLANS,
        brand=BRAND_NAME, upi=UPI_ID, upi_name=UPI_NAME, support=SUPPORT)


@app.route("/static/<path:f>")
def static_files(f):
    return send_from_directory("static", f)


@app.route("/api/order", methods=["POST"])
def create_order():
    try:
        d = request.get_json() or {}
        app_key = (d.get("app") or "").strip().lower()
        plan_key = (d.get("plan") or "").strip().lower()
        name = (d.get("name") or "").strip()
        contact = (d.get("contact") or "").strip()
        utr = (d.get("utr") or "").strip()
        screenshot_data = d.get("screenshot") or ""
        referred_by = (d.get("referred_by") or "").strip()

        if app_key not in APPS: return jsonify({"ok": False, "error": "App select karo"}), 400
        if plan_key not in PLANS: return jsonify({"ok": False, "error": "Plan select karo"}), 400
        if len(name) < 2: return jsonify({"ok": False, "error": "Naam chhota"}), 400
        if len(contact) < 3: return jsonify({"ok": False, "error": "Contact bhejo"}), 400
        if len(utr) < 10 or len(utr) > 30 or not re.match(r'^[A-Za-z0-9]+$', utr):
            return jsonify({"ok": False, "error": "UTR invalid"}), 400
        if not screenshot_data: return jsonify({"ok": False, "error": "Screenshot upload karo"}), 400

        screenshot_filename = ""
        try:
            b64 = screenshot_data.split(",", 1)[1] if "," in screenshot_data else screenshot_data
            img_bytes = base64.b64decode(b64)
            if len(img_bytes) > 5 * 1024 * 1024:
                return jsonify({"ok": False, "error": "Image 5MB se badi"}), 400
            screenshot_filename = f"pay_{secrets.token_hex(8)}.png"
            with open(os.path.join(UPLOAD_DIR, screenshot_filename), "wb") as f:
                f.write(img_bytes)
        except Exception as ex:
            return jsonify({"ok": False, "error": "Screenshot fail"}), 400

        con = db(); c = con.cursor()
        c.execute("SELECT id FROM orders WHERE utr=?", (utr,))
        if c.fetchone():
            con.close()
            return jsonify({"ok": False, "error": "UTR already used"}), 400

        user_token = "U" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(10))

        score, reason = calc_risk(utr, name, contact, screenshot_filename)
        plan = PLANS[plan_key]
        c.execute("""INSERT INTO orders(app,plan,price,name,contact,utr,screenshot,
                     risk_score,risk_reason,status,created_at,user_token,referred_by)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (app_key, plan_key, plan["price"], name, contact, utr,
                   screenshot_filename, score, reason, "pending",
                   datetime.now().isoformat(), user_token, referred_by))
        oid = c.lastrowid
        con.commit(); con.close()
        return jsonify({"ok": True, "order_id": oid, "risk": score, "user_token": user_token})
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)}), 500


@app.route("/api/order-status/<int:oid>")
def order_status(oid):
    con = db(); c = con.cursor()
    c.execute("SELECT status, key_given FROM orders WHERE id=?", (oid,))
    row = c.fetchone(); con.close()
    if not row: return jsonify({"ok": False}), 404
    return jsonify({"ok": True, "status": row[0], "key": row[1]})


@app.route("/dashboard")
def dashboard():
    token = request.args.get("token", "")
    return render_template("dashboard.html", token=token,
        brand=BRAND_NAME, support=SUPPORT)


@app.route("/api/dashboard/<token>")
def api_dashboard(token):
    con = db(); c = con.cursor()
    c.execute("""SELECT id, app, plan, price, name, status, created_at, key_given
                 FROM orders WHERE user_token=? ORDER BY id DESC""", (token,))
    rows = c.fetchall()
    c.execute("""SELECT COUNT(*), SUM(price) FROM orders
                 WHERE user_token=? AND status='approved'""", (token,))
    stat = c.fetchone()
    total_orders = stat[0] or 0
    total_spent = stat[1] or 0
    c.execute("SELECT COUNT(*) FROM orders WHERE referred_by=?", (token,))
    referrals = c.fetchone()[0] or 0
    con.close()

    reward_progress = total_orders % 5
    rewards_earned = total_orders // 5
    next_reward_in = 5 - reward_progress if reward_progress > 0 else 5

    return jsonify({
        "ok": True,
        "orders": [
            {"id": r[0], "app": r[1], "plan": r[2], "price": r[3],
             "name": r[4], "status": r[5], "created_at": r[6], "key": r[7]}
            for r in rows
        ],
        "stats": {
            "total_orders": total_orders,
            "total_spent": total_spent,
            "referrals": referrals,
            "rewards_earned": rewards_earned,
            "reward_progress": reward_progress,
            "next_reward_in": next_reward_in
        }
    })


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("user") == ADMIN_USER and request.form.get("pass") == ADMIN_PASS:
            session["admin"] = True
            return redirect("/admin")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect("/admin/login")


@app.route("/admin")
@admin_required
def admin_panel():
    con = db(); c = con.cursor()
    c.execute("""SELECT id,app,plan,price,name,contact,utr,screenshot,risk_score,risk_reason,created_at
                 FROM orders WHERE status='pending' ORDER BY risk_score DESC, id DESC""")
    pending = c.fetchall()
    c.execute("""SELECT id,app,plan,name,contact,key_given,risk_score,approved_at
                 FROM orders WHERE status='approved' ORDER BY id DESC LIMIT 50""")
    approved = c.fetchall()
    c.execute("""SELECT id,app,plan,name,contact,risk_score FROM orders
                 WHERE status='rejected' ORDER BY id DESC LIMIT 30""")
    rejected = c.fetchall()
    c.execute("SELECT app,plan,COUNT(*) FROM keys WHERE used=0 GROUP BY app,plan")
    stock = {}
    for a, p, cnt in c.fetchall(): stock[f"{a}|{p}"] = cnt
    c.execute("SELECT COUNT(*) FROM orders WHERE status='approved'")
    total_sales = c.fetchone()[0]
    c.execute("SELECT SUM(price) FROM orders WHERE status='approved'")
    revenue = c.fetchone()[0] or 0
    con.close()
    return render_template("admin.html", pending=pending, approved=approved,
        rejected=rejected, stock=stock, apps=APPS, plans=PLANS,
        total_sales=total_sales, revenue=revenue)


@app.route("/admin/addkeys", methods=["POST"])
@admin_required
def admin_addkeys():
    try:
        data = request.get_json() or {}
        app_key = data.get("app","").strip()
        plan_key = data.get("plan","").strip()
        keys_text = data.get("keys","").strip()
        if app_key not in APPS or plan_key not in PLANS:
            return jsonify({"ok": False, "error": "Invalid"}), 400
        keys = [k.strip() for k in re.split(r'[\n,]+', keys_text) if k.strip()]
        if not keys: return jsonify({"ok": False, "error": "Keys daalo"}), 400
        con = db(); c = con.cursor(); added = 0; dup = 0
        for k in keys:
            try:
                c.execute("INSERT INTO keys(app,plan,key,used,added_at) VALUES(?,?,?,0,?)",
                          (app_key, plan_key, k, datetime.now().isoformat()))
                added += 1
            except sqlite3.IntegrityError:
                dup += 1
        con.commit(); con.close()
        return jsonify({"ok": True, "added": added, "duplicate": dup})
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)}), 500


@app.route("/admin/approve/<int:oid>", methods=["POST"])
@admin_required
def admin_approve(oid):
    try:
        con = db(); c = con.cursor()
        c.execute("SELECT app,plan,status FROM orders WHERE id=?", (oid,))
        row = c.fetchone()
        if not row: con.close(); return jsonify({"ok": False, "error": "Order nahi mila"}), 404
        if row[2] != "pending": con.close(); return jsonify({"ok": False, "error": "Already"}), 400
        app_key, plan_key = row[0], row[1]
        c.execute("SELECT id,key FROM keys WHERE app=? AND plan=? AND used=0 LIMIT 1", (app_key, plan_key))
        k = c.fetchone()
        if not k: con.close(); return jsonify({"ok": False, "error": "Stock khatam"}), 400
        key_id, key_text = k
        now = datetime.now().isoformat()
        c.execute("UPDATE keys SET used=1 WHERE id=?", (key_id,))
        c.execute("UPDATE orders SET status='approved', key_given=?, approved_at=? WHERE id=?",
                  (key_text, now, oid))
        con.commit(); con.close()
        return jsonify({"ok": True, "key": key_text})
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)}), 500


@app.route("/admin/reject/<int:oid>", methods=["POST"])
@admin_required
def admin_reject(oid):
    con = db(); c = con.cursor()
    c.execute("UPDATE orders SET status='rejected' WHERE id=?", (oid,))
    con.commit(); con.close()
    return jsonify({"ok": True})


@app.route("/admin/stock-list/<app_k>/<plan_k>")
@admin_required
def stock_list(app_k, plan_k):
    con = db(); c = con.cursor()
    c.execute("SELECT id,key,used FROM keys WHERE app=? AND plan=? ORDER BY id", (app_k, plan_k))
    rows = c.fetchall(); con.close()
    return jsonify({"ok": True, "keys": [{"id": r[0], "key": r[1], "used": r[2]} for r in rows]})


@app.route("/admin/delete-key/<int:kid>", methods=["POST"])
@admin_required
def admin_delete_key(kid):
    con = db(); c = con.cursor()
    c.execute("DELETE FROM keys WHERE id=?", (kid,))
    con.commit(); con.close()
    return jsonify({"ok": True})


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
