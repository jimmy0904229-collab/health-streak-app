import traceback
try:
    from app import app
    print('Imported app successfully')
    with app.test_client() as c:
        resp = c.get('/')
        print('Status code:', resp.status_code)
        print('Response data:')
        print(resp.get_data(as_text=True))
except Exception as e:
    print('Exception when importing or requesting:')
    traceback.print_exc()