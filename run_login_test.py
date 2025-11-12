from app import app, db, User
from werkzeug.security import generate_password_hash
import traceback


def main():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='testuser').first():
            u = User(username='testuser', password=generate_password_hash('pass'), display_name='Test User')
            db.session.add(u)
            db.session.commit()

    app.testing = True
    client = app.test_client()
    try:
        resp = client.post('/login', data={'username':'testuser', 'password':'pass'}, follow_redirects=True)
        print('Status:', resp.status_code)
        print(resp.data.decode())
    except Exception:
        print('Exception during login:')
        traceback.print_exc()


if __name__ == '__main__':
    main()
