#!/usr/bin/env python3
"""
Response Formatter - Creates clean WhatsApp messages
No markdown symbols (* _ ~) - just plain text with emojis
"""

from datetime import datetime


def format_expense_confirmation(result):
    """Format expense confirmation for WhatsApp"""

    expense = result['expense']
    budget = result.get('budget', {})
    anomaly = result.get('anomaly', {})

    # Budget progress bar
    bar = ""
    if budget.get('exists'):
        pct = budget['percentage']
        filled = int(pct / 5)
        empty = 20 - filled
        bar_visual = '█' * filled + '░' * empty

        bar = (
            f"\n"
            f"\n"
            f":bar_chart: {expense['category'].title()} Budget\n"
            f"${budget['currentSpend']:.0f} / ${budget['monthlyLimit']:.0f} ({pct}%)\n"
            f"{bar_visual}\n"
            f"Remaining: ${budget['remaining']:.0f}"
        )

    msg = (
        f":white_check_mark: Expense Logged!\n"
        f"\n"
        f":moneybag: Amount: ${expense['amount']:.2f}\n"
        f":file_folder: Category: {expense['category'].title()}\n"
        f":convenience_store: Vendor: {expense.get('vendor', 'Unknown')}\n"
        f":bust_in_silhouette: By: {result['userName']}"
        f"{bar}"
    )

    if anomaly.get('isAnomaly'):
        severity_icon = ':rotating_light:' if anomaly['severity'] == 'high' else ':warning:'
        msg += (
            f"\n\n"
            f"{severity_icon} Unusual Expense!\n"
            f"{anomaly['reason']}"
        )

    if budget.get('exists') and budget['percentage'] >= 80:
        msg += (
            f"\n\n"
            f":warning: Budget Alert!\n"
            f"Only ${budget['remaining']:.0f} left for {expense['category']}!"
        )

    return msg


def format_error_message(error_type):
    """Format error messages"""

    messages = {
        'no_amount': ":x: I couldn't find an amount.\n\nTry: Spent $45 on groceries",
        'not_registered': (
            ":wave: Welcome! You're not registered yet.\n"
            "\n"
            "Your phone number wasn't found in our system.\n"
            "Ask your family admin to add your number."
        ),
        'system_error': ":x: Oops! Something went wrong. Please try again."
    }

    return messages.get(error_type, messages['system_error'])


# Test
if __name__ == '__main__':
    test_result = {
        'expense': {
            'amount': 45.00,
            'category': 'groceries',
            'vendor': 'Walmart'
        },
        'budget': {
            'exists': True,
            'monthlyLimit': 500,
            'currentSpend': 380,
            'remaining': 120,
            'percentage': 76
        },
        'anomaly': {'isAnomaly': False},
        'userName': 'Mom'
    }

    print(format_expense_confirmation(test_result))