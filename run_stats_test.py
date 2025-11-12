from app import app, db, User, Post
from werkzeug.security import generate_password_hash
import traceback


def main():
    with app.app_context():
        db.create_all()
        # ensure test user
        if not User.query.filter_by(username='statuser').first():
            u = User(username='statuser', password=generate_password_hash('pass'), display_name='Stat User')
            db.session.add(u)
            db.session.commit()
        u = User.query.filter_by(username='statuser').first()
        # create posts on different days
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        # clear user's posts
        Post.query.filter_by(user_id=u.id).delete()
        db.session.commit()
        for i, mins in enumerate([10, 20, 0, 30, 0, 15, 0]):
            if mins>0:
                p = Post(user_id=u.id, sport='跑步', minutes=mins, message='test', created_at=now - timedelta(days=(6-i)))
                db.session.add(p)
        db.session.commit()

    app.testing = True
    c = app.test_client()
    # login
    resp = c.post('/login', data={'username':'statuser','password':'pass'}, follow_redirects=True)
    print('login', resp.status_code)
    resp2 = c.get('/stats')
    print('stats status', resp2.status_code)
    print(resp2.get_data(as_text=True)[:800])

if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
