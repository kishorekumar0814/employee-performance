from flask import Flask, render_template, request, redirect, url_for, session, flash, make_response
import sqlite3, pickle, os
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
from functools import wraps
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "employee-performance-secret-key-change-me")
DB = "performance.db"
MODEL_FILE = "employee_performance_model.pkl"
FEATURE_FILE = "selected_features.pkl"
CATEGORY = {0:"Average", 1:"Excellent", 2:"Good", 3:"Poor", 4:"Very Good"}


def is_postgres():
    return bool(os.environ.get("DATABASE_URL"))


def execute(c, query, params=()):
    if is_postgres():
        return c.execute(query.replace("?", "%s"), params)
    return c.execute(query, params)


def db():
    if is_postgres():
        conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
        conn.cursor_factory = RealDictCursor
        return conn

    # SQLite connection tuned for Flask so simultaneous requests do not
    # immediately fail with "database is locked".
    c = sqlite3.connect(DB, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


def ensure_column(c, table, column, definition):
    if is_postgres():
        exists = execute(c, """SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = ? AND column_name = ?
        )""", (table, column)).fetchone()[0]
        if not exists:
            execute(c, f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        return

    cols = [r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def create_table_sqls():
    if is_postgres():
        return {
            "companies": """CREATE TABLE IF NOT EXISTS companies(
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL)""",
            "users": """CREATE TABLE IF NOT EXISTS users(
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE,
                password TEXT,
                role TEXT,
                company_id INTEGER)""",
            "employees": """CREATE TABLE IF NOT EXISTS employees(
                id SERIAL PRIMARY KEY,
                employee_id TEXT,
                name TEXT,
                age REAL,
                years_experience REAL,
                department TEXT,
                job_role TEXT,
                created_by TEXT,
                created_at TEXT,
                company_id INTEGER)""",
            "predictions": """CREATE TABLE IF NOT EXISTS predictions(
                id SERIAL PRIMARY KEY,
                employee_id TEXT,
                attendance_rate REAL,
                training_hours REAL,
                overtime_hours REAL,
                projects_completed REAL,
                satisfaction_score REAL,
                work_life_balance REAL,
                salary REAL,
                experience_per_age REAL,
                attendance_training REAL,
                salary_per_experience REAL,
                prediction TEXT,
                created_by TEXT,
                created_at TEXT,
                company_id INTEGER)"""
        }

    return {
        "companies": """CREATE TABLE IF NOT EXISTS companies(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL)""",
        "users": """CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE, password TEXT, role TEXT, company_id INTEGER)""",
        "employees": """CREATE TABLE IF NOT EXISTS employees(
            id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT,
            name TEXT, age REAL, years_experience REAL, department TEXT,
            job_role TEXT, created_by TEXT, created_at TEXT, company_id INTEGER)""",
        "predictions": """CREATE TABLE IF NOT EXISTS predictions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT,
            attendance_rate REAL, training_hours REAL, overtime_hours REAL,
            projects_completed REAL, satisfaction_score REAL, work_life_balance REAL,
            salary REAL, experience_per_age REAL, attendance_training REAL,
            salary_per_experience REAL, prediction TEXT, created_by TEXT,
            created_at TEXT, company_id INTEGER)"""
    }


def init_db():
    c = db()
    table_sqls = create_table_sqls()
    c.execute(table_sqls["companies"])
    c.execute(table_sqls["users"])
    c.execute(table_sqls["employees"])
    c.execute(table_sqls["predictions"])

    # Upgrade the original database without deleting existing data.
    for table, col, definition in [
        ("users", "company_id", "INTEGER"),
        ("employees", "company_id", "INTEGER"),
        ("predictions", "company_id", "INTEGER")
    ]:
        ensure_column(c, table, col, definition)

    company = c.execute("SELECT * FROM companies ORDER BY id LIMIT 1").fetchone()
    if not company:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        execute(c, "INSERT INTO companies(name,created_at) VALUES(?,?)", ("Nila Company", now))
        company = execute(c, "SELECT * FROM companies WHERE name=?", ("Nila Company",)).fetchone()
    cid = company["id"]

    # Preserve the old demo accounts, assigning them to the first company.
    execute(c, "UPDATE users SET company_id=? WHERE company_id IS NULL", (cid,))
    execute(c, "UPDATE employees SET company_id=? WHERE company_id IS NULL", (cid,))
    execute(c, "UPDATE predictions SET company_id=? WHERE company_id IS NULL", (cid,))

    admin = c.execute("SELECT * FROM users WHERE username='admin'").fetchone()
    if not admin:
        execute(c, "INSERT INTO users(username,password,role,company_id) VALUES(?,?,?,?)",
                ("admin", "admin123", "admin", cid))
    hr = c.execute("SELECT * FROM users WHERE username='hr'").fetchone()
    if not hr:
        execute(c, "INSERT INTO users(username,password,role,company_id) VALUES(?,?,?,?)",
                ("hr", "hr123", "hr", cid))
    c.commit(); c.close()


def load_model():
    try:
        with open(MODEL_FILE,"rb") as f: m = pickle.load(f)
        with open(FEATURE_FILE,"rb") as f: sf = list(pickle.load(f))
        return m, sf
    except Exception:
        return None, None
model, selected_features = load_model()


def required(role=None):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if role and session.get("role") != role:
                flash("Access denied.", "error")
                return redirect(url_for("dashboard"))
            return fn(*a, **kw)
        return wrapper
    return deco


def current_user():
    c = db()
    u = c.execute("""SELECT u.*,c.name company_name FROM users u
                   JOIN companies c ON c.id=u.company_id WHERE u.id=?""",
                  (session["user_id"],)).fetchone()
    c.close()
    return u


@app.context_processor
def inject_global():
    return {"current_user_obj": current_user() if "user_id" in session else None}


@app.route("/")
def home():
    return redirect(url_for("dashboard")) if "user_id" in session else render_template("welcome.html")


@app.route("/signup", methods=["GET","POST"])
def signup():
    if request.method == "POST":
        u = request.form["username"].strip(); p = request.form["password"]
        role = request.form.get("role", "").lower(); company_name = request.form["company_name"].strip()
        if not u or not p or role not in ("hr", "admin") or not company_name:
            flash("Please enter User ID, Password, Company and Role.", "error")
            return render_template("signup.html")
        if len(p) < 4:
            flash("Password must contain at least 4 characters.", "error")
            return render_template("signup.html")
        c = db()
        try:
            company = execute(c, "SELECT * FROM companies WHERE lower(name)=lower(?)", (company_name,)).fetchone()
            if not company:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                execute(c, "INSERT INTO companies(name,created_at) VALUES(?,?)", (company_name, now))
                company = execute(c, "SELECT * FROM companies WHERE lower(name)=lower(?)", (company_name,)).fetchone()
            if role == "admin":
                exists = execute(c, "SELECT 1 FROM users WHERE company_id=? AND role='admin'", (company["id"],)).fetchone()
                if exists:
                    flash("This company already has an Admin. Ask the existing Admin to create/manage HR accounts.", "error")
                    c.close(); return render_template("signup.html")
            execute(c, "INSERT INTO users(username,password,role,company_id) VALUES(?,?,?,?)",
                    (u, p, role, company["id"]))
            c.commit()
            flash("Account created successfully. Please login.", "success")
            return redirect(url_for("login"))
        except (sqlite3.IntegrityError, psycopg2.IntegrityError):
            flash("User ID already exists. Please choose another.", "error")
        finally:
            c.close()
    return render_template("signup.html")


@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u = request.form["username"].strip(); p = request.form["password"]; role = request.form.get("role", "").lower()
        c = db(); user = execute(c, """SELECT * FROM users
            WHERE username=? AND password=? AND role=?""", (u, p, role)).fetchone(); c.close()
        if user:
            session.clear()
            session["user_id"] = user["id"]; session["user"] = user["username"]
            session["role"] = user["role"]; session["company_id"] = user["company_id"]
            return redirect(url_for("dashboard"))
        flash("Invalid User ID, password or role.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("home"))


@app.route("/dashboard")
@required()
def dashboard():
    return redirect(url_for("hr_dashboard" if session["role"] == "hr" else "admin_dashboard"))


@app.route("/company")
@required()
def company_profile():
    c = db(); cid = session["company_id"]
    company = execute(c, "SELECT * FROM companies WHERE id=?", (cid,)).fetchone()
    admin = execute(c, "SELECT username FROM users WHERE company_id=? AND role='admin'", (cid,)).fetchone()
    hrs = execute(c, "SELECT username FROM users WHERE company_id=? AND role='hr' ORDER BY username", (cid,)).fetchall()
    emp_count = execute(c, "SELECT COUNT(*) n FROM employees WHERE company_id=?", (cid,)).fetchone()["n"]
    pred_count = execute(c, "SELECT COUNT(*) n FROM predictions WHERE company_id=?", (cid,)).fetchone()["n"]
    c.close()
    return render_template("company_profile.html", company=company, admin=admin, hrs=hrs,
                           emp_count=emp_count, pred_count=pred_count)


@app.route("/hr")
@required("hr")
def hr_dashboard():
    c = db(); cid = session["company_id"]; uid = session["user"]
    employees = execute(c, """SELECT * FROM employees WHERE company_id=? AND created_by=?
                           ORDER BY id DESC""", (cid, uid)).fetchall()
    predictions = execute(c, """SELECT p.*,e.name FROM predictions p LEFT JOIN employees e
                             ON e.employee_id=p.employee_id AND e.company_id=p.company_id
                             WHERE p.company_id=? AND p.created_by=? ORDER BY p.id DESC LIMIT 10""", (cid, uid)).fetchall()
    hr_count = execute(c, "SELECT COUNT(*) n FROM users WHERE company_id=? AND role='hr'", (cid,)).fetchone()["n"]
    c.close()
    return render_template("hr_dashboard.html", employees=employees, predictions=predictions,
                           model_ready=(model is not None and selected_features is not None),
                           hr_count=hr_count)


@app.route("/employee/add", methods=["GET","POST"])
@required("hr")
def add_employee():
    if request.method == "POST":
        c = None
        try:
            c = db(); cid = session["company_id"]
            execute(c, """INSERT INTO employees
                (employee_id,name,age,years_experience,department,job_role,created_by,created_at,company_id)
                VALUES(?,?,?,?,?,?,?,?,?)""", (
                request.form["employee_id"].strip(), request.form["name"].strip(),
                float(request.form["age"]), float(request.form["years_experience"]),
                request.form["department"].strip(), request.form["job_role"].strip(),
                session["user"], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), cid))
            c.commit(); flash("Employee saved successfully.", "success")
            return redirect(url_for("hr_dashboard"))
        except Exception as e: flash(f"Error: {e}", "error")
        finally:
            if c is not None: c.close()
    return render_template("add_employee.html")


def get_employee_for_access(employee_id):
    c = db()
    if session["role"] == "admin":
        emp = execute(c, "SELECT * FROM employees WHERE employee_id=? AND company_id=?",
                      (employee_id, session["company_id"])).fetchone()
    else:
        emp = execute(c, """SELECT * FROM employees WHERE employee_id=? AND company_id=?
                         AND created_by=?""", (employee_id, session["company_id"], session["user"])).fetchone()
    c.close(); return emp


@app.route("/predict/<employee_id>", methods=["GET","POST"])
@required("hr")
def predict(employee_id):
    emp = get_employee_for_access(employee_id)
    if not emp: flash("Employee not found or access denied.", "error"); return redirect(url_for("hr_dashboard"))
    if request.method == "POST":
        if model is None:
            flash("Model files are missing.", "error"); return redirect(url_for("predict", employee_id=employee_id))
        try:
            attendance = float(request.form["attendance_rate"]); training = float(request.form["training_hours"])
            overtime = float(request.form["overtime_hours"]); projects = float(request.form["projects_completed"])
            satisfaction = float(request.form["satisfaction_score"]); balance = float(request.form["work_life_balance"])
            salary = float(request.form["salary"])
            exp_age = emp["years_experience"] / (emp["age"] + 1); train_project = training / (projects + 1)
            att_train = attendance * training; sal_exp = salary / (emp["years_experience"] + 1)
            row = {"attendance_rate": attendance, "training_hours": training, "overtime_hours": overtime,
                   "projects_completed": projects, "satisfaction_score": satisfaction, "work_life_balance": balance,
                   "salary": salary, "experience_per_age": exp_age, "training_per_project": train_project,
                   "attendance_training": att_train, "salary_per_experience": sal_exp}
            x = pd.DataFrame([row])[selected_features]; result = CATEGORY.get(int(model.predict(x)[0]), "Unknown")
            c = None
            try:
                c = db(); execute(c, """INSERT INTO predictions(
                    employee_id,attendance_rate,training_hours,overtime_hours,projects_completed,
                    satisfaction_score,work_life_balance,salary,experience_per_age,attendance_training,
                    salary_per_experience,prediction,created_by,created_at,company_id)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    employee_id, attendance, training, overtime, projects, satisfaction, balance, salary, exp_age,
                    att_train, sal_exp, result, session["user"], datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    session["company_id"]))
                c.commit()
            finally:
                if c is not None: c.close()
            return render_template("prediction_result.html", employee=emp, prediction=result)
        except Exception as e: flash(f"Prediction error: {e}", "error")
    return render_template("predict.html", employee=emp)


@app.route("/history/<employee_id>")
@required()
def history(employee_id):
    emp = get_employee_for_access(employee_id)
    if not emp: flash("Employee not found or access denied.", "error"); return redirect(url_for("dashboard"))
    c = db()
    rows = execute(c, """SELECT * FROM predictions WHERE employee_id=? AND company_id=?
                      AND (?='admin' OR created_by=?) ORDER BY id DESC""",
                   (employee_id, session["company_id"], session["role"], session["user"])).fetchall()
    c.close()
    return render_template("history.html", employee=emp, predictions=rows)


@app.route("/admin")
@required("admin")
def admin_dashboard():
    c = db(); cid = session["company_id"]
    total_e = execute(c, "SELECT COUNT(*) n FROM employees WHERE company_id=?", (cid,)).fetchone()["n"]
    total_p = execute(c, "SELECT COUNT(*) n FROM predictions WHERE company_id=?", (cid,)).fetchone()["n"]
    total_hr = execute(c, "SELECT COUNT(*) n FROM users WHERE company_id=? AND role='hr'", (cid,)).fetchone()["n"]
    admin_name = execute(c, "SELECT username FROM users WHERE company_id=? AND role='admin'", (cid,)).fetchone()
    rows = execute(c, """SELECT p.*,e.name,e.department,e.job_role FROM predictions p
                      LEFT JOIN employees e ON e.employee_id=p.employee_id AND e.company_id=p.company_id
                      WHERE p.company_id=? ORDER BY p.id DESC""", (cid,)).fetchall()
    hrs = execute(c, "SELECT username FROM users WHERE company_id=? AND role='hr' ORDER BY username", (cid,)).fetchall()
    summary = execute(c, "SELECT prediction,COUNT(*) count FROM predictions WHERE company_id=? GROUP BY prediction", (cid,)).fetchall()
    c.close()
    return render_template("admin_dashboard.html", total_employees=total_e, total_predictions=total_p,
                           total_hr=total_hr, predictions=rows, summary=summary, hrs=hrs,
                           admin_name=admin_name["username"] if admin_name else "-")


@app.route("/admin/report")
@required("admin")
def report():
    c = db(); rows = execute(c, """SELECT p.*,e.name,e.department,e.job_role FROM predictions p
                              LEFT JOIN employees e ON e.employee_id=p.employee_id AND e.company_id=p.company_id
                              WHERE p.company_id=? ORDER BY p.id DESC""", (session["company_id"],)).fetchall(); c.close()
    return render_template("report.html", rows=rows)


@app.route("/admin/report/download")
@required("admin")
def download():
    c = db(); rows = execute(c, """SELECT p.*,e.name,e.department,e.job_role FROM predictions p
                              LEFT JOIN employees e ON e.employee_id=p.employee_id AND e.company_id=p.company_id
                              WHERE p.company_id=? ORDER BY p.id DESC""", (session["company_id"],)).fetchall(); c.close()
    cols = ["employee_id", "name", "department", "job_role", "attendance_rate", "training_hours", "overtime_hours",
            "projects_completed", "satisfaction_score", "work_life_balance", "salary", "prediction", "created_by", "created_at"]
    out = [",".join(cols)]
    for r in rows: out.append(",".join('"' + str(r[k] if r[k] is not None else "").replace('"', '""') + '"' for k in cols))
    res = make_response("\n".join(out)); res.headers["Content-Disposition"] = "attachment; filename=company_performance_report.csv"
    res.headers["Content-Type"] = "text/csv"; return res


init_db()
if __name__ == "__main__":
    # Disable the debug reloader because it starts a second process and can
    # compete for the SQLite database during startup.
    app.run(debug=True, use_reloader=False, threaded=True)
