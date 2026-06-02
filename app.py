#!/usr/bin/env python3
from flask import Flask, request, jsonify
from flask_cors import CORS
import json, os, sqlite3
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

DB_PATH = os.environ.get("DB_PATH", "/data/crm_v5.db" if os.path.exists("/data") else os.path.join(os.path.dirname(os.path.abspath(__file__)), "crm_v5.db"))

PRICE_MAP = {
    "3 Bulan Rp920.000": {"harga": 920000, "bulan": 3},
    "6 Bulan Rp1.650.000": {"harga": 1650000, "bulan": 6},
    "12 Bulan Rp3.100.000": {"harga": 3100000, "bulan": 12},
}

def get_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nama TEXT, whatsapp TEXT, akun_telegram TEXT,
        jenis_paket TEXT, tanggal_mulai TEXT, tanggal_expired TEXT,
        status TEXT DEFAULT 'Aktif', harga INTEGER DEFAULT 0,
        status_pembayaran TEXT DEFAULT 'Lunas', bulan_custom INTEGER DEFAULT 0,
        synced INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS payment_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER, jenis_paket TEXT, harga INTEGER, bulan INTEGER,
        tanggal_mulai TEXT, tanggal_expired TEXT,
        status_pembayaran TEXT DEFAULT 'Lunas', tipe TEXT DEFAULT 'baru',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (member_id) REFERENCES members(id)
    )""")
    db.commit()
    return db

def calc_expired(tanggal_mulai_str, bulan):
    try:
        dt = datetime.strptime(tanggal_mulai_str, '%d/%m/%Y')
    except:
        try:
            dt = datetime.strptime(tanggal_mulai_str, '%Y-%m-%d')
        except:
            return ''
    month = dt.month + bulan
    year = dt.year + (month - 1) // 12
    month = ((month - 1) % 12) + 1
    max_days = [31, 29 if year % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    day = min(dt.day, max_days[month - 1])
    return datetime(year, month, day).strftime('%d/%m/%Y')

def format_date(d):
    try:
        return datetime.strptime(d, '%Y-%m-%d').strftime('%d/%m/%Y')
    except:
        return d

def parse_date(d):
    for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(d, fmt)
        except:
            continue
    return None

def member_row(r):
    return {"id": r[0], "nama": r[1], "whatsapp": r[2], "akun_telegram": r[3],
            "jenis_paket": r[4], "tanggal_mulai": r[5], "tanggal_expired": r[6],
            "status": r[7], "harga": r[8], "status_pembayaran": r[9]}

@app.route("/cgi-bin/api.py", methods=["GET","POST","OPTIONS"])
@app.route("/api", methods=["GET","POST","OPTIONS"])
def api():
    if request.method == "OPTIONS":
        return jsonify({}), 200

    action = request.args.get("action", "")
    db = get_db()

    # ─── ADD MEMBER ───
    if request.method == "POST" and action == "add":
        body = request.get_json(force=True)
        nama = body.get("nama", "").strip()
        wa = body.get("whatsapp", "").strip()
        tg = body.get("akun_telegram", "").strip()
        paket = body.get("jenis_paket", "")
        mulai = body.get("tanggal_mulai", "")
        status_bayar = body.get("status_pembayaran", "Lunas")

        if not nama or not tg:
            return jsonify({"error": "Nama dan Telegram wajib diisi"})

        if paket == "other":
            bulan = int(body.get("bulan_custom", 3))
            harga = int(body.get("harga_custom", 0))
            paket_label = f"{bulan} Bulan Rp{harga:,}".replace(",", ".")
        else:
            info = PRICE_MAP.get(paket, {"harga": 920000, "bulan": 3})
            harga = info["harga"]
            bulan = info["bulan"]
            paket_label = paket

        mulai_fmt = format_date(mulai)
        expired = calc_expired(mulai_fmt, bulan)

        db.execute("""INSERT INTO members (nama, whatsapp, akun_telegram, jenis_paket, tanggal_mulai, tanggal_expired, harga, status_pembayaran, bulan_custom)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                   [nama, wa, tg, paket_label, mulai_fmt, expired, harga, status_bayar, bulan if paket == "other" else 0])
        db.commit()
        mid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("""INSERT INTO payment_history (member_id, jenis_paket, harga, bulan, tanggal_mulai, tanggal_expired, status_pembayaran, tipe)
                      VALUES (?, ?, ?, ?, ?, ?, ?, 'baru')""",
                   [mid, paket_label, harga, bulan, mulai_fmt, expired, status_bayar])
        db.commit()
        count = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]
        row = db.execute("SELECT id, nama, whatsapp, akun_telegram, jenis_paket, tanggal_mulai, tanggal_expired, status, harga, status_pembayaran FROM members WHERE id = ?", [mid]).fetchone()
        return jsonify({"success": True, "total": count, "member": member_row(row)})

    # ─── UPDATE STATUS ───
    elif request.method == "POST" and action == "update_status":
        body = request.get_json(force=True)
        mid = body.get("id")
        new_status = body.get("status", "")
        if not mid or new_status not in ("Aktif", "Berhenti Berlangganan"):
            return jsonify({"error": "ID dan status valid diperlukan"})
        db.execute("UPDATE members SET status = ?, synced = 0 WHERE id = ?", [new_status, mid])
        db.commit()
        row = db.execute("SELECT id, nama, whatsapp, akun_telegram, jenis_paket, tanggal_mulai, tanggal_expired, status, harga, status_pembayaran FROM members WHERE id = ?", [mid]).fetchone()
        return jsonify({"success": True, "member": member_row(row)} if row else {"error": "Not found"})

    # ─── PERPANJANG ───
    elif request.method == "POST" and action == "perpanjang":
        body = request.get_json(force=True)
        mid = body.get("id")
        paket = body.get("jenis_paket", "")
        mulai_new = body.get("tanggal_mulai", "")
        status_bayar = body.get("status_pembayaran", "Lunas")

        if not mid:
            return jsonify({"error": "ID diperlukan"})
        old = db.execute("SELECT tanggal_expired FROM members WHERE id = ?", [mid]).fetchone()
        if not old:
            return jsonify({"error": "Member tidak ditemukan"})

        mulai_fmt = format_date(mulai_new) if mulai_new else old[0]

        if paket == "other":
            bulan = int(body.get("bulan_custom", 3))
            harga = int(body.get("harga_custom", 0))
            paket_label = f"{bulan} Bulan Rp{harga:,}".replace(",", ".")
        else:
            info = PRICE_MAP.get(paket, {"harga": 920000, "bulan": 3})
            harga = info["harga"]
            bulan = info["bulan"]
            paket_label = paket

        expired_new = calc_expired(mulai_fmt, bulan)
        db.execute("""UPDATE members SET jenis_paket = ?, tanggal_mulai = ?, tanggal_expired = ?,
                      harga = ?, status_pembayaran = ?, status = 'Aktif', synced = 0 WHERE id = ?""",
                   [paket_label, mulai_fmt, expired_new, harga, status_bayar, mid])
        db.execute("""INSERT INTO payment_history (member_id, jenis_paket, harga, bulan, tanggal_mulai, tanggal_expired, status_pembayaran, tipe)
                      VALUES (?, ?, ?, ?, ?, ?, ?, 'perpanjang')""",
                   [mid, paket_label, harga, bulan, mulai_fmt, expired_new, status_bayar])
        db.commit()
        row = db.execute("SELECT id, nama, whatsapp, akun_telegram, jenis_paket, tanggal_mulai, tanggal_expired, status, harga, status_pembayaran FROM members WHERE id = ?", [mid]).fetchone()
        return jsonify({"success": True, "member": member_row(row)})

    # ─── EDIT ───
    elif request.method == "POST" and action == "edit":
        body = request.get_json(force=True)
        mid = body.get("id")
        if not mid:
            return jsonify({"error": "ID diperlukan"})
        sets, vals = [], []
        for field in ["nama", "whatsapp", "akun_telegram", "status_pembayaran"]:
            if field in body:
                sets.append(f"{field} = ?")
                vals.append(body[field].strip() if isinstance(body[field], str) else body[field])
        if "jenis_paket" in body:
            paket = body["jenis_paket"]
            if paket == "other":
                bulan = int(body.get("bulan_custom", 3))
                harga = int(body.get("harga_custom", 0))
                paket_label = f"{bulan} Bulan Rp{harga:,}".replace(",", ".")
            else:
                info = PRICE_MAP.get(paket, {"harga": 920000, "bulan": 3})
                harga = info["harga"]
                bulan = info["bulan"]
                paket_label = paket
            sets += ["jenis_paket = ?", "harga = ?"]
            vals += [paket_label, harga]
        if "tanggal_mulai" in body:
            m = body["tanggal_mulai"]
            mulai_fmt = format_date(m) if "-" in m else m
            sets.append("tanggal_mulai = ?")
            vals.append(mulai_fmt)
        if "jenis_paket" in body or "tanggal_mulai" in body:
            cur = db.execute("SELECT jenis_paket, tanggal_mulai, harga FROM members WHERE id = ?", [mid]).fetchone()
            if cur:
                p = body.get("jenis_paket", cur[0])
                b = int(body.get("bulan_custom", 3)) if p == "other" else PRICE_MAP.get(p, {"bulan": 3})["bulan"]
                start = mulai_fmt if "tanggal_mulai" in body else cur[1]
                exp = calc_expired(start, b)
                sets.append("tanggal_expired = ?")
                vals.append(exp)
        if sets:
            vals.append(mid)
            db.execute(f"UPDATE members SET {', '.join(sets)}, synced = 0 WHERE id = ?", vals)
            db.commit()
        row = db.execute("SELECT id, nama, whatsapp, akun_telegram, jenis_paket, tanggal_mulai, tanggal_expired, status, harga, status_pembayaran FROM members WHERE id = ?", [mid]).fetchone()
        return jsonify({"success": True, "member": member_row(row)} if row else {"error": "Not found"})

    # ─── ALL MEMBERS ───
    elif action == "all":
        sf = request.args.get("status", "")
        search = request.args.get("search", "")
        sql = "SELECT id, nama, whatsapp, akun_telegram, jenis_paket, tanggal_mulai, tanggal_expired, status, harga, status_pembayaran FROM members"
        conds, qp = [], []
        if sf:
            conds.append("status = ?")
            qp.append(sf)
        if search:
            conds.append("(LOWER(nama) LIKE ? OR LOWER(akun_telegram) LIKE ?)")
            qp += [f"%{search.lower()}%", f"%{search.lower()}%"]
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY id"
        return jsonify([member_row(r) for r in db.execute(sql, qp).fetchall()])

    # ─── STATS ───
    elif action == "stats":
        rows = db.execute("SELECT tanggal_mulai, harga, tipe, status_pembayaran, bulan FROM payment_history ORDER BY id").fetchall()
        monthly = {}
        for r in rows:
            dt = parse_date(r[0])
            if not dt: continue
            key = dt.strftime('%Y-%m')
            if key not in monthly:
                monthly[key] = {"revenue": 0, "baru": 0, "perpanjang": 0, "belum_lunas": 0}
            if r[3] == "Lunas":
                monthly[key]["revenue"] += (r[1] or 0)
            else:
                monthly[key]["belum_lunas"] += 1
            if r[2] == "baru":
                monthly[key]["baru"] += 1
            else:
                monthly[key]["perpanjang"] += 1
        berhenti_count = db.execute("SELECT COUNT(*) FROM members WHERE status = 'Berhenti Berlangganan'").fetchone()[0]
        aktif_count = db.execute("SELECT COUNT(*) FROM members WHERE status = 'Aktif'").fetchone()[0]
        total_count = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]
        total_revenue = db.execute("SELECT COALESCE(SUM(harga),0) FROM payment_history WHERE status_pembayaran = 'Lunas'").fetchone()[0]
        total_belum = db.execute("SELECT COALESCE(SUM(harga),0) FROM payment_history WHERE status_pembayaran = 'Belum Lunas'").fetchone()[0]
        total_renewals = db.execute("SELECT COUNT(*) FROM payment_history WHERE tipe = 'perpanjang'").fetchone()[0]
        paket_dist = {}
        for r in db.execute("SELECT jenis_paket, COUNT(*), SUM(harga) FROM members WHERE status='Aktif' GROUP BY jenis_paket").fetchall():
            paket_dist[r[0]] = {"count": r[1], "revenue": r[2] or 0}
        return jsonify({
            "total_members": total_count, "aktif": aktif_count, "berhenti": berhenti_count,
            "total_revenue": total_revenue, "total_belum_lunas": total_belum,
            "total_renewals": total_renewals, "monthly": monthly, "paket_distribution": paket_dist
        })

    # ─── HISTORY ───
    elif action == "history":
        mid = request.args.get("id", "")
        if mid:
            rows = db.execute("""SELECT id, jenis_paket, harga, bulan, tanggal_mulai, tanggal_expired, status_pembayaran, tipe, created_at
                                 FROM payment_history WHERE member_id = ? ORDER BY id DESC""", [mid]).fetchall()
            return jsonify([{"id": r[0], "jenis_paket": r[1], "harga": r[2], "bulan": r[3],
                             "tanggal_mulai": r[4], "tanggal_expired": r[5], "status_pembayaran": r[6],
                             "tipe": r[7], "created_at": r[8]} for r in rows])
        return jsonify([])

    # ─── PENDING SYNC ───
    elif action == "pending":
        rows = db.execute("SELECT id, nama, whatsapp, akun_telegram, jenis_paket, tanggal_mulai, tanggal_expired, status, harga, status_pembayaran FROM members WHERE synced = 0 ORDER BY id").fetchall()
        return jsonify([member_row(r) for r in rows])

    # ─── MARK SYNCED ───
    elif action == "mark_synced":
        ids = request.args.get("ids", "")
        if ids:
            id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
            if id_list:
                ph = ",".join(["?"] * len(id_list))
                db.execute(f"UPDATE members SET synced = 1 WHERE id IN ({ph})", id_list)
                db.commit()
        return jsonify({"success": True})

    # ─── EXPIRING ───
    elif action == "expiring":
        today = datetime.now()
        results = {}
        for i in range(3):
            d = today + timedelta(days=i)
            ds = d.strftime('%d/%m/%Y')
            rows = db.execute("SELECT id, nama, whatsapp, akun_telegram, jenis_paket, tanggal_mulai, tanggal_expired, status, harga, status_pembayaran FROM members WHERE tanggal_expired = ? AND status = 'Aktif'", [ds]).fetchall()
            if rows:
                results[ds] = [member_row(r) for r in rows]
        return jsonify({"dates_checked": [(today + timedelta(days=i)).strftime('%d/%m/%Y') for i in range(3)], "expiring": results})

    # ─── DELETE LAST ───
    elif action == "delete_last":
        db.execute("DELETE FROM members WHERE id = (SELECT MAX(id) FROM members)")
        db.commit()
        count = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]
        return jsonify({"success": True, "total": count})

    # ─── CLEAR ───
    elif action == "clear":
        pin = request.args.get("pin", "")
        if pin == "2026":
            db.execute("DELETE FROM members")
            db.execute("DELETE FROM payment_history")
            db.execute("DELETE FROM sqlite_sequence WHERE name='members'")
            db.execute("DELETE FROM sqlite_sequence WHERE name='payment_history'")
            db.commit()
            return jsonify({"success": True, "message": "All data cleared"})
        return jsonify({"error": "Wrong PIN"})

    # ─── DEFAULT ───
    else:
        count = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]
        return jsonify({"status": "ok", "total_members": count})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
