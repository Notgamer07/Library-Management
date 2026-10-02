import os
import sys
import django
from django.test import Client

# Setup Django environment
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
web_dir = os.path.join(root_dir, "web")
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
if web_dir not in sys.path:
    sys.path.insert(0, web_dir)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "library_management.settings")
django.setup()

client = Client()

def test_routes():
    routes = [
        ("/health", "timestamp"),
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

    # Test POST /api/pipeline/run-once/ (returns 202 Accepted or 409 Conflict if already executing)
    post_res = client.post("/api/pipeline/run-once/")
    post_ok = post_res.status_code in [200, 202, 409]
    print(f"  {'[PASS]' if post_ok else '[FAIL]'} POST /api/pipeline/run-once/ -> Status {post_res.status_code}, Payload: {post_res.json()}")
    if not post_ok:
        all_passed = False

    if all_passed:
        print("\nAll UI and API routes verified successfully!")
    else:
        print("\nSome routes failed verification.")

if __name__ == "__main__":
    test_routes()
