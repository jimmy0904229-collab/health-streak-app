from app import app, db, User, Post
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta

def seed():
    with app.app_context():
        # create demo users if none
        if not User.query.first():
            u1 = User(username='alice', password=generate_password_hash('pass'), display_name='Alice')
            u2 = User(username='bob', password=generate_password_hash('pass'), display_name='Bob')
            u3 = User(username='carol', password=generate_password_hash('pass'), display_name='Carol')
            db.session.add_all([u1, u2, u3])
            db.session.commit()
            # create some posts
            now = datetime.utcnow()
            p1 = Post(user_id=u1.id, sport='跑步', minutes=30, message='早上跑步', created_at=now - timedelta(days=1))
            p2 = Post(user_id=u2.id, sport='游泳', minutes=45, message='泳池練習', created_at=now - timedelta(days=2))
            p3 = Post(user_id=u3.id, sport='騎車', minutes=60, message='長距離騎乘', created_at=now - timedelta(days=3))
            db.session.add_all([p1, p2, p3])
            db.session.commit()
            print('Seeded demo users and posts')
        else:
            print('DB already has users; skipping seed')

if __name__ == '__main__':
    seed()
