#!/usr/bin/env python3
"""
Alexa Skill Handler for Smart Expense Verifier
Handles voice commands for logging expenses and checking budgets
"""

import json
import sys
import os
import boto3
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from flask import Flask, request, jsonify

# Add paths for imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
LAMBDA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LAMBDA_ROOT)

from expense_processor.app import process_expense, get_budget_status  # type: ignore

# DynamoDB
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
expenses_table = dynamodb.Table('SEV_Expenses')
budgets_table = dynamodb.Table('SEV_Budgets')

# Load family ID
family_id = None
family_id_path = os.path.join(PROJECT_ROOT, 'family_id.txt')
try:
    with open(family_id_path, 'r') as f:
        family_id = f.read().strip()
    print(f"📋 Family ID: {family_id[:8]}...")
except FileNotFoundError:
    print("⚠️  family_id.txt not found")

# Default user (for prototype - in production, use Alexa account linking)
DEFAULT_USER = {
    'userId': 'user-001',
    'familyId': family_id,
    'name': 'You'
}

# Flask app for local testing
app = Flask(__name__)


# ============================================================
# ALEXA RESPONSE BUILDERS
# ============================================================

def build_response(speech, should_end=False, reprompt=None):
    """Build a standard Alexa response"""
    
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
            'outputSpeech': {
                'type': 'PlainText',
                'text': reprompt
            }
        }
    
    return response


def build_card_response(speech, title, card_text, should_end=False):
    """Build Alexa response with a visual card"""
    
    response = build_response(speech, should_end)
    response['response']['card'] = {
        'type': 'Simple',
        'title': title,
        'content': card_text
    }
    
    return response


# ============================================================
# INTENT HANDLERS
# ============================================================

def handle_launch():
    """Handle skill launch - "Alexa, open expense tracker" """
    
    speech = (
        "Welcome to Family Expense Tracker! "
        "You can log expenses by saying something like, "
        "I spent 45 dollars on groceries. "
        "Or check your budget by saying, how much did we spend? "
        "What would you like to do?"
    )
    
    reprompt = "You can say, I spent 30 dollars on dining, or, check budget."
    
    return build_response(speech, should_end=False, reprompt=reprompt)


def handle_log_expense(intent):
    """Handle LogExpenseIntent - "I spent $45 on groceries" """
    
    slots = intent.get('slots', {})
    
    # Get amount
    amount_slot = slots.get('amount', {})
    amount = amount_slot.get('value')
    
    if not amount:
        return build_response(
            "How much did you spend? Please say the amount.",
            should_end=False,
            reprompt="Please say the amount, like 45 dollars."
        )
    
    # Get category
    category_slot = slots.get('category', {})
    category = category_slot.get('value', 'other')
    
    # Get vendor (optional)
    vendor_slot = slots.get('vendor', {})
    vendor = vendor_slot.get('value', 'Unknown')
    
    print(f"🗣️  Alexa: Log ${amount} for {category} at {vendor}")
    
    # Process the expense
    try:
        message = f"Spent ${amount} on {category} at {vendor}"
        result = process_expense(DEFAULT_USER, message)
        
        if result['type'] == 'expense_logged':
            budget = result.get('budget', {})
            
            # Build speech response
            speech = f"Got it! I've logged {amount} dollars for {category}"
            
            if vendor and vendor != 'Unknown':
                speech += f" at {vendor}"
            
            speech += ". "
            
            # Add budget info
            if budget.get('exists'):
                speech += (
                    f"Your {category} budget this month is at "
                    f"{budget['percentage']:.0f} percent. "
                    f"You have {budget['remaining']:.0f} dollars remaining. "
                )
                
                # Budget warning
                if budget['percentage'] >= 80:
                    speech += (
                        f"Warning! Your {category} budget is almost used up. "
                        f"Only {budget['remaining']:.0f} dollars left. "
                    )
            
            # Anomaly warning
            if result.get('anomaly', {}).get('isAnomaly'):
                speech += (
                    f"By the way, this seems higher than usual. "
                    f"{result['anomaly']['reason']}. "
                )
            
            speech += "Anything else?"
            
            # Card for Alexa app
            card_text = (
                f"Amount: ${amount}\n"
                f"Category: {category}\n"
                f"Vendor: {vendor}\n"
            )
            
            if budget.get('exists'):
                card_text += (
                    f"\nBudget: ${budget['currentSpend']:.0f} / ${budget['monthlyLimit']:.0f} "
                    f"({budget['percentage']:.0f}%)\n"
                    f"Remaining: ${budget['remaining']:.0f}"
                )
            
            return build_card_response(
                speech=speech,
                title="Expense Logged ✅",
                card_text=card_text,
                should_end=False
            )
        
        else:
            return build_response(
                "Sorry, I couldn't log that expense. Please try again. "
                "Say something like, I spent 45 dollars on groceries.",
                should_end=False
            )
    
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return build_response(
            "Sorry, something went wrong. Please try again.",
            should_end=False
        )


def handle_check_budget(intent):
    """Handle CheckBudgetIntent - "How much did we spend?" """
    
    slots = intent.get('slots', {})
    
    # Get category (optional)
    category_slot = slots.get('category', {})
    category = category_slot.get('value')
    
    print(f"🗣️  Alexa: Check budget for {category or 'all'}")
    
    try:
        if category:
            # Check specific category budget
            budget = get_budget_status(DEFAULT_USER['familyId'], category)
            
            if budget.get('exists'):
                speech = (
                    f"Your {category} budget this month: "
                    f"You've spent {budget['currentSpend']:.0f} dollars "
                    f"out of {budget['monthlyLimit']:.0f} dollars. "
                    f"That's {budget['percentage']:.0f} percent. "
                    f"You have {budget['remaining']:.0f} dollars remaining. "
                    f"Would you like to check another category?"
                )
                
                card_text = (
                    f"{category.title()} Budget\n"
                    f"Spent: ${budget['currentSpend']:.0f}\n"
                    f"Limit: ${budget['monthlyLimit']:.0f}\n"
                    f"Used: {budget['percentage']:.0f}%\n"
                    f"Remaining: ${budget['remaining']:.0f}"
                )
                
                return build_card_response(
                    speech=speech,
                    title=f"{category.title()} Budget",
                    card_text=card_text,
                    should_end=False
                )
            else:
                return build_response(
                    f"I don't have a budget set for {category}. "
                    f"Would you like to check a different category?",
                    should_end=False
                )
        
        else:
            # Get overall spending summary
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
                return build_response(
                    "No expenses recorded this week. "
                    "You can log one by saying, I spent 45 dollars on groceries.",
                    should_end=False
                )
            
            # Calculate totals
            total = sum(float(e['amount']) for e in expenses)
            
            # Group by category
            by_category = {}
            for e in expenses:
                cat = e['category']
                by_category[cat] = by_category.get(cat, 0) + float(e['amount'])
            
            # Sort by amount
            top_categories = sorted(by_category.items(), key=lambda x: x[1], reverse=True)
            
            speech = (
                f"This week, your family has spent {total:.0f} dollars total. "
            )
            
            if top_categories:
                speech += "The top categories are: "
                for i, (cat, amt) in enumerate(top_categories[:3]):
                    if i == len(top_categories[:3]) - 1 and i > 0:
                        speech += f"and {cat} at {amt:.0f} dollars. "
                    else:
                        speech += f"{cat} at {amt:.0f} dollars, "
            
            speech += "Would you like more details on any category?"
            
            # Card
            card_text = f"Weekly Spending: ${total:.0f}\n\n"
            for cat, amt in top_categories:
                pct = (amt / total * 100) if total > 0 else 0
                card_text += f"{cat.title()}: ${amt:.0f} ({pct:.0f}%)\n"
            
            return build_card_response(
                speech=speech,
                title="Weekly Spending Summary",
                card_text=card_text,
                should_end=False
            )
    
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return build_response(
            "Sorry, I couldn't get the spending information. Please try again.",
            should_end=False
        )


def handle_help():
    """Handle AMAZON.HelpIntent"""
    
    return build_response(
        "Here's what you can do with Family Expense Tracker. "
        "To log an expense, say something like, I spent 45 dollars on groceries. "
        "To check your budget, say, how much did we spend this week? "
        "Or, what's our dining budget? "
        "What would you like to do?",
        should_end=False,
        reprompt="Say, I spent 30 dollars on dining, or, check budget."
    )


def handle_stop():
    """Handle AMAZON.StopIntent and AMAZON.CancelIntent"""
    
    return build_response(
        "Goodbye! Keep tracking those expenses!",
        should_end=True
    )


def handle_fallback():
    """Handle AMAZON.FallbackIntent"""
    
    return build_response(
        "I didn't catch that. "
        "Try saying, I spent 45 dollars on groceries, "
        "or, how much did we spend this week?",
        should_end=False,
        reprompt="Say, I spent 30 dollars on dining, or, check budget."
    )


# ============================================================
# MAIN REQUEST HANDLER
# ============================================================

def handle_alexa_request(event):
    """
    Main handler - routes Alexa requests to the right function
    """
    
    request_type = event.get('request', {}).get('type', '')
    
    print(f"\n{'='*60}")
    print(f"🗣️  ALEXA REQUEST: {request_type}")
    
    # Launch Request - "Alexa, open expense tracker"
    if request_type == 'LaunchRequest':
        print("   → Launch")
        return handle_launch()
    
    # Intent Request - User said something specific
    elif request_type == 'IntentRequest':
        intent = event['request']['intent']
        intent_name = intent['name']
        
        print(f"   → Intent: {intent_name}")
        print(f"   → Slots: {json.dumps(intent.get('slots', {}), default=str)}")
        
        if intent_name == 'LogExpenseIntent':
            return handle_log_expense(intent)
        
        elif intent_name == 'CheckBudgetIntent':
            return handle_check_budget(intent)
        
        elif intent_name == 'AMAZON.HelpIntent':
            return handle_help()
        
        elif intent_name in ['AMAZON.StopIntent', 'AMAZON.CancelIntent']:
            return handle_stop()
        
        elif intent_name == 'AMAZON.FallbackIntent':
            return handle_fallback()
        
        else:
            return handle_fallback()
    
    # Session Ended
    elif request_type == 'SessionEndedRequest':
        print("   → Session ended")
        return build_response("", should_end=True)
    
    else:
        return handle_fallback()


# ============================================================
# FLASK SERVER (for local testing + ngrok)
# ============================================================

@app.route('/', methods=['GET'])
def home():
    return """
    <html>
    <body style="font-family: Arial; padding: 40px; text-align: center;">
        <h1>🗣️ Alexa Skill - Family Expense Tracker</h1>
        <p style="font-size: 24px; color: green;">Server is Running</p>
        <p>Alexa endpoint: <code>/alexa</code></p>
        <p><a href="/test">Test Endpoint</a></p>
    </body>
    </html>
    """


@app.route('/test', methods=['GET'])
def test():
    return jsonify({
        'status': 'ok',
        'message': 'Alexa skill server is running',
        'family_id': family_id[:8] + '...' if family_id else 'not set'
    })


@app.route('/alexa', methods=['POST'])
def alexa_webhook():
    """Receives Alexa requests"""
    
    event = request.get_json()
    print(f"\n📨 Received Alexa request")
    
    response = handle_alexa_request(event)
    
    print(f"📤 Response: {response['response']['outputSpeech']['text'][:100]}...")
    
    return jsonify(response)


# ============================================================
# LOCAL TESTING
# ============================================================

def test_locally():
    """Test the Alexa skill without Alexa"""
    
    print("🧪 Testing Alexa Skill Locally\n")
    
    # Test 1: Launch
    print("Test 1: Launch Request")
    print("-" * 50)
    event = {'request': {'type': 'LaunchRequest'}}
    result = handle_alexa_request(event)
    print(f"Alexa says: {result['response']['outputSpeech']['text']}\n")
    
    # Test 2: Log Expense
    print("Test 2: Log Expense - $45 on groceries")
    print("-" * 50)
    event = {
        'request': {
            'type': 'IntentRequest',
            'intent': {
                'name': 'LogExpenseIntent',
                'slots': {
                    'amount': {'value': '45'},
                    'category': {'value': 'groceries'},
                    'vendor': {'value': 'Walmart'}
                }
            }
        }
    }
    result = handle_alexa_request(event)
    print(f"Alexa says: {result['response']['outputSpeech']['text']}\n")
    
    # Test 3: Log Another Expense
    print("Test 3: Log Expense - $30 on dining")
    print("-" * 50)
    event = {
        'request': {
            'type': 'IntentRequest',
            'intent': {
                'name': 'LogExpenseIntent',
                'slots': {
                    'amount': {'value': '30'},
                    'category': {'value': 'dining'},
                    'vendor': {}
                }
            }
        }
    }
    result = handle_alexa_request(event)
    print(f"Alexa says: {result['response']['outputSpeech']['text']}\n")
    
    # Test 4: Check Budget
    print("Test 4: Check groceries budget")
    print("-" * 50)
    event = {
        'request': {
            'type': 'IntentRequest',
            'intent': {
                'name': 'CheckBudgetIntent',
                'slots': {
                    'category': {'value': 'groceries'}
                }
            }
        }
    }
    result = handle_alexa_request(event)
    print(f"Alexa says: {result['response']['outputSpeech']['text']}\n")
    
    # Test 5: Weekly Summary
    print("Test 5: Weekly spending summary")
    print("-" * 50)
    event = {
        'request': {
            'type': 'IntentRequest',
            'intent': {
                'name': 'CheckBudgetIntent',
                'slots': {
                    'category': {}
                }
            }
        }
    }
    result = handle_alexa_request(event)
    print(f"Alexa says: {result['response']['outputSpeech']['text']}\n")
    
    # Test 6: Help
    print("Test 6: Help")
    print("-" * 50)
    event = {
        'request': {
            'type': 'IntentRequest',
            'intent': {
                'name': 'AMAZON.HelpIntent',
                'slots': {}
            }
        }
    }
    result = handle_alexa_request(event)
    print(f"Alexa says: {result['response']['outputSpeech']['text']}\n")
    
    print("=" * 60)
    print("✅ All Alexa tests complete!")
    print("=" * 60)


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        # Run local tests
        test_locally()
    else:
        # Start Flask server
        print("\n" + "=" * 60)
        print("🗣️  ALEXA SKILL SERVER - Family Expense Tracker")
        print("=" * 60)
        print(f"📋 Family ID: {family_id[:8]}..." if family_id else "⚠️  No family ID")
        print(f"🌐 Server: http://localhost:5001")
        print(f"🔗 Alexa endpoint: http://localhost:5001/alexa")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Open new terminal: ngrok http 5001")
        print("2. Copy ngrok URL")
        print("3. Paste in Alexa Developer Console → Endpoint")
        print("\nPress Ctrl+C to stop")
        print("=" * 60 + "\n")
        
        app.run(host='0.0.0.0', port=5001, debug=True)