"""
Anomaly Detection Service for ExpenseAuditor
Uses Interquartile Range (IQR) and category-relative statistical thresholds to detect unusual transactions.
"""

from typing import List, Dict, Any, Union
import pandas as pd
import numpy as np
from services.analysis_service import transactions_to_df


def detect_unusual_transactions(
    transactions: Union[List[Dict[str, Any]], pd.DataFrame],
    iqr_multiplier: float = 1.5,
    min_category_samples: int = 3
) -> List[Dict[str, Any]]:
    """
    Detect potentially unusual expense transactions using IQR and category-relative statistics.
    
    Args:
        transactions: List of transaction dicts or DataFrame
        iqr_multiplier: Multiplier for IQR threshold (default 1.5 for standard outliers)
        min_category_samples: Minimum transactions in a category before applying category-specific IQR
        
    Returns:
        List of flagged unusual transaction dicts with explanation, reason, and severity.
    """
    df = transactions_to_df(transactions)
    if df.empty:
        return []

    expense_df = df[df['type'] == 'expense'].copy()
    if expense_df.empty:
        return []

    # Calculate global expense statistics
    global_median = float(expense_df['amount'].median())
    global_mean = float(expense_df['amount'].mean())
    global_q1 = float(expense_df['amount'].quantile(0.25))
    global_q3 = float(expense_df['amount'].quantile(0.75))
    global_iqr = global_q3 - global_q1
    global_threshold = global_q3 + (iqr_multiplier * global_iqr) if global_iqr > 0 else (global_mean * 2.5)

    anomalies = []

    # Group by category for localized anomaly detection
    for category, cat_df in expense_df.groupby('category'):
        cat_amounts = cat_df['amount']
        cat_count = len(cat_df)
        cat_mean = float(cat_amounts.mean())
        cat_median = float(cat_amounts.median())

        if cat_count >= min_category_samples:
            q1 = float(cat_amounts.quantile(0.25))
            q3 = float(cat_amounts.quantile(0.75))
            iqr = q3 - q1
            cat_threshold = q3 + (iqr_multiplier * iqr) if iqr > 0 else (cat_mean * 2.0)
            # Ensure category threshold is at least 1.5x median or mean
            cat_threshold = max(cat_threshold, cat_median * 1.5, cat_mean * 1.4)
        else:
            # For small category sizes, combine category mean with global metrics
            cat_threshold = max(cat_mean * 2.0, global_threshold * 0.8)

        for idx, row in cat_df.iterrows():
            amt = float(row['amount'])
            
            is_anomaly = False
            severity = "Moderate"
            reason = ""
            comparison_ratio = 1.0

            # Condition 1: Exceeds category threshold and is noticeably high
            if amt > cat_threshold and amt > cat_median:
                is_anomaly = True
                comparison_ratio = round(amt / cat_mean, 1) if cat_mean > 0 else 2.0
                
                if comparison_ratio >= 3.5 or (global_iqr > 0 and amt > global_q3 + 3.0 * global_iqr):
                    severity = "High"
                elif comparison_ratio >= 2.0:
                    severity = "Medium"
                else:
                    severity = "Moderate"

                reason = (
                    f"Amount ₹{amt:,.2f} is {comparison_ratio}x higher than your normal "
                    f"{category} spending pattern (average ₹{cat_mean:,.2f})."
                )

            # Condition 2: High global outlier even if category threshold is high
            elif amt > (global_q3 + 2.5 * global_iqr) and global_iqr > 0 and amt > (cat_median * 1.5):
                is_anomaly = True
                comparison_ratio = round(amt / global_median, 1) if global_median > 0 else 2.0
                severity = "High"
                reason = (
                    f"Amount ₹{amt:,.2f} is significantly higher than overall spending "
                    f"(median expense ₹{global_median:,.2f})."
                )

            if is_anomaly:
                anomalies.append({
                    'id': row.get('id', None),
                    'date': str(row['date']),
                    'amount': round(amt, 2),
                    'category': str(category),
                    'description': str(row.get('description') or row.get('note') or 'No description'),
                    'type': 'expense',
                    'reason': reason,
                    'severity': severity,
                    'comparison_ratio': comparison_ratio,
                    'category_avg': round(cat_mean, 2),
                    'headline': f"Potentially unusual transaction in {category}"
                })

    # Sort anomalies by severity (High > Medium > Moderate) and amount descending
    severity_order = {'High': 0, 'Medium': 1, 'Moderate': 2}
    anomalies.sort(key=lambda x: (severity_order.get(x['severity'], 3), -x['amount']))

    return anomalies


def explain_anomaly(transaction: Dict[str, Any], category_avg: float = 0, global_median: float = 0) -> str:
    """Generate a clear explanation for why a transaction was flagged as unusual."""
    amt = transaction.get('amount', 0)
    cat = transaction.get('category', 'Expense')
    
    if category_avg > 0:
        ratio = round(amt / category_avg, 1)
        return (
            f"Your typical {cat} transaction is ₹{category_avg:,.2f}, while this transaction is ₹{amt:,.2f}. "
            f"This is {ratio}x higher than your normal spending pattern in this category."
        )
    elif global_median > 0:
        ratio = round(amt / global_median, 1)
        return (
            f"Your median overall expense is ₹{global_median:,.2f}, while this transaction is ₹{amt:,.2f}. "
            f"This represents a significant outlier in your spending history."
        )
    else:
        return f"This transaction of ₹{amt:,.2f} is significantly higher than your recorded baseline."

