#!/usr/bin/env python3
"""
Combined Server - Handles both WhatsApp and Alexa on ONE port
"""

import json
import sys
import os

# Add paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
LAMBDA_ROOT = os.path.join(PROJECT_ROOT, 'lambda')
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LAMBDA_ROOT)

from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import boto3
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from expense_processor.app import process_expense, get_budget_status

# ============================================================
# CONFIGURATION
# ============================================================

# Load Twilio credentials
TWILIO_SID = None
TWILIO_TOKEN = None
TWILIO_WHATSAPP = None

credentials_path = os.path.join(PROJECT_ROOT, 'twilio_credentials.txt')
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
    print(f"✅ Twilio loaded: {TWILIO_SID[:10]}...")
except FileNotFoundError:
    print("⚠️  twilio_credentials.txt not found")

# Twilio client
twilio_client = Client(TWILIO_SID, TWILIO_TOKEN) if TWILIO_SID else None

# Load family ID
family_id = None
try:
    with open(os.path.join(PROJECT_ROOT, 'family_id.txt'), 'r') as f:
        family_id = f.read().strip()
    print(f"✅ Family ID: {family_id[:8]}...")
except FileNotFoundError:
    print("⚠️  family_id.txt not found")

# DynamoDB
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
users_table = dynamodb.Table('SEV_Users')
expenses_table = dynamodb.Table('SEV_Expenses')

# Default user for Alexa
DEFAULT_USER = {
    'userId': 'user-001',
    'familyId': family_id,
    'name': 'You'
}

# Flask app
app = Flask(__name__)


# ============================================================
# HOME PAGE
# ============================================================

@app.route('/', methods=['GET'])
def home():
    return """
    <html>
    <body style="font-family: Arial; padding: 40px; text-align: center;">
        <h1>💰 Smart Expense Verifier</h1>
        <p style="font-size: 24px; color: green;">✅ Server Running</p>
        <table style="margin: 20px auto; text-align: left;">
            <tr><td>📱 WhatsApp:</td><td><code>/whatsapp</code></td></tr>
            <tr><td>🗣️ Alexa:</td><td><code>/alexa</code></td></tr>
            <tr><td>🧪 Test:</td><td><a href="/test">/test</a></td></tr>
        </table>
    </body>
    </html>
    """

@app.route('/test', methods=['GET'])
def test():
    return jsonify({
        'status': 'ok',
        'message': 'Combined server running!',
        'endpoints': {
            'whatsapp': '/whatsapp (POST)',
            'alexa': '/alexa (POST)',
            'test': '/test (GET)'
        },
        'family_id': family_id[:8] + '...' if family_id else 'not set'
    })


# ============================================================
# WHATSAPP HANDLER
# ============================================================

def get_user_by_phone(phone):
    """Look up user by phone number"""
    try:
        clean_phone = phone.replace('whatsapp:', '').strip()
        response = users_table.query(
            IndexName='phone-index',
            KeyConditionExpression='phone = :phone',
            ExpressionAttributeValues={':phone': clean_phone}
        )
        items = response.get('Items', [])
        if items:
            return items[0]
        
        # Debug
        print(f"⚠️  No user for phone: {clean_phone}")
        all_users = users_table.scan()
        for u in all_users.get('Items', []):
            print(f"   DB has: {u['name']} → {u['phone']}")
        return None
    except Exception as e:
        print(f"❌ User lookup error: {str(e)}")
        return None


def format_expense_response(result):
    """Format WhatsApp response"""
    expense = result['expense']
    budget = result.get('budget', {})
    anomaly = result.get('anomaly', {})
    
    bar = ""
    if budget.get('exists'):
        pct = budget['percentage']
        filled = int(pct / 5)
        empty = 20 - filled
        bar_visual = '█' * filled + '░' * empty
        bar = (
            f"\n\n📊 {expense['category'].title()} Budget\n"
            f"${budget['currentSpend']:.0f} / ${budget['monthlyLimit']:.0f} ({pct}%)\n"
            f"{bar_visual}\n"
            f"Remaining: ${budget['remaining']:.0f}"
        )
    
    msg = (
        f"✅ Expense Logged!\n\n"
        f"💰 Amount: ${expense['amount']:.2f}\n"
        f"📁 Category: {expense['category'].title()}\n"
        f"🏪 Vendor: {expense.get('vendor', 'Unknown')}\n"
        f"👤 By: {result['userName']}"
        f"{bar}"
    )
    
    if anomaly.get('isAnomaly'):
        severity_icon = '🚨' if anomaly['severity'] == 'high' else '⚠️'
        msg += f"\n\n{severity_icon} Unusual Expense!\n{anomaly['reason']}"
    
    if budget.get('exists') and budget['percentage'] >= 80:
        msg += f"\n\n⚠️ Budget Alert!\nOnly ${budget['remaining']:.0f} left for {expense['category']}!"
    
    return msg


@app.route('/whatsapp', methods=['POST'])
def whatsapp_webhook():
    """Handle WhatsApp messages"""
    
    from_number = request.values.get('From', '')
    message_body = request.values.get('Body', '').strip()
    num_media = int(request.values.get('NumMedia', 0))
    
    print(f"\n{'='*60}")
    print(f"📱 WHATSAPP MESSAGE")
    print(f"   From: {from_number}")
    print(f"   Message: {message_body}")
    print(f"{'='*60}")
    
    resp = MessagingResponse()
    
    user_info = get_user_by_phone(from_number)
    
    if not user_info:
        resp.message(
            f"👋 Welcome! You're not registered yet.\n\n"
            f"Your number: {from_number.replace('whatsapp:', '')}\n"
            f"Ask your family admin to add your number."
        )
        return str(resp)
    
    try:
        message_upper = message_body.upper().strip()
        
        if message_upper == 'TEST':
            resp.message(
                f"✅ Bot is working!\n\n"
                f"👤 Name: {user_info['name']}\n"
                f"📱 Phone: {user_info['phone']}\n"
                f"👨‍👩‍👧 Family: {user_info['familyId'][:8]}...\n"
                f"🔑 Role: {user_info.get('role', 'member')}\n\n"
                f"Try: Spent $45 on groceries at Walmart"
            )
        
        elif message_upper == 'HELP':
            resp.message(
                "📖 Smart Expense Verifier - Help\n\n"
                "📝 Log Expense:\n"
                "- Spent $45 on groceries at Walmart\n"
                "- $20 uber ride\n"
                "- Paid $120 electricity bill\n\n"
                "⚡ Commands:\n"
                "- TEST - Check bot status\n"
                "- HELP - Show this menu\n\n"
                "Try it now! Send an expense 💰"
            )
        
        elif num_media > 0:
            resp.message("📸 Receipt scanning coming soon!\nPlease type the expense details.")
        
        else:
            result = process_expense(user_info, message_body)
            
            if result['type'] == 'expense_logged':
                resp.message(format_expense_response(result))
            elif result['type'] == 'not_expense':
                resp.message(
                    "🤔 I didn't recognize that as an expense.\n\n"
                    "Try:\n- Spent $45 on groceries\n- $20 uber ride\n\n"
                    "Send HELP for more info"
                )
            else:
                resp.message("❌ Something went wrong. Please try again!")
        
        return str(resp)
    
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        resp.message("❌ Oops! Something went wrong. Please try again.")
        return str(resp)
    


# ============================================================
# ALEXA HANDLER
# ============================================================

def build_alexa_response(speech, should_end=False, reprompt=None, card_title=None, card_text=None):
    """Build Alexa response"""
    response = {
        'version': '1.0',
        'response': {
            'outputSpeech': {
                'type': 'PlainText',
                'text': speech
            },
            'shouldEndSession': should_end
        }
    }
    
    if reprompt:
        response['response']['reprompt'] = {
            'outputSpeech': {'type': 'PlainText', 'text': reprompt}
        }
    
    if card_title:
        response['response']['card'] = {
            'type': 'Simple',
            'title': card_title,
            'content': card_text or speech
        }
    
    return response


@app.route('/alexa', methods=['POST'])
def alexa_webhook():
    """Handle Alexa requests"""
    
    event = request.get_json()
    request_type = event.get('request', {}).get('type', '')
    
    print(f"\n{'='*60}")
    print(f"🗣️  ALEXA REQUEST: {request_type}")
    print(f"{'='*60}")
    
    # Launch
    if request_type == 'LaunchRequest':
        return jsonify(build_alexa_response(
            "Welcome to Family Expense Tracker! "
            "You can log expenses by saying, I spent 45 dollars on groceries. "
            "Or check your budget by saying, how much did we spend? "
            "What would you like to do?",
            reprompt="Say, I spent 30 dollars on dining, or, check budget."
        ))
    
    # Intent
    elif request_type == 'IntentRequest':
        intent = event['request']['intent']
        intent_name = intent['name']
        slots = intent.get('slots', {})
        
        print(f"   Intent: {intent_name}")
        
        # LOG EXPENSE
        if intent_name == 'LogExpenseIntent':
            amount = slots.get('amount', {}).get('value')
            category = slots.get('category', {}).get('value', 'other')
            vendor = slots.get('vendor', {}).get('value', 'Unknown')
            
            if not amount:
                return jsonify(build_alexa_response(
                    "How much did you spend?",
                    reprompt="Please say the amount."
                ))
            
            try:
                message = f"Spent ${amount} on {category} at {vendor}"
                result = process_expense(DEFAULT_USER, message)
                
                if result['type'] == 'expense_logged':
                    budget = result.get('budget', {})
                    
                    speech = f"Got it! I've logged {amount} dollars for {category}"
                    if vendor and vendor != 'Unknown':
                        speech += f" at {vendor}"
                    speech += ". "
                    
                    if budget.get('exists'):
                        speech += (
                            f"Your {category} budget is at {budget['percentage']:.0f} percent. "
                            f"{budget['remaining']:.0f} dollars remaining. "
                        )
                    
                    if result.get('anomaly', {}).get('isAnomaly'):
                        speech += f"This seems higher than usual. {result['anomaly']['reason']}. "
                    
                    speech += "Anything else?"
                    
                    return jsonify(build_alexa_response(
                        speech,
                        card_title="Expense Logged ✅",
                        card_text=f"${amount} - {category} at {vendor}"
                    ))
                
                return jsonify(build_alexa_response("Sorry, couldn't log that. Try again."))
            
            except Exception as e:
                print(f"❌ Error: {str(e)}")
                return jsonify(build_alexa_response("Something went wrong. Try again."))
        
        # CHECK BUDGET
        elif intent_name == 'CheckBudgetIntent':
            category = slots.get('category', {}).get('value')
            
            try:
                if category:
                    budget = get_budget_status(DEFAULT_USER['familyId'], category)
                    
                    if budget.get('exists'):
                        speech = (
                            f"Your {category} budget: "
                            f"Spent {budget['currentSpend']:.0f} dollars "
                            f"out of {budget['monthlyLimit']:.0f}. "
                            f"That's {budget['percentage']:.0f} percent. "
                            f"{budget['remaining']:.0f} dollars remaining. "
                            f"Check another category?"
                        )
                    else:
                        speech = f"No budget set for {category}. Check another category?"
                    
                    return jsonify(build_alexa_response(speech))
                
                else:
                    # Weekly summary
                    seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
                    
                    response = expenses_table.query(
                        IndexName='familyId-createdAt-index',
                        KeyConditionExpression='familyId = :fid AND createdAt > :since',
                        ExpressionAttributeValues={
                            ':fid': DEFAULT_USER['familyId'],
                            ':since': seven_days_ago
                        }
                    )
                    
                    expenses = response.get('Items', [])
                    
                    if not expenses:
                        return jsonify(build_alexa_response(
                            "No expenses this week. Log one by saying, I spent 45 dollars on groceries."
                        ))
                    
                    total = sum(float(e['amount']) for e in expenses)
                    by_category = {}
                    for e in expenses:
                        cat = e['category']
                        by_category[cat] = by_category.get(cat, 0) + float(e['amount'])
                    
                    top = sorted(by_category.items(), key=lambda x: x[1], reverse=True)[:3]
                    
                    speech = f"This week, your family spent {total:.0f} dollars. "
                    if top:
                        speech += "Top categories: "
                        for cat, amt in top:
                            speech += f"{cat} at {amt:.0f} dollars, "
                    speech += "Want details on any category?"
                    
                    return jsonify(build_alexa_response(
                        speech,
                        card_title="Weekly Summary",
                        card_text=f"Total: ${total:.0f}"
                    ))
            
            except Exception as e:
                print(f"❌ Error: {str(e)}")
                return jsonify(build_alexa_response("Couldn't get spending info. Try again."))
        
        # HELP
        elif intent_name == 'AMAZON.HelpIntent':
            return jsonify(build_alexa_response(
                "You can say, I spent 45 dollars on groceries, "
                "or, how much did we spend this week? What would you like to do?",
                reprompt="Say an expense or ask about spending."
            ))
        
        # STOP
        elif intent_name in ['AMAZON.StopIntent', 'AMAZON.CancelIntent']:
            return jsonify(build_alexa_response(
                "Goodbye! Keep tracking those expenses!",
                should_end=True
            ))
        
        # FALLBACK
        else:
            return jsonify(build_alexa_response(
                "I didn't catch that. Try, I spent 45 dollars on groceries.",
                reprompt="Say an expense or ask about spending."
            ))
    
    # Session ended
    return jsonify(build_alexa_response("", should_end=True))


# ============================================================
# START SERVER
# ============================================================

if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("💰 SMART EXPENSE VERIFIER - Combined Server")
    print("=" * 60)
    print(f"📱 WhatsApp endpoint: http://localhost:5000/whatsapp")
    print(f"🗣️  Alexa endpoint:    http://localhost:5000/alexa")
    print(f"🧪 Test endpoint:     http://localhost:5000/test")
    print(f"🌐 Home:              http://localhost:5000/")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Open new terminal: ngrok http 5000")
    print("2. Copy ngrok HTTPS URL")
    print("3. Twilio webhook:  https://YOUR-URL/whatsapp")
    print("4. Alexa endpoint:  https://YOUR-URL/alexa")
    print("\nPress Ctrl+C to stop")
    print("=" * 60 + "\n")
    
    app.run(host='0.0.0.0', port=5000, debug=True)