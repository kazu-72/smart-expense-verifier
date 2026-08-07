#!/usr/bin/env python3
"""
WhatsApp Bot for Smart Expense Verifier
This is the main server that receives WhatsApp messages
"""

import json
import sys
import os

# Add paths so we can import from other folders
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
LAMBDA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LAMBDA_ROOT)

from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import boto3
from datetime import datetime

# ============================================================
# CONFIGURATION
# ============================================================

# Load Twilio credentials
TWILIO_SID = None
TWILIO_TOKEN = None
TWILIO_WHATSAPP = None

credentials_path = os.path.join(PROJECT_ROOT, 'twilio_credentials.txt')
print(f":open_file_folder: Looking for credentials at: {credentials_path}")

try:
    with open(credentials_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line.startswith('TWILIO_ACCOUNT_SID='):
                TWILIO_SID = line.split('=', 1)[1]
            elif line.startswith('TWILIO_AUTH_TOKEN='):
                TWILIO_TOKEN = line.split('=', 1)[1]
            elif line.startswith('TWILIO_WHATSAPP_NUMBER='):
                TWILIO_WHATSAPP = line.split('=', 1)[1]

    print(f":white_check_mark: Twilio SID: {TWILIO_SID[:10]}...")
    print(f":white_check_mark: Twilio WhatsApp: {TWILIO_WHATSAPP}")

except FileNotFoundError:
    print(":x: twilio_credentials.txt not found!")
    print(f"   Expected at: {credentials_path}")
    print("   Create it with your Twilio credentials")
    sys.exit(1)

# Twilio client
twilio_client = Client(TWILIO_SID, TWILIO_TOKEN)

# DynamoDB
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
users_table = dynamodb.Table('SEV_Users')

# Import expense processor
from expense_processor.app import process_expense  # type: ignore

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def get_user_by_phone(phone):
    """
    Look up user by their WhatsApp phone number
    """
    try:
        # Remove 'whatsapp:' prefix that Twilio adds
        clean_phone = phone.replace('whatsapp:', '').strip()

        print(f":mag: Looking up user with phone: {clean_phone}")

        response = users_table.query(
            IndexName='phone-index',
            KeyConditionExpression='phone = :phone',
            ExpressionAttributeValues={':phone': clean_phone}
        )

        items = response.get('Items', [])

        if items:
            print(f":white_check_mark: Found user: {items[0]['name']}")
            return items[0]
        else:
            print(f":warning:  No user found for phone: {clean_phone}")

            # Debug: Show all users in database
            all_users = users_table.scan()
            print(f":clipboard: Users in database:")
            for user in all_users.get('Items', []):
                print(f"   - {user['name']}: {user['phone']}")

            return None

    except Exception as e:
        print(f":x: Error looking up user: {str(e)}")
        return None


def format_expense_response(result):
    """
    Format a clean WhatsApp response message (no markdown symbols)
    """
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
            f":bar_chart: {expense['category'].title()} Budget\n"
            f"${budget['currentSpend']:.0f} / ${budget['monthlyLimit']:.0f} ({pct}%)\n"
            f"{bar_visual}\n"
            f"Remaining: ${budget['remaining']:.0f}"
        )

    # Main message
    msg = (
        f":white_check_mark: Expense Logged!\n"
        f"\n"
        f":moneybag: Amount: ${expense['amount']:.2f}\n"
        f":file_folder: Category: {expense['category'].title()}\n"
        f":convenience_store: Vendor: {expense.get('vendor', 'Unknown')}\n"
        f":bust_in_silhouette: By: {result['userName']}"
        f"{bar}"
    )

    # Anomaly warning
    if anomaly.get('isAnomaly'):
        severity_icon = ':rotating_light:' if anomaly['severity'] == 'high' else ':warning:'
        msg += (
            f"\n\n"
            f"{severity_icon} Unusual Expense!\n"
            f"{anomaly['reason']}"
        )

    # Budget warning
    if budget.get('exists') and budget['percentage'] >= 80:
        msg += (
            f"\n\n"
            f":warning: Budget Alert!\n"
            f"Only ${budget['remaining']:.0f} left for {expense['category']}!"
        )

    return msg


# ============================================================
# FLASK APP
# ============================================================

app = Flask(__name__)


@app.route('/', methods=['GET'])
def home():
    """Home page - shows bot status"""
    return """
    <html>
    <body style="font-family: Arial; padding: 40px; text-align: center;">
        <h1>:moneybag: Smart Expense Verifier</h1>
        <h2>WhatsApp Bot</h2>
        <p style="font-size: 24px; color: green;">:white_check_mark: Server is Running</p>
        <p>Webhook endpoint: <code>/whatsapp</code></p>
        <p><a href="/test">Test Endpoint</a></p>
    </body>
    </html>
    """


@app.route('/test', methods=['GET'])
def test_endpoint():
    """Test endpoint to verify server is running"""
    return json.dumps({
        'status': 'ok',
        'message': 'WhatsApp webhook server is running!',
        'time': datetime.now().isoformat(),
        'endpoints': {
            'home': '/ (GET)',
            'webhook': '/whatsapp (POST)',
            'test': '/test (GET)'
        }
    }, indent=2), 200, {'Content-Type': 'application/json'}


@app.route('/whatsapp', methods=['POST'])
def whatsapp_webhook():
    """
    MAIN WEBHOOK - Receives WhatsApp messages from Twilio

    Twilio sends a POST request here every time someone
    sends a WhatsApp message to the sandbox number.
    """

    # ---- Step 1: Get message details from Twilio ----
    from_number = request.values.get('From', '')
    message_body = request.values.get('Body', '').strip()
    num_media = int(request.values.get('NumMedia', 0))

    print(f"\n{'='*60}")
    print(f":iphone: INCOMING WHATSAPP MESSAGE")
    print(f"   From: {from_number}")
    print(f"   Message: {message_body}")
    print(f"   Media: {num_media}")
    print(f"{'='*60}")

    # ---- Step 2: Create Twilio response object ----
    resp = MessagingResponse()

    # ---- Step 3: Look up user in database ----
    user_info = get_user_by_phone(from_number)

    if not user_info:
        resp.message(
            ":wave: Welcome! You're not registered yet.\n\n"
            "Your phone number wasn't found in our system.\n"
            "Ask your family admin to add your number.\n\n"
            f"Your number: {from_number.replace('whatsapp:', '')}"
        )
        return str(resp)

    # ---- Step 4: Handle the message ----
    try:
        message_upper = message_body.upper().strip()

        # Command: TEST
        if message_upper == 'TEST':
            resp.message(
                f":white_check_mark: Bot is working!\n"
                f"\n"
                f":bust_in_silhouette: Name: {user_info['name']}\n"
                f":iphone: Phone: {user_info['phone']}\n"
                f":man-woman-girl: Family: {user_info['familyId'][:8]}...\n"
                f":key: Role: {user_info.get('role', 'member')}\n"
                f"\n"
                f"Try sending an expense:\n"
                f"Spent $45 on groceries at Walmart"
            )
            return str(resp)

        # Command: HELP
        elif message_upper == 'HELP':
            resp.message(
                ":book: Smart Expense Verifier - Help\n"
                "\n"
                ":memo: Log Expense:\n"
                "Just type naturally:\n"
                "- Spent $45 on groceries at Walmart\n"
                "- $20 uber ride\n"
                "- Paid $120 electricity bill\n"
                "- Lunch at Chipotle for $15\n"
                "\n"
                ":zap: Commands:\n"
                "- TEST - Check bot status\n"
                "- HELP - Show this menu\n"
                "\n"
                "Try it now! Send an expense :moneybag:"
            )
            return str(resp)

        # Receipt photo
        elif num_media > 0:
            resp.message(
                ":camera_with_flash: Receipt scanning coming soon!\n\n"
                "For now, please type the expense:\n"
                "_Spent $45 on groceries at Walmart_"
            )
            return str(resp)

        # Process as expense
        else:
            print(f":moneybag: Processing as expense...")

            result = process_expense(user_info, message_body)

            if result['type'] == 'expense_logged':
                response_text = format_expense_response(result)
                resp.message(response_text)
                print(f":white_check_mark: Expense logged: ${result['expense']['amount']}")

            elif result['type'] == 'not_expense':
                resp.message(
                    ":thinking_face: I didn't recognize that as an expense.\n\n"
                    "Try something like:\n"
                    "• _Spent $45 on groceries_\n"
                    "• _$20 uber ride_\n"
                    "• _Paid $120 electricity bill_\n\n"
                    "Send *HELP* for more info"
                )
                print(f":warning:  Not recognized as expense")

            else:
                resp.message(":x: Something went wrong. Please try again!")
                print(f":x: Unknown result type: {result.get('type')}")

            return str(resp)

    except Exception as e:
        print(f":x: ERROR: {str(e)}")
        import traceback
        traceback.print_exc()

        resp.message(":x: Oops! Something went wrong. Please try again.")
        return str(resp)


# ============================================================
# START SERVER
# ============================================================

if __name__ == '__main__':
    print("\n" + "="*60)
    print(":rocket: SMART EXPENSE VERIFIER - WhatsApp Bot")
    print("="*60)
    print(f":iphone: Twilio Account: {TWILIO_SID[:10]}...")
    print(f":iphone: WhatsApp Number: {TWILIO_WHATSAPP}")
    print(f":globe_with_meridians: Server: http://localhost:5000")
    print(f":link: Webhook: http://localhost:5000/whatsapp")
    print(f":test_tube: Test: http://localhost:5000/test")
    print("="*60)
    print("\n:warning:  NEXT STEPS:")
    print("1. Open a NEW terminal and run: ngrok http 5000")
    print("2. Copy the HTTPS URL from ngrok")
    print("3. Go to Twilio Console → WhatsApp Sandbox")
    print("4. Paste: https://YOUR-NGROK-URL/whatsapp")
    print("5. Send 'TEST' from WhatsApp")
    print("\nPress Ctrl+C to stop the server")
    print("="*60 + "\n")

    app.run(host='0.0.0.0', port=5000, debug=True)