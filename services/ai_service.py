"""
AI Service for ExpenseAuditor
Integrates LangChain and Ollama with intelligent pattern analysis and robust offline fallback.
Provides exactly 3 personalised recommendations for Personal and Business accounts,
anomaly explanations, and interactive advisory chat.
"""

import os
import json
import re
from typing import Any, Dict, List, Optional
import requests
from collections import Counter
from datetime import datetime


def get_ollama_client():
    """Try to initialize LangChain ChatOllama or return None if unavailable."""
    try:
        from langchain_ollama import ChatOllama
        ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        ollama_model = os.environ.get("OLLAMA_MODEL", "llama3.2")
        llm = ChatOllama(base_url=ollama_host, model=ollama_model, timeout=15)
        return llm
    except Exception:
        return None


def generate_personal_recommendations_fallback(context: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Generate exactly 3 high-quality deterministic recommendations for Personal users
    based on observed transaction data when AI is unavailable.
    """
    recs = []
    top_5 = context.get('top_5_categories', [])
    anomalies = context.get('unusual_transactions', [])
    duplicates = context.get('duplicate_groups', [])
    savings_rate = context.get('savings_rate', 0)
    total_expense = context.get('total_expenses', 0)
    total_income = context.get('total_income', 0)

    # 1. Top spending category optimization
    if top_5:
        top_cat = top_5[0]
        cat_name = top_cat['category']
        cat_amt = top_cat['total_amount']
        cat_pct = top_cat['percentage']
        target_reduction = round(cat_amt * 0.15, 2)
        recs.append({
            'title': f"Optimise {cat_name} spending by 15%",
            'category': cat_name,
            'advice': f"{cat_name} accounts for {cat_pct}% of your total expenses (₹{cat_amt:,.2f}). Trimming non-essential {cat_name.lower()} expenses by 15% would save approximately ₹{target_reduction:,.2f} monthly.",
            'action': f"Set a monthly {cat_name} budget cap of ₹{round(cat_amt * 0.85, 2):,.2f}."
        })
    else:
        recs.append({
            'title': "Track daily expenses consistently",
            'category': "Budgeting",
            'advice': "Log every transaction to build an accurate baseline for automated categorization and predictive savings.",
            'action': "Set a daily spending reminder and review weekly totals."
        })

    # 2. Address anomalies or duplicate transactions
    if duplicates:
        dup = duplicates[0]
        recs.append({
            'title': "Review potential duplicate transactions",
            'category': "Duplicate Audit",
            'advice': f"Detected {len(duplicates)} duplicate group(s) totaling ₹{sum(d.get('potential_excess', 0) for d in duplicates):,.2f} in potential duplicate charges.",
            'action': "Verify billing statements with your merchant or bank to dispute duplicate charges."
        })
    elif anomalies:
        anom = anomalies[0]
        recs.append({
            'title': f"Audit high-value transaction in {anom['category']}",
            'category': anom['category'],
            'advice': f"Flagged ₹{anom['amount']:,.2f} on {anom['date']} for {anom['description']}, which is {anom.get('comparison_ratio', 2)}x higher than your typical {anom['category']} expense.",
            'action': "Review whether this was a planned one-off expense or if future limits are needed."
        })
    elif len(top_5) > 1:
        second_cat = top_5[1]
        recs.append({
            'title': f"Monitor secondary spending in {second_cat['category']}",
            'category': second_cat['category'],
            'advice': f"{second_cat['category']} represents ₹{second_cat['total_amount']:,.2f} ({second_cat['percentage']}%) of overall expenses across {second_cat['count']} transactions.",
            'action': "Look for bundled subscriptions or alternatives to reduce recurring fees."
        })
    else:
        recs.append({
            'title': "Build an emergency fund reserve",
            'category': "Savings",
            'advice': f"Current net balance is ₹{context.get('net_balance', 0):,.2f}. Aim to keep at least 3 months of essential living expenses reserved in a liquid account.",
            'action': "Automate a monthly transfer of 10-20% of net income into savings."
        })

    # 3. Savings rate or budget discipline
    if savings_rate < 20 and total_income > 0:
        gap = round((total_income * 0.20) - max(0, context.get('net_balance', 0)), 2)
        recs.append({
            'title': "Target a 20% baseline savings rate",
            'category': "Savings Target",
            'advice': f"Your current savings rate is {savings_rate}%. Saving an additional ₹{max(1000, gap):,.2f} per month will reach the recommended 20% financial wellness benchmark.",
            'action': "Adopt the 50/30/20 budgeting rule (Needs / Wants / Savings)."
        })
    elif len(top_5) > 2:
        third_cat = top_5[2]
        recs.append({
            'title': f"Control recurring {third_cat['category']} expenses",
            'category': third_cat['category'],
            'advice': f"Third highest expense category is {third_cat['category']} with ₹{third_cat['total_amount']:,.2f} total spend.",
            'action': f"Audit recurring bills in {third_cat['category']} before the next monthly billing cycle."
        })
    else:
        recs.append({
            'title': "Automate savings at the start of each month",
            'category': "Goal Planning",
            'advice': "Transfer savings immediately upon receiving salary rather than saving what remains at month-end.",
            'action': "Set up auto-debit rules on pay day into your high-yield savings account."
        })

    return recs[:3]


def generate_business_recommendations_fallback(context: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Generate exactly 3 high-quality deterministic recommendations for Business users
    based on observed transaction data when AI is unavailable.
    """
    recs = []
    top_5 = context.get('top_5_categories', [])
    anomalies = context.get('unusual_transactions', [])
    duplicates = context.get('duplicate_groups', [])
    profit_margin = context.get('profit_margin', 0)
    total_revenue = context.get('total_income', 0)
    total_expenses = context.get('total_expenses', 0)

    # 1. Top Business Cost Category Optimization
    if top_5:
        top_cost = top_5[0]
        cat_name = top_cost['category']
        cat_amt = top_cost['total_amount']
        cat_pct = top_cost['percentage']
        target_saving = round(cat_amt * 0.10, 2)
        recs.append({
            'title': f"Renegotiate top cost driver ({cat_name})",
            'category': cat_name,
            'advice': f"{cat_name} represents {cat_pct}% of total operating expenditures (₹{cat_amt:,.2f}). Negotiating a 10% volume discount or contract revision can improve operating cash flow by ₹{target_saving:,.2f}.",
            'action': "Request updated quote tiers or benchmark alternative vendors."
        })
    else:
        recs.append({
            'title': "Streamline operational cost tracking",
            'category': "Operations",
            'advice': "Maintain granular categorization for vendor payables and inventory orders to identify margin leaks.",
            'action': "Reconcile vendor invoices weekly against purchase orders."
        })

    # 2. Duplicate Payments / Anomaly Audits
    if duplicates:
        recs.append({
            'title': "Prevent duplicate vendor payments & double-billing",
            'category': "Payment Controls",
            'advice': f"Identified {len(duplicates)} potential duplicate payment cluster(s) with combined potential excess of ₹{sum(d.get('potential_excess', 0) for d in duplicates):,.2f}.",
            'action': "Enforce 2-way matching on vendor invoices and PO numbers before release."
        })
    elif anomalies:
        anom = anomalies[0]
        recs.append({
            'title': f"Audit high-variance expenditure in {anom['category']}",
            'category': anom['category'],
            'advice': f"Unusual outlay of ₹{anom['amount']:,.2f} recorded on {anom['date']} ({anom['description']}), exceeding standard category thresholds.",
            'action': "Verify receipt justification and ensure proper departmental pre-approval."
        })
    elif len(top_5) > 1:
        second_cost = top_5[1]
        recs.append({
            'title': f"Optimize secondary operating cost in {second_cost['category']}",
            'category': second_cost['category'],
            'advice': f"{second_cost['category']} expenses total ₹{second_cost['total_amount']:,.2f} across {second_cost['count']} transactions.",
            'action': "Consolidate recurring procurement to leverage bulk purchasing rates."
        })
    else:
        recs.append({
            'title': "Implement strict internal spending caps",
            'category': "Cost Control",
            'advice': "Set department-level monthly spending limits to prevent unexpected operational expense spikes.",
            'action': "Establish mandatory sign-off thresholds for expenses exceeding ₹10,000."
        })

    # 3. Margin Enhancement & Cash Flow Management
    if profit_margin < 25 and total_revenue > 0:
        recs.append({
            'title': "Improve net operating profit margin",
            'category': "Profitability",
            'advice': f"Current estimated profit margin is {profit_margin}%. A 5% reduction in recurring overheads combined with optimized pricing can increase net margins.",
            'action': "Conduct a quarterly pricing and supplier cost audit."
        })
    elif len(top_5) > 2:
        third_cost = top_5[2]
        recs.append({
            'title': f"Review recurring vendor contracts for {third_cost['category']}",
            'category': third_cost['category'],
            'advice': f"{third_cost['category']} represents ₹{third_cost['total_amount']:,.2f} ({third_cost['percentage']}%) of overall business spend.",
            'action': "Evaluate annualized contract values against actual departmental utilization."
        })
    else:
        recs.append({
            'title': "Maintain a 45-day operational cash buffer",
            'category': "Working Capital",
            'advice': "Ensure reserves cover at least 45 to 60 days of fixed operating expenses to insulate against payment delays.",
            'action': "Accelerate accounts receivable collection cycles with early-payment incentives."
        })

    return recs[:3]


def generate_ai_recommendations(
    analysis_context: Dict[str, Any],
    user_type: str = 'personal'
) -> Dict[str, Any]:
    """
    Generate exactly 3 personalised financial recommendations using LangChain + Ollama.
    Falls back gracefully to deterministic rule-based analysis if AI service is offline.
    
    Args:
        analysis_context: Structured dictionary containing KPIs, top 5 categories, anomalies, duplicates, etc.
        user_type: 'personal' or 'business'
        
    Returns:
        Dictionary containing:
        - recommendations: List of exactly 3 recommendation dicts (title, category, advice, action)
        - ai_available: bool
        - status_message: str
        - model_used: Optional[str]
    """
    # Check if Ollama is available
    llm = get_ollama_client()
    
    if not llm:
        # Fallback to local rule engine
        if user_type == 'business':
            recs = generate_business_recommendations_fallback(analysis_context)
        else:
            recs = generate_personal_recommendations_fallback(analysis_context)
            
        return {
            'recommendations': recs,
            'ai_available': False,
            'status_message': "AI service unavailable — basic financial analysis is still available.",
            'model_used': None
        }

    # Format structured context for the prompt
    top_5_str = "\n".join([
        f"- {c['rank']}. {c['category']}: ₹{c['total_amount']:,.2f} ({c['percentage']}% of total, {c['count']} txns)"
        for c in analysis_context.get('top_5_categories', [])
    ]) or "No expense categories recorded."

    anomalies_str = "\n".join([
        f"- {a['date']} | ₹{a['amount']:,.2f} in {a['category']} ({a['description']}) -> {a['reason']}"
        for a in analysis_context.get('unusual_transactions', [])[:3]
    ]) or "None detected."

    duplicates_str = "\n".join([
        f"- {d['match_type']}: {d['description']} ({d['count']} items, ₹{d['total_amount']:,.2f} total)"
        for d in analysis_context.get('duplicate_groups', [])[:2]
    ]) or "None detected."

    if user_type == 'business':
        prompt = f"""You are ExpenseAuditor AI, a senior business financial consultant.
Analyze the following verified financial summary:

[BUSINESS FINANCIAL METRICS]
Total Revenue: ₹{analysis_context.get('total_income', 0):,.2f}
Total Operating Expenses: ₹{analysis_context.get('total_expenses', 0):,.2f}
Estimated Profit: ₹{analysis_context.get('net_balance', 0):,.2f}
Profit Margin: {analysis_context.get('profit_margin', 0)}%

[TOP 5 EXPENSE CATEGORIES]
{top_5_str}

[UNUSUAL TRANSACTIONS]
{anomalies_str}

[POTENTIAL DUPLICATE PAYMENTS]
{duplicates_str}

CRITICAL RULES:
1. Generate EXACTLY 3 actionable cost-optimisation recommendations for this business.
2. Every recommendation MUST reference specific observed numbers, categories, suppliers, or patterns from the data above.
3. DO NOT invent financial data or speculate outside the provided metrics.
4. Focus on: Supplier costs, Inventory costs, Operational expenses, High-cost categories, Duplicate payments, Profit improvement.

Respond ONLY with valid JSON in this exact structure, with no markdown formatting around it:
[
  {{
    "title": "Short punchy title (max 8 words)",
    "category": "Category or Feature Name",
    "advice": "Detailed observation citing specific numbers from the data (2-3 sentences)",
    "action": "Clear actionable next step"
  }},
  {{
    "title": "...",
    "category": "...",
    "advice": "...",
    "action": "..."
  }},
  {{
    "title": "...",
    "category": "...",
    "advice": "...",
    "action": "..."
  }}
]"""
    else:
        prompt = f"""You are ExpenseAuditor AI, a senior personal financial advisor.
Analyze the following verified personal spending summary:

[PERSONAL FINANCIAL METRICS]
Total Income: ₹{analysis_context.get('total_income', 0):,.2f}
Total Expenses: ₹{analysis_context.get('total_expenses', 0):,.2f}
Net Savings: ₹{analysis_context.get('net_balance', 0):,.2f}
Savings Rate: {analysis_context.get('savings_rate', 0)}%

[TOP 5 SPENDING CATEGORIES]
{top_5_str}

[POTENTIALLY UNUSUAL TRANSACTIONS]
{anomalies_str}

[POTENTIAL DUPLICATE CHARGES]
{duplicates_str}

CRITICAL RULES:
1. Generate EXACTLY 3 actionable, personalised recommendations for this individual.
2. Every recommendation MUST reference specific observed numbers, categories, or spending patterns from the data above.
3. DO NOT invent financial data or speculate outside the provided metrics.
4. Focus on: Food expenses, Shopping, Transportation, Subscriptions, Entertainment, Savings, Budget optimisation.

Respond ONLY with valid JSON in this exact structure, with no markdown formatting around it:
[
  {{
    "title": "Short punchy title (max 8 words)",
    "category": "Category Name",
    "advice": "Detailed observation citing specific numbers from the data (2-3 sentences)",
    "action": "Clear actionable next step"
  }},
  {{
    "title": "...",
    "category": "...",
    "advice": "...",
    "action": "..."
  }},
  {{
    "title": "...",
    "category": "...",
    "advice": "...",
    "action": "..."
  }}
]"""

    try:
        response = llm.invoke(prompt)
        content = response.content.strip()
        
        # Clean potential markdown code blocks
        if "```" in content:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
            if match:
                content = match.group(1).strip()

        parsed = json.loads(content)
        if isinstance(parsed, list) and len(parsed) >= 3:
            recs = parsed[:3]
            return {
                'recommendations': recs,
                'ai_available': True,
                'status_message': "AI recommendations generated successfully via Ollama.",
                'model_used': getattr(llm, 'model', 'ollama')
            }
    except Exception:
        # Fallback to rule engine on parse/invoke failure
        pass

    if user_type == 'business':
        recs = generate_business_recommendations_fallback(analysis_context)
    else:
        recs = generate_personal_recommendations_fallback(analysis_context)

    return {
        'recommendations': recs,
        'ai_available': False,
        'status_message': "AI service unavailable — basic financial analysis is still available.",
        'model_used': None
    }


def explain_anomaly(transaction: Dict[str, Any], category_avg: float, global_median: float) -> str:
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


# =====================================================================
# Legacy AI functions preserved for backward compatibility
# =====================================================================

def generate_insights(transactions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate basic insights from a list of transaction dicts (preserved for backward compatibility)."""
    insights = {}
    if not transactions:
        insights['summary'] = 'No transactions available for insights.'
        insights['top_categories'] = []
        return insights

    total_income = sum(t['amount'] for t in transactions if t['type'] == 'income')
    total_expense = sum(t['amount'] for t in transactions if t['type'] == 'expense')
    insights['total_income'] = round(total_income, 2)
    insights['total_expense'] = round(total_expense, 2)
    insights['net'] = round(total_income - total_expense, 2)

    categories = [t.get('category') or 'Uncategorized' for t in transactions if t['type'] == 'expense']
    cat_counts = Counter(categories)
    top = cat_counts.most_common(5)
    insights['top_categories'] = [{'category': c, 'count': n} for c, n in top]

    dates = {}
    for t in transactions:
        d = t.get('date')
        try:
            day = datetime.fromisoformat(d).date()
        except Exception:
            continue
        dates.setdefault(day, 0)
        if t['type'] == 'expense':
            dates[day] += t['amount']

    if dates:
        avg_daily = sum(dates.values()) / len(dates)
        insights['avg_daily_expense'] = round(avg_daily, 2)
    else:
        insights['avg_daily_expense'] = 0

    tips = []
    if insights['avg_daily_expense'] > 1000:
        tips.append('Your average daily expense is high; consider reviewing recurring costs.')
    if top and top[0][1] > 3:
        tips.append(f"Top category: {top[0][0]} — try setting a budget for it.")

    insights['tips'] = tips
    return insights


def chat_with_ai(messages: List[Dict[str, str]], system_prompt: str = None) -> Dict[str, Any]:
    """Chat with AI using Ollama or OpenAI fallback."""
    llm = get_ollama_client()
    if llm:
        try:
            full_prompt = (system_prompt + "\n\n" if system_prompt else "")
            for m in messages:
                full_prompt += f"{m.get('role', 'user').title()}: {m.get('content', '')}\n"
            resp = llm.invoke(full_prompt)
            return {
                'success': True,
                'message': resp.content,
                'model': getattr(llm, 'model', 'ollama')
            }
        except Exception as e:
            pass

    api_key = os.environ.get('OPENAI_API_KEY')
    if api_key:
        try:
            request_messages = []
            if system_prompt:
                request_messages.append({'role': 'system', 'content': system_prompt})
            request_messages.extend(messages)
            response = requests.post(
                'https://api.openai.com/v1/chat/completions',
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json={'model': 'gpt-4o-mini', 'messages': request_messages, 'max_tokens': 1000, 'temperature': 0.7},
                timeout=20
            )
            if response.ok:
                data = response.json()
                return {'success': True, 'message': data['choices'][0]['message']['content'], 'model': data.get('model')}
        except Exception:
            pass

    return {
        'success': True,
        'message': "I am ExpenseAuditor AI. You can review your categorized spending, track potential duplicates, and audit unusual transactions directly in your dashboard.",
        'model': 'local-assistant'
    }


def get_expense_advisor_response(user_message: str, transactions: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Get financial advice from AI based on user financial data."""
    context = ""
    if transactions:
        total_income = sum(t['amount'] for t in transactions if t['type'] == 'income')
        total_expense = sum(t['amount'] for t in transactions if t['type'] == 'expense')
        context = f"\nUser Financial Context:\n- Total Income: ₹{total_income:,.2f}\n- Total Expenses: ₹{total_expense:,.2f}\n- Net: ₹{total_income - total_expense:,.2f}"
    
    system_prompt = (
        "You are a helpful financial advisor for ExpenseAuditor, an AI-powered spending pattern analyzer. "
        "Provide practical, actionable financial advice based strictly on user financial context."
    )
    return chat_with_ai([{'role': 'user', 'content': user_message + context}], system_prompt)


def estimate_daily_saving_amount(goal_title: str, target_amount: float, current_saved: float, 
                                 due_date: str, avg_daily_expense: float = None, 
                                 monthly_income: float = None) -> Dict[str, Any]:
    """Estimate daily saving amount needed to reach goal."""
    try:
        today = datetime.now().date()
        target_date = datetime.strptime(due_date, '%Y-%m-%d').date()
        days_remaining = (target_date - today).days
        
        if days_remaining <= 0:
            return {'success': False, 'error': 'Target date has already passed'}
        
        amount_needed = target_amount - current_saved
        if amount_needed <= 0:
            return {
                'success': True,
                'daily_amount': 0,
                'recommendation': f'Congratulations! You have already reached your goal of ₹{target_amount:,.2f}!'
            }
        
        daily_required = amount_needed / days_remaining
        return {
            'success': True,
            'daily_amount': round(daily_required, 2),
            'simple_daily_requirement': round(daily_required, 2),
            'days_remaining': days_remaining,
            'recommendation': f'To reach your goal of ₹{target_amount:,.2f}, save ₹{daily_required:,.2f} daily for the next {days_remaining} days.'
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}
