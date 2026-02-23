"""
Smart Quiz System — Flask Backend (MongoDB Atlas Edition)
All score calculations & answer validation happen server-side only.
HTML/CSS/JS unchanged — only DB layer swapped to MongoDB.
"""

import os, json, csv, io
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv
from bson import ObjectId

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, jsonify, flash, Response
)
from flask_bcrypt import Bcrypt
from flask_wtf.csrf import CSRFProtect
from pymongo import MongoClient, ASCENDING, DESCENDING

load_dotenv()

app = Flask(__name__)
app.secret_key        = os.getenv("SECRET_KEY", "change-me-in-production")
app.config["WTF_CSRF_TIME_LIMIT"] = None
bcrypt = Bcrypt(app)
csrf   = CSRFProtect(app)

# ──────────────────────────────────────────
#  MongoDB Atlas connection
# ──────────────────────────────────────────
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/quiz_system")
client    = MongoClient(MONGO_URI)
db        = client[os.getenv("DB_NAME", "quiz_system")]

# Collections
admins        = db["admin"]
participants  = db["participants"]
questions     = db["questions"]
quiz_settings = db["quiz_settings"]
submissions   = db["submissions"]
violations    = db["violations"]

# ── Ensure a quiz_settings doc exists ──
if quiz_settings.count_documents({}) == 0:
    quiz_settings.insert_one({
        "duration_minutes": 30,
        "is_active":        False,
        "start_time":       None,
        "end_time":         None,
        "max_violations":   3,
    })

# ──────────────────────────────────────────
#  Helper: convert ObjectId → str in a doc
# ──────────────────────────────────────────
def fix(doc):
    """Convert _id ObjectId to string 'id' so templates work like MySQL rows."""
    if doc is None:
        return None
    doc = dict(doc)
    if "_id" in doc:
        doc["id"] = str(doc["_id"])
    return doc

def fix_many(docs):
    return [fix(d) for d in docs]

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
#  Quiz helpers
# ──────────────────────────────────────────
def get_settings():
    return fix(quiz_settings.find_one())

def quiz_is_open(s=None):
    s = s or get_settings()
    if not s or not s.get("is_active"):
        return False
    now = datetime.now()
    if s.get("start_time") and now < s["start_time"]:
        return False
    if s.get("end_time")   and now > s["end_time"]:
        return False
    return True

# ──────────────────────────────────────────
#  PUBLIC — Landing
# ──────────────────────────────────────────
@app.route("/")
def landing():
    settings = get_settings()
    return render_template("landing.html",
                           quiz_open=quiz_is_open(settings), settings=settings)

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
        admin    = admins.find_one({"email": email})
        if admin and bcrypt.check_password_hash(admin["password_hash"], password):
            session["admin_id"]    = str(admin["_id"])
            session["admin_email"] = admin["email"]
            flash("Welcome back!", "success")
            return redirect(url_for("admin_dashboard"))
        flash("Invalid credentials.", "danger")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_id",    None)
    session.pop("admin_email", None)
    return redirect(url_for("admin_login"))

# ──────────────────────────────────────────
#  ADMIN — Dashboard
# ──────────────────────────────────────────
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    settings       = get_settings()
    total_q        = questions.count_documents({"is_active": True})
    total_p        = participants.count_documents({})
    total_attempts = submissions.count_documents({})
    viol_agg       = list(violations.aggregate([
        {"$group": {"_id": None, "total": {"$sum": "$violation_count"}}}
    ]))
    total_viol = viol_agg[0]["total"] if viol_agg else 0

    # Recent submissions joined with participant names
    recent_raw = list(submissions.find().sort("submitted_at", DESCENDING).limit(10))
    recent_subs = []
    for sub in recent_raw:
        s = fix(sub)
        pid = sub.get("participant_id")
        p   = participants.find_one({"_id": ObjectId(pid)}) if pid else None
        if p:
            s["name"]        = p.get("name", "")
            s["register_no"] = p.get("register_no", "")
        recent_subs.append(s)

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
    is_active  = bool(request.form.get("is_active"))
    max_viol   = int(request.form.get("max_violations", 3))

    start_raw  = request.form.get("start_time") or None
    end_raw    = request.form.get("end_time")   or None
    start_time = datetime.strptime(start_raw, "%Y-%m-%dT%H:%M") if start_raw else None
    end_time   = datetime.strptime(end_raw,   "%Y-%m-%dT%H:%M") if end_raw   else None

    quiz_settings.update_one({}, {"$set": {
        "duration_minutes": duration,
        "is_active":        is_active,
        "start_time":       start_time,
        "end_time":         end_time,
        "max_violations":   max_viol,
    }})
    flash("Quiz settings updated.", "success")
    return redirect(url_for("admin_dashboard"))

# ──────────────────────────────────────────
#  ADMIN — Questions
# ──────────────────────────────────────────
@app.route("/admin/questions")
@admin_required
def admin_questions():
    qs = fix_many(questions.find().sort("_id", DESCENDING))
    return render_template("admin_questions.html", questions=qs)

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
        questions.insert_one({
            "question_text":  q,
            "option_a": a, "option_b": b, "option_c": c, "option_d": d,
            "correct_answer": ans, "marks": mrk, "is_active": True,
            "created_at": datetime.now()
        })
        flash("Question added.", "success")
        return redirect(url_for("admin_questions"))
    return render_template("admin_add_question.html", question=None)

@app.route("/admin/questions/<qid>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_question(qid):
    question = fix(questions.find_one({"_id": ObjectId(qid)}))
    if not question:
        flash("Question not found.", "danger")
        return redirect(url_for("admin_questions"))
    if request.method == "POST":
        questions.update_one({"_id": ObjectId(qid)}, {"$set": {
            "question_text":  request.form.get("question_text", "").strip(),
            "option_a":       request.form.get("option_a", "").strip(),
            "option_b":       request.form.get("option_b", "").strip(),
            "option_c":       request.form.get("option_c", "").strip(),
            "option_d":       request.form.get("option_d", "").strip(),
            "correct_answer": request.form.get("correct_answer", "A"),
            "marks":          int(request.form.get("marks", 1)),
        }})
        flash("Question updated.", "success")
        return redirect(url_for("admin_questions"))
    return render_template("admin_add_question.html", question=question)

@app.route("/admin/questions/<qid>/delete", methods=["POST"])
@admin_required
def admin_delete_question(qid):
    questions.update_one({"_id": ObjectId(qid)}, {"$set": {"is_active": False}})
    flash("Question deleted.", "info")
    return redirect(url_for("admin_questions"))

# ──────────────────────────────────────────
#  ADMIN — Participants
# ──────────────────────────────────────────
@app.route("/admin/participants")
@admin_required
def admin_participants():
    parts = []
    for p in participants.find().sort("_id", DESCENDING):
        row = fix(p)
        pid = str(p["_id"])
        sub = submissions.find_one({"participant_id": pid})
        if sub:
            row["score"]        = sub.get("score", 0)
            row["total_marks"]  = sub.get("total_marks", 0)
            row["submitted_at"] = sub.get("submitted_at")
            row["auto_submitted"]= sub.get("auto_submitted", False)
        else:
            row["score"] = row["total_marks"] = None
        viol = violations.find_one({"participant_id": pid})
        row["violation_count"] = viol["violation_count"] if viol else 0
        parts.append(row)
    return render_template("admin_participants.html", participants=parts)

# ──────────────────────────────────────────
#  ADMIN — Violations
# ──────────────────────────────────────────
@app.route("/admin/violations")
@admin_required
def admin_violations():
    viols = []
    for v in violations.find().sort("timestamp", DESCENDING):
        row = fix(v)
        pid = v.get("participant_id")
        p   = participants.find_one({"_id": ObjectId(pid)}) if pid else None
        row["name"]        = p["name"]        if p else "Unknown"
        row["register_no"] = p["register_no"] if p else "—"
        viols.append(row)
    return render_template("admin_violations.html", violations=viols)

# ──────────────────────────────────────────
#  ADMIN — Leaderboard
# ──────────────────────────────────────────
@app.route("/admin/leaderboard")
@admin_required
def admin_leaderboard():
    board = []
    for sub in submissions.find().sort([("score", DESCENDING), ("time_taken", ASCENDING)]):
        row = fix(sub)
        pid = sub.get("participant_id")
        p   = participants.find_one({"_id": ObjectId(pid)}) if pid else None
        row["name"]        = p["name"]        if p else "Unknown"
        row["register_no"] = p["register_no"] if p else "—"
        viol = violations.find_one({"participant_id": pid}) if pid else None
        row["violations"]  = viol["violation_count"] if viol else 0
        board.append(row)
    return render_template("admin_leaderboard.html", board=board)

# ──────────────────────────────────────────
#  ADMIN — Export CSV
# ──────────────────────────────────────────
@app.route("/admin/export/csv")
@admin_required
def admin_export_csv():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name","Register No","Email","Score","Total","Time(s)",
                     "Auto-Submitted","Submitted At","Violations"])
    for sub in submissions.find().sort("score", DESCENDING):
        pid  = sub.get("participant_id")
        p    = participants.find_one({"_id": ObjectId(pid)}) if pid else {}
        viol = violations.find_one({"participant_id": pid}) if pid else {}
        writer.writerow([
            p.get("name",""), p.get("register_no",""), p.get("email",""),
            sub.get("score",0), sub.get("total_marks",0), sub.get("time_taken",0),
            sub.get("auto_submitted",False), sub.get("submitted_at",""),
            viol.get("violation_count",0) if viol else 0
        ])
    output.seek(0)
    return Response(output, mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=quiz_results.csv"})

# ──────────────────────────────────────────
#  PARTICIPANT — Login / Register
# ──────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def participant_login():
    if session.get("participant_id"):
        return redirect(url_for("quiz_page"))
    if request.method == "POST":
        name   = request.form.get("name",        "").strip()
        reg_no = request.form.get("register_no", "").strip()
        email  = request.form.get("email",       "").strip().lower()
        if not all([name, reg_no, email]):
            flash("All fields are required.", "danger")
            return redirect(request.url)
        if not quiz_is_open():
            flash("Quiz is not active right now.", "warning")
            return redirect(url_for("landing"))

        p = participants.find_one({"$or": [
            {"register_no": reg_no}, {"email": email}
        ]})
        if p:
            if p.get("attempt_status") == "completed":
                flash("You have already completed this quiz. Only one attempt is allowed.", "danger")
                return redirect(url_for("participant_login"))
        else:
            result = participants.insert_one({
                "name": name, "register_no": reg_no, "email": email,
                "attempt_status": "not_attempted", "quiz_start_time": None,
                "created_at": datetime.now()
            })
            p = participants.find_one({"_id": result.inserted_id})

        participants.update_one({"_id": p["_id"]}, {"$set": {
            "attempt_status":  "in_progress",
            "quiz_start_time": datetime.now()
        }})
        session["participant_id"]   = str(p["_id"])
        session["participant_name"] = p["name"]
        session["quiz_start_ts"]    = datetime.now().timestamp()
        return redirect(url_for("quiz_page"))
    return render_template("participant_login.html", quiz_open=quiz_is_open())

@app.route("/logout")
def participant_logout():
    session.pop("participant_id",   None)
    session.pop("participant_name", None)
    session.pop("quiz_start_ts",    None)
    return redirect(url_for("landing"))

# ──────────────────────────────────────────
#  PARTICIPANT — Quiz Page
# ──────────────────────────────────────────
@app.route("/quiz")
@participant_required
def quiz_page():
    p = fix(participants.find_one({"_id": ObjectId(session["participant_id"])}))
    if p and p.get("attempt_status") == "completed":
        return redirect(url_for("result_page"))
    settings = get_settings()
    if not quiz_is_open(settings):
        flash("Quiz is not active.", "warning")
        return redirect(url_for("landing"))

    # Fetch questions WITHOUT correct_answer (never send to frontend)
    qs = fix_many(questions.find(
        {"is_active": True},
        {"correct_answer": 0}          # exclude correct answer from query result
    ).sort("_id", ASCENDING))

    start_ts   = session.get("quiz_start_ts") or datetime.now().timestamp()
    elapsed    = datetime.now().timestamp() - float(start_ts)
    total_secs = (settings.get("duration_minutes", 30)) * 60
    remaining  = max(0, int(total_secs - elapsed))

    return render_template("quiz.html",
        questions=qs, settings=settings,
        remaining_seconds=remaining,
        participant_name=session["participant_name"]
    )

# ──────────────────────────────────────────
#  API — Record Violation
# ──────────────────────────────────────────
@app.route("/api/violation", methods=["POST"])
@participant_required
def record_violation():
    data   = request.get_json() or {}
    v_type = data.get("type", "tab_switch")
    device = data.get("device", "")[:500]
    pid    = session["participant_id"]

    existing = violations.find_one({"participant_id": pid})
    if existing:
        new_count = existing["violation_count"] + 1
        violations.update_one({"participant_id": pid}, {"$set": {
            "violation_count": new_count,
            "violation_type":  v_type,
            "timestamp":       datetime.now()
        }})
    else:
        new_count = 1
        violations.insert_one({
            "participant_id": pid, "violation_count": 1,
            "violation_type": v_type, "device_info": device,
            "timestamp": datetime.now()
        })

    settings  = get_settings()
    max_viol  = settings.get("max_violations", 3) if settings else 3
    return jsonify({"count": new_count, "max": max_viol,
                    "auto_submit": new_count >= max_viol})

# ──────────────────────────────────────────
#  API — Save Answers (auto-save stub)
# ──────────────────────────────────────────
@app.route("/api/save-answers", methods=["POST"])
@participant_required
def save_answers():
    return jsonify({"ok": True})

# ──────────────────────────────────────────
#  API — Submit Quiz
# ──────────────────────────────────────────
@app.route("/api/submit", methods=["POST"])
@participant_required
def submit_quiz():
    pid = session["participant_id"]
    p   = participants.find_one({"_id": ObjectId(pid)})
    if p and p.get("attempt_status") == "completed":
        return jsonify({"error": "Already submitted."}), 400

    data        = request.get_json() or {}
    answers     = data.get("answers", {})       # { str(question_id): "A"|...|"D" }
    time_taken  = int(data.get("time_taken", 0))
    auto_submit = bool(data.get("auto_submit", False))

    # Server-side time guard
    settings   = get_settings()
    start_ts   = session.get("quiz_start_ts") or datetime.now().timestamp()
    elapsed    = datetime.now().timestamp() - float(start_ts)
    total_secs = (settings.get("duration_minutes", 30) if settings else 30) * 60
    if elapsed > total_secs + 30:
        auto_submit = True

    # Server-side scoring — fetch WITH correct_answer
    qs          = list(questions.find({"is_active": True}))
    score       = 0
    total_marks = 0
    for q in qs:
        total_marks += q.get("marks", 1)
        qid_str = str(q["_id"])
        if qid_str in answers:
            if answers[qid_str].upper() == q.get("correct_answer", "").upper():
                score += q.get("marks", 1)

    submissions.insert_one({
        "participant_id": pid,
        "score":          score,
        "total_marks":    total_marks,
        "time_taken":     time_taken,
        "auto_submitted": auto_submit,
        "answers_json":   json.dumps(answers),
        "submitted_at":   datetime.now()
    })
    participants.update_one({"_id": ObjectId(pid)},
                            {"$set": {"attempt_status": "completed"}})

    session["last_score"] = score
    session["last_total"] = total_marks
    return jsonify({"ok": True, "redirect": url_for("result_page")})

# ──────────────────────────────────────────
#  PARTICIPANT — Result
# ──────────────────────────────────────────
@app.route("/result")
@participant_required
def result_page():
    pid = session["participant_id"]
    sub_doc = submissions.find_one({"participant_id": pid},
                                   sort=[("submitted_at", DESCENDING)])
    if not sub_doc:
        return redirect(url_for("quiz_page"))

    sub = fix(sub_doc)
    p   = participants.find_one({"_id": ObjectId(pid)})
    sub["name"]        = p["name"]        if p else ""
    sub["register_no"] = p["register_no"] if p else ""

    # Rank: how many scored strictly more
    rank = submissions.count_documents({"score": {"$gt": sub["score"]}}) + 1
    viol = violations.find_one({"participant_id": pid})
    violations_count = viol["violation_count"] if viol else 0
    pct  = round((sub["score"] / sub["total_marks"]) * 100, 1) if sub.get("total_marks") else 0

    return render_template("result.html", sub=sub, rank=rank,
                           violations=violations_count, pct=pct)

# ──────────────────────────────────────────
#  PUBLIC — Leaderboard
# ──────────────────────────────────────────
@app.route("/leaderboard")
def leaderboard():
    board = []
    for sub in submissions.find().sort([("score", DESCENDING),
                                        ("time_taken", ASCENDING)]).limit(50):
        row = fix(sub)
        pid = sub.get("participant_id")
        p   = participants.find_one({"_id": ObjectId(pid)}) if pid else None
        row["name"]        = p["name"]        if p else "Unknown"
        row["register_no"] = p["register_no"] if p else "—"
        board.append(row)
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
