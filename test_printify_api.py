#!/usr/bin/env python3
"""
Test script to debug Printify API connection
Usage: python test_printify_api.py
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_TOKEN = os.getenv('PRINTIFY_API_TOKEN')
SHOP_ID = os.getenv('PRINTIFY_SHOP_ID')

if not API_TOKEN or not SHOP_ID:
    print("ERROR: PRINTIFY_API_TOKEN and PRINTIFY_SHOP_ID must be set in .env file")
    exit(1)

print(f"Testing Printify API...")
print(f"Shop ID: {SHOP_ID}")
print(f"API Token: {API_TOKEN[:10]}...")

headers = {
    'Authorization': f'Bearer {API_TOKEN}',
    'Content-Type': 'application/json'
}

# Test 1: Get shops
print("\n--- Test 1: List Shops ---")
try:
    url = 'https://api.printify.com/v1/shops.json'
    response = requests.get(url, headers=headers, timeout=30)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        shops = response.json()
        print(f"Shops found: {len(shops)}")
        for shop in shops:
            print(f"  - Shop ID: {shop.get('id')}, Title: {shop.get('title')}")
    else:
        print(f"Error: {response.text}")
except Exception as e:
    print(f"Exception: {e}")

# Test 2: Get orders (without .json)
print("\n--- Test 2: Get Orders (without .json) ---")
try:
    url = f'https://api.printify.com/v1/shops/{SHOP_ID}/orders'
    params = {'page': 1, 'limit': 5}
    print(f"URL: {url}")
    print(f"Params: {params}")
    response = requests.get(url, headers=headers, params=params, timeout=30)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Response keys: {data.keys()}")
        orders = data.get('data', [])
        print(f"Orders found: {len(orders)}")
        if orders:
            print(f"First order sample:")
            order = orders[0]
            print(f"  ID: {order.get('id')}")
            print(f"  Label: {order.get('label')}")
            print(f"  Metadata: {order.get('metadata')}")
    else:
        print(f"Error: {response.text}")
except Exception as e:
    print(f"Exception: {e}")

# Test 3: Get orders (with .json)
print("\n--- Test 3: Get Orders (with .json) ---")
try:
    url = f'https://api.printify.com/v1/shops/{SHOP_ID}/orders.json'
    params = {'page': 1, 'limit': 5}
    print(f"URL: {url}")
    print(f"Params: {params}")
    response = requests.get(url, headers=headers, params=params, timeout=30)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Response keys: {data.keys()}")
        orders = data.get('data', [])
        print(f"Orders found: {len(orders)}")
        
        if orders:
            print("\n--- Sample Order Details ---")
            for i, order in enumerate(orders[:3], 1):
                print(f"\nOrder {i}:")
                print(f"  ID: {order.get('id')}")
                print(f"  Label: {order.get('label')}")
                print(f"  Metadata: {order.get('metadata')}")
                print(f"  Status: {order.get('status')}")
                
                # Show order-level costs
                total_tax = order.get('total_tax', 0) / 100
                print(f"  Sales Tax: ${total_tax:.2f}")
                
                # Show line items with costs
                line_items = order.get('line_items', [])
                print(f"  Line Items: {len(line_items)}")
                for j, item in enumerate(line_items, 1):
                    product_cost = item.get('cost', 0) / 100
                    shipping_cost = item.get('shipping_cost', 0) / 100
                    print(f"    Item {j}: Product=${product_cost:.2f}, Shipping=${shipping_cost:.2f}")
                    print(f"      Quantity: {item.get('quantity')}")
    else:
        print(f"Error: {response.text}")
except Exception as e:
    print(f"Exception: {e}")

print("\n--- Done ---")
