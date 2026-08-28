"""
Analysis Service for ExpenseAuditor
Provides Pandas-powered financial analysis and category aggregations.
"""

from typing import List, Dict, Any, Optional, Union
import pandas as pd
import numpy as np
from datetime import datetime


def transactions_to_df(transactions: Union[List[Dict[str, Any]], pd.DataFrame]) -> pd.DataFrame:
    """Convert transaction dicts/rows to a standardized pandas DataFrame."""
    if isinstance(transactions, pd.DataFrame):
        df = transactions.copy()
    elif not transactions:
        df = pd.DataFrame(columns=['id', 'date', 'amount', 'category', 'description', 'type', 'user_id'])
    else:
        df = pd.DataFrame(transactions)

    # Standardize column names if note is used instead of description
    if 'note' in df.columns and 'description' not in df.columns:
        df['description'] = df['note']
    elif 'description' in df.columns and 'note' not in df.columns:
        df['note'] = df['description']

    # Ensure required columns exist
    for col in ['date', 'amount', 'category', 'description', 'type']:
        if col not in df.columns:
            df[col] = ''

    # Clean data types
    df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0.0)
    df['type'] = df['type'].astype(str).str.strip().str.lower()
    df['category'] = df['category'].astype(str).str.strip().replace({'': 'Uncategorized', 'nan': 'Uncategorized', 'None': 'Uncategorized'})
    df['description'] = df['description'].astype(str).str.strip()
    df['date'] = df['date'].astype(str).str.strip()

    # Parse dates safely
    df['parsed_date'] = pd.to_datetime(df['date'], errors='coerce')
    df['year_month'] = df['parsed_date'].dt.strftime('%Y-%m').fillna('Unknown')
    
    return df


def calculate_financial_metrics(transactions: Union[List[Dict[str, Any]], pd.DataFrame], user_type: str = 'personal') -> Dict[str, Any]:
    """
    Calculate comprehensive financial metrics using pandas.
    
    Args:
        transactions: List of transaction dicts or DataFrame
        user_type: 'personal' or 'business'
        
    Returns:
        Structured dictionary with metrics, top 5 categories, monthly trends, etc.
    """
    df = transactions_to_df(transactions)
    
    if df.empty or len(df) == 0:
        return {
            'total_income': 0.0,
            'total_expenses': 0.0,
            'net_balance': 0.0,
            'savings_rate': 0.0,
            'profit_margin': 0.0,
            'transaction_count': 0,
            'avg_expense': 0.0,
            'avg_income': 0.0,
            'top_5_categories': [],
            'all_categories': [],
            'monthly_trends': [],
            'user_type': user_type
        }

    income_df = df[df['type'] == 'income']
    expense_df = df[df['type'] == 'expense']

    total_income = float(income_df['amount'].sum())
    total_expenses = float(expense_df['amount'].sum())
    net_balance = total_income - total_expenses
    
    # Calculate savings rate or profit margin
    if total_income > 0:
        rate = round((net_balance / total_income) * 100, 2)
    else:
        rate = 0.0

    avg_expense = float(expense_df['amount'].mean()) if not expense_df.empty else 0.0
    avg_income = float(income_df['amount'].mean()) if not income_df.empty else 0.0

    # Top 5 expense categories
    top_5_categories = get_top_5_categories(df)
    
    # All category breakdowns
    all_categories = get_category_breakdown(df)

    # Monthly trends
    monthly_trends = get_monthly_trends(df)

    return {
        'total_income': round(total_income, 2),
        'total_expenses': round(total_expenses, 2),
        'net_balance': round(net_balance, 2),
        'savings_rate': rate,
        'profit_margin': rate,
        'transaction_count': int(len(df)),
        'expense_count': int(len(expense_df)),
        'income_count': int(len(income_df)),
        'avg_expense': round(avg_expense, 2),
        'avg_income': round(avg_income, 2),
        'top_5_categories': top_5_categories,
        'all_categories': all_categories,
        'monthly_trends': monthly_trends,
        'user_type': user_type
    }


def get_top_5_categories(df_or_list: Union[List[Dict[str, Any]], pd.DataFrame]) -> List[Dict[str, Any]]:
    """
    Calculate top 5 expense categories with total amount, count, and percentage of total expenses.
    """
    df = transactions_to_df(df_or_list)
    expense_df = df[df['type'] == 'expense']
    
    if expense_df.empty:
        return []

    total_expense = float(expense_df['amount'].sum())
    if total_expense <= 0:
        return []

    grouped = expense_df.groupby('category').agg(
        total_amount=('amount', 'sum'),
        count=('amount', 'count'),
        avg_amount=('amount', 'mean')
    ).reset_index()

    grouped = grouped.sort_values(by='total_amount', ascending=False).head(5)
    
    top_5 = []
    for rank, (_, row) in enumerate(grouped.iterrows(), 1):
        amt = float(row['total_amount'])
        pct = round((amt / total_expense) * 100, 1) if total_expense > 0 else 0.0
        top_5.append({
            'rank': rank,
            'category': str(row['category']),
            'total_amount': round(amt, 2),
            'count': int(row['count']),
            'avg_amount': round(float(row['avg_amount']), 2),
            'percentage': pct
        })

    return top_5


def get_category_breakdown(df_or_list: Union[List[Dict[str, Any]], pd.DataFrame]) -> List[Dict[str, Any]]:
    """Get breakdown of all categories for expenses and income."""
    df = transactions_to_df(df_or_list)
    if df.empty:
        return []

    total_expense = float(df[df['type'] == 'expense']['amount'].sum())
    
    breakdown = []
    for (category, tx_type), group in df.groupby(['category', 'type']):
        amt = float(group['amount'].sum())
        pct = round((amt / total_expense * 100), 1) if (tx_type == 'expense' and total_expense > 0) else 0.0
        breakdown.append({
            'category': str(category),
            'type': str(tx_type),
            'total_amount': round(amt, 2),
            'count': int(len(group)),
            'avg_amount': round(float(group['amount'].mean()), 2),
            'percentage': pct
        })
        
    return sorted(breakdown, key=lambda x: (x['type'], -x['total_amount']))


def get_monthly_trends(df_or_list: Union[List[Dict[str, Any]], pd.DataFrame]) -> List[Dict[str, Any]]:
    """Calculate monthly income, expense, and net savings trends."""
    df = transactions_to_df(df_or_list)
    if df.empty:
        return []

    # Exclude invalid dates
    valid_df = df[df['year_month'] != 'Unknown']
    if valid_df.empty:
        return []

    monthly_summary = []
    months = sorted(valid_df['year_month'].unique())
    
    for ym in months:
        m_df = valid_df[valid_df['year_month'] == ym]
        inc = float(m_df[m_df['type'] == 'income']['amount'].sum())
        exp = float(m_df[m_df['type'] == 'expense']['amount'].sum())
        net = inc - exp
        
        # Human-readable month name
        try:
            dt = datetime.strptime(ym, '%Y-%m')
            label = dt.strftime('%b %Y')
        except Exception:
            label = ym

        monthly_summary.append({
            'year_month': ym,
            'label': label,
            'income': round(inc, 2),
            'expenses': round(exp, 2),
            'net': round(net, 2),
            'count': int(len(m_df))
        })

    return monthly_summary


def parse_and_validate_csv(file_stream_or_str: Union[str, bytes, Any]) -> Dict[str, Any]:
    """
    Parse and validate CSV transaction data.
    
    Supports at least 50+ transactions.
    Validates:
    - Required columns: date, amount, category, description (or note), type
    - Date format (YYYY-MM-DD or standard parseable dates)
    - Numeric positive amounts
    - Valid transaction types ('income' or 'expense')
    - Missing values and dirty data
    - Intra-file duplicate rows
    
    Returns structured results:
    {
        'success': bool,
        'valid_transactions': List[Dict],
        'validation_errors': List[Dict],
        'total_rows': int,
        'valid_count': int,
        'invalid_count': int,
        'duplicate_count': int,
        'message': str
    }
    """
    import io
    import csv

    if isinstance(file_stream_or_str, bytes):
        text = file_stream_or_str.decode('utf-8', errors='replace')
    elif isinstance(file_stream_or_str, str):
        text = file_stream_or_str
    else:
        # File-like object
        try:
            content = file_stream_or_str.read()
            if isinstance(content, bytes):
                text = content.decode('utf-8', errors='replace')
            else:
                text = str(content)
        except Exception as e:
            return {
                'success': False,
                'valid_transactions': [],
                'validation_errors': [{'row': 0, 'error': f'Failed to read file: {str(e)}'}],
                'total_rows': 0,
                'valid_count': 0,
                'invalid_count': 0,
                'duplicate_count': 0,
                'message': f"Failed to read CSV: {str(e)}"
            }

    if not text.strip():
        return {
            'success': False,
            'valid_transactions': [],
            'validation_errors': [{'row': 0, 'error': 'CSV file is empty'}],
            'total_rows': 0,
            'valid_count': 0,
            'invalid_count': 0,
            'duplicate_count': 0,
            'message': 'Uploaded CSV is empty'
        }

    # Normalize newlines
    lines = text.strip().splitlines()
    if len(lines) < 2:
        return {
            'success': False,
            'valid_transactions': [],
            'validation_errors': [{'row': 1, 'error': 'CSV must contain a header and at least one transaction row'}],
            'total_rows': len(lines),
            'valid_count': 0,
            'invalid_count': len(lines),
            'duplicate_count': 0,
            'message': 'CSV does not contain any transaction rows'
        }

    # Read using csv.reader to handle quotes and commas properly
    reader = csv.reader(io.StringIO(text))
    try:
        raw_header = next(reader)
    except StopIteration:
        return {
            'success': False,
            'valid_transactions': [],
            'validation_errors': [{'row': 0, 'error': 'No header row found'}],
            'total_rows': 0,
            'valid_count': 0,
            'invalid_count': 0,
            'duplicate_count': 0,
            'message': 'No header row found'
        }

    header = [col.strip().lower().replace(' ', '_') for col in raw_header]

    # Map possible synonyms to standard names
    col_map = {}
    for idx, col in enumerate(header):
        if col in ['date', 'txn_date', 'transaction_date', 'datetime']:
            col_map['date'] = idx
        elif col in ['amount', 'amt', 'value', 'price', 'total']:
            col_map['amount'] = idx
        elif col in ['category', 'cat', 'expense_category']:
            col_map['category'] = idx
        elif col in ['description', 'desc', 'note', 'details', 'particulars', 'narration']:
            col_map['description'] = idx
        elif col in ['type', 'txn_type', 'transaction_type', 'dr_cr']:
            col_map['type'] = idx

    # Check essential columns
    missing_cols = []
    for req in ['date', 'amount']:
        if req not in col_map:
            missing_cols.append(req)

    if missing_cols:
        return {
            'success': False,
            'valid_transactions': [],
            'validation_errors': [{'row': 1, 'error': f"Missing essential column(s): {', '.join(missing_cols)}"}],
            'total_rows': len(lines) - 1,
            'valid_count': 0,
            'invalid_count': len(lines) - 1,
            'duplicate_count': 0,
            'message': f"CSV is missing required headers: {', '.join(missing_cols)}"
        }

    valid_transactions = []
    validation_errors = []
    seen_rows = set()
    duplicate_count = 0
    row_num = 1

    for row in reader:
        row_num += 1
        # Skip empty lines
        if not row or not any(cell.strip() for cell in row):
            continue

        row_dict = {}
        for col_name, idx in col_map.items():
            row_dict[col_name] = row[idx].strip() if idx < len(row) else ''

        # 1. Validate Date
        raw_date = row_dict.get('date', '').strip()
        parsed_date = None
        if not raw_date:
            validation_errors.append({
                'row': row_num,
                'error': 'Missing transaction date',
                'raw_data': row_dict
            })
            continue

        try:
            # Handle common date formats (YYYY-MM-DD, DD-MM-YYYY, MM/DD/YYYY)
            dt = pd.to_datetime(raw_date, dayfirst=False, errors='coerce')
            if pd.isna(dt):
                dt = pd.to_datetime(raw_date, dayfirst=True, errors='coerce')
            if pd.isna(dt):
                raise ValueError(f"Invalid date: {raw_date}")
            parsed_date = dt.strftime('%Y-%m-%d')
        except Exception:
            validation_errors.append({
                'row': row_num,
                'error': f"Invalid date format: '{raw_date}'. Use YYYY-MM-DD",
                'raw_data': row_dict
            })
            continue

        # 2. Validate Amount
        raw_amount = row_dict.get('amount', '').strip().replace('$', '').replace('₹', '').replace(',', '')
        try:
            amount_val = float(raw_amount)
            if amount_val <= 0 or np.isnan(amount_val):
                validation_errors.append({
                    'row': row_num,
                    'error': f"Amount must be a positive number greater than 0 (got '{raw_amount}')",
                    'raw_data': row_dict
                })
                continue
        except (ValueError, TypeError):
            validation_errors.append({
                'row': row_num,
                'error': f"Invalid numeric amount: '{raw_amount}'",
                'raw_data': row_dict
            })
            continue

        # 3. Validate Type
        raw_type = row_dict.get('type', '').strip().lower()
        if not raw_type:
            # Default to expense if not specified
            txn_type = 'expense'
        elif raw_type in ['expense', 'debit', 'dr', 'out', 'exp']:
            txn_type = 'expense'
        elif raw_type in ['income', 'credit', 'cr', 'in', 'rev', 'revenue']:
            txn_type = 'income'
        else:
            validation_errors.append({
                'row': row_num,
                'error': f"Invalid transaction type: '{raw_type}'. Allowed values: 'expense' or 'income'",
                'raw_data': row_dict
            })
            continue

        # 4. Clean Category and Description
        category = row_dict.get('category', '').strip()
        if not category or category.lower() in ['nan', 'none', 'null']:
            category = 'General' if txn_type == 'expense' else 'Income'

        description = row_dict.get('description', '').strip()
        if not description or description.lower() in ['nan', 'none', 'null']:
            description = category

        # 5. Check for intra-CSV duplicates
        row_signature = (parsed_date, round(amount_val, 2), category.lower(), description.lower(), txn_type)
        if row_signature in seen_rows:
            duplicate_count += 1
        seen_rows.add(row_signature)

        valid_transactions.append({
            'date': parsed_date,
            'amount': round(amount_val, 2),
            'category': category,
            'description': description,
            'type': txn_type,
            'row_number': row_num
        })

    total_valid = len(valid_transactions)
    total_invalid = len(validation_errors)
    
    if total_valid > 0:
        msg = f"Successfully parsed {total_valid} transaction(s)."
        if total_invalid > 0:
            msg += f" {total_invalid} row(s) contained validation errors and were skipped."
        if duplicate_count > 0:
            msg += f" {duplicate_count} potential intra-file duplicate(s) detected."
    else:
        msg = f"No valid transactions could be parsed. {total_invalid} validation error(s) found."

    return {
        'success': total_valid > 0,
        'valid_transactions': valid_transactions,
        'validation_errors': validation_errors,
        'total_rows': total_valid + total_invalid,
        'valid_count': total_valid,
        'invalid_count': total_invalid,
        'duplicate_count': duplicate_count,
        'message': msg
    }

