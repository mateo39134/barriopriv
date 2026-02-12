from flask import Flask, render_template, jsonify, request
from flask import Flask, render_template, jsonify, request, session, redirect, url_for
import sqlite3
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, messaging
import os
import json

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = "tu_clave_secreta_123"  # Necesaria para guardar el lote en sesión

# Firebase - usa variable de entorno en Render, archivo local en tu PC
if os.getenv("FIREBASE_CREDENTIALS"):
    cred_dict = json.loads(os.getenv("FIREBASE_CREDENTIALS"))
    cred = credentials.Certificate(cred_dict)
else:
    cred = credentials.Certificate("barrioseguro-dca9a-firebase-adminsdk-fbsvc-7e07d9aae4.json")

firebase_admin.initialize_app(cred)

DB = "eventos.db"

def conectar_db():
    return sqlite3.connect(DB)

def inicializar_db():
    con = conectar_db()
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS lotes (
        lote INTEGER PRIMARY KEY,
        estado TEXT DEFAULT 'NORMAL'
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS eventos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lote INTEGER,
        tipo TEXT,
        fecha_hora TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS fcm_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token TEXT UNIQUE NOT NULL,
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    for i in range(1, 69):
        cur.execute("INSERT OR IGNORE INTO lotes (lote) VALUES (?)", (i,))

    con.commit()
    con.close()

inicializar_db()

def enviar_push(titulo, cuerpo):
    con = conectar_db()
    cur = con.cursor()
    cur.execute("SELECT token FROM fcm_tokens")
    tokens = [row[0] for row in cur.fetchall()]
    con.close()

    if not tokens:
        print("No hay tokens para push")
        return

    message = messaging.MulticastMessage(
        notification=messaging.Notification(
            title=titulo,
            body=cuerpo
        ),
        tokens=tokens
    )

    try:
        response = messaging.send_multicast(message)
        print(f"Push enviado: {response.success_count} ok, {response.failure_count} fallos")
    except Exception as e:
        print("Error al enviar push:", e)

@app.route("/")
def menu_principal():
    return render_template("index.html")

@app.route("/guardia", methods=["GET", "POST"])
def guardia():
    if request.method == "POST":
        password = request.form.get("password")
        if password == "guardia123":  # ← CAMBIA ESTA CONTRASEÑA
            return render_template("mapa.html")
        else:
            return render_template("login.html", error="Contraseña incorrecta")

    return render_template("login.html", error="")

@app.route("/vecinos", methods=["GET", "POST"])
def vecinos():
    # Si ya tiene lote en sesión, entra directo
    if 'mi_lote' in session:
        return render_template("sistema2.html", mi_lote=session['mi_lote'])

    # Si es POST (envió el formulario), valida el lote
    if request.method == "POST":
        mi_lote = request.form.get("mi_lote")
        try:
            mi_lote = int(mi_lote)
            if 1 <= mi_lote <= 68:
                session['mi_lote'] = mi_lote
                return render_template("sistema2.html", mi_lote=mi_lote)
            else:
                return render_template("lote_login.html", error="Lote inválido (1-68)")
        except ValueError:
            return render_template("lote_login.html", error="Ingresa un número válido")

    # Si no tiene lote, muestra la pantalla de login
    return render_template("lote_login.html", error="")

@app.route("/estado")
def estado():
    con = conectar_db()
    cur = con.cursor()
    cur.execute("SELECT lote, estado FROM lotes")
    datos = {l: e for l, e in cur.fetchall()}
    con.close()
    return jsonify(datos)

@app.route("/alarma/<int:lote>", methods=["POST"])
def disparar_alarma(lote):
    con = conectar_db()
    cur = con.cursor()
    cur.execute("SELECT estado FROM lotes WHERE lote=?", (lote,))
    estado = cur.fetchone()[0]

    if estado == "NORMAL":
        cur.execute("UPDATE lotes SET estado='ALARMA' WHERE lote=?", (lote,))
        desde = f" (desde lote {session.get('mi_lote', 'desconocido')})" if 'mi_lote' in session else ""
        cur.execute("INSERT INTO eventos (lote, tipo, fecha_hora) VALUES (?, ?, ?)",
                    (lote, f"ALARMA_DISPARADA{desde}", datetime.now().isoformat()))
        con.commit()
        enviar_push("🚨 Alarma activada", f"Lote {lote} en peligro{desde}")

    con.close()
    return "OK"

@app.route("/reset/<int:lote>", methods=["POST"])
def reset_lote(lote):
    con = conectar_db()
    cur = con.cursor()
    cur.execute("UPDATE lotes SET estado='NORMAL' WHERE lote=?", (lote,))
    cur.execute("INSERT INTO eventos (lote, tipo, fecha_hora) VALUES (?, ?, ?)",
                (lote, "RESET_MANUAL", datetime.now().isoformat()))
    con.commit()
    enviar_push("✅ Alarma verificada", f"Lote {lote} ya está seguro")
    con.close()
    return "OK"

@app.route("/eventos")
def ver_eventos():
    con = conectar_db()
    cur = con.cursor()
    cur.execute("SELECT lote, tipo, fecha_hora FROM eventos ORDER BY id DESC LIMIT 20")
    datos = cur.fetchall()
    con.close()
    return jsonify(datos)

@app.route("/guardar-token", methods=["POST"])
def guardar_token():
    data = request.json
    token = data.get("token")
    if not token:
        return jsonify({"error": "No token"}), 400

    con = conectar_db()
    cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO fcm_tokens (token) VALUES (?)", (token,))
    con.commit()
    con.close()
    return jsonify({"ok": True})

@app.route("/mensaje", methods=["POST"])
def mensaje():
    data = request.json
    lote = data.get("lote")
    texto = data.get("texto")
    if not lote or not texto:
        return jsonify({"error": "Faltan datos"}), 400

    desde = f" (desde lote {session.get('mi_lote', 'desconocido')})" if 'mi_lote' in session else ""
    texto_completo = texto + desde
    con = conectar_db()
    cur = con.cursor()
    cur.execute("INSERT INTO eventos (lote, tipo, fecha_hora) VALUES (?, ?, ?)",
                (lote, f"REPORTE_VECINO: {texto_completo}", datetime.now().isoformat()))
    con.commit()
    con.close()
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
