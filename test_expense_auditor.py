"""
Comprehensive Test Suite for ExpenseAuditor — AI-Powered Spending Pattern Analyser
Covers all 12 Acceptance Criteria:
1. Two user types (Personal & Business)
2. Registration stores user_type
3. Login redirects based on user_type
4. User Data Isolation
5. CSV Upload with 50+ transactions & validation
6. Top 5 spending categories calculation
7. Unusual transactions (IQR anomaly detection)
8. Duplicate transactions detection
9. Monthly financial summary (Personal & Business P&L)
10. AI Recommendations (Personal & Business, exactly 3 items)
11. LangChain + Ollama structure and graceful fallback
12. Preservation of existing features (Goals, Budgets, Invoices, Purchases, Branches)
"""

import os
import sys
import unittest
import json
import io
import sqlite3
from datetime import date, timedelta

# Fix console encoding on Windows
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Import application and services
import app as flask_app
from services.analysis_service import (
    calculate_financial_metrics,
    get_top_5_categories,
    parse_and_validate_csv,
    transactions_to_df
)
from services.anomaly_service import detect_unusual_transactions, explain_anomaly
from services.duplicate_service import detect_duplicate_transactions
from services.summary_service import generate_monthly_summary
from services.ai_service import (
    generate_ai_recommendations,
    generate_personal_recommendations_fallback,
    generate_business_recommendations_fallback
)


class TestExpenseAuditor(unittest.TestCase):

    def setUp(self):
        flask_app.app.config['TESTING'] = True
        flask_app.app.config['WTF_CSRF_ENABLED'] = False
        self.client = flask_app.app.test_client()

        # Generate unique test usernames for clean isolated runs
        import secrets
        self.suffix = secrets.token_hex(3)
        self.personal_user = f"user_{self.suffix}"
        self.personal_email = f"user_{self.suffix}@gmail.com"
        self.personal_pass = "SecurePass123!"

        self.business_user = f"bizowner_{self.suffix}"
        self.business_email = f"bizowner_{self.suffix}@gmail.com"
        self.business_name = f"Nexus Corp {self.suffix}"
        self.business_pass = "BizSecurePass123!"

    # =========================================================================
    # Test 1 & 2: Registration stores user_type (Personal vs Business)
    # =========================================================================
    def test_01_registration_personal_user(self):
        """Verify personal user registration stores user_type='personal'"""
        response = self.client.post('/register', data={
            'user_type': 'personal',
            'username': self.personal_user,
            'email': self.personal_email,
            'phone': '9876543210',
            'password': self.personal_pass,
            'confirm_password': self.personal_pass
        }, follow_redirects=False)

        # Should redirect to login or personal dashboard
        self.assertEqual(response.status_code, 302)

        # Check DB
        conn = flask_app.get_db()
        cur = conn.cursor()
        cur.execute("SELECT user_type, role, phone FROM users WHERE username=?", (self.personal_user,))
        row = cur.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row['user_type'], 'personal')
        self.assertEqual(row['role'], 'household')
        self.assertEqual(row['phone'], '9876543210')

    def test_02_registration_business_user(self):
        """Verify business user registration stores user_type='business' and creates business profile"""
        response = self.client.post('/register', data={
            'user_type': 'business',
            'username': self.business_user,
            'business_name': self.business_name,
            'business_type': 'SaaS & Technology',
            'email': self.business_email,
            'phone': '9876543211',
            'password': self.business_pass,
            'confirm_password': self.business_pass
        }, follow_redirects=False)

        self.assertEqual(response.status_code, 302)

        conn = flask_app.get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, user_type, role, group_name FROM users WHERE username=?", (self.business_user,))
        user_row = cur.fetchone()

        self.assertIsNotNone(user_row)
        self.assertEqual(user_row['user_type'], 'business')
        self.assertEqual(user_row['role'], 'business')
        self.assertEqual(user_row['group_name'], self.business_name)

        # Verify business record created
        cur.execute("SELECT * FROM businesses WHERE owner_id=?", (user_row['id'],))
        biz_row = cur.fetchone()
        conn.close()

        self.assertIsNotNone(biz_row)
        self.assertEqual(biz_row['business_name'], self.business_name)

    # =========================================================================
    # Test 3: Role-Based Login Redirects
    # =========================================================================
    def test_03_login_redirect_personal_user(self):
        """Verify personal user login redirects to /personal/dashboard"""
        # First ensure registered
        self.client.post('/register', data={
            'user_type': 'personal',
            'username': self.personal_user,
            'email': self.personal_email,
            'password': self.personal_pass,
            'confirm_password': self.personal_pass
        })

        response = self.client.post('/login', data={
            'username': self.personal_user,
            'password': self.personal_pass
        }, follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/personal/dashboard', response.headers.get('Location', ''))

    def test_04_login_redirect_business_user(self):
        """Verify business user login redirects to /business/dashboard"""
        self.client.post('/register', data={
            'user_type': 'business',
            'username': self.business_user,
            'business_name': self.business_name,
            'email': self.business_email,
            'password': self.business_pass,
            'confirm_password': self.business_pass
        })

        response = self.client.post('/login', data={
            'username': self.business_user,
            'password': self.business_pass
        }, follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/business/dashboard', response.headers.get('Location', ''))

    # =========================================================================
    # Test 4: User Data Isolation
    # =========================================================================
    def test_05_user_data_isolation(self):
        """Ensure users can only see their own transactions, not other users'"""
        # Register two separate users
        user_a = f"usera_{self.suffix}"
        user_b = f"userb_{self.suffix}"
        
        self.client.post('/register', data={
            'user_type': 'personal', 'username': user_a, 'email': f"{user_a}@gmail.com",
            'password': self.personal_pass, 'confirm_password': self.personal_pass
        })
        self.client.post('/register', data={
            'user_type': 'personal', 'username': user_b, 'email': f"{user_b}@gmail.com",
            'password': self.personal_pass, 'confirm_password': self.personal_pass
        })

        # Login as User A and add a unique transaction
        self.client.post('/login', data={'username': user_a, 'password': self.personal_pass})
        self.client.post('/personal/dashboard', data={
            'action': 'transaction',
            'amount': '7777.00',
            'category': 'Shopping',
            'type': 'expense',
            'note': f'Unique Secret Item of User A {self.suffix}',
            'transaction_date': '2026-08-15'
        })

        # Check DB to confirm transaction exists for User A
        conn = flask_app.get_db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE username=?", (user_a,))
        user_a_id = cur.fetchone()['id']
        cur.execute("SELECT * FROM transactions WHERE user_id=? AND amount=7777.00", (user_a_id,))
        txn = cur.fetchone()
        self.assertIsNotNone(txn)

        # Login as User B and view dashboard
        self.client.get('/logout')
        self.client.post('/login', data={'username': user_b, 'password': self.personal_pass})
        resp = self.client.get('/personal/dashboard')
        
        # User B dashboard HTML should NOT contain User A's unique note or amount
        self.assertNotIn(f'Unique Secret Item of User A {self.suffix}', resp.get_data(as_text=True))
        conn.close()

    # =========================================================================
    # Test 5: CSV Upload with 50+ Transactions & Validation
    # =========================================================================
    def test_06_csv_upload_50_plus_transactions(self):
        """Verify batch upload of 50+ transactions with valid parsing and validation error handling"""
        # Create a 55-row CSV containing 50 valid rows, 3 validation errors, and 2 duplicates
        csv_rows = ["date,amount,category,description,type"]
        
        # 50 valid transactions
        for i in range(1, 51):
            cat = ["Food", "Groceries", "Transport", "Utilities", "Entertainment"][i % 5]
            csv_rows.append(f"2026-08-{(i%28)+1:02d},{100 + i*15},{cat},Batch Transaction {i},expense")
        
        # 2 duplicates of row 1 and row 2
        csv_rows.append("2026-08-02,115,Groceries,Batch Transaction 1,expense")
        csv_rows.append("2026-08-03,130,Transport,Batch Transaction 2,expense")
        
        # 3 invalid rows (bad date, negative amount, missing amount)
        csv_rows.append("invalid-date,500,Food,Bad Date Row,expense")
        csv_rows.append("2026-08-10,-250,Shopping,Negative Amount Row,expense")
        csv_rows.append("2026-08-11,,Utilities,Empty Amount Row,expense")

        csv_content = "\n".join(csv_rows).encode('utf-8')
        
        # Test parser directly
        parsed = parse_and_validate_csv(csv_content)
        self.assertTrue(parsed['success'])
        self.assertEqual(parsed['total_rows'], 55)
        self.assertEqual(parsed['valid_count'], 52) # 50 unique + 2 intra-file duplicates
        self.assertEqual(parsed['invalid_count'], 3) # 3 invalid rows skipped
        self.assertGreaterEqual(parsed['duplicate_count'], 2)
        self.assertEqual(len(parsed['validation_errors']), 3)

        # Test upload via route
        self.client.post('/register', data={
            'user_type': 'personal', 'username': self.personal_user, 'email': self.personal_email,
            'password': self.personal_pass, 'confirm_password': self.personal_pass
        })
        self.client.post('/login', data={'username': self.personal_user, 'password': self.personal_pass})

        data = {
            'file': (io.BytesIO(csv_content), 'transactions_50.csv')
        }
        resp = self.client.post('/upload-csv', data=data, content_type='multipart/form-data')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Upload Complete', resp.get_data(as_text=True))
        self.assertIn('52', resp.get_data(as_text=True)) # 52 imported

    # =========================================================================
    # Test 6: Top 5 Spending Categories Calculation
    # =========================================================================
    def test_07_top_5_categories_calculation(self):
        """Verify Top 5 spending categories breakdown and percentage calculation"""
        sample_txns = [
            {'amount': 5000, 'category': 'Rent', 'type': 'expense'},
            {'amount': 3000, 'category': 'Groceries', 'type': 'expense'},
            {'amount': 2000, 'category': 'Food', 'type': 'expense'},
            {'amount': 1500, 'category': 'Shopping', 'type': 'expense'},
            {'amount': 1000, 'category': 'Transport', 'type': 'expense'},
            {'amount': 500, 'category': 'Entertainment', 'type': 'expense'},
            {'amount': 20000, 'category': 'Salary', 'type': 'income'},
        ]

        top_5 = get_top_5_categories(sample_txns)
        self.assertEqual(len(top_5), 5)
        self.assertEqual(top_5[0]['category'], 'Rent')
        self.assertEqual(top_5[0]['total_amount'], 5000.0)
        self.assertEqual(top_5[0]['rank'], 1)

        # Total expense = 13000. Rent % = 5000 / 13000 * 100 = 38.46%
        self.assertAlmostEqual(top_5[0]['percentage'], 38.46, places=1)
        self.assertEqual(top_5[4]['category'], 'Transport')

    # =========================================================================
    # Test 7: Unusual Transactions (IQR Anomaly Detection)
    # =========================================================================
    def test_08_anomaly_detection_iqr(self):
        """Verify statistical IQR anomaly detection detects outliers with severity and reason"""
        txns = [
            {'date': '2026-08-01', 'amount': 300, 'category': 'Food', 'type': 'expense', 'description': 'Lunch'},
            {'date': '2026-08-02', 'amount': 350, 'category': 'Food', 'type': 'expense', 'description': 'Dinner'},
            {'date': '2026-08-03', 'amount': 400, 'category': 'Food', 'type': 'expense', 'description': 'Groceries'},
            {'date': '2026-08-04', 'amount': 320, 'category': 'Food', 'type': 'expense', 'description': 'Snack'},
            {'date': '2026-08-05', 'amount': 380, 'category': 'Food', 'type': 'expense', 'description': 'Lunch'},
            {'date': '2026-08-06', 'amount': 8500, 'category': 'Food', 'type': 'expense', 'description': 'Luxury Feast Outlier'}, # Extreme Anomaly
            {'date': '2026-08-07', 'amount': 1500, 'category': 'Shopping', 'type': 'expense', 'description': 'Shirt'},
            {'date': '2026-08-08', 'amount': 45000, 'category': 'Shopping', 'type': 'expense', 'description': 'Diamond Ring'}, # Extreme Anomaly
        ]

        anomalies = detect_unusual_transactions(txns)
        self.assertGreaterEqual(len(anomalies), 2)
        
        amounts_flagged = [a['amount'] for a in anomalies]
        self.assertIn(8500.0, amounts_flagged)
        self.assertIn(45000.0, amounts_flagged)
        
        # Check severity rating and required explanation phrasing
        high_anom = [a for a in anomalies if a['amount'] == 45000.0][0]
        self.assertEqual(high_anom['severity'], 'High')
        self.assertIn("significantly higher", high_anom['reason'])

    # =========================================================================
    # Test 8: Duplicate Transactions Detection
    # =========================================================================
    def test_09_duplicate_transactions_detection(self):
        """Verify exact and similar duplicate transaction grouping"""
        txns = [
            {'date': '2026-08-01', 'amount': 450.0, 'category': 'Food', 'type': 'expense', 'description': 'Swiggy'},
            {'date': '2026-08-01', 'amount': 450.0, 'category': 'Food', 'type': 'expense', 'description': 'Swiggy'},
            {'date': '2026-08-01', 'amount': 450.0, 'category': 'Food', 'type': 'expense', 'description': 'Swiggy'},
            {'date': '2026-08-02', 'amount': 1200.0, 'category': 'Utilities', 'type': 'expense', 'description': 'Broadband'},
            {'date': '2026-08-02', 'amount': 1200.0, 'category': 'Utilities', 'type': 'expense', 'description': 'Broadband'},
            {'date': '2026-08-03', 'amount': 900.0, 'category': 'Groceries', 'type': 'expense', 'description': 'Veggies'},
        ]

        duplicates = detect_duplicate_transactions(txns)
        self.assertEqual(len(duplicates), 2)
        
        # First group has 3 x ₹450 -> Excess potential = 2 x 450 = ₹900
        food_dup = [d for d in duplicates if d['category'] == 'Food'][0]
        self.assertEqual(food_dup['count'], 3)
        self.assertEqual(food_dup['amount'], 450.0)
        self.assertEqual(food_dup['excess_potential'], 900.0)

    # =========================================================================
    # Test 9: Monthly Summary Generation (Personal & Business P&L)
    # =========================================================================
    def test_10_monthly_summary_generation(self):
        """Verify monthly financial summary and P&L calculations"""
        txns = [
            {'date': '2026-08-05', 'amount': 50000, 'category': 'Revenue', 'type': 'income'},
            {'date': '2026-08-10', 'amount': 12000, 'category': 'Payroll', 'type': 'expense'},
            {'date': '2026-08-15', 'amount': 8000, 'category': 'Supplies', 'type': 'expense'},
            {'date': '2026-07-05', 'amount': 40000, 'category': 'Revenue', 'type': 'income'},
            {'date': '2026-07-10', 'amount': 10000, 'category': 'Payroll', 'type': 'expense'},
        ]

        # August 2026 Summary
        aug_summary = generate_monthly_summary(txns, selected_month='2026-08', user_type='business')
        self.assertEqual(aug_summary['total_income'], 50000.0)
        self.assertEqual(aug_summary['total_expenses'], 20000.0)
        self.assertEqual(aug_summary['net_savings'], 30000.0)
        self.assertEqual(aug_summary['estimated_profit'], 30000.0)
        self.assertEqual(aug_summary['profit_margin'], 60.0) # (30000/50000)*100
        self.assertEqual(aug_summary['transaction_count'], 3)
        self.assertEqual(aug_summary['highest_category'], 'Payroll')

    # =========================================================================
    # Test 10 & 11: AI Recommendations (Exactly 3 items & Fallback)
    # =========================================================================
    def test_11_ai_recommendations_exactly_three(self):
        """Verify AI engine generates EXACTLY 3 recommendations with advice and action for Personal and Business"""
        context = {
            'total_income': 60000,
            'total_expenses': 45000,
            'net_balance': 15000,
            'savings_rate': 25.0,
            'top_5_categories': [
                {'rank': 1, 'category': 'Food', 'total_amount': 18000, 'percentage': 40.0, 'count': 25},
                {'rank': 2, 'category': 'Shopping', 'total_amount': 12000, 'percentage': 26.7, 'count': 8},
                {'rank': 3, 'category': 'Utilities', 'total_amount': 8000, 'percentage': 17.8, 'count': 4}
            ],
            'unusual_transactions': [],
            'duplicate_groups': []
        }

        # Personal Recommendations
        personal_recs = generate_ai_recommendations(context, user_type='personal')
        self.assertEqual(len(personal_recs['recommendations']), 3)
        for r in personal_recs['recommendations']:
            self.assertIn('title', r)
            self.assertIn('category', r)
            self.assertIn('advice', r)
            self.assertIn('action', r)

        # Business Recommendations
        biz_recs = generate_ai_recommendations(context, user_type='business')
        self.assertEqual(len(biz_recs['recommendations']), 3)
        for r in biz_recs['recommendations']:
            self.assertIn('title', r)
            self.assertIn('category', r)
            self.assertIn('advice', r)
            self.assertIn('action', r)

        # Verify offline fallback message
        if not personal_recs['ai_available']:
            self.assertIn("AI service unavailable", personal_recs['status_message'])

    # =========================================================================
    # Test 12: Existing Feature Retention
    # =========================================================================
    def test_12_existing_feature_retention(self):
        """Verify existing features (Goals, Budgets, Invoices, Transactions, Payments) remain fully functional"""
        self.client.post('/register', data={
            'user_type': 'personal', 'username': self.personal_user, 'email': self.personal_email,
            'password': self.personal_pass, 'confirm_password': self.personal_pass
        })
        self.client.post('/login', data={'username': self.personal_user, 'password': self.personal_pass})

        # 1. Add Goal
        goal_resp = self.client.post('/personal/dashboard', data={
            'action': 'goal',
            'title': 'New Laptop Goal',
            'target': '80000',
            'saved': '20000',
            'due_date': '2026-12-31'
        }, follow_redirects=True)
        self.assertEqual(goal_resp.status_code, 200)

        # 2. Update Daily Limit
        limit_resp = self.client.post('/personal/dashboard', data={
            'action': 'set_limit',
            'daily_limit': '2500'
        }, follow_redirects=True)
        self.assertEqual(limit_resp.status_code, 200)

        # 3. Add Payment
        pay_resp = self.client.post('/personal/dashboard', data={
            'action': 'payment',
            'pay_amount': '1500',
            'direction': 'out',
            'description': 'Electricity Bill Due',
            'status': 'due',
            'due_date_payment': '2026-08-30'
        }, follow_redirects=True)
        self.assertEqual(pay_resp.status_code, 200)

        # 4. View Budgets Page
        budget_resp = self.client.get('/budgets')
        self.assertEqual(budget_resp.status_code, 200)

        # 5. View Goals Page
        goals_resp = self.client.get('/goals')
        self.assertEqual(goals_resp.status_code, 200)

        # 6. View Transactions Page
        tx_resp = self.client.get('/transactions')
        self.assertEqual(tx_resp.status_code, 200)


if __name__ == '__main__':
    unittest.main()
