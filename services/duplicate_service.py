"""
Duplicate Transaction Detection Service for ExpenseAuditor
Identifies potential duplicate charges and payments based on date, amount, category, and description.
"""

from typing import List, Dict, Any, Union
import pandas as pd
from services.analysis_service import transactions_to_df


def detect_duplicate_transactions(transactions: Union[List[Dict[str, Any]], pd.DataFrame]) -> List[Dict[str, Any]]:
    """
    Detect potentially duplicate transactions and return grouped duplicate sets.
    
    Args:
        transactions: List of transaction dicts or DataFrame
        
    Returns:
        List of duplicate groups, where each group contains:
        - group_id
        - match_criteria (e.g., 'Exact match on Date, Amount, Category, and Description')
        - items: list of transaction objects
        - total_duplicated_amount: combined sum of duplicates
        - potential_excess: excess amount charged due to duplication
    """
    df = transactions_to_df(transactions)
    if df.empty or len(df) < 2:
        return []

    # Clean description for normalization
    df['clean_desc'] = df['description'].astype(str).str.strip().str.lower()
    df['clean_cat'] = df['category'].astype(str).str.strip().str.lower()
    df['clean_date'] = df['date'].astype(str).str.strip()
    df['round_amount'] = df['amount'].round(2)

    duplicate_groups = []
    seen_indices = set()

    # Step 1: Exact match on (date, round_amount, clean_cat, clean_desc, type)
    exact_groups = df.groupby(['clean_date', 'round_amount', 'clean_cat', 'clean_desc', 'type'])
    for (dt, amt, cat, desc, typ), group in exact_groups:
        if len(group) > 1:
            indices = set(group.index)
            seen_indices.update(indices)
            items = []
            for _, row in group.iterrows():
                items.append({
                    'id': row.get('id', None),
                    'date': str(row['date']),
                    'amount': float(row['round_amount']),
                    'category': str(row['category']),
                    'description': str(row.get('description') or row.get('note') or ''),
                    'type': str(row['type']),
                    'user': str(row.get('user', ''))
                })
            
            duplicate_groups.append({
                'group_id': f"DUP-{len(duplicate_groups) + 1}",
                'match_type': 'Exact Duplicate',
                'description': f"Same Date, Amount (₹{amt:,.2f}), Category ({cat.title()}), and Description",
                'count': len(items),
                'single_amount': float(amt),
                'total_amount': round(float(amt) * len(items), 2),
                'potential_excess': round(float(amt) * (len(items) - 1), 2),
                'items': items
            })

    # Step 2: Match on (date, round_amount, clean_cat, type) for remaining rows (same amount & category on same day)
    remaining_df = df[~df.index.isin(seen_indices)]
    if not remaining_df.empty:
        similar_groups = remaining_df.groupby(['clean_date', 'round_amount', 'clean_cat', 'type'])
        for (dt, amt, cat, typ), group in similar_groups:
            if len(group) > 1:
                items = []
                for _, row in group.iterrows():
                    items.append({
                        'id': row.get('id', None),
                        'date': str(row['date']),
                        'amount': float(row['round_amount']),
                        'category': str(row['category']),
                        'description': str(row.get('description') or row.get('note') or ''),
                        'type': str(row['type']),
                        'user': str(row.get('user', ''))
                    })
                
                duplicate_groups.append({
                    'group_id': f"DUP-{len(duplicate_groups) + 1}",
                    'match_type': 'Potential Similar Duplicate',
                    'description': f"Same Date ({dt}), Amount (₹{amt:,.2f}), and Category ({cat.title()})",
                    'count': len(items),
                    'single_amount': float(amt),
                    'total_amount': round(float(amt) * len(items), 2),
                    'potential_excess': round(float(amt) * (len(items) - 1), 2),
                    'items': items
                })

    return duplicate_groups
