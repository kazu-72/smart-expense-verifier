"""
Seed sample family data for testing
Run once: python3 seed_data.py
"""

import boto3
import uuid
from datetime import datetime, timezone

REGION = 'us-east-1'
dynamodb = boto3.resource('dynamodb', region_name=REGION)

def seed_data():
    print(":seedling: Seeding sample data...\n")

    # Generate unique family ID
    family_id = str(uuid.uuid4())
    print(f":clipboard: Family ID: {family_id}")
    print(":warning:  SAVE THIS! You'll need it for testing.\n")

    # Create family
    families_table = dynamodb.Table('SEV_Families')
    families_table.put_item(Item={
        'familyId': family_id,
        'familyName': 'My Test Family',
        'currency': 'USD',
        'monthlyBudget': 3000,
        'adminUserId': 'user-001',
        'createdAt': datetime.now(timezone.utc).isoformat()
    })
    print(":white_check_mark: Family created: My Test Family")

    # Create users
    users_table = dynamodb.Table('SEV_Users')

    # :warning: IMPORTANT: Replace with YOUR WhatsApp number (with country code)
    # Format: +[country code][number]
    # Examples: +919876543210 (India), +14155551234 (US)
    users = [
        {
            'userId': 'user-001',
            'familyId': family_id,
            'name': 'You',
            'phone': '+919971386096',  # :warning: CHANGE THIS TO YOUR NUMBER!
            'role': 'admin'
        }
    ]

    for user in users:
        users_table.put_item(Item=user)
        print(f":white_check_mark: User created: {user['name']} ({user['phone']})")

    # Create budgets
    budgets_table = dynamodb.Table('SEV_Budgets')
    categories = {
        'groceries': 500,
        'dining': 300,
        'transport': 200,
        'utilities': 250,
        'entertainment': 150,
        'shopping': 200,
        'healthcare': 200,
        'education': 300,
        'electronics': 100,
        'personal': 100,
        'other': 100
    }

    current_month = datetime.now(timezone.utc).strftime('%Y-%m')

    for category, limit in categories.items():
        budgets_table.put_item(Item={
            'budgetId': str(uuid.uuid4()),
            'familyId': family_id,
            'category': category,
            'monthlyLimit': limit,
            'currentSpend': 0,
            'month': current_month,
            'alertThreshold': 80
        })

    print(f"\n:white_check_mark: Created {len(categories)} budget categories")

    print("\n" + "="*60)
    print(":white_check_mark: Sample data seeded successfully!")
    print("="*60)
    print(f"\n:clipboard: Your Family ID: {family_id}")
    print("\nNext steps:")
    print("1. Verify in AWS Console: DynamoDB → Tables → Browse items")
    print("2. Save your family ID for later use")

    # Save to file
    with open('family_id.txt', 'w') as f:
        f.write(family_id)
    print("\n:floppy_disk: Family ID saved to: family_id.txt")

if __name__ == '__main__':
    try:
        seed_data()
    except Exception as e:
        print(f"\n:x: Error: {str(e)}")
        import traceback
        traceback.print_exc()