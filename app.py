"""
Smart Quiz System — Flask Backend (app.py)
All score calculations & answer validation happen server-side only.
"""

import os, json, csv, io
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv

import pymysql
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, jsonify, flash, Response
)
from flask_bcrypt import Bcrypt
from flask_wtf.csrf import CSRFProtect

load_dotenv()

app = Flask(__name__)
app.secret_key        = os.getenv("SECRET_KEY", "change-me-in-production")
app.config["WTF_CSRF_TIME_LIMIT"] = None      # session-bound tokens
bcrypt = Bcrypt(app)
csrf   = CSRFProtect(app)

# ──────────────────────────────────────────
#  DB helper
# ──────────────────────────────────────────
def get_db():
    return pymysql.connect(
        host     = os.getenv("DB_HOST",     "localhost"),
        user     = os.getenv("DB_USER",     "root"),
        password = os.getenv("DB_PASSWORD", ""),
        database = os.getenv("DB_NAME",     "quiz_system"),
        cursorclass = pymysql.cursors.DictCursor,
        autocommit  = True,
    )

def query(sql, args=(), one=False, commit=False):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(sql, args)
            if commit:
                db.commit()
                return cur.lastrowid
            return cur.fetchone() if one else cur.fetchall()
    finally:
        db.close()

# ──────────────────────────────────────────
#  Auth decorators
# ──────────────────────────────────────────
def admin_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if not session.get("admin_id"):
            flash("Admin login required.", "danger")
            return redirect(url_for("admin_login"))
        return f(*a, **kw)
    return dec

def participant_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if not session.get("participant_id"):
            flash("Please log in first.", "warning")
            return redirect(url_for("participant_login"))
        return f(*a, **kw)
    return dec

# ──────────────────────────────────────────
#  Utility
# ──────────────────────────────────────────
def get_quiz_settings():
    return query("SELECT * FROM quiz_settings ORDER BY id LIMIT 1", one=True)

def quiz_is_open(settings=None):
    s = settings or get_quiz_settings()
    if not s or not s["is_active"]:
        return False
    now = datetime.now()
    if s["start_time"] and now < s["start_time"]:
        return False
    if s["end_time"] and now > s["end_time"]:
        return False
    return True

# ──────────────────────────────────────────
#  PUBLIC — Landing
# ──────────────────────────────────────────
@app.route("/")
def landing():
    settings = get_quiz_settings()
    return render_template("landing.html", quiz_open=quiz_is_open(settings), settings=settings)

# ──────────────────────────────────────────
#  ADMIN — Login / Logout
# ──────────────────────────────────────────
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_id"):
        return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        admin    = query("SELECT * FROM admin WHERE email=%s", (email,), one=True)
        if admin and bcrypt.check_password_hash(admin["password_hash"], password):
            session["admin_id"]    = admin["id"]
            session["admin_email"] = admin["email"]
            flash("Welcome back!", "success")
            return redirect(url_for("admin_dashboard"))
        flash("Invalid credentials.", "danger")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_id", None)
    session.pop("admin_email", None)
    return redirect(url_for("admin_login"))

# ──────────────────────────────────────────
#  ADMIN — Dashboard
# ──────────────────────────────────────────
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    settings       = get_quiz_settings()
    total_q        = query("SELECT COUNT(*) AS c FROM questions WHERE is_active=1", one=True)["c"]
    total_p        = query("SELECT COUNT(*) AS c FROM participants",                one=True)["c"]
    total_attempts = query("SELECT COUNT(*) AS c FROM submissions",                 one=True)["c"]
    total_viol     = query("SELECT SUM(violation_count) AS c FROM violations",      one=True)["c"] or 0
    recent_subs    = query(
        "SELECT s.*, p.name, p.register_no FROM submissions s "
        "JOIN participants p ON p.id=s.participant_id "
        "ORDER BY s.submitted_at DESC LIMIT 10"
    )
    return render_template("admin_dashboard.html",
        settings=settings, total_q=total_q, total_p=total_p,
        total_attempts=total_attempts, total_viol=total_viol,
        recent_subs=recent_subs, quiz_open=quiz_is_open(settings)
    )

# ──────────────────────────────────────────
#  ADMIN — Quiz Settings
# ──────────────────────────────────────────
@app.route("/admin/settings", methods=["POST"])
@admin_required
def admin_save_settings():
    duration   = int(request.form.get("duration", 30))
    is_active  = 1 if request.form.get("is_active") else 0
    start_time = request.form.get("start_time") or None
    end_time   = request.form.get("end_time")   or None
    max_viol   = int(request.form.get("max_violations", 3))
    query(
        "UPDATE quiz_settings SET duration_minutes=%s, is_active=%s, "
        "start_time=%s, end_time=%s, max_violations=%s WHERE id=1",
        (duration, is_active, start_time, end_time, max_viol), commit=True
    )
    flash("Quiz settings updated.", "success")
    return redirect(url_for("admin_dashboard"))

# ──────────────────────────────────────────
#  ADMIN — Questions
# ──────────────────────────────────────────
@app.route("/admin/questions")
@admin_required
def admin_questions():
    questions = query("SELECT * FROM questions ORDER BY id DESC")
    return render_template("admin_questions.html", questions=questions)

@app.route("/admin/questions/add", methods=["GET", "POST"])
@admin_required
def admin_add_question():
    if request.method == "POST":
        q   = request.form.get("question_text", "").strip()
        a   = request.form.get("option_a", "").strip()
        b   = request.form.get("option_b", "").strip()
        c   = request.form.get("option_c", "").strip()
        d   = request.form.get("option_d", "").strip()
        ans = request.form.get("correct_answer", "A")
        mrk = int(request.form.get("marks", 1))
        if not all([q, a, b, c, d]):
            flash("All fields are required.", "danger")
            return redirect(request.url)
        query(
            "INSERT INTO questions (question_text,option_a,option_b,option_c,option_d,correct_answer,marks)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (q, a, b, c, d, ans, mrk), commit=True
        )
        flash("Question added.", "success")
        return redirect(url_for("admin_questions"))
    return render_template("admin_add_question.html", question=None)

@app.route("/admin/questions/<int:qid>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_question(qid):
    question = query("SELECT * FROM questions WHERE id=%s", (qid,), one=True)
    if not question:
        flash("Question not found.", "danger")
        return redirect(url_for("admin_questions"))
    if request.method == "POST":
        q   = request.form.get("question_text", "").strip()
        a   = request.form.get("option_a", "").strip()
        b   = request.form.get("option_b", "").strip()
        c   = request.form.get("option_c", "").strip()
        d   = request.form.get("option_d", "").strip()
        ans = request.form.get("correct_answer", "A")
        mrk = int(request.form.get("marks", 1))
        query(
            "UPDATE questions SET question_text=%s,option_a=%s,option_b=%s,"
            "option_c=%s,option_d=%s,correct_answer=%s,marks=%s WHERE id=%s",
            (q, a, b, c, d, ans, mrk, qid), commit=True
        )
        flash("Question updated.", "success")
        return redirect(url_for("admin_questions"))
    return render_template("admin_add_question.html", question=question)

@app.route("/admin/questions/<int:qid>/delete", methods=["POST"])
@admin_required
def admin_delete_question(qid):
    query("UPDATE questions SET is_active=0 WHERE id=%s", (qid,), commit=True)
    flash("Question deleted.", "info")
    return redirect(url_for("admin_questions"))

# ──────────────────────────────────────────
#  ADMIN — Participants
# ──────────────────────────────────────────
@app.route("/admin/participants")
@admin_required
def admin_participants():
    participants = query(
        "SELECT p.*, s.score, s.total_marks, s.submitted_at, s.auto_submitted, "
        "v.violation_count "
        "FROM participants p "
        "LEFT JOIN submissions s ON s.participant_id=p.id "
        "LEFT JOIN violations  v ON v.participant_id=p.id "
        "ORDER BY p.id DESC"
    )
    return render_template("admin_participants.html", participants=participants)

# ──────────────────────────────────────────
#  ADMIN — Violations
# ──────────────────────────────────────────
@app.route("/admin/violations")
@admin_required
def admin_violations():
    violations = query(
        "SELECT v.*, p.name, p.register_no FROM violations v "
        "JOIN participants p ON p.id=v.participant_id "
        "ORDER BY v.timestamp DESC"
    )
    return render_template("admin_violations.html", violations=violations)

# ──────────────────────────────────────────
#  ADMIN — Leaderboard
# ──────────────────────────────────────────
@app.route("/admin/leaderboard")
@admin_required
def admin_leaderboard():
    board = query(
        "SELECT p.name, p.register_no, s.score, s.total_marks, s.time_taken, "
        "s.auto_submitted, s.submitted_at, "
        "COALESCE(v.violation_count, 0) AS violations "
        "FROM submissions s "
        "JOIN participants p ON p.id = s.participant_id "
        "LEFT JOIN violations v ON v.participant_id = s.participant_id "
        "ORDER BY s.score DESC, s.time_taken ASC"
    )
    return render_template("admin_leaderboard.html", board=board)

# ──────────────────────────────────────────
#  ADMIN — Export CSV
# ──────────────────────────────────────────
@app.route("/admin/export/csv")
@admin_required
def admin_export_csv():
    rows = query(
        "SELECT p.name, p.register_no, p.email, s.score, s.total_marks, "
        "s.time_taken, s.auto_submitted, s.submitted_at, "
        "COALESCE(v.violation_count,0) AS violations "
        "FROM submissions s "
        "JOIN participants p ON p.id=s.participant_id "
        "LEFT JOIN violations v ON v.participant_id=s.participant_id "
        "ORDER BY s.score DESC"
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name","Register No","Email","Score","Total","Time(s)",
                     "Auto-Submitted","Submitted At","Violations"])
    for r in rows:
        writer.writerow([r["name"], r["register_no"], r["email"], r["score"],
                         r["total_marks"], r["time_taken"], r["auto_submitted"],
                         r["submitted_at"], r["violations"]])
    output.seek(0)
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=quiz_results.csv"}
    )

# ──────────────────────────────────────────
#  PARTICIPANT — Login / Register
# ──────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def participant_login():
    if session.get("participant_id"):
        return redirect(url_for("quiz_page"))
    if request.method == "POST":
        name    = request.form.get("name", "").strip()
        reg_no  = request.form.get("register_no", "").strip()
        email   = request.form.get("email", "").strip().lower()
        if not all([name, reg_no, email]):
            flash("All fields are required.", "danger")
            return redirect(request.url)

        # Check quiz is open
        if not quiz_is_open():
            flash("Quiz is not active right now.", "warning")
            return redirect(url_for("landing"))

        # Get or create participant
        p = query("SELECT * FROM participants WHERE register_no=%s OR email=%s",
                  (reg_no, email), one=True)
        if p:
            if p["attempt_status"] == "completed":
                flash("You have already completed this quiz. Only one attempt is allowed.", "danger")
                return redirect(url_for("participant_login"))
        else:
            pid = query(
                "INSERT INTO participants (name, register_no, email) VALUES (%s,%s,%s)",
                (name, reg_no, email), commit=True
            )
            p = query("SELECT * FROM participants WHERE id=%s", (pid,), one=True)

        # Mark in_progress
        query("UPDATE participants SET attempt_status='in_progress', quiz_start_time=NOW()"
              " WHERE id=%s", (p["id"],), commit=True)
        session["participant_id"]   = p["id"]
        session["participant_name"] = p["name"]
        session["quiz_start_ts"]    = datetime.now().timestamp()
        return redirect(url_for("quiz_page"))
    return render_template("participant_login.html", quiz_open=quiz_is_open())

@app.route("/logout")
def participant_logout():
    session.pop("participant_id", None)
    session.pop("participant_name", None)
    session.pop("quiz_start_ts", None)
    return redirect(url_for("landing"))

# ──────────────────────────────────────────
#  PARTICIPANT — Quiz Page
# ──────────────────────────────────────────
@app.route("/quiz")
@participant_required
def quiz_page():
    # Already submitted?
    p = query("SELECT * FROM participants WHERE id=%s",
              (session["participant_id"],), one=True)
    if p["attempt_status"] == "completed":
        return redirect(url_for("result_page"))

    settings  = get_quiz_settings()
    if not quiz_is_open(settings):
        flash("Quiz is not active.", "warning")
        return redirect(url_for("landing"))

    questions = query(
        "SELECT id, question_text, option_a, option_b, option_c, option_d, marks "
        "FROM questions WHERE is_active=1 ORDER BY id"
    )
    # Compute remaining seconds
    start_ts   = session.get("quiz_start_ts") or datetime.now().timestamp()
    elapsed    = datetime.now().timestamp() - float(start_ts)
    total_secs = settings["duration_minutes"] * 60
    remaining  = max(0, int(total_secs - elapsed))
    return render_template("quiz.html",
        questions=questions, settings=settings,
        remaining_seconds=remaining,
        participant_name=session["participant_name"]
    )

# ──────────────────────────────────────────
#  API — Record Violation
# ──────────────────────────────────────────
@app.route("/api/violation", methods=["POST"])
@participant_required
def record_violation():
    data       = request.get_json() or {}
    v_type     = data.get("type", "tab_switch")
    device     = data.get("device", "")[:500]
    pid        = session["participant_id"]

    existing   = query("SELECT * FROM violations WHERE participant_id=%s", (pid,), one=True)
    if existing:
        new_count = existing["violation_count"] + 1
        query("UPDATE violations SET violation_count=%s, violation_type=%s, timestamp=NOW()"
              " WHERE participant_id=%s", (new_count, v_type, pid), commit=True)
    else:
        new_count = 1
        query("INSERT INTO violations (participant_id, violation_count, violation_type, device_info)"
              " VALUES (%s,%s,%s,%s)", (pid, 1, v_type, device), commit=True)

    settings  = get_quiz_settings()
    max_viol  = settings["max_violations"] if settings else 3
    return jsonify({"count": new_count, "max": max_viol, "auto_submit": new_count >= max_viol})

# ──────────────────────────────────────────
#  API — Save Answers (auto-save)
# ──────────────────────────────────────────
@app.route("/api/save-answers", methods=["POST"])
@participant_required
def save_answers():
    # Just an acknowledgement — real save happens on submit
    return jsonify({"ok": True})

# ──────────────────────────────────────────
#  API — Submit Quiz
# ──────────────────────────────────────────
@app.route("/api/submit", methods=["POST"])
@participant_required
def submit_quiz():
    pid  = session["participant_id"]
    p    = query("SELECT * FROM participants WHERE id=%s", (pid,), one=True)

    # Guard: already submitted
    if p["attempt_status"] == "completed":
        return jsonify({"error": "Already submitted."}), 400

    data         = request.get_json() or {}
    answers      = data.get("answers", {})    # { str(question_id): "A"|"B"|"C"|"D" }
    time_taken   = int(data.get("time_taken", 0))
    auto_submit  = bool(data.get("auto_submit", False))

    # Server-side time validation
    settings    = get_quiz_settings()
    start_ts    = session.get("quiz_start_ts") or datetime.now().timestamp()
    elapsed     = datetime.now().timestamp() - float(start_ts)
    total_secs  = (settings["duration_minutes"] if settings else 30) * 60
    if elapsed > total_secs + 30:          # 30 s grace
        auto_submit = True

    # Score calculation — NEVER send answers to frontend
    questions   = query("SELECT id, correct_answer, marks FROM questions WHERE is_active=1")
    score       = 0
    total_marks = 0
    for q in questions:
        total_marks += q["marks"]
        if str(q["id"]) in answers:
            if answers[str(q["id"])].upper() == q["correct_answer"]:
                score += q["marks"]

    # Save submission
    query(
        "INSERT INTO submissions (participant_id, score, total_marks, time_taken, "
        "auto_submitted, answers_json) VALUES (%s,%s,%s,%s,%s,%s)",
        (pid, score, total_marks, time_taken, auto_submit,
         json.dumps(answers)), commit=True
    )
    # Mark participant done
    query("UPDATE participants SET attempt_status='completed' WHERE id=%s",
          (pid,), commit=True)

    session["last_score"]       = score
    session["last_total"]       = total_marks
    session["last_time"]        = time_taken
    session["last_auto"]        = auto_submit
    return jsonify({"ok": True, "redirect": url_for("result_page")})

# ──────────────────────────────────────────
#  PARTICIPANT — Result
# ──────────────────────────────────────────
@app.route("/result")
@participant_required
def result_page():
    pid = session["participant_id"]
    sub = query(
        "SELECT s.*, p.name, p.register_no FROM submissions s "
        "JOIN participants p ON p.id=s.participant_id "
        "WHERE s.participant_id=%s ORDER BY s.submitted_at DESC LIMIT 1",
        (pid,), one=True
    )
    if not sub:
        return redirect(url_for("quiz_page"))

    # Rank
    rank_row = query(
        "SELECT COUNT(*) AS r FROM submissions WHERE score > %s", (sub["score"],), one=True
    )
    rank = (rank_row["r"] or 0) + 1
    viol = query("SELECT * FROM violations WHERE participant_id=%s", (pid,), one=True)
    violations = viol["violation_count"] if viol else 0
    pct = round((sub["score"] / sub["total_marks"]) * 100, 1) if sub["total_marks"] else 0
    return render_template("result.html", sub=sub, rank=rank,
                           violations=violations, pct=pct)

# ──────────────────────────────────────────
#  PUBLIC — Leaderboard
# ──────────────────────────────────────────
@app.route("/leaderboard")
def leaderboard():
    board = query(
        "SELECT p.name, p.register_no, s.score, s.total_marks, "
        "s.time_taken, s.submitted_at "
        "FROM submissions s JOIN participants p ON p.id=s.participant_id "
        "ORDER BY s.score DESC, s.time_taken ASC LIMIT 50"
    )
    return render_template("leaderboard.html", board=board)

# ──────────────────────────────────────────
#  Error handlers
# ──────────────────────────────────────────
@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, msg="Forbidden"), 403

@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, msg="Page not found"), 404

@app.errorhandler(500)
def server_error(e):
    return render_template("error.html", code=500, msg="Server error"), 500

# ──────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
