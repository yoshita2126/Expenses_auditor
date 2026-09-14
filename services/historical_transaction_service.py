"""Calendar-aware historical transaction queries for the authenticated chat assistant."""

import calendar
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]


def add_months(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(index, 12)
    return date(year, month_index + 1, 1)


def month_range(year: int, month: int) -> Tuple[date, date]:
    start = date(year, month, 1)
    return start, add_months(start, 1)


def resolve_date_range(text: str, today: Optional[date] = None) -> Optional[Tuple[date, date, str]]:
    """Resolve supported natural-language month references to a half-open range."""
    today = today or date.today()
    value = text.lower()
    current = date(today.year, today.month, 1)

    if "last 6 months" in value:
        start, end = add_months(current, -6), current
        return start, end, f"{start.strftime('%B %Y')} to {add_months(end, -1).strftime('%B %Y')}"
    if "last 3 months" in value:
        start, end = add_months(current, -3), current
        return start, end, f"{start.strftime('%B %Y')} to {add_months(end, -1).strftime('%B %Y')}"
    if "two months ago" in value or "2 months ago" in value:
        start, end = add_months(current, -2), add_months(current, -1)
        return start, end, start.strftime("%B %Y")
    if "three months ago" in value or "3 months ago" in value:
        start, end = add_months(current, -3), add_months(current, -2)
        return start, end, start.strftime("%B %Y")
    if "last month" in value or "previous month" in value:
        start, end = add_months(current, -1), current
        return start, end, start.strftime("%B %Y")
    if "this month" in value or "current month" in value:
        start, end = current, add_months(current, 1)
        return start, end, start.strftime("%B %Y")
    if "last year" in value:
        start = date(today.year - 1, 1, 1)
        return start, date(today.year, 1, 1), str(today.year - 1)
    if "this year" in value:
        start = date(today.year, 1, 1)
        return start, date(today.year + 1, 1, 1), str(today.year)

    range_match = re.search(
        r"(?:from|between)\s+(%s)(?:\s+(\d{4}))?\s+(?:to|and)\s+(%s)(?:\s+(\d{4}))?" %
        ("|".join(MONTH_NAMES), "|".join(MONTH_NAMES)), value
    )
    if range_match:
        first = MONTH_NAMES.index(range_match.group(1)) + 1
        second = MONTH_NAMES.index(range_match.group(3)) + 1
        year = int(range_match.group(2) or range_match.group(4) or today.year)
        end_year = year + 1 if second <= first else year
        start = date(year, first, 1)
        end = add_months(date(end_year, second, 1), 1)
        return start, end, f"{start.strftime('%B %Y')} to {add_months(end, -1).strftime('%B %Y')}"

    month_match = re.search(r"\b(%s)(?:\s+(\d{4}))?\b" % "|".join(MONTH_NAMES), value)
    if month_match:
        month = MONTH_NAMES.index(month_match.group(1)) + 1
        year = int(month_match.group(2) or today.year)
        start, end = month_range(year, month)
        return start, end, start.strftime("%B %Y")
    return None


def filter_transactions(transactions: List[Dict[str, Any]], start: date, end: date) -> List[Dict[str, Any]]:
    result = []
    for transaction in transactions:
        try:
            transaction_date = date.fromisoformat(str(transaction.get("date"))[:10])
        except (TypeError, ValueError):
            continue
        if start <= transaction_date < end:
            result.append(transaction)
    return sorted(result, key=lambda item: str(item.get("date", "")), reverse=True)


def money(amount: float) -> str:
    return f"₹{amount:,.2f}"


def historical_response(message: str, transactions: List[Dict[str, Any]]) -> Optional[str]:
    """Return a deterministic response for historical transaction questions."""
    value = message.lower()
    resolved = resolve_date_range(value)
    if not resolved:
        return None
    start, end, label = resolved

    month_without_year = re.search(r"\b(%s)\b" % "|".join(MONTH_NAMES), value)
    if month_without_year and not re.search(r"\b%s\s+\d{4}\b" % month_without_year.group(1), value):
        matching_years = sorted({str(item.get("date", ""))[:4] for item in transactions if str(item.get("date", ""))[5:7] == f"{MONTH_NAMES.index(month_without_year.group(1)) + 1:02d}"})
        if len(matching_years) > 1:
            return f"Which {month_without_year.group(1).title()} do you mean — " + " or ".join(matching_years) + "?"

    period = filter_transactions(transactions, start, end)
    expenses = [t for t in period if str(t.get("type", "expense")).lower() == "expense"]

    if not period:
        return f"I couldn't find any transactions for {label}."

    category_match = re.search(r"(?:on|for)\s+([a-z][a-z &-]{2,30}?)(?:\s+(?:last|previous|this|in|from|between)|\?|$)", value)
    category = category_match.group(1).strip() if category_match else None
    if category:
        matching = [t for t in expenses if category in str(t.get("category", "")).lower() or category in str(t.get("note", "")).lower()]
        total = sum(float(t.get("amount") or 0) for t in matching)
        return f"You spent {money(total)} on {category.title()} during {label}, across {len(matching)} transaction{'s' if len(matching) != 1 else ''}." if matching else f"I couldn't find any {category.title()} expenses for {label}."

    if "biggest" in value or "largest" in value or "top expense" in value:
        ranked = sorted(expenses, key=lambda item: float(item.get("amount") or 0), reverse=True)
        details = "; ".join(
            f"{item.get('date')} — {item.get('note') or item.get('category') or 'Expense'} — {money(float(item.get('amount') or 0))}"
            for item in ranked[:5]
        )
        return f"Your biggest expenses in {label}: {details}."

    if "categories" in value or "category" in value and "what" in value:
        category_totals: Dict[str, float] = {}
        for item in expenses:
            category = item.get("category") or "Uncategorized"
            category_totals[category] = category_totals.get(category, 0) + float(item.get("amount") or 0)
        summary = "; ".join(f"{category}: {money(amount)}" for category, amount in sorted(category_totals.items(), key=lambda pair: pair[1], reverse=True))
        return f"Your spending categories for {label}: {summary or 'No expense categories recorded.'}"

    if "last 3 months" in value or "last 6 months" in value or "spending" in value and ("months" in value or "trend" in value):
        monthly: Dict[str, float] = {}
        for item in expenses:
            month = str(item.get("date", ""))[:7]
            monthly[month] = monthly.get(month, 0) + float(item.get("amount") or 0)
        summary = "; ".join(f"{month}: {money(amount)}" for month, amount in sorted(monthly.items()))
        return f"Your expense trend for {label}: {summary or 'No expense totals available.'}"

    total = sum(float(item.get("amount") or 0) for item in expenses)
    if "how much" in value or "total" in value or "spend" in value or "spent" in value:
        return f"You spent {money(total)} during {label}, across {len(expenses)} expense{'s' if len(expenses) != 1 else ''}."

    details = "\n".join(
        f"{item.get('date')} — {item.get('note') or item.get('category') or 'Transaction'} — {item.get('category') or 'Uncategorized'} — {money(float(item.get('amount') or 0))}"
        for item in period[:20]
    )
    suffix = f"\nShowing 20 of {len(period)} transactions." if len(period) > 20 else ""
    return f"{label} transactions:\n{details}\n\nTotal expenses: {money(sum(float(item.get('amount') or 0) for item in expenses))}.{suffix}"
