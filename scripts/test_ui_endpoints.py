import os
import sys
import django
from django.test import Client

# Setup Django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "library_management.settings")
django.setup()

client = Client()

def test_routes():
    routes = [
        ("/", "Circulation Desk & Student Checkout"),
        ("/books/", "Book Catalog & Inventory"),
        ("/books/?page=1&page_size=8", "Page 1 of"),
        ("/books/?page=2&page_size=8", "Page 2 of"),
        ("/location/", "Due Books & Returns Processing"),
        ("/admin-dashboard/", "Medallion ETL Pipeline Control Center"),
        ("/api/pipeline/status/", "pipeline"),
    ]

    all_passed = True
    print("Testing UI and API routes:")
    for path, expected_content in routes:
        response = client.get(path)
        content = response.content.decode("utf-8")
        status_ok = response.status_code == 200
        content_ok = expected_content in content
        
        status_mark = "[PASS]" if (status_ok and content_ok) else "[FAIL]"
        print(f"  {status_mark} {path} -> Status {response.status_code}, Found '{expected_content}': {content_ok}")
        if not (status_ok and content_ok):
            all_passed = False

    # Test POST /api/pipeline/run-once/
    post_res = client.post("/api/pipeline/run-once/")
    print(f"  {post_res.status_code} POST /api/pipeline/run-once/ -> {post_res.json()}")

    if all_passed:
        print("\nAll UI and API routes verified successfully!")
    else:
        print("\nSome routes failed verification.")

if __name__ == "__main__":
    test_routes()
