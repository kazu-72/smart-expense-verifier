"""
Expense Processor - Core AI logic for Smart Expense Verifier
Extracts expense details from natural language using AWS Bedrock
"""

import json
import boto3
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# AWS clients
bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

# DynamoDB tables
expenses_table = dynamodb.Table('SEV_Expenses')
budgets_table = dynamodb.Table('SEV_Budgets')
users_table = dynamodb.Table('SEV_Users')


def extract_expense_from_message(message):
    """
    Use AWS Bedrock (Claude) to extract expense details from natural language
    
    Args:
        message (str): User's message like "Spent $45 on groceries at Walmart"
    
    Returns:
        dict: Extracted expense data
    """
    
    prompt = f"""You are a financial assistant. Extract expense details from the user's message and return ONLY valid JSON.

User message: "{message}"

Return this exact JSON format:
{{
    "is_expense": true,
    "amount": <number>,
    "currency": "USD",
    "category": "<one of: groceries, dining, transport, utilities, entertainment, healthcare, education, shopping, electronics, personal, other>",
    "vendor": "<store/merchant name or null>",
    "description": "<brief description>"
}}

If the message is NOT an expense (it's a question or command), return:
{{
    "is_expense": false,
    "intent": "<query|set_budget|greeting|help|unknown>",
    "details": "<what the user is asking>"
}}

Rules:
- Extract the exact amount mentioned
- Choose the most appropriate category
- If vendor is mentioned, include it
- Be precise and consistent"""

    try:
        # Call Bedrock API
        response = bedrock.invoke_model(
            modelId='anthropic.claude-3-haiku-20240307-v1:0',  # Using Haiku (cheaper)
            contentType='application/json',
            accept='application/json',
            body=json.dumps({
                'anthropic_version': 'bedrock-2023-05-31',
                'max_tokens': 500,
                'messages': [
                    {'role': 'user', 'content': prompt}
                ]
            })
        )
        
        # Parse response
        result = json.loads(response['body'].read())
        content = result['content'][0]['text']
        
        # Extract JSON from response
        start = content.find('{')
        end = content.rfind('}') + 1
        
        if start == -1 or end == 0:
            # Fallback if no JSON found
            return {
                'is_expense': False,
                'intent': 'unknown',
                'details': 'Could not parse message'
            }
        
        extracted = json.loads(content[start:end])
        return extracted
        
    except Exception as e:
        print(f"Error calling Bedrock: {str(e)}")
        # Fallback to simple pattern matching
        return extract_expense_fallback(message)


def extract_expense_fallback(message):
    """
    Fallback expense extraction using simple pattern matching
    Used if Bedrock fails or for testing without AI
    """
    import re
    
    message_lower = message.lower()
    
    # Extract amount
    amount_match = re.search(r'\$?(\d+(?:\.\d{2})?)', message)
    amount = float(amount_match.group(1)) if amount_match else 0
    
    # Detect category by keywords
    categories = {
        'groceries': ['grocery', 'groceries', 'food', 'walmart', 'whole foods', 'trader joe', 'safeway'],
        'dining': ['restaurant', 'lunch', 'dinner', 'breakfast', 'cafe', 'chipotle', 'starbucks', 'mcdonald'],
        'transport': ['uber', 'lyft', 'gas', 'taxi', 'parking', 'metro', 'bus', 'train'],
        'utilities': ['electricity', 'water', 'internet', 'phone bill', 'gas bill', 'electric bill'],
        'entertainment': ['movie', 'netflix', 'concert', 'game', 'spotify', 'hulu', 'theater'],
        'shopping': ['amazon', 'target', 'mall', 'clothes', 'shoes', 'shopping'],
        'healthcare': ['doctor', 'hospital', 'pharmacy', 'medicine', 'cvs', 'walgreens'],
        'education': ['school', 'tuition', 'books', 'course', 'class'],
        'electronics': ['best buy', 'apple store', 'laptop', 'phone', 'computer', 'electronics']
    }
    
    detected_category = 'other'
    detected_vendor = None
    
    for category, keywords in categories.items():
        for keyword in keywords:
            if keyword in message_lower:
                detected_category = category
                if keyword in ['walmart', 'whole foods', 'chipotle', 'starbucks', 'amazon', 'target', 'cvs', 'best buy']:
                    detected_vendor = keyword.title()
                break
        if detected_category != 'other':
            break
    
    return {
        'is_expense': True,
        'amount': amount,
        'currency': 'USD',
        'category': detected_category,
        'vendor': detected_vendor,
        'description': message
    }


def check_anomaly(family_id, category, amount):
    """
    Check if expense is unusual compared to historical spending
    
    Args:
        family_id (str): Family ID
        category (str): Expense category
        amount (float): Expense amount
    
    Returns:
        dict: Anomaly detection result
    """
    
    try:
        # Query recent expenses in this category (last 90 days)
        from datetime import timedelta
        ninety_days_ago = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        
        response = expenses_table.query(
            IndexName='familyId-createdAt-index',
            KeyConditionExpression='familyId = :fid AND createdAt > :since',
            FilterExpression='category = :cat',
            ExpressionAttributeValues={
                ':fid': family_id,
                ':cat': category,
                ':since': ninety_days_ago
            },
            Limit=100
        )
        
        expenses = response.get('Items', [])
        
        if len(expenses) < 3:
            return {
                'isAnomaly': False,
                'reason': 'Not enough historical data',
                'severity': 'none'
            }
        
        # Calculate average
        amounts = [float(e['amount']) for e in expenses]
        avg = sum(amounts) / len(amounts)
        max_amount = max(amounts)
        
        # Check if current amount is unusual
        if amount > avg * 4:
            return {
                'isAnomaly': True,
                'severity': 'high',
                'reason': f'${amount:.0f} is {amount/avg:.1f}x the average ${avg:.0f} for {category}',
                'average': avg,
                'current': amount
            }
        elif amount > avg * 2.5:
            return {
                'isAnomaly': True,
                'severity': 'medium',
                'reason': f'${amount:.0f} is {amount/avg:.1f}x the average ${avg:.0f} for {category}',
                'average': avg,
                'current': amount
            }
        elif amount > max_amount:
            return {
                'isAnomaly': True,
                'severity': 'low',
                'reason': f'${amount:.0f} is the highest {category} expense recorded',
                'average': avg,
                'current': amount
            }
        
        return {
            'isAnomaly': False,
            'reason': 'Within normal range',
            'severity': 'none',
            'average': avg
        }
        
    except Exception as e:
        print(f"Error checking anomaly: {str(e)}")
        return {
            'isAnomaly': False,
            'reason': 'Could not check anomaly',
            'severity': 'none'
        }


def get_budget_status(family_id, category):
    """
    Get current budget status for a category
    
    Args:
        family_id (str): Family ID
        category (str): Budget category
    
    Returns:
        dict: Budget status with current spend, limit, remaining
    """
    
    try:
        current_month = datetime.now(timezone.utc).strftime('%Y-%m')
        
        response = budgets_table.query(
            IndexName='familyId-index',
            KeyConditionExpression='familyId = :fid',
            FilterExpression='category = :cat AND #m = :month',
            ExpressionAttributeNames={'#m': 'month'},
            ExpressionAttributeValues={
                ':fid': family_id,
                ':cat': category,
                ':month': current_month
            }
        )
        
        items = response.get('Items', [])
        
        if items:
            budget = items[0]
            monthly_limit = float(budget['monthlyLimit'])
            current_spend = float(budget['currentSpend'])
            remaining = monthly_limit - current_spend
            percentage = round((current_spend / monthly_limit) * 100, 1) if monthly_limit > 0 else 0
            
            return {
                'exists': True,
                'monthlyLimit': monthly_limit,
                'currentSpend': current_spend,
                'remaining': remaining,
                'percentage': percentage,
                'budgetId': budget['budgetId']
            }
        
        return {'exists': False}
        
    except Exception as e:
        print(f"Error getting budget status: {str(e)}")
        return {'exists': False}


def update_budget_spend(family_id, category, amount):
    """
    Increment the current spend for a budget category
    
    Args:
        family_id (str): Family ID
        category (str): Budget category
        amount (float): Amount to add
    """
    
    try:
        budget_status = get_budget_status(family_id, category)
        
        if budget_status.get('exists'):
            budget_id = budget_status['budgetId']
            
            budgets_table.update_item(
                Key={'budgetId': budget_id},
                UpdateExpression='SET currentSpend = currentSpend + :amt',
                ExpressionAttributeValues={':amt': Decimal(str(amount))}
            )
            
            print(f"✅ Updated budget for {category}: +${amount}")
        else:
            print(f"⚠️  No budget found for {category}")
            
    except Exception as e:
        print(f"Error updating budget: {str(e)}")


def process_expense(user_info, message):
    """
    Main function: Process an expense message end-to-end
    
    Args:
        user_info (dict): User information (userId, familyId, name)
        message (str): User's expense message
    
    Returns:
        dict: Processing result with expense details, anomaly info, budget status
    """
    
    print(f"\n📝 Processing expense from {user_info['name']}: {message}")
    
    # Step 1: Extract expense details using AI
    extracted = extract_expense_from_message(message)
    
    if not extracted.get('is_expense', False):
        print("ℹ️  Not an expense message")
        return {
            'type': 'not_expense',
            'intent': extracted.get('intent', 'unknown'),
            'details': extracted.get('details', '')
        }
    
    family_id = user_info['familyId']
    amount = extracted['amount']
    category = extracted['category']
    vendor = extracted.get('vendor', 'Unknown')
    
    print(f"💰 Extracted: ${amount} | {category} | {vendor}")
    
    # Step 2: Check for anomalies
    anomaly = check_anomaly(family_id, category, amount)
    
    if anomaly.get('isAnomaly'):
        print(f"⚠️  Anomaly detected: {anomaly['reason']}")
    
    # Step 3: Save expense to DynamoDB
    expense_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    status = 'flagged' if anomaly.get('isAnomaly') else 'verified'
    
    expense_item = {
        'expenseId': expense_id,
        'familyId': family_id,
        'userId': user_info['userId'],
        'amount': Decimal(str(amount)),
        'currency': extracted.get('currency', 'USD'),
        'category': category,
        'vendor': vendor,
        'description': extracted.get('description', message),
        'source': 'whatsapp',
        'status': status,
        'flagReason': anomaly.get('reason', ''),
        'createdAt': now,
        'month': datetime.now(timezone.utc).strftime('%Y-%m')
    }
    
    expenses_table.put_item(Item=expense_item)
    print(f"✅ Expense saved: {expense_id}")
    
    # Step 4: Update budget
    update_budget_spend(family_id, category, amount)
    
    # Step 5: Get updated budget status
    budget_status = get_budget_status(family_id, category)
    
    print(f"📊 Budget status: {budget_status.get('percentage', 0)}%")
    
    # Step 6: Return result
    return {
        'type': 'expense_logged',
        'expenseId': expense_id,
        'expense': {
            'amount': amount,
            'category': category,
            'vendor': vendor,
            'description': extracted.get('description', message)
        },
        'anomaly': anomaly,
        'budget': budget_status,
        'userName': user_info['name']
    }


# Test function
if __name__ == '__main__':
    """
    Test the expense processor locally
    """
    print("🧪 Testing Expense Processor\n")
    
    # Load family ID from file relative to this script
    repo_root = Path(__file__).resolve().parents[2]
    family_id_path = repo_root / 'family_id.txt'
    try:
        with family_id_path.open('r') as f:
            family_id = f.read().strip()
    except FileNotFoundError:
        print("❌ family_id.txt not found. Run seed_data.py first!")
        exit(1)
    
    # Mock user info
    test_user = {
        'userId': 'user-001',
        'familyId': family_id,
        'name': 'Test User'
    }
    
    # Test messages
    test_messages = [
        "Spent $45 on groceries at Walmart",
        "Paid $120 for electricity bill",
        "$30 uber ride to airport",
        "Lunch at Chipotle for $15",
        "$500 on electronics at Best Buy"  # Should trigger anomaly
    ]
    
    for msg in test_messages:
        result = process_expense(test_user, msg)
        print(f"\n{'='*60}")
        print(f"Result: {json.dumps(result, indent=2, default=str)}")
        print(f"{'='*60}\n")
