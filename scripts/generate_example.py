import pandas as pd

data = [
    {
        'url': 'https://wildberries.ru/catalog/1234567',
        'brand': 'Nike Air Max',
        'marketplace': 'Wildberries',
        'price_original': 12000,
        'price_suspect': 4500
    },
    {
        'url': 'https://ozon.ru/product/87654321',
        'brand': 'Adidas Running',
        'marketplace': 'Ozon',
        'price_original': 15000,
        'price_suspect': 9800
    },
    {
        'url': 'https://yandex.ru/market/dresses/product-id-12345',
        'brand': 'Zara Dress',
        'marketplace': 'Яндекс Маркет',
        'price_original': 8900,
        'price_suspect': 6200
    }
]

df = pd.DataFrame(data)

try:
    df.to_excel('example_products.xlsx', index=False)
    print("✓ Created example_products.xlsx")
    print(f"✓ 3 rows with columns: {list(df.columns)}")
except Exception as e:
    print(f"Error: {e}")
    print("Try installing openpyxl: pip install openpyxl")
