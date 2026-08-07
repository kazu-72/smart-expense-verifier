"""
Create all DynamoDB tables for Smart Expense Verifier5
Run once: python3 create_tables.py
"""

import boto3
import sys

REGION = 'us-east-1'
dynamodb = boto3.client('dynamodb', region_name=REGION)

def create_table(table_name, key_schema, attribute_definitions, gsi=None):
    """Create a DynamoDB table if it doesn't exist"""
    try:
        dynamodb.describe_table(TableName=table_name)
        print(f":white_check_mark: Table {table_name} already exists")
        return
    except dynamodb.exceptions.ResourceNotFoundException:
        pass

    params = {
        'TableName': table_name,
        'KeySchema': key_schema,
        'AttributeDefinitions': attribute_definitions,
        'BillingMode': 'PAY_PER_REQUEST'
    }

    if gsi:
        params['GlobalSecondaryIndexes'] = gsi

    dynamodb.create_table(**params)
    print(f":hourglass_flowing_sand: Creating {table_name}...")

    waiter = dynamodb.get_waiter('table_exists')
    waiter.wait(TableName=table_name)
    print(f":white_check_mark: {table_name} created!")

def main():
    print(":rocket: Creating DynamoDB tables for Smart Expense Verifier...\n")

    # Table 1: Families
    print("Creating SEV_Families table...")
    create_table(
        'SEV_Families',
        [{'AttributeName': 'familyId', 'KeyType': 'HASH'}],
        [{'AttributeName': 'familyId', 'AttributeType': 'S'}]
    )

    # Table 2: Users
    print("\nCreating SEV_Users table...")
    create_table(
        'SEV_Users',
        [{'AttributeName': 'userId', 'KeyType': 'HASH'}],
        [
            {'AttributeName': 'userId', 'AttributeType': 'S'},
            {'AttributeName': 'familyId', 'AttributeType': 'S'},
            {'AttributeName': 'phone', 'AttributeType': 'S'}
        ],
        [
            {
                'IndexName': 'familyId-index',
                'KeySchema': [{'AttributeName': 'familyId', 'KeyType': 'HASH'}],
                'Projection': {'ProjectionType': 'ALL'}
            },
            {
                'IndexName': 'phone-index',
                'KeySchema': [{'AttributeName': 'phone', 'KeyType': 'HASH'}],
                'Projection': {'ProjectionType': 'ALL'}
            }
        ]
    )

    # Table 3: Expenses
    print("\nCreating SEV_Expenses table...")
    create_table(
        'SEV_Expenses',
        [{'AttributeName': 'expenseId', 'KeyType': 'HASH'}],
        [
            {'AttributeName': 'expenseId', 'AttributeType': 'S'},
            {'AttributeName': 'familyId', 'AttributeType': 'S'},
            {'AttributeName': 'createdAt', 'AttributeType': 'S'}
        ],
        [
            {
                'IndexName': 'familyId-createdAt-index',
                'KeySchema': [
                    {'AttributeName': 'familyId', 'KeyType': 'HASH'},
                    {'AttributeName': 'createdAt', 'KeyType': 'RANGE'}
                ],
                'Projection': {'ProjectionType': 'ALL'}
            }
        ]
    )

    # Table 4: Budgets
    print("\nCreating SEV_Budgets table...")
    create_table(
        'SEV_Budgets',
        [{'AttributeName': 'budgetId', 'KeyType': 'HASH'}],
        [
            {'AttributeName': 'budgetId', 'AttributeType': 'S'},
            {'AttributeName': 'familyId', 'AttributeType': 'S'}
        ],
        [
            {
                'IndexName': 'familyId-index',
                'KeySchema': [{'AttributeName': 'familyId', 'KeyType': 'HASH'}],
                'Projection': {'ProjectionType': 'ALL'}
            }
        ]
    )

    print("\n" + "="*60)
    print(":white_check_mark: All tables created successfully!")
    print("="*60)
    print("\nNext steps:")
    print("1. Run: python3 seed_data.py")
    print("2. Verify in AWS Console: DynamoDB → Tables")

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"\n:x: Error: {str(e)}")
        sys.exit(1)
