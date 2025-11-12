from app import app, db, User, Post
from werkzeug.security import generate_password_hash
import traceback


def main():
    with app.app_context():
        db.create_all()
        # ensure demo users
        if not User.query.filter_by(username='lbuser').first():
            u = User(username='lbuser', password=generate_password_hash('pass'), display_name='LB User')
            db.session.add(u)
            db.session.commit()
            # create posts across days
            from datetime import datetime, timedelta
            now = datetime.utcnow()
            p1 = Post(user_id=u.id, sport='跑步', minutes=10, created_at=now)
            p2 = Post(user_id=u.id, sport='游泳', minutes=20, created_at=now - timedelta(days=2))
            db.session.add_all([p1, p2])
            db.session.commit()

    app.testing = True
    c = app.test_client()
    resp = c.post('/login', data={'username':'lbuser','password':'pass'}, follow_redirects=True)
    print('login', resp.status_code)
    r = c.get('/leaderboard')
    print('leaderboard', r.status_code)
    print(r.get_data(as_text=True)[:800])

if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
