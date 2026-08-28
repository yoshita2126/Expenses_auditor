"""
Monthly Financial Summary Service for ExpenseAuditor
Calculates monthly financial summaries, profit/loss statements, and category metrics for personal and business users.
"""

from typing import List, Dict, Any, Optional, Union
import pandas as pd
from datetime import datetime, date
import calendar
from services.analysis_service import transactions_to_df
from services.anomaly_service import detect_unusual_transactions
from services.duplicate_service import detect_duplicate_transactions


def get_available_months(transactions: Union[List[Dict[str, Any]], pd.DataFrame]) -> List[Dict[str, str]]:
    """Get list of distinct months available in transaction history sorted descending."""
    df = transactions_to_df(transactions)
    if df.empty:
        today_ym = date.today().strftime('%Y-%m')
        return [{'value': today_ym, 'label': date.today().strftime('%B %Y')}]

    valid_df = df[df['year_month'] != 'Unknown']
    if valid_df.empty:
        today_ym = date.today().strftime('%Y-%m')
        return [{'value': today_ym, 'label': date.today().strftime('%B %Y')}]

    unique_yms = sorted(valid_df['year_month'].unique(), reverse=True)
    months = []
    for ym in unique_yms:
        try:
            dt = datetime.strptime(ym, '%Y-%m')
            label = dt.strftime('%B %Y')
        except Exception:
            label = ym
        months.append({'value': ym, 'label': label})

    return months


def generate_monthly_summary(
    transactions: Union[List[Dict[str, Any]], pd.DataFrame],
    selected_month: Optional[str] = None,
    user_type: str = 'personal'
) -> Dict[str, Any]:
    """
    Generate complete monthly financial summary for personal or business account.
    
    Args:
        transactions: List of transaction dicts or DataFrame
        selected_month: 'YYYY-MM', 'current', 'previous', or None (defaults to latest available or current)
        user_type: 'personal' or 'business'
        
    Returns:
        Structured monthly summary dictionary.
    """
    df = transactions_to_df(transactions)
    available_months = get_available_months(df)
    
    # Determine the target year_month
    today_ym = date.today().strftime('%Y-%m')
    
    if not selected_month or selected_month == 'current':
        if available_months:
            target_ym = available_months[0]['value']
        else:
            target_ym = today_ym
    elif selected_month == 'previous':
        if len(available_months) > 1:
            target_ym = available_months[1]['value']
        else:
            # Fallback calculate previous month
            today = date.today()
            first = today.replace(day=1)
            prev = first - pd.Timedelta(days=1)
            target_ym = prev.strftime('%Y-%m')
    else:
        target_ym = selected_month

    # Filter dataframe by target month
    if not df.empty and target_ym != 'all':
        month_df = df[df['year_month'] == target_ym].copy()
    else:
        month_df = df.copy()

    # Format human-readable label
    try:
        dt = datetime.strptime(target_ym, '%Y-%m')
        month_label = dt.strftime('%B %Y')
    except Exception:
        month_label = target_ym if target_ym != 'all' else 'All Time'

    income_df = month_df[month_df['type'] == 'income']
    expense_df = month_df[month_df['type'] == 'expense']

    total_income = float(income_df['amount'].sum())
    total_expenses = float(expense_df['amount'].sum())
    net_savings = total_income - total_expenses
    
    # Calculate savings rate or profit margin
    rate = round((net_savings / total_income * 100), 2) if total_income > 0 else 0.0

    # Highest spending category in this month
    highest_category = "None"
    highest_category_amount = 0.0
    highest_category_pct = 0.0
    
    if not expense_df.empty:
        cat_sums = expense_df.groupby('category')['amount'].sum().sort_values(ascending=False)
        if not cat_sums.empty:
            highest_category = str(cat_sums.index[0])
            highest_category_amount = round(float(cat_sums.iloc[0]), 2)
            if total_expenses > 0:
                highest_category_pct = round((highest_category_amount / total_expenses * 100), 1)

    # Detect unusual & duplicate transactions in this month
    unusual_txns = detect_unusual_transactions(month_df)
    duplicate_groups = detect_duplicate_transactions(month_df)
    
    # Calculate daily average for the month
    try:
        year, month = map(int, target_ym.split('-'))
        days_in_month = calendar.monthrange(year, month)[1]
    except Exception:
        days_in_month = 30
        
    avg_daily_spend = round(total_expenses / max(1, days_in_month), 2)

    summary = {
        'selected_month': target_ym,
        'month_label': month_label,
        'available_months': available_months,
        'user_type': user_type,
        
        # Core KPIs
        'total_income': round(total_income, 2),
        'total_expenses': round(total_expenses, 2),
        'net_savings': round(net_savings, 2),
        'savings_rate': rate,
        'profit_margin': rate,
        'transaction_count': int(len(month_df)),
        'expense_count': int(len(expense_df)),
        'income_count': int(len(income_df)),
        
        # Highlights
        'highest_spending_category': highest_category,
        'highest_spending_amount': highest_category_amount,
        'highest_spending_percentage': highest_category_pct,
        'avg_daily_spend': avg_daily_spend,
        
        # Anomaly & Duplicate counts
        'unusual_transactions_count': len(unusual_txns),
        'unusual_transactions': unusual_txns,
        'duplicate_transactions_count': sum(len(g['items']) for g in duplicate_groups),
        'duplicate_groups_count': len(duplicate_groups),
        'duplicate_groups': duplicate_groups,
    }

    # Add specific Business KPIs
    if user_type == 'business':
        summary['revenue'] = round(total_income, 2)
        summary['operating_expenses'] = round(total_expenses, 2)
        summary['estimated_profit'] = round(net_savings, 2)
        summary['highest_business_cost'] = highest_category
        summary['highest_business_cost_amount'] = highest_category_amount
        
        # Sub-category checks (supplier, inventory, employee)
        supplier_expenses = float(expense_df[expense_df['category'].str.lower().str.contains('supplier|vendor|procurement|raw', na=False)]['amount'].sum())
        inventory_expenses = float(expense_df[expense_df['category'].str.lower().str.contains('inventory|stock|goods|merchandise', na=False)]['amount'].sum())
        employee_expenses = float(expense_df[expense_df['category'].str.lower().str.contains('salary|payroll|employee|wage|staff|bonus', na=False)]['amount'].sum())
        
        summary['supplier_expenses'] = round(supplier_expenses, 2)
        summary['inventory_expenses'] = round(inventory_expenses, 2)
        summary['employee_expenses'] = round(employee_expenses, 2)

    return summary
