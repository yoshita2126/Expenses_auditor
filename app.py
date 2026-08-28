from flask import Flask, render_template, render_template_string, request, redirect
from flask import session, url_for, jsonify, Response, send_file

import sqlite3
import re
import secrets
import io
import csv
import json
from pathlib import Path

import os
import jwt
from services.analysis_service import (
    calculate_financial_metrics,
    get_top_5_categories,
    get_category_breakdown,
    get_monthly_trends,
    transactions_to_df,
    parse_and_validate_csv
)
from services.anomaly_service import detect_unusual_transactions, explain_anomaly
from services.duplicate_service import detect_duplicate_transactions
from services.summary_service import generate_monthly_summary, get_available_months
from services.ai_service import (
    generate_ai_recommendations,
    generate_insights,
    chat_with_ai,
    get_expense_advisor_response,
    estimate_daily_saving_amount
)
from services.email_service import send_email
from services.forecast_service import forecast_monthly_expense
from datetime import date, datetime, timedelta, timezone
import calendar
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, cast

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

app = Flask(__name__)

app.secret_key = secrets.token_hex(32)

# Register API routes
from api_routes import register_api_routes
register_api_routes(app)



# =========================================================
# VALIDATIONS
# =========================================================

def valid_username(username: str) -> bool:

    return len(username) >= 3


def valid_password(password: str) -> bool:

    pattern = (
        r"^(?=.*[a-z])"
        r"(?=.*[A-Z])"
        r"(?=.*\d)"
        r"(?=.*[@$!%*?&])"
        r".{8,}$"
    )

    return bool(re.match(pattern, password))


def valid_gmail(email: str) -> bool:

    pattern = r'^[a-zA-Z0-9._%+-]+@gmail\.com$'

    return bool(re.match(pattern, email))


def valid_amount(amount: Any) -> bool:

    try:

        value = float(amount)

        return value > 0

    except Exception:

        return False


# =========================================================
# CORS
# =========================================================

@app.after_request
def add_cors(response: Response) -> Response:

    response.headers["Access-Control-Allow-Origin"] = "*"

    response.headers["Access-Control-Allow-Headers"] = (
        "Content-Type,Authorization"
    )

    response.headers["Access-Control-Allow-Methods"] = (
        "GET,POST,OPTIONS"
    )

    return response


def get_json_data() -> Dict[str, Any]:
    raw_data = request.get_json(silent=True)
    return raw_data if isinstance(raw_data, dict) else {}


# =========================================================
# DATABASE
# =========================================================

def get_db():

    db_path = Path(__file__).resolve().parent / "data.db"
    conn = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)

    conn.row_factory = sqlite3.Row

    return conn


def init_db():

    conn = get_db()

    cur = conn.cursor()

    # USERS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            username TEXT UNIQUE NOT NULL,

            email TEXT UNIQUE,

            phone TEXT,

            password TEXT NOT NULL,

            role TEXT,

            group_name TEXT,

            registration_date TEXT,

            daily_limit REAL DEFAULT 1000,
  
            email_verified INTEGER DEFAULT 0
        )
    """)

    # Add monthly_budget column to users if it doesn't exist
    cur.execute("PRAGMA table_info(users)")
    cols = [r[1] for r in cur.fetchall()]
    if 'monthly_budget' not in cols:
        try:
            cur.execute("ALTER TABLE users ADD COLUMN monthly_budget REAL DEFAULT NULL")
        except Exception:
            # ignore if alter fails for any reason
            pass

    # GROUPS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS groups(

            group_name TEXT PRIMARY KEY,

            password TEXT NOT NULL,

            role TEXT,

            registration_date TEXT
        )
    """)

    # TRANSACTIONS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            group_name TEXT,

            user TEXT,

            amount REAL,

            category TEXT,

            type TEXT,

            note TEXT,

            date TEXT
        )
    """)

    # GOALS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS goals(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            group_name TEXT,

            user TEXT,

            title TEXT,

            target REAL,

            saved REAL,

            due_date TEXT
        )
    """)

    # PAYMENTS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            group_name TEXT,

            user TEXT,

            amount REAL,

            direction TEXT,

            description TEXT,

            status TEXT,

            due_date TEXT
        )
    """)

    # RECURRING PAYMENTS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS recurring_payments(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            group_name TEXT,

            user TEXT,

            amount REAL,

            category TEXT,

            type TEXT,

            note TEXT,

            start_date TEXT,

            frequency_days INTEGER,

            next_date TEXT,

            active INTEGER DEFAULT 1
        )
    """)

    # OTP TOKENS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS otp_tokens(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            email TEXT,

            phone TEXT,

            otp TEXT NOT NULL,

            expires_at TEXT NOT NULL,

            created_at TEXT NOT NULL
        )
    """)

    # BUSINESSES
    cur.execute("""
        CREATE TABLE IF NOT EXISTS businesses(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            business_name TEXT NOT NULL,

            owner_id INTEGER NOT NULL,

            gst_id TEXT UNIQUE,

            pan TEXT,

            address TEXT,

            city TEXT,

            state TEXT,

            pincode TEXT,

            phone TEXT,

            email TEXT,

            business_type TEXT,

            industry TEXT,

            registration_date TEXT,

            status TEXT DEFAULT 'active',

            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
    """)

    # BRANCHES
    cur.execute("""
        CREATE TABLE IF NOT EXISTS branches(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            business_id INTEGER NOT NULL,

            branch_name TEXT NOT NULL,

            address TEXT,

            city TEXT,

            state TEXT,

            pincode TEXT,

            phone TEXT,

            manager_id INTEGER,

            registration_date TEXT,

            status TEXT DEFAULT 'active',

            FOREIGN KEY(business_id) REFERENCES businesses(id),

            FOREIGN KEY(manager_id) REFERENCES users(id)
        )
    """)

    # PRODUCTS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            business_id INTEGER NOT NULL,

            product_name TEXT NOT NULL,

            sku TEXT UNIQUE,

            category TEXT,

            unit_price REAL,

            cost_price REAL,

            tax_rate REAL DEFAULT 0,

            description TEXT,

            registration_date TEXT,

            status TEXT DEFAULT 'active',

            FOREIGN KEY(business_id) REFERENCES businesses(id)
        )
    """)

    # INVENTORY
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            branch_id INTEGER NOT NULL,

            product_id INTEGER NOT NULL,

            stock_quantity REAL DEFAULT 0,

            reorder_level REAL DEFAULT 10,

            last_updated TEXT,

            FOREIGN KEY(branch_id) REFERENCES branches(id),

            FOREIGN KEY(product_id) REFERENCES products(id)
        )
    """)

    # STOCK TRANSACTIONS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stock_transactions(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            inventory_id INTEGER NOT NULL,

            transaction_type TEXT,

            quantity REAL,

            reference_id TEXT,

            notes TEXT,

            transaction_date TEXT,

            FOREIGN KEY(inventory_id) REFERENCES inventory(id)
        )
    """)

    # SUPPLIERS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS suppliers(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            business_id INTEGER NOT NULL,

            supplier_name TEXT NOT NULL,

            contact_person TEXT,

            email TEXT,

            phone TEXT,

            address TEXT,

            city TEXT,

            state TEXT,

            pincode TEXT,

            gst_id TEXT,

            payment_terms TEXT,

            registration_date TEXT,

            status TEXT DEFAULT 'active',

            FOREIGN KEY(business_id) REFERENCES businesses(id)
        )
    """)

    # INVOICES (Sales)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS invoices(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            business_id INTEGER NOT NULL,

            branch_id INTEGER NOT NULL,

            invoice_number TEXT UNIQUE NOT NULL,

            customer_name TEXT NOT NULL,

            customer_email TEXT,

            customer_phone TEXT,

            customer_address TEXT,

            invoice_date TEXT,

            due_date TEXT,

            subtotal REAL DEFAULT 0,

            tax_amount REAL DEFAULT 0,

            total_amount REAL DEFAULT 0,

            payment_status TEXT DEFAULT 'unpaid',

            payment_date TEXT,

            notes TEXT,

            created_by INTEGER,

            created_at TEXT,

            FOREIGN KEY(business_id) REFERENCES businesses(id),

            FOREIGN KEY(branch_id) REFERENCES branches(id),

            FOREIGN KEY(created_by) REFERENCES users(id)
        )
    """)

    # INVOICE ITEMS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS invoice_items(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            invoice_id INTEGER NOT NULL,

            product_id INTEGER,

            description TEXT NOT NULL,

            quantity REAL,

            unit_price REAL,

            tax_rate REAL DEFAULT 0,

            line_total REAL,

            FOREIGN KEY(invoice_id) REFERENCES invoices(id),

            FOREIGN KEY(product_id) REFERENCES products(id)
        )
    """)

    # PURCHASE ORDERS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS purchase_orders(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            business_id INTEGER NOT NULL,

            supplier_id INTEGER NOT NULL,

            po_number TEXT UNIQUE NOT NULL,

            order_date TEXT,

            expected_delivery_date TEXT,

            subtotal REAL DEFAULT 0,

            tax_amount REAL DEFAULT 0,

            total_amount REAL DEFAULT 0,

            status TEXT DEFAULT 'pending',

            delivery_date TEXT,

            notes TEXT,

            created_by INTEGER,

            created_at TEXT,

            FOREIGN KEY(business_id) REFERENCES businesses(id),

            FOREIGN KEY(supplier_id) REFERENCES suppliers(id),

            FOREIGN KEY(created_by) REFERENCES users(id)
        )
    """)

    # PO ITEMS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS po_items(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            po_id INTEGER NOT NULL,

            product_id INTEGER,

            description TEXT NOT NULL,

            quantity REAL,

            unit_price REAL,

            tax_rate REAL DEFAULT 0,

            line_total REAL,

            FOREIGN KEY(po_id) REFERENCES purchase_orders(id),

            FOREIGN KEY(product_id) REFERENCES products(id)
        )
    """)

    # GST TRANSACTIONS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gst_transactions(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            business_id INTEGER NOT NULL,

            transaction_type TEXT,

            invoice_id INTEGER,

            po_id INTEGER,

            taxable_amount REAL,

            cgst_rate REAL,

            cgst_amount REAL,

            sgst_rate REAL,

            sgst_amount REAL,

            igst_rate REAL,

            igst_amount REAL,

            total_tax REAL,

            transaction_date TEXT,

            FOREIGN KEY(business_id) REFERENCES businesses(id),

            FOREIGN KEY(invoice_id) REFERENCES invoices(id),

            FOREIGN KEY(po_id) REFERENCES purchase_orders(id)
        )
    """)

    # Schema Migrations for ExpenseAuditor
    # 1. Add user_type to users
    cur.execute("PRAGMA table_info(users)")
    user_cols = [r[1] for r in cur.fetchall()]
    if 'user_type' not in user_cols:
        try:
            cur.execute("ALTER TABLE users ADD COLUMN user_type TEXT DEFAULT 'personal'")
        except Exception:
            pass
    if 'phone' not in user_cols:
        try:
            cur.execute("ALTER TABLE users ADD COLUMN phone TEXT DEFAULT NULL")
        except Exception:
            pass

    # Backfill user_type from role if empty
    try:
        cur.execute("""
            UPDATE users
            SET user_type = CASE WHEN LOWER(role) = 'business' THEN 'business' ELSE 'personal' END
            WHERE user_type IS NULL OR user_type = ''
        """)
    except Exception:
        pass

    # 2. Add user_id to transactions
    cur.execute("PRAGMA table_info(transactions)")
    txn_cols = [r[1] for r in cur.fetchall()]
    if 'user_id' not in txn_cols:
        try:
            cur.execute("ALTER TABLE transactions ADD COLUMN user_id INTEGER DEFAULT NULL")
        except Exception:
            pass

    # Backfill user_id in transactions
    try:
        cur.execute("""
            UPDATE transactions
            SET user_id = (
                SELECT id FROM users
                WHERE LOWER(users.username) = LOWER(transactions.user)
                   OR LOWER(users.group_name) = LOWER(transactions.group_name)
                LIMIT 1
            )
            WHERE user_id IS NULL
        """)
    except Exception:
        pass

    conn.commit()

    conn.close()



init_db()

# JWT settings
JWT_SECRET = os.environ.get('JWT_SECRET') or secrets.token_hex(32)
JWT_ALGO = 'HS256'


def create_jwt(identity: str, group_name: str, role: str, expires_minutes: int = 60*24) -> str:
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        'sub': identity,
        'group': group_name,
        'role': role,
        'iat': now,
        'exp': now + timedelta(minutes=expires_minutes)
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)
    return token


def decode_jwt(token: str) -> Optional[Dict[str, Any]]:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except Exception:
        return None


def jwt_required(f: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        # Check Authorization header first
        auth = request.headers.get('Authorization', '')
        if auth.startswith('Bearer '):
            token = auth.split(' ', 1)[1].strip()
            payload = decode_jwt(token)
            if payload:
                cast(Any, request).jwt_payload = payload
                return f(*args, **kwargs)
            return jsonify(success=False, error='Invalid or expired token'), 401

        # fallback to session cookie
        if 'user' in session:
            return f(*args, **kwargs)

        return jsonify(success=False, error='Authentication required'), 401

    return decorated


# =========================================================
# REGISTER
# =========================================================

@app.route("/", methods=["GET", "POST"])
@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        raw_type = request.form.get("user_type") or request.form.get("account_type") or request.form.get("role") or "personal"
        user_type = "business" if raw_type.strip().lower() == "business" else "personal"

        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        # Business specific fields
        business_name = request.form.get("business_name", "").strip()
        business_type = request.form.get("business_type", "").strip() or "General"
        gst_id = request.form.get("gst_id", "").strip()

        role = "business" if user_type == "business" else "household"
        group_name = (
            business_name if (user_type == "business" and business_name)
            else (request.form.get("group_name", "").strip() or username)
        )

        # EMAIL VALIDATION
        if not email or not valid_gmail(email):
            return """
            <h2>Invalid Email</h2>
            <p>Please provide a valid Gmail address (e.g., user@gmail.com)</p>
            <a href='/'>Go Back</a>
            """

        # USERNAME VALIDATION
        if not valid_username(username):
            return """
            <h2>Invalid Username</h2>
            <p>Username must contain at least 3 characters</p>
            <a href='/'>Go Back</a>
            """

        # PASSWORD VALIDATION
        if not valid_password(password):
            return """
            <h2>Password Invalid</h2>
            <h3>Password must contain:</h3>
            <ul>
                <li>1 Capital Letter</li>
                <li>1 Small Letter</li>
                <li>1 Number</li>
                <li>1 Special Character</li>
                <li>Minimum 8 Characters</li>
            </ul>
            <a href="/">Go Back</a>
            """

        if password != confirm_password:
            return """
            <h2>Password Mismatch</h2>
            <p>Password and confirm password must match.</p>
            <a href="/">Go Back</a>
            """

        # HASH PASSWORD
        hashed_password = generate_password_hash(password)
        registration_date = date.today().isoformat()

        conn = get_db()
        cur = conn.cursor()

        try:
            # INSERT USER
            cur.execute(
                """
                INSERT INTO users(
                    username,
                    email,
                    phone,
                    password,
                    role,
                    group_name,
                    registration_date,
                    user_type
                )
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    username,
                    email,
                    phone,
                    hashed_password,
                    role,
                    group_name,
                    registration_date,
                    user_type
                ),
            )

            user_id = cur.lastrowid

            if user_type == "business":
                # Create business record if registering as business
                cur.execute("""
                    INSERT INTO businesses (
                        owner_id, business_name, gst_id, business_type,
                        phone, email, registration_date, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id,
                    business_name or group_name,
                    gst_id or f"GST-{secrets.token_hex(4).upper()}",
                    business_type,
                    phone,
                    email,
                    registration_date,
                    'active'
                ))

            conn.commit()

        except sqlite3.IntegrityError as e:
            conn.close()
            if "email" in str(e):
                return """
                <h2>Email already registered</h2>
                <a href='/'>Go Back</a>
                """
            else:
                return """
                <h2>Username already exists</h2>
                <a href='/'>Go Back</a>
                """

        conn.close()
        return redirect(url_for("login"))

    return render_template("register.html")


# =========================================================
# LOGIN
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form["username"].strip()
        password = request.form["password"].strip()

        conn = get_db()
        cur = conn.cursor()

        # GET USER (case-insensitive lookup by username or email)
        cur.execute(
            "SELECT * FROM users WHERE LOWER(username)=LOWER(?) OR LOWER(email)=LOWER(?)",
            (username, username)
        )

        user = cur.fetchone()

        # CHECK USER PASSWORD
        if user and check_password_hash(
            user["password"],
            password
        ):
            user_type = user["user_type"] if ("user_type" in user.keys() and user["user_type"]) else ("business" if user["role"] == "business" else "personal")
            
            session["user"] = user["username"]
            session["user_id"] = user["id"]
            session["user_type"] = user_type
            session["role"] = user["role"]
            session["group_name"] = user["group_name"]
            session["registration_date"] = user["registration_date"]
            session["daily_limit"] = user["daily_limit"] if "daily_limit" in user.keys() else 1000

            # If business user, link business_id
            if user_type == "business":
                cur.execute("SELECT id FROM businesses WHERE owner_id = ?", (user["id"],))
                biz = cur.fetchone()
                if biz:
                    session["business_id"] = biz["id"]
                else:
                    # Create default business entry if not exists
                    cur.execute("""
                        INSERT INTO businesses (owner_id, business_name, business_type, email, phone, registration_date, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (user["id"], user["group_name"] or user["username"], "General", user["email"], user["phone"], date.today().isoformat(), 'active'))
                    conn.commit()
                    session["business_id"] = cur.lastrowid

            conn.close()

            # Redirect based on user_type
            if user_type == "business":
                return redirect(url_for("business_dashboard"))
            else:
                return redirect(url_for("personal_dashboard"))

        conn.close()

        return """
        <h2>Invalid Username, Email, or Password</h2>
        <a href='/login'>Try Again</a>
        """

    return render_template("login.html")



# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


# =========================================================
# FORGOT PASSWORD
# =========================================================

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():

    if request.method == "POST":

        account = request.form.get("email", "").strip()
        session.pop("password_reset_email", None)
        session.pop("pending_reset_email", None)

        if not account:
            return render_template("forgot_password.html", error="Username or email is required")

        conn = get_db()
        cur = conn.cursor()

        # Check account and always send to the registered email address.
        cur.execute("SELECT * FROM users WHERE email = ? OR username = ?", (account, account))
        user = cur.fetchone()

        conn.close()

        if not user or not user["email"]:
            return render_template("forgot_password.html", error="Registered email not found")

        email = user["email"]

        # Generate and send OTP
        from services import otp_service
        from services.otp_service import generate_otp, send_otp, store_otp

        otp = generate_otp()

        store_result = store_otp(email=email, otp=otp)

        if not store_result:
            return render_template("forgot_password.html", error="Failed to generate OTP. Try again.")

        send_result = send_otp(email=email, otp=otp)

        if not send_result.get('success'):
            error_message = send_result.get('error') or 'Unknown email send error'
            return render_template("forgot_password.html", error=f"Failed to send OTP: {error_message}")

        session["pending_reset_email"] = email

        return redirect(url_for("reset_password", email=email, sent=1))

    return render_template("forgot_password.html")


@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():

    email = request.args.get("email", "").strip()

    if request.method == "POST":

        otp = request.form.get("otp", "").strip()

        if not otp:
            return render_template("verify_otp.html", email=email, error="OTP is required")

        from services.otp_service import verify_otp as verify_otp_func

        if not verify_otp_func(otp=otp, email=email):
            return render_template("verify_otp.html", email=email, error="Invalid or expired OTP")

        session["password_reset_email"] = email

        return redirect(url_for("reset_password", email=email))

    return render_template("verify_otp.html", email=email)


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():

    email = request.args.get("email", "").strip()
    verified_email = session.get("password_reset_email", "")
    pending_email = session.get("pending_reset_email", "")

    if not email or email not in {verified_email, pending_email}:
        return redirect(url_for("forgot_password"))

    if request.method == "POST":

        otp = request.form.get("otp", "").strip()

        new_password = request.form.get("password", "").strip()

        confirm_password = request.form.get("confirm_password", "").strip()

        from services.otp_service import verify_otp as verify_otp_func

        if not verify_otp_func(otp=otp, email=email):
            return render_template(
                "reset_password.html",
                email=email,
                otp_sent=True,
                error="Invalid or expired OTP"
            )

        if new_password != confirm_password:
            return render_template("reset_password.html", email=email, otp_sent=True, error="Passwords do not match")

        if not valid_password(new_password):
            return render_template("reset_password.html", email=email, otp_sent=True, error="Password must contain: uppercase, lowercase, number, special char, minimum 8 characters")

        hashed_password = generate_password_hash(new_password)

        conn = get_db()
        cur = conn.cursor()

        try:
            cur.execute("UPDATE users SET password = ? WHERE email = ?", (hashed_password, email))
            conn.commit()

            from services.otp_service import delete_otp
            delete_otp(email)
            session.pop("password_reset_email", None)
            session.pop("pending_reset_email", None)

        except Exception as e:
            return render_template("reset_password.html", email=email, otp_sent=True, error=f"Error resetting password: {str(e)}")

        finally:
            conn.close()

        return render_template("reset_success.html")

    return render_template("reset_password.html", email=email, otp_sent=request.args.get("sent") == "1")


# =========================================================
# BUSINESS MODULE
# =========================================================

@app.route("/business/register", methods=["GET", "POST"])
def business_register():
    """Register a new business account"""
    
    if not session.get('user'):
        return redirect(url_for('login'))
    
    if request.method == "POST":
        from services.business_service import register_business
        
        conn = get_db()
        cur = conn.cursor()
        
        # Get user ID
        cur.execute("SELECT id FROM users WHERE username = ?", (session['user'],))
        user = cur.fetchone()
        conn.close()
        
        if not user:
            return render_template("business_register.html", error="User not found")
        
        business_name = request.form.get("business_name", "").strip()
        gst_id = request.form.get("gst_id", "").strip()
        business_type = request.form.get("business_type", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        address = request.form.get("address", "").strip()
        city = request.form.get("city", "").strip()
        state = request.form.get("state", "").strip()
        pincode = request.form.get("pincode", "").strip()
        
        if not business_name or not gst_id:
            return render_template("business_register.html", error="Business name and GST ID are required")
        
        result = register_business(
            owner_id=user['id'],
            business_name=business_name,
            gst_id=gst_id,
            business_type=business_type,
            phone=phone,
            email=email,
            address=address,
            city=city,
            state=state,
            pincode=pincode
        )
        
        if result['success']:
            session['business_id'] = result['business_id']
            return redirect(url_for('business_dashboard'))
        else:
            return render_template("business_register.html", error=result.get('error', 'Registration failed'))
    
    return render_template("business_register.html")


@app.route("/business/dashboard")
def business_dashboard():
    """Business dashboard with ExpenseAuditor analytics"""
    
    if not session.get('user'):
        return redirect(url_for('login'))

    user = session['user']
    user_id = session.get('user_id')
    group_name = session.get('group_name', user)
    
    from services.business_service import (
        get_business_by_id,
        get_business_branches,
        get_business_stats,
        get_business_invoices,
        get_business_purchase_orders,
        get_business_suppliers,
        get_business_products
    )
    
    conn = get_db()
    cur = conn.cursor()

    # Ensure business_id is set
    business_id = session.get('business_id')
    if not business_id and user_id:
        cur.execute("SELECT id FROM businesses WHERE owner_id = ?", (user_id,))
        biz_row = cur.fetchone()
        if biz_row:
            business_id = biz_row['id']
            session['business_id'] = business_id
        else:
            # Auto-create business if missing
            cur.execute("""
                INSERT INTO businesses (owner_id, business_name, business_type, email, registration_date, status)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, group_name, 'General', f"{user}@example.com", date.today().isoformat(), 'active'))
            conn.commit()
            business_id = cur.lastrowid
            session['business_id'] = business_id

    business = get_business_by_id(business_id) if business_id else None
    if not business:
        business = {
            'id': business_id or 1,
            'business_name': group_name,
            'business_type': 'General Business',
            'gst_id': 'GST-PENDING',
            'city': 'Headquarters',
            'state': 'Main',
            'phone': 'N/A',
            'email': session.get('user', '') + '@example.com'
        }

    # Fetch business transactions (isolated to this business / user)
    filter_from = request.args.get('date_from', '')
    filter_to = request.args.get('date_to', '')
    transaction_query = """
        SELECT * FROM transactions
        WHERE (user_id = ? OR (user_id IS NULL AND (group_name = ? OR user = ?)))
    """
    transaction_params = [user_id, group_name, user]
    if filter_from:
        transaction_query += " AND date >= ?"
        transaction_params.append(filter_from)
    if filter_to:
        transaction_query += " AND date <= ?"
        transaction_params.append(filter_to)
    transaction_query += " ORDER BY date DESC, id DESC"
    cur.execute(transaction_query, tuple(transaction_params))
    
    rows = cur.fetchall()
    conn.close()

    tx_list = [dict(r) for r in rows]

    # Run ExpenseAuditor engines
    metrics = calculate_financial_metrics(tx_list, user_type='business')
    unusual_transactions = detect_unusual_transactions(tx_list)
    duplicate_payments = detect_duplicate_transactions(tx_list)

    selected_month = request.args.get('month', 'current')
    monthly_summary = generate_monthly_summary(tx_list, selected_month=selected_month, user_type='business')
    
    ai_result = generate_ai_recommendations(monthly_summary, user_type='business')
    recommendations = ai_result.get('recommendations', [])[:3]
    ai_available = ai_result.get('ai_available', False)
    ai_status_message = ai_result.get('status_message', '')

    branches = get_business_branches(business_id) if business_id else []
    stats = get_business_stats(business_id) if business_id else {
        'total_revenue': metrics['total_income'],
        'total_branches': len(branches),
        'total_products': 0,
        'low_stock_count': 0,
        'pending_amount': 0,
        'purchase_total': metrics['total_expenses'],
        'gst_payable': 0
    }
    invoices = get_business_invoices(business_id)[:5] if business_id else []
    purchase_orders = get_business_purchase_orders(business_id)[:5] if business_id else []
    suppliers = get_business_suppliers(business_id) if business_id else []
    products = get_business_products(business_id) if business_id else []

    # Chart data for cost categories
    top_5_costs = metrics.get('top_5_categories', [])
    cost_labels = [c['category'] for c in top_5_costs]
    cost_amounts = [c['total_amount'] for c in top_5_costs]
    
    chart_data = {
        "labels": cost_labels if cost_labels else ["No Expenses"],
        "datasets": [{
            "data": cost_amounts if cost_amounts else [1],
            "backgroundColor": [
                "#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6"
            ],
            "borderColor": "#1E293B",
            "borderWidth": 2
        }]
    }

    # Monthly Trends Data
    monthly_trends = metrics.get('monthly_trends', [])
    trends_labels = [m['label'] for m in monthly_trends]
    trends_revenue = [m['income'] for m in monthly_trends]
    trends_expenses = [m['expenses'] for m in monthly_trends]

    trends_data = {
        "labels": trends_labels,
        "datasets": [
            {
                "label": "Revenue",
                "data": trends_revenue,
                "borderColor": "#10B981",
                "backgroundColor": "rgba(16, 185, 129, 0.1)",
                "borderWidth": 2,
                "tension": 0.4
            },
            {
                "label": "Operating Expenses",
                "data": trends_expenses,
                "borderColor": "#EF4444",
                "backgroundColor": "rgba(239, 68, 68, 0.1)",
                "borderWidth": 2,
                "tension": 0.4
            }
        ]
    }

    return render_template(
        "business_dashboard.html",
        business=business,
        branches=branches,
        stats=stats,
        invoices=invoices,
        purchase_orders=purchase_orders,
        suppliers=suppliers,
        products=products,
        transactions=tx_list[:15],
        metrics=metrics,
        top_5_costs=top_5_costs,
        unusual_transactions=unusual_transactions,
        duplicate_payments=duplicate_payments,
        monthly_summary=monthly_summary,
        recommendations=recommendations,
        ai_available=ai_available,
        ai_status_message=ai_status_message,
        chart_data=json.dumps(chart_data),
        trends_data=json.dumps(trends_data),
        selected_month=selected_month,
        available_months=monthly_summary.get('available_months', []),
        filter_from=filter_from,
        filter_to=filter_to
    )



@app.route("/business/branches")
def business_branches():
    """View and manage branches"""
    
    if not session.get('user') or not session.get('business_id'):
        return redirect(url_for('login'))
    
    from services.business_service import get_business_branches
    
    business_id = session.get('business_id')
    branches = get_business_branches(business_id)
    
    return render_template("business_branches.html", branches=branches)


@app.route("/business/inventory")
def business_inventory():
    """View and manage inventory"""
    
    if not session.get('user') or not session.get('business_id'):
        return redirect(url_for('login'))
    
    from services.business_service import get_business_branches, get_branch_inventory, get_business_products
    
    business_id = session.get('business_id')
    branch_id = request.args.get('branch_id', type=int)
    
    branches = get_business_branches(business_id)
    products = get_business_products(business_id)
    
    if branch_id:
        inventory = get_branch_inventory(branch_id)
    else:
        inventory = []
    
    return render_template(
        "business_inventory.html",
        branches=branches,
        inventory=inventory,
        products=products,
        selected_branch_id=branch_id
    )


@app.route("/business/products")
def business_products():
    """View and manage products"""
    
    if not session.get('user') or not session.get('business_id'):
        return redirect(url_for('login'))
    
    from services.business_service import get_business_products
    
    business_id = session.get('business_id')
    products = get_business_products(business_id)
    
    return render_template("business_products.html", products=products)


@app.route("/business/suppliers")
def business_suppliers():
    """View and manage suppliers"""
    
    if not session.get('user') or not session.get('business_id'):
        return redirect(url_for('login'))
    
    from services.business_service import get_business_suppliers
    
    business_id = session.get('business_id')
    suppliers = get_business_suppliers(business_id)
    
    return render_template("business_suppliers.html", suppliers=suppliers)


@app.route("/business/invoices")
def business_invoices():
    """Create and track sales invoices"""

    if not session.get('user') or not session.get('business_id'):
        return redirect(url_for('login'))

    from services.business_service import (
        get_business_branches,
        get_business_products,
        get_business_invoices,
    )

    business_id = session.get('business_id')
    return render_template(
        "business_invoices.html",
        branches=get_business_branches(business_id),
        products=get_business_products(business_id),
        invoices=get_business_invoices(business_id),
    )


@app.route("/business/purchases")
def business_purchases():
    """Create and track purchase orders"""

    if not session.get('user') or not session.get('business_id'):
        return redirect(url_for('login'))

    from services.business_service import (
        get_business_branches,
        get_business_products,
        get_business_purchase_orders,
        get_business_suppliers,
    )

    business_id = session.get('business_id')
    return render_template(
        "business_purchases.html",
        branches=get_business_branches(business_id),
        products=get_business_products(business_id),
        suppliers=get_business_suppliers(business_id),
        purchase_orders=get_business_purchase_orders(business_id),
    )


@app.route("/business/gst")
def business_gst():
    """GST input/output tax report"""

    if not session.get('user') or not session.get('business_id'):
        return redirect(url_for('login'))

    from services.business_service import get_gst_report

    business_id = session.get('business_id')
    report = get_gst_report(business_id)

    return render_template("business_gst.html", report=report)


@app.route("/business/api/create-branch", methods=["POST"])
def api_create_branch():
    """API to create a new branch"""
    
    if not session.get('user') or not session.get('business_id'):
        return jsonify(success=False, error="Unauthorized"), 401
    
    from services.business_service import create_branch
    
    data = get_json_data()
    business_id = session.get('business_id')
    
    branch_name = data.get('branch_name', '').strip()
    address = data.get('address', '').strip()
    city = data.get('city', '').strip()
    state = data.get('state', '').strip()
    pincode = data.get('pincode', '').strip()
    phone = data.get('phone', '').strip()
    
    if not branch_name:
        return jsonify(success=False, error="Branch name is required"), 400
    
    result = create_branch(
        business_id=business_id,
        branch_name=branch_name,
        address=address,
        city=city,
        state=state,
        pincode=pincode,
        phone=phone
    )
    
    return jsonify(result)


@app.route("/business/api/add-product", methods=["POST"])
def api_add_product():
    """API to add a new product"""
    
    if not session.get('user') or not session.get('business_id'):
        return jsonify(success=False, error="Unauthorized"), 401
    
    from services.business_service import add_product
    
    data = get_json_data()
    business_id = session.get('business_id')
    
    product_name = data.get('product_name', '').strip()
    sku = data.get('sku', '').strip()
    category = data.get('category', '').strip()
    unit_price = data.get('unit_price', 0)
    cost_price = data.get('cost_price', 0)
    tax_rate = data.get('tax_rate', 0)
    description = data.get('description', '').strip()
    
    if not product_name or not sku:
        return jsonify(success=False, error="Product name and SKU are required"), 400
    
    result = add_product(
        business_id=business_id,
        product_name=product_name,
        sku=sku,
        category=category,
        unit_price=float(unit_price) if unit_price else 0,
        cost_price=float(cost_price) if cost_price else 0,
        tax_rate=float(tax_rate) if tax_rate else 0,
        description=description
    )
    
    return jsonify(result)


@app.route("/business/api/add-supplier", methods=["POST"])
def api_add_supplier():
    """API to add a new supplier"""
    
    if not session.get('user') or not session.get('business_id'):
        return jsonify(success=False, error="Unauthorized"), 401
    
    from services.business_service import add_supplier
    
    data = get_json_data()
    business_id = session.get('business_id')
    
    supplier_name = data.get('supplier_name', '').strip()
    contact_person = data.get('contact_person', '').strip()
    email = data.get('email', '').strip()
    phone = data.get('phone', '').strip()
    address = data.get('address', '').strip()
    city = data.get('city', '').strip()
    state = data.get('state', '').strip()
    pincode = data.get('pincode', '').strip()
    gst_id = data.get('gst_id', '').strip()
    payment_terms = data.get('payment_terms', '').strip()
    
    if not supplier_name:
        return jsonify(success=False, error="Supplier name is required"), 400
    
    result = add_supplier(
        business_id=business_id,
        supplier_name=supplier_name,
        contact_person=contact_person,
        email=email,
        phone=phone,
        address=address,
        city=city,
        state=state,
        pincode=pincode,
        gst_id=gst_id,
        payment_terms=payment_terms
    )
    
    return jsonify(result)


@app.route("/business/api/update-stock", methods=["POST"])
def api_update_stock():
    """API to adjust stock manually"""

    if not session.get('user') or not session.get('business_id'):
        return jsonify(success=False, error="Unauthorized"), 401

    from services.business_service import update_stock

    data = get_json_data()
    branch_id = data.get('branch_id')
    product_id = data.get('product_id')
    quantity = data.get('quantity')
    reorder_level = data.get('reorder_level')
    notes = data.get('notes', '').strip()

    if not branch_id or not product_id or quantity is None:
        return jsonify(success=False, error="Branch, product, and quantity are required"), 400

    result = update_stock(
        branch_id=int(branch_id),
        product_id=int(product_id),
        new_quantity=float(quantity),
        transaction_type="adjustment",
        reference_id="manual",
        notes=notes
    )

    if result.get("success") and reorder_level not in (None, ""):
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE inventory SET reorder_level=? WHERE id=?",
            (float(reorder_level), result["inventory_id"]),
        )
        conn.commit()
        conn.close()

    return jsonify(result)


@app.route("/business/api/create-invoice", methods=["POST"])
def api_create_invoice():
    """API to create a sales invoice"""

    if not session.get('user') or not session.get('business_id'):
        return jsonify(success=False, error="Unauthorized"), 401

    from services.business_service import create_invoice

    data = get_json_data()
    business_id = session.get('business_id')

    customer_name = data.get('customer_name', '').strip()
    branch_id = data.get('branch_id')
    product_id = data.get('product_id')
    quantity = data.get('quantity')

    if not customer_name or not branch_id or not product_id or not quantity:
        return jsonify(success=False, error="Customer, branch, product, and quantity are required"), 400

    result = create_invoice(
        business_id=business_id,
        branch_id=int(branch_id),
        customer_name=customer_name,
        customer_email=data.get('customer_email', '').strip(),
        customer_phone=data.get('customer_phone', '').strip(),
        product_id=int(product_id),
        quantity=float(quantity),
        due_date=data.get('due_date', '').strip(),
        notes=data.get('notes', '').strip(),
    )

    return jsonify(result)


@app.route("/business/api/mark-invoice-paid", methods=["POST"])
def api_mark_invoice_paid():
    """API to mark an invoice paid"""

    if not session.get('user') or not session.get('business_id'):
        return jsonify(success=False, error="Unauthorized"), 401

    from services.business_service import mark_invoice_paid

    data = get_json_data()
    invoice_id = data.get('invoice_id')
    if not invoice_id:
        return jsonify(success=False, error="Invoice ID is required"), 400

    return jsonify(mark_invoice_paid(int(invoice_id), session.get('business_id')))


@app.route("/business/api/create-purchase", methods=["POST"])
def api_create_purchase():
    """API to create a received purchase order"""

    if not session.get('user') or not session.get('business_id'):
        return jsonify(success=False, error="Unauthorized"), 401

    from services.business_service import create_purchase_order

    data = get_json_data()
    required = ["supplier_id", "branch_id", "product_id", "quantity", "unit_price"]
    if any(not data.get(field) for field in required):
        return jsonify(success=False, error="Supplier, branch, product, quantity, and unit price are required"), 400

    result = create_purchase_order(
        business_id=session.get('business_id'),
        supplier_id=int(data.get('supplier_id')),
        branch_id=int(data.get('branch_id')),
        product_id=int(data.get('product_id')),
        quantity=float(data.get('quantity')),
        unit_price=float(data.get('unit_price')),
        expected_delivery_date=data.get('expected_delivery_date', '').strip(),
        notes=data.get('notes', '').strip(),
    )

    return jsonify(result)


@app.route("/api/register", methods=["POST"])
def api_register():

    data = request.get_json(silent=True) or {}

    raw_type = data.get("user_type") or data.get("account_type") or data.get("role") or "personal"
    user_type = "business" if raw_type.strip().lower() == "business" else "personal"

    username = data.get("username", "").strip()
    email = data.get("email", "").strip()
    phone = data.get("phone", "").strip()
    password = data.get("password", "").strip()
    confirm_password = data.get("confirm_password", "").strip()

    business_name = data.get("business_name", "").strip()
    business_type = data.get("business_type", "").strip() or "General"
    gst_id = data.get("gst_id", "").strip()

    role = "business" if user_type == "business" else "household"
    group_name = (
        business_name if (user_type == "business" and business_name)
        else (data.get("group_name", "").strip() or username)
    )

    if not username or not email or not password or not confirm_password:
        return jsonify(
            success=False,
            error="Username, Gmail, password, and confirm password are required"
        ), 400

    if not valid_gmail(email):
        return jsonify(
            success=False,
            error="Please provide a valid Gmail address"
        ), 400

    if not valid_username(username):
        return jsonify(
            success=False,
            error="Username must contain at least 3 characters"
        ), 400

    if password != confirm_password:
        return jsonify(
            success=False,
            error="Password and confirm password must match"
        ), 400

    if not valid_password(password):
        return jsonify(
            success=False,
            error="""
Password must contain:
1 Capital Letter
1 Small Letter
1 Number
1 Special Character
Minimum 8 Characters
"""
        ), 400

    # HASH USER PASSWORD
    hashed_password = generate_password_hash(password)

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT id FROM users WHERE username=? OR email=?",
        (username, email)
    )

    existing_user = cur.fetchone()

    if existing_user:
        conn.close()
        return jsonify(
            success=False,
            error="Username or Gmail already exists"
        ), 409

    registration_date = date.today().isoformat()

    cur.execute(
        """
        INSERT INTO users(
            username,
            email,
            phone,
            password,
            role,
            group_name,
            registration_date,
            user_type
        )
        VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            username,
            email,
            phone,
            hashed_password,
            role,
            group_name,
            registration_date,
            user_type
        ),
    )

    user_id = cur.lastrowid

    if user_type == "business":
        cur.execute("""
            INSERT INTO businesses (
                owner_id, business_name, gst_id, business_type,
                phone, email, registration_date, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            business_name or group_name,
            gst_id or f"GST-{secrets.token_hex(4).upper()}",
            business_type,
            phone,
            email,
            registration_date,
            'active'
        ))

    conn.commit()
    conn.close()

    return jsonify(
        success=True,
        user_id=user_id,
        username=username,
        email=email,
        role=role,
        group_name=group_name,
        user_type=user_type
    )


# =========================================================
# API LOGIN
# =========================================================

@app.route("/api/login", methods=["POST"])
def api_login():

    data = request.get_json(silent=True) or {}

    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify(
            success=False,
            error="Username and password are required"
        ), 400

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM users WHERE LOWER(username)=LOWER(?) OR LOWER(email)=LOWER(?)",
        (username, username)
    )

    user = cur.fetchone()

    if not user or not check_password_hash(
        user["password"],
        password
    ):
        conn.close()
        return jsonify(
            success=False,
            error="Invalid credentials"
        ), 401

    user_type = user["user_type"] if ("user_type" in user.keys() and user["user_type"]) else ("business" if user["role"] == "business" else "personal")

    session["user"] = user["username"]
    session["user_id"] = user["id"]
    session["user_type"] = user_type
    session["role"] = user["role"]
    session["group_name"] = user["group_name"]

    business_id = None
    if user_type == "business":
        cur.execute("SELECT id FROM businesses WHERE owner_id = ?", (user["id"],))
        biz = cur.fetchone()
        if biz:
            business_id = biz["id"]
            session["business_id"] = business_id

    conn.close()

    return jsonify(
        success=True,
        user_id=user["id"],
        username=user["username"],
        role=user["role"],
        group_name=user["group_name"],
        user_type=user_type,
        business_id=business_id,
        redirect_url="/business/dashboard" if user_type == "business" else "/personal/dashboard"
    )



@app.route('/api/auth/token', methods=['POST'])
def api_auth_token():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    if not username or not password:
        return jsonify(success=False, error='username/password required'), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM users WHERE username=? OR email=?', (username, username))
    user = cur.fetchone()
    conn.close()

    if not user or not check_password_hash(user['password'], password):
        return jsonify(success=False, error='Invalid credentials'), 401

    token = create_jwt(user['username'], user['group_name'], user['role'])

    return jsonify(success=True, token=token, username=user['username'], role=user['role'], group_name=user['group_name'])



# ==========================
# AI INSIGHTS API
# ==========================

@app.route('/api/ai/insights', methods=['POST'])
def api_ai_insights():

    # allow JWT or session
    auth_ok = False
    auth = request.headers.get('Authorization','')
    if auth.startswith('Bearer '):
        payload = decode_jwt(auth.split(' ',1)[1].strip())
        if payload:
            auth_ok = True
            group_name = payload.get('group')
    if not auth_ok and 'user' in session:
        auth_ok = True
        group_name = session['group_name']

    if not auth_ok:
        return jsonify(success=False, error='Authentication required'), 401

    data = request.get_json(silent=True) or {}
    date_from = data.get('date_from')
    date_to = data.get('date_to')

    # group_name obtained above

    conn = get_db()
    cur = conn.cursor()

    query = "SELECT date, user, type, amount, category, note FROM transactions WHERE group_name=?"
    params = [group_name]
    if date_from:
        query += ' AND date >= ?'
        params.append(date_from)
    if date_to:
        query += ' AND date <= ?'
        params.append(date_to)

    cur.execute(query + ' ORDER BY id DESC', tuple(params))
    rows = cur.fetchall()
    conn.close()

    txs = []
    for r in rows:
        txs.append({
            'date': r['date'],
            'user': r['user'],
            'type': r['type'],
            'amount': r['amount'],
            'category': r['category'],
            'note': r['note']
        })

    insights = generate_insights(txs)

    return jsonify(success=True, insights=insights)


# ==========================
# OCR UPLOAD API
# ==========================

@app.route('/api/ocr/scan', methods=['POST'])
def api_ocr_scan():

    # allow JWT or session
    auth_ok = False
    auth = request.headers.get('Authorization','')
    if auth.startswith('Bearer '):
        payload = decode_jwt(auth.split(' ',1)[1].strip())
        if payload:
            auth_ok = True
    if not auth_ok and 'user' in session:
        auth_ok = True

    if not auth_ok:
        return jsonify(success=False, error='Authentication required'), 401

    if 'file' not in request.files:
        return jsonify(success=False, error='File is required'), 400

    f = request.files['file']
    content = f.read()

    from services.ocr_service import ocr_image

    result = ocr_image(content)

    return jsonify(success=True, result=result)


# =========================================================
# DASHBOARD
# =========================================================

def render_simple_page(title: str, content: str) -> str:
    template = '''
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>{{ title }}</title>
      <link rel="stylesheet" href="/static/style.css">
    </head>
    <body class="dashboard-page">
      <aside class="sidebar">
        <div class="sidebar-logo">
          <div class="logo-icon">💰</div>
          <span class="logo-text">ExpensesIQ</span>
        </div>
        <nav class="sidebar-nav">
          <a href="{{ url_for('personal_dashboard') }}" class="nav-item"> <span class="nav-icon">📊</span> <span class="nav-text">Dashboard</span> </a>
          <a href="{{ url_for('transactions_page') }}" class="nav-item"> <span class="nav-icon">💳</span> <span class="nav-text">Transactions</span> </a>
          <a href="{{ url_for('budgets') }}" class="nav-item"> <span class="nav-icon">🎯</span> <span class="nav-text">Budgets</span> </a>
          <a href="{{ url_for('goals_page') }}" class="nav-item"> <span class="nav-icon">🎪</span> <span class="nav-text">Goals</span> </a>
          <a href="{{ url_for('calendar_page') }}" class="nav-item"> <span class="nav-icon">📅</span> <span class="nav-text">Calendar</span> </a>
        </nav>
        <div class="sidebar-footer">
          <a href="/logout" class="logout-btn">
            <span class="nav-icon">🚪</span>
            <span class="nav-text">Logout</span>
          </a>
        </div>
      </aside>
      <main class="dashboard-main">
        <header class="dashboard-header">
          <div class="header-left">
            <h1>{{ title }}</h1>
            <span class="header-subtitle">Welcome back, {{ user }}!</span>
          </div>
        </header>
        <section class="dashboard-content">
          <div class="dashboard-card">
            <div class="card-header">
              <h2>{{ title }}</h2>
            </div>
            <div class="content-body">{{ content|safe }}</div>
          </div>
        </section>
      </main>
    </body>
    </html>
    '''
    return render_template_string(template, title=title, content=content, user=session.get('user', 'Guest'))

# =========================================================
# CSV UPLOAD ROUTES
# =========================================================

@app.route("/upload-csv", methods=["GET", "POST"])
@app.route("/personal/upload-csv", methods=["GET", "POST"])
@app.route("/business/upload-csv", methods=["GET", "POST"])
def upload_csv():
    if "user" not in session:
        return redirect(url_for("login"))
    
    user = session["user"]
    user_id = session.get("user_id")
    group_name = session.get("group_name", user)
    user_type = session.get("user_type", "personal")
    
    upload_result = None
    if request.method == "POST":
        if 'file' not in request.files:
            upload_result = {'success': False, 'message': 'No file selected in upload request.'}
        else:
            file = request.files['file']
            if file.filename == '':
                upload_result = {'success': False, 'message': 'No file was selected.'}
            elif not file.filename.lower().endswith('.csv'):
                upload_result = {'success': False, 'message': 'Invalid file format. Please upload a valid .csv file.'}
            else:
                try:
                    content = file.read()
                    parsed = parse_and_validate_csv(content)
                    
                    if parsed['valid_count'] > 0:
                        conn = get_db()
                        cur = conn.cursor()
                        
                        for txn in parsed['valid_transactions']:
                            cur.execute(
                                """
                                INSERT INTO transactions (
                                    user_id, group_name, user, amount, category, type, note, date
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    user_id,
                                    group_name,
                                    user,
                                    txn['amount'],
                                    txn['category'],
                                    txn['type'],
                                    txn['description'],
                                    txn['date']
                                )
                            )
                        conn.commit()
                        conn.close()
                    
                    upload_result = parsed
                except Exception as e:
                    upload_result = {
                        'success': False,
                        'message': f"Error processing CSV: {str(e)}",
                        'validation_errors': [{'row': 0, 'error': str(e)}],
                        'valid_count': 0,
                        'invalid_count': 1,
                        'duplicate_count': 0
                    }

    return render_template(
        "upload_csv.html",
        user=user,
        user_type=user_type,
        upload_result=upload_result
    )


@app.route("/download-sample-csv")
def download_sample_csv():
    """Download a pre-formatted 50+ transaction sample CSV for testing."""
    sample_csv_path = Path(__file__).resolve().parent / "sample_transactions.csv"
    sample_rows = [
        ("date", "amount", "category", "description", "type"),
        ("2026-08-01", "450", "Food", "Swiggy lunch order", "expense"),
        ("2026-08-01", "450", "Food", "Swiggy lunch order", "expense"),
        ("2026-08-02", "300", "Transport", "Uber city commute", "expense"),
        ("2026-08-02", "1250", "Groceries", "Supermarket supplies", "expense"),
        ("2026-08-03", "850", "Shopping", "Amazon stationery", "expense"),
        ("2026-08-03", "350", "Food", "Coffee with team", "expense"),
        ("2026-08-04", "1200", "Utilities", "Broadband Internet bill", "expense"),
        ("2026-08-05", "55000", "Salary", "Monthly Salary Credit", "income"),
        ("2026-08-05", "450", "Food", "Zomato dinner", "expense"),
        ("2026-08-06", "18500", "Shopping", "Designer Luxury Watch", "expense"),
        ("2026-08-07", "650", "Transport", "Fuel Petrol refuel", "expense"),
        ("2026-08-07", "1100", "Entertainment", "Weekend cinema tickets", "expense"),
        ("2026-08-08", "2400", "Utilities", "Electricity bill", "expense"),
        ("2026-08-09", "450", "Food", "Lunch wrap", "expense"),
        ("2026-08-10", "1500", "Healthcare", "Pharmacy medicines", "expense"),
        ("2026-08-10", "3000", "Freelance", "Consulting milestone payment", "income"),
        ("2026-08-11", "900", "Groceries", "Organic vegetables", "expense"),
        ("2026-08-12", "750", "Food", "Pizza dinner", "expense"),
        ("2026-08-12", "750", "Food", "Pizza dinner", "expense"),
        ("2026-08-13", "400", "Transport", "Metro smart card recharge", "expense"),
        ("2026-08-14", "1800", "Shopping", "Running shoes", "expense"),
        ("2026-08-15", "600", "Entertainment", "Streaming subscription", "expense"),
        ("2026-08-15", "1200", "Food", "Family dinner", "expense"),
        ("2026-08-16", "2500", "Education", "Online course certificate", "expense"),
        ("2026-08-17", "350", "Food", "Bakery snacks", "expense"),
        ("2026-08-18", "1600", "Groceries", "Weekly grocery store", "expense"),
        ("2026-08-19", "500", "Transport", "Cab ride", "expense"),
        ("2026-08-20", "8000", "Investments", "Mutual Fund SIP", "expense"),
        ("2026-08-20", "2000", "Dividends", "Stock dividend yield", "income"),
        ("2026-08-21", "450", "Food", "Subway lunch", "expense"),
        ("2026-08-22", "1300", "Shopping", "Home decor lamp", "expense"),
        ("2026-08-22", "650", "Transport", "Fuel fill", "expense"),
        ("2026-08-23", "950", "Food", "Brunch cafe", "expense"),
        ("2026-08-24", "1500", "Utilities", "Mobile postpaid bill", "expense"),
        ("2026-08-25", "350", "Food", "Juice bar", "expense"),
        ("2026-08-25", "1200", "Shopping", "Cookware item", "expense"),
        ("2026-08-26", "22000", "Electronics", "New Smartphone Upgrade", "expense"),
        ("2026-08-27", "400", "Transport", "Taxi commute", "expense"),
        ("2026-08-27", "1100", "Groceries", "Supermart items", "expense"),
        ("2026-08-28", "850", "Food", "Dinner with friends", "expense"),
        ("2026-08-28", "850", "Food", "Dinner with friends", "expense"),
        ("2026-08-29", "1500", "Entertainment", "Concert entry passes", "expense"),
        ("2026-08-29", "700", "Transport", "Airport cab", "expense"),
        ("2026-08-30", "5000", "Bonus", "Quarterly performance bonus", "income"),
        ("2026-08-30", "2800", "Groceries", "Monthly bulk pantry restock", "expense"),
        ("2026-08-31", "1200", "Food", "Month-end celebration meal", "expense"),
        ("2026-08-31", "600", "Utilities", "Water utility bill", "expense"),
        ("2026-08-31", "1500", "Savings", "Emergency fund deposit", "expense"),
        ("2026-08-31", "450", "Transport", "City train pass", "expense"),
        ("2026-08-31", "300", "Food", "Coffee & pastry", "expense")
    ]
    with open(sample_csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerows(sample_rows)
            
    return send_file(sample_csv_path, mimetype='text/csv', as_attachment=True, download_name='sample_50_transactions.csv')


@app.route("/api/upload-csv", methods=["POST"])
def api_upload_csv():
    """API endpoint for CSV transaction batch upload"""
    if "user" not in session:
        auth = request.headers.get('Authorization', '')
        if auth.startswith('Bearer '):
            payload = decode_jwt(auth.split(' ', 1)[1].strip())
            if not payload:
                return jsonify(success=False, error="Invalid token"), 401
            user = payload.get('sub')
            group_name = payload.get('group', user)
        else:
            return jsonify(success=False, error="Unauthorized"), 401
    else:
        user = session["user"]
        group_name = session.get("group_name", user)

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = ?", (user,))
    user_row = cur.fetchone()
    user_id = user_row['id'] if user_row else None

    if 'file' not in request.files:
        conn.close()
        return jsonify(success=False, error="No file uploaded"), 400

    file = request.files['file']
    if not file.filename.lower().endswith('.csv'):
        conn.close()
        return jsonify(success=False, error="Only CSV files are supported"), 400

    parsed = parse_and_validate_csv(file.read())
    if parsed['valid_count'] > 0:
        for txn in parsed['valid_transactions']:
            cur.execute("""
                INSERT INTO transactions (user_id, group_name, user, amount, category, type, note, date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, group_name, user, txn['amount'], txn['category'], txn['type'], txn['description'], txn['date']))
        conn.commit()

    conn.close()
    return jsonify(parsed), 200 if parsed['success'] else 400


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard", methods=["GET", "POST"])
@app.route("/personal/dashboard", methods=["GET", "POST"])
def personal_dashboard():
    """ExpenseAuditor Personal Dashboard"""

    if "user" not in session:
        return redirect(url_for("login"))

    # Role redirect if business user accesses personal dashboard directly
    if session.get("user_type") == "business" and request.path == "/dashboard":
        return redirect(url_for("business_dashboard"))

    user = session["user"]
    user_id = session.get("user_id")
    role = session.get("role", "household")
    group_name = session.get("group_name", user)
    member_name = session.get("member_name", user)
    day_limit = session.get("daily_limit", 1000)

    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        action = request.form.get("action", "transaction")

        if action == "transaction":
            amount = request.form.get("amount")
            category = request.form.get("category", "").strip()
            if category == "Other":
                category = request.form.get("category_other", "").strip() or category
            transaction_type = request.form.get("type", "expense")
            note = request.form.get("note", "").strip()
            transaction_date = request.form.get("transaction_date", "").strip()

            if not valid_amount(amount):
                conn.close()
                return redirect(url_for("personal_dashboard"))

            txn_date = date.today().isoformat()
            if transaction_date:
                try:
                    datetime.fromisoformat(transaction_date)
                    txn_date = transaction_date
                except ValueError:
                    pass

            cur.execute(
                "INSERT INTO transactions (user_id, group_name, user, amount, category, type, note, date) VALUES (?,?,?,?,?,?,?,?)",
                (
                    user_id,
                    group_name,
                    member_name,
                    float(amount),
                    category,
                    transaction_type,
                    note,
                    txn_date,
                ),
            )
            conn.commit()
            conn.close()
            return redirect(url_for("personal_dashboard"))

        if action == "goal":
            title = request.form.get("title", "").strip()
            target = request.form.get("target")
            saved = request.form.get("saved", "0")
            due_date = request.form.get("due_date")

            try:
                target_value = float(target)
                saved_value = float(saved)
            except Exception:
                conn.close()
                return redirect(url_for("personal_dashboard"))

            if not title or target_value <= 0 or saved_value < 0:
                conn.close()
                return redirect(url_for("personal_dashboard"))

            cur.execute(
                "INSERT INTO goals (group_name, user, title, target, saved, due_date) VALUES (?,?,?,?,?,?)",
                (
                    group_name,
                    member_name,
                    title,
                    target_value,
                    saved_value,
                    due_date,
                ),
            )
            conn.commit()
            conn.close()
            return redirect(url_for("personal_dashboard"))

        if action == "goal_update":
            goal_id = request.form.get("goal_id")
            target = request.form.get("target")
            saved = request.form.get("saved", "0")
            due_date = request.form.get("due_date")

            try:
                goal_id_value = int(goal_id)
                target_value = float(target)
                saved_value = float(saved)
            except Exception:
                conn.close()
                return redirect(url_for("personal_dashboard"))

            if target_value <= 0 or saved_value < 0:
                conn.close()
                return redirect(url_for("personal_dashboard"))

            cur.execute(
                """
                UPDATE goals
                SET target=?, saved=?, due_date=?
                WHERE id=? AND group_name=?
                """,
                (
                    target_value,
                    saved_value,
                    due_date,
                    goal_id_value,
                    group_name,
                ),
            )
            conn.commit()
            conn.close()
            return redirect(url_for("personal_dashboard"))

        if action == "set_limit":
            daily_limit = request.form.get("daily_limit")
            if valid_amount(daily_limit):
                session["daily_limit"] = float(daily_limit)
                cur.execute(
                    "UPDATE users SET daily_limit=? WHERE username=?",
                    (float(daily_limit), user),
                )
                conn.commit()
            conn.close()
            return redirect(url_for("personal_dashboard"))

        if action == "payment":
            amount = request.form.get("pay_amount")
            direction = request.form.get("direction", "out")
            description = request.form.get("description", "").strip()
            status = request.form.get("status", "due")
            due_date_payment = request.form.get("due_date_payment")

            if not valid_amount(amount) or not description:
                conn.close()
                return redirect(url_for("personal_dashboard"))

            cur.execute(
                "INSERT INTO payments (group_name, user, amount, direction, description, status, due_date) VALUES (?,?,?,?,?,?,?)",
                (
                    group_name,
                    member_name,
                    float(amount),
                    direction,
                    description,
                    status,
                    due_date_payment,
                ),
            )
            conn.commit()
            conn.close()
            return redirect(url_for("personal_dashboard"))

    # Fetch user transactions (user isolation)
    filter_from = request.args.get('date_from', '')
    filter_to = request.args.get('date_to', '')
    selected_month = request.args.get('month', 'current')

    query = "SELECT * FROM transactions WHERE (user_id = ? OR (user_id IS NULL AND (group_name = ? OR user = ?)))"
    params = [user_id, group_name, user]

    if filter_from:
        query += " AND date >= ?"
        params.append(filter_from)
    if filter_to:
        query += " AND date <= ?"
        params.append(filter_to)

    query += " ORDER BY date DESC, id DESC"
    cur.execute(query, tuple(params))
    all_transactions = cur.fetchall()
    tx_list = [dict(t) for t in all_transactions]

    # Pagination
    try:
        page = int(request.args.get('page', 1))
        if page < 1:
            page = 1
    except ValueError:
        page = 1

    per_page = 10
    offset = (page - 1) * per_page
    total_count = len(tx_list)
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    transactions = tx_list[offset:offset + per_page]

    # Run ExpenseAuditor Engines
    metrics = calculate_financial_metrics(tx_list, user_type='personal')
    unusual_transactions = detect_unusual_transactions(tx_list)
    duplicate_transactions = detect_duplicate_transactions(tx_list)
    monthly_summary = generate_monthly_summary(tx_list, selected_month=selected_month, user_type='personal')

    ai_result = generate_ai_recommendations(monthly_summary, user_type='personal')
    recommendations = ai_result.get('recommendations', [])[:3]
    ai_available = ai_result.get('ai_available', False)
    ai_status_message = ai_result.get('status_message', '')

    total_income = metrics['total_income']
    total_expense = metrics['total_expenses']
    net_balance = metrics['net_balance']
    savings_rate = metrics['savings_rate']
    top_5_categories = metrics.get('top_5_categories', [])

    today = date.today().isoformat()
    today_expense = sum(
        t["amount"]
        for t in tx_list
        if t["type"] == "expense" and t["date"] == today
    )

    week_expense = sum(
        t["amount"]
        for t in tx_list
        if t["type"] == "expense"
        and t["date"] and (date.today() - timedelta(days=6)).isoformat() <= t["date"] <= today
    )

    month_expense = sum(
        t["amount"]
        for t in tx_list
        if t["type"] == "expense"
        and t["date"] and t["date"][:7] == date.today().strftime('%Y-%m')
    )

    monthly_budget = session.get('monthly_budget', month_expense)
    if 'daily_limit' not in session:
        days_in_month = calendar.monthrange(date.today().year, date.today().month)[1]
        day_limit = (monthly_budget / max(1, days_in_month)) if monthly_budget else 0

    category_data = metrics.get('all_categories', [])

    # Chart data for Expense Overview (Top 5 / Breakdown)
    chart_labels = [c['category'] for c in top_5_categories] if top_5_categories else ["No Expenses"]
    chart_amounts = [c['total_amount'] for c in top_5_categories] if top_5_categories else [0]
    
    chart_data = {
        "labels": chart_labels,
        "datasets": [{
            "data": chart_amounts,
            "backgroundColor": [
                "#6366F1", "#38BDF8", "#F59E0B", "#EF4444", "#8B5CF6", "#10B981"
            ],
            "borderColor": "var(--surface)",
            "borderWidth": 2
        }]
    }

    # Monthly Trends Data
    monthly_trends = metrics.get('monthly_trends', [])
    trends_labels = [m['label'] for m in monthly_trends]
    trends_income = [m['income'] for m in monthly_trends]
    trends_expenses = [m['expenses'] for m in monthly_trends]

    trends_data = {
        "labels": trends_labels,
        "datasets": [
            {
                "label": "Income",
                "data": trends_income,
                "borderColor": "#22C55E",
                "backgroundColor": "rgba(34, 197, 94, 0.1)",
                "borderWidth": 2,
                "tension": 0.4
            },
            {
                "label": "Expenses",
                "data": trends_expenses,
                "borderColor": "#EF4444",
                "backgroundColor": "rgba(239, 68, 68, 0.1)",
                "borderWidth": 2,
                "tension": 0.4
            }
        ]
    }

    alert = ""
    if role != "business" and today_expense > float(day_limit):
        alert = "Warning: Daily expense limit crossed!"

    goals = []
    cur.execute(
        "SELECT * FROM goals WHERE group_name=? ORDER BY id DESC",
        (group_name,)
    )
    for goal in cur.fetchall():
        target = goal["target"] or 0
        saved = goal["saved"] or 0
        progress = int(min(100, (saved / target * 100) if target else 0))
        goals.append({
            "id": goal["id"],
            "title": goal["title"],
            "target": target,
            "saved": saved,
            "due_date": goal["due_date"],
            "progress": progress,
        })

    payments = []
    show_business_features = (role == "business")
    if show_business_features:
        cur.execute(
            "SELECT * FROM payments WHERE group_name=? ORDER BY id DESC",
            (group_name,)
        )
        payments = [dict(p) for p in cur.fetchall()]

    conn.close()

    return render_template(
        "dashboard_redesigned.html",
        transactions=transactions,
        page=page,
        total_pages=total_pages,
        total_income=round(total_income, 2),
        total_expense=round(total_expense, 2),
        net_balance=round(net_balance, 2),
        balance=round(net_balance, 2),
        savings_rate=savings_rate,
        today_expense=round(today_expense, 2),
        week_expense=round(week_expense, 2),
        month_expense=round(month_expense, 2),
        category_data=category_data,
        metrics=metrics,
        top_5_categories=top_5_categories,
        unusual_transactions=unusual_transactions,
        duplicate_transactions=duplicate_transactions,
        monthly_summary=monthly_summary,
        recommendations=recommendations,
        ai_available=ai_available,
        ai_status_message=ai_status_message,
        chart_data=json.dumps(chart_data),
        trends_data=json.dumps(trends_data),
        trends_labels=trends_labels,
        trends_income=trends_income,
        trends_expenses=trends_expenses,
        alert=alert,
        user=user,
        role=role,
        group_name=group_name,
        member_name=member_name,
        day_limit=round(float(day_limit), 2),
        member_limit=round(float(day_limit), 2),
        show_business_features=show_business_features,
        goals=goals,
        payments=payments,
        filter_from=filter_from,
        filter_to=filter_to,
        selected_month=selected_month,
        available_months=monthly_summary.get('available_months', []),
        monthly_budget=round(float(monthly_budget), 2),
        today_date=date.today().isoformat(),
    )


@app.route('/test-otp')
def test_otp():
    """Test page for OTP SMS functionality"""
    return render_template('test_otp.html')

@app.route('/transactions')
def transactions_page():
    if 'user' not in session:
        return redirect(url_for('login'))

    group_name = session['group_name']
    requested_date = request.args.get('date', '').strip()
    conn = get_db()
    cur = conn.cursor()

    if requested_date:
        cur.execute(
            'SELECT * FROM transactions WHERE group_name=? AND date=? ORDER BY id DESC',
            (group_name, requested_date),
        )
        rows = [dict(r) for r in cur.fetchall()]
        total_for_date = sum(r.get('amount', 0.0) for r in rows if r.get('type') == 'expense')
    else:
        cur.execute('SELECT * FROM transactions WHERE group_name=? ORDER BY id DESC', (group_name,))
        rows = [dict(r) for r in cur.fetchall()]
        total_for_date = None

    conn.close()

    return render_template(
        'transactions.html',
        transactions=rows,
        user=session.get('user'),
        date_filter=requested_date,
        total_for_date=total_for_date,
    )

@app.route('/goals', methods=['GET', 'POST'])
def goals_page():
    if 'user' not in session:
        return redirect(url_for('login'))

    group_name = session['group_name']
    conn = get_db()
    cur = conn.cursor()

    if request.method == 'POST':
        goal_id = request.form.get('goal_id')
        target = request.form.get('target')
        saved = request.form.get('saved', '0')
        due_date = request.form.get('due_date')

        try:
            goal_id_value = int(goal_id)
            target_value = float(target)
            saved_value = float(saved)
        except Exception:
            conn.close()
            return redirect(url_for('goals_page'))

        if target_value > 0 and saved_value >= 0:
            cur.execute(
                'UPDATE goals SET target=?, saved=?, due_date=? WHERE id=? AND group_name=?',
                (target_value, saved_value, due_date, goal_id_value, group_name),
            )
            conn.commit()

        conn.close()
        return redirect(url_for('goals_page'))

    cur.execute('SELECT * FROM goals WHERE group_name=? ORDER BY id DESC', (group_name,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    goals = []
    for g in rows:
        progress = int(min(100, (g['saved'] / g['target'] * 100) if g['target'] else 0))
        goals.append({
            'id': g['id'],
            'title': g['title'],
            'target': g['target'],
            'saved': g['saved'],
            'due_date': g['due_date'],
            'progress': progress,
        })

    return render_template('goals.html', goals=goals)

@app.route('/budgets', methods=['GET', 'POST'])
def budgets():
    if 'user' not in session:
        return redirect(url_for('login'))

    user = session['user']
    group_name = session.get('group_name')
    conn = get_db()
    cur = conn.cursor()

    # compute used monthly expense
    cur.execute('SELECT * FROM transactions WHERE group_name=?', (group_name,))
    txs = [dict(t) for t in cur.fetchall()]
    month_expense = sum(
        t['amount'] for t in txs
        if t.get('type') == 'expense' and datetime.fromisoformat(t.get('date')).date().month == date.today().month
    )

    # load current stored budget for user
    cur.execute('SELECT monthly_budget FROM users WHERE username=?', (user,))
    row = cur.fetchone()
    stored_budget = row['monthly_budget'] if row is not None else None

    if request.method == 'POST':
        # set/update monthly budget for this user
        mb = request.form.get('monthly_budget', '').strip()
        try:
            mb_val = float(mb) if mb else None
        except Exception:
            mb_val = None

        cur.execute('UPDATE users SET monthly_budget=? WHERE username=?', (mb_val, user))
        conn.commit()
        session['monthly_budget'] = mb_val
        stored_budget = mb_val

        return redirect(url_for('budgets'))

    # derive daily limit from stored monthly budget or used month expense
    monthly_budget = stored_budget if stored_budget is not None else month_expense
    days_in_month = calendar.monthrange(date.today().year, date.today().month)[1]
    derived_daily = (monthly_budget / max(1, days_in_month)) if monthly_budget else 0

    if stored_budget is not None and monthly_budget > 0:
        progress_pct = round(min(100, (month_expense / stored_budget) * 100), 1)
        remaining_amount = stored_budget - month_expense
        budget_status = 'On track' if month_expense <= stored_budget else 'Over budget'
        status_text = 'left' if remaining_amount >= 0 else 'over'
        remaining_label = f"₹{abs(round(remaining_amount,2)):.2f} {status_text}"
    else:
        progress_pct = 100
        remaining_amount = 0
        budget_status = 'Budget not set'
        remaining_label = 'Set a target to track progress'

    conn.close()

    budget_display = f'₹{round(float(stored_budget),2):,.2f}' if stored_budget is not None else 'Not set'

    html = f"""
    <div class="budget-hero">
      <div>
        <h3>Smart budget planning</h3>
        <p>Stay ahead of your spending with a clear monthly snapshot, daily guidance, and a progress meter designed for easy review.</p>
      </div>
      <div class="budget-summary-pill">
        <span>Monthly target</span>
        <strong>{budget_display}</strong>
      </div>
    </div>

    <div class="dashboard-grid budget-metrics">
      <div class="budget-stat">
        <span>Used this month</span>
        <div class="stat-value">₹{round(month_expense,2):,.2f}</div>
        <div class="stat-note">Current expense total for {date.today():%B %Y}</div>
      </div>
      <div class="budget-stat">
        <span>Monthly budget</span>
        <div class="stat-value">{budget_display}</div>
        <div class="stat-note">Your target amount</div>
      </div>
      <div class="budget-stat">
        <span>Daily guidance</span>
        <div class="stat-value">₹{round(float(derived_daily),2):,.2f}</div>
        <div class="stat-note">Suggested daily spend based on budget</div>
      </div>
    </div>

    <div class="budget-progress">
      <div class="progress-header">
        <div>
          <div class="progress-title">Budget progress</div>
          <div class="progress-label">{budget_status}</div>
        </div>
        <div><strong>{progress_pct}%</strong></div>
      </div>
      <div class="budget-progress-bar">
        <div class="budget-progress-fill" style="width:{progress_pct}%;"></div>
      </div>
      <div class="budget-progress-info">
        <p><strong>{budget_display}</strong> target</p>
        <p><strong>{remaining_label}</strong> remaining</p>
      </div>
    </div>

    <div class="dashboard-card budget-form-card">
      <h3>Update monthly budget</h3>
      <form method="post" class="dashboard-form">
        <div class="form-group">
          <label>Monthly budget (₹)
            <input class="form-input" name="monthly_budget" type="number" step="0.01" min="0" value="{stored_budget if stored_budget is not None else ''}">
          </label>
        </div>
        <button class="form-btn primary" type="submit">Save budget</button>
      </form>
      <div class="budget-tip">Leave this blank to continue using actual spending as your monthly benchmark.</div>
    </div>
    """

    return render_simple_page('Budgets', html)

@app.route('/calendar')
def calendar_page():
    if 'user' not in session:
        return redirect(url_for('login'))

    # show a simple monthly calendar with per-day expense totals
    user = session['user']
    group_name = session.get('group_name')

    # determine month/year to display from query params
    try:
        year = int(request.args.get('year', date.today().year))
        month = int(request.args.get('month', date.today().month))
    except Exception:
        year = date.today().year
        month = date.today().month

    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM transactions WHERE group_name=?', (group_name,))
    txs = [dict(t) for t in cur.fetchall()]

    # prepare per-day totals and transaction counts for the month
    days_in_month = calendar.monthrange(year, month)[1]
    day_info = {d: {'total': 0.0, 'count': 0} for d in range(1, days_in_month + 1)}
    for t in txs:
        if t.get('type') != 'expense':
            continue
        try:
            td = datetime.fromisoformat(t.get('date')).date()
        except Exception:
            continue
        if td.year == year and td.month == month:
            info = day_info.get(td.day)
            if info is not None:
                info['total'] += t.get('amount', 0.0)
                info['count'] += 1

    # navigation months
    prev_month = month - 1
    prev_year = year
    if prev_month < 1:
        prev_month = 12
        prev_year -= 1

    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1

    conn.close()

    return render_template(
        'calendar.html',
        year=year,
        month=month,
        month_name=calendar.month_name[month],
        days_in_month=days_in_month,
        day_info=day_info,
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month,
        user=user,
        calendar=calendar,
        date=date,
    )

@app.route('/profile')
def profile():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    user = session["user"]
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT username, email FROM users WHERE username=?", (user,))
    user_data = cur.fetchone()
    conn.close()
    
    email = user_data["email"] if user_data else ""
    
    return render_template(
        "profile.html",
        user=user,
        email=email,
        first_name="",
        last_name="",
        phone="",
        member_since="2024"
    )

@app.route('/settings')
def settings():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_simple_page('Settings', '<p>Application settings will appear here.</p>')


@app.route('/preferences')
def preferences():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    return render_template("preferences.html")


@app.route('/help-support')
def help_support():
    if 'user' not in session:
        return redirect(url_for('login'))

    user = session['user']
    user_id = session.get('user_id')
    group_name = session.get('group_name', user)
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT date, amount, type, category, note
        FROM transactions
        WHERE user_id = ? OR (user_id IS NULL AND (group_name = ? OR user = ?))
        ORDER BY date DESC, id DESC
        """,
        (user_id, group_name, user)
    )
    chat_transactions = [dict(row) for row in cur.fetchall()]
    conn.close()

    return render_template(
        "help_support.html",
        chat_transactions=json.dumps(chat_transactions),
        chat_monthly_budget=session.get('monthly_budget')
    )


@app.route('/set_member', methods=['POST'])
def set_member():
    if 'user' not in session:
        return redirect(url_for('login'))

    member_name = request.form.get('member_name', '').strip()
    if member_name:
        session['member_name'] = member_name
    else:
        session.pop('member_name', None)

    return redirect(url_for('personal_dashboard'))


# ==========================
# EXPORT CSV
# ==========================

@app.route('/export/csv')
def export_csv():

    if 'user' not in session:
        return redirect(url_for('login'))

    group_name = session['group_name']

    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT date, user, type, amount, category, note FROM transactions WHERE group_name=? ORDER BY id DESC",
        (group_name,)
    )

    rows = cur.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['date', 'user', 'type', 'amount', 'category', 'note'])

    for r in rows:
        writer.writerow([r['date'], r['user'], r['type'], r['amount'], r['category'], r['note']])

    resp = Response(output.getvalue(), mimetype='text/csv')
    resp.headers['Content-Disposition'] = 'attachment; filename=transactions.csv'

    conn.close()

    return resp


# ==========================
# EXPORT PDF
# ==========================

@app.route('/export/pdf')
def export_pdf():

    if 'user' not in session:
        return redirect(url_for('login'))

    group_name = session['group_name']

    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT date, user, type, amount, category, note FROM transactions WHERE group_name=? ORDER BY id DESC",
        (group_name,)
    )

    rows = cur.fetchall()

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    y = height - 40
    p.setFont('Helvetica-Bold', 14)
    p.drawString(40, y, f"Transactions - {group_name}")
    y -= 30
    p.setFont('Helvetica', 10)

    headers = ['Date', 'User', 'Type', 'Amount', 'Category', 'Note']
    p.drawString(40, y, ' | '.join(headers))
    y -= 18

    for r in rows:
        line = f"{r['date']} | {r['user']} | {r['type']} | {r['amount']} | {r['category']} | {r['note']}"
        p.drawString(40, y, (line[:120]))
        y -= 14
        if y < 60:
            p.showPage()
            y = height - 40
            p.setFont('Helvetica', 10)

    p.save()

    buffer.seek(0)
    resp = Response(buffer.read(), mimetype='application/pdf')
    resp.headers['Content-Disposition'] = 'attachment; filename=transactions.pdf'

    conn.close()

    return resp


# ==========================
# EXPORT EXCEL
# ==========================

@app.route('/export/xlsx')
def export_xlsx():

    if 'user' not in session:
        return redirect(url_for('login'))

    group_name = session['group_name']

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT date, user, type, amount, category, note FROM transactions WHERE group_name=? ORDER BY id DESC",
        (group_name,)
    )

    rows = cur.fetchall()

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    wb = Workbook()
    ws = wb.active
    ws.title = "Transactions"

    # Add headers
    headers = ['Date', 'User', 'Type', 'Amount', 'Category', 'Note']
    ws.append(headers)

    # Style header row
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")

    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # Add data rows
    for r in rows:
        ws.append([r['date'], r['user'], r['type'], r['amount'], r['category'], r['note']])

    # Auto-adjust column widths
    for column in ws.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except Exception:
                pass
        adjusted_width = min(max_length + 2, 50)
        ws.column_dimensions[column_letter].width = adjusted_width

    # Format amount column as currency
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=4, max_col=4):
        for cell in row:
            cell.number_format = '$#,##0.00'

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    resp = Response(buffer.getvalue(), mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp.headers['Content-Disposition'] = 'attachment; filename=transactions.xlsx'

    conn.close()

    return resp


# ==========================
# REST API - Transactions
# ==========================


@app.route('/api/transactions', methods=['GET'])
@jwt_required
def api_transactions_list():
    # pagination
    try:
        page = int(request.args.get('page', 1))
    except Exception:
        page = 1
    per_page = int(request.args.get('per_page', 20))
    offset = (page - 1) * per_page

    # determine group
    if hasattr(request, 'jwt_payload'):
        group_name = request.jwt_payload.get('group')
    else:
        group_name = session.get('group_name')

    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM transactions WHERE group_name=?', (group_name,))
    total = cur.fetchone()[0]
    cur.execute('SELECT * FROM transactions WHERE group_name=? ORDER BY id DESC LIMIT ? OFFSET ?', (group_name, per_page, offset))
    rows = cur.fetchall()
    conn.close()

    txs = [dict(r) for r in rows]
    return jsonify(success=True, transactions=txs, total=total, page=page, per_page=per_page)


@app.route('/api/transactions', methods=['POST'])
@jwt_required
def api_transactions_create():
    data = request.get_json(silent=True) or {}
    amount = data.get('amount')
    category = data.get('category','')
    ttype = data.get('type','expense')
    note = data.get('note','')

    if amount is None:
        return jsonify(success=False, error='amount required'), 400
    try:
        amount = float(amount)
    except Exception:
        return jsonify(success=False, error='invalid amount'), 400

    group_name = request.jwt_payload.get('group') if hasattr(request, 'jwt_payload') else session.get('group_name')
    user = request.jwt_payload.get('sub') if hasattr(request, 'jwt_payload') else session.get('user')

    conn = get_db()
    cur = conn.cursor()
    cur.execute('INSERT INTO transactions (group_name, user, amount, category, type, note, date) VALUES (?,?,?,?,?,?,?)', (
        group_name, user, amount, category, ttype, note, date.today().isoformat()
    ))
    conn.commit()
    conn.close()

    return jsonify(success=True)


@app.route('/api/transactions/<int:trx_id>', methods=['PUT'])
@jwt_required
def api_transactions_update(trx_id):
    data = request.get_json(silent=True) or {}
    amount = data.get('amount')
    category = data.get('category')
    ttype = data.get('type')
    note = data.get('note')

    fields = []
    params = []
    if amount is not None:
        try:
            amount = float(amount)
            fields.append('amount=?')
            params.append(amount)
        except Exception:
            return jsonify(success=False, error='invalid amount'), 400
    if category is not None:
        fields.append('category=?')
        params.append(category)
    if ttype is not None:
        fields.append('type=?')
        params.append(ttype)
    if note is not None:
        fields.append('note=?')
        params.append(note)

    if not fields:
        return jsonify(success=False, error='nothing to update'), 400

    params.append(trx_id)

    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"UPDATE transactions SET {', '.join(fields)} WHERE id=?", tuple(params))
    conn.commit()
    conn.close()

    return jsonify(success=True)


@app.route('/api/transactions/<int:trx_id>', methods=['DELETE'])
@jwt_required
def api_transactions_delete(trx_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('DELETE FROM transactions WHERE id=?', (trx_id,))
    conn.commit()
    conn.close()
    return jsonify(success=True)


# ==========================
# Recurring payments
# ==========================

@app.route('/api/recurring', methods=['POST'])
@jwt_required
def api_recurring_create():
    data = request.get_json(silent=True) or {}
    amount = data.get('amount')
    category = data.get('category','')
    ttype = data.get('type','expense')
    note = data.get('note','')
    start_date = data.get('start_date') or date.today().isoformat()
    frequency_days = int(data.get('frequency_days', 30))

    if amount is None:
        return jsonify(success=False, error='amount required'), 400
    try:
        amount = float(amount)
    except Exception:
        return jsonify(success=False, error='invalid amount'), 400

    group_name = request.jwt_payload.get('group') if hasattr(request, 'jwt_payload') else session.get('group_name')
    user = request.jwt_payload.get('sub') if hasattr(request, 'jwt_payload') else session.get('user')

    conn = get_db()
    cur = conn.cursor()
    cur.execute('INSERT INTO recurring_payments (group_name, user, amount, category, type, note, start_date, frequency_days, next_date, active) VALUES (?,?,?,?,?,?,?,?,?,?)', (
        group_name, user, amount, category, ttype, note, start_date, frequency_days, start_date, 1
    ))
    conn.commit()
    conn.close()

    return jsonify(success=True)


@app.route('/api/recurring', methods=['GET'])
@jwt_required
def api_recurring_list():
    group_name = request.jwt_payload.get('group') if hasattr(request, 'jwt_payload') else session.get('group_name')
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM recurring_payments WHERE group_name=?', (group_name,))
    rows = cur.fetchall()
    conn.close()
    return jsonify(success=True, recurring=[dict(r) for r in rows])


@app.route('/api/recurring/process', methods=['POST'])
def api_recurring_process():
    # lightweight processor: create due transactions and advance next_date
    conn = get_db()
    cur = conn.cursor()
    today = date.today().isoformat()
    cur.execute('SELECT * FROM recurring_payments WHERE active=1 AND next_date<=?', (today,))
    due = cur.fetchall()

    processed = 0
    for r in due:
        # insert transaction
        cur.execute('INSERT INTO transactions (group_name, user, amount, category, type, note, date) VALUES (?,?,?,?,?,?,?)', (
            r['group_name'], r['user'], r['amount'], r['category'], r['type'], r['note'], today
        ))
        # compute next_date
        try:
            nd = datetime.fromisoformat(r['next_date']).date() + timedelta(days=r['frequency_days'])
            cur.execute('UPDATE recurring_payments SET next_date=? WHERE id=?', (nd.isoformat(), r['id']))
        except Exception:
            pass
        processed += 1

    conn.commit()
    conn.close()
    return jsonify(success=True, processed=processed)


# ==========================
# Email notifications
# ==========================

@app.route('/api/notify/send', methods=['POST'])
@jwt_required
def api_notify_send():
    data = request.get_json(silent=True) or {}
    to = data.get('to')
    subject = data.get('subject', 'Notification')
    body = data.get('body', '')
    if not to:
        return jsonify(success=False, error='to is required'), 400
    res = send_email(to, subject, body)
    return jsonify(success=True, result=res)


# ==========================
# Forecasting
# ==========================

@app.route('/api/forecast', methods=['GET'])
@jwt_required
def api_forecast():
    # collect transactions for group
    if hasattr(request, 'jwt_payload'):
        group_name = request.jwt_payload.get('group')
    else:
        group_name = session.get('group_name')

    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT date, type, amount FROM transactions WHERE group_name=?', (group_name,))
    rows = cur.fetchall()
    conn.close()

    txs = [dict(r) for r in rows]
    res = forecast_monthly_expense(txs, months=3)
    return jsonify(success=True, forecast=res)


# =========================================================
# ADD TRANSACTION
# =========================================================

@app.route("/add_transaction", methods=["POST"])
def add_transaction():

    if "user" not in session:

        return redirect(url_for("login"))

    amount = request.form["amount"]

    if not valid_amount(amount):

        return """
        <h2>Invalid Amount</h2>

        <a href='/dashboard'>Go Back</a>
        """

    amount = float(amount)

    category = request.form["category"]

    transaction_type = request.form["type"]

    note = request.form.get("note", "").strip()

    conn = get_db()

    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO transactions(

            group_name,
            user,
            amount,
            category,
            type,
            note,
            date

        )
        VALUES(?,?,?,?,?,?,?)
        """,
        (
            session["group_name"],
            session["user"],
            amount,
            category,
            transaction_type,
            note,
            date.today().isoformat(),
        ),
    )

    conn.commit()

    conn.close()

    return redirect(url_for("personal_dashboard"))


# =========================================================
# DELETE TRANSACTION
# =========================================================

@app.route("/delete/<int:id>")
def delete_transaction(id):

    if "user" not in session:

        return redirect(url_for("login"))

    conn = get_db()

    cur = conn.cursor()

    cur.execute(
        """
        DELETE FROM transactions
        WHERE id=?
        """,
        (id,)
    )

    conn.commit()

    conn.close()

    return redirect(url_for("personal_dashboard"))


# =========================================================
# EDIT TRANSACTION
# =========================================================

@app.route("/edit/<int:id>", methods=["GET", "POST"])
def edit_transaction(id):

    if "user" not in session:

        return redirect(url_for("login"))

    conn = get_db()

    cur = conn.cursor()

    cur.execute(
        """
        SELECT * FROM transactions
        WHERE id=?
        """,
        (id,)
    )

    transaction = cur.fetchone()

    if not transaction:

        conn.close()

        return """
        <h2>Transaction Not Found</h2>
        """

    if request.method == "POST":

        amount = request.form["amount"]

        if not valid_amount(amount):

            conn.close()

            return """
            <h2>Invalid Amount</h2>

            <a href='/dashboard'>Go Back</a>
            """

        amount = float(amount)

        category = request.form["category"]
        if category == "Other":
            category = request.form.get("category_other", "").strip() or category

        transaction_type = request.form["type"]

        note = request.form["note"].strip()

        cur.execute(
            """
            UPDATE transactions

            SET
                amount=?,
                category=?,
                type=?,
                note=?

            WHERE id=?
            """,
            (
                amount,
                category,
                transaction_type,
                note,
                id,
            ),
        )

        conn.commit()

        conn.close()

        return redirect(url_for("personal_dashboard"))

    conn.close()

    return render_template(
        "edit_transaction.html",
        transaction=transaction,
        role=session.get("role", "household")
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(debug=True)
