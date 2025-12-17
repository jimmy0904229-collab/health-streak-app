"""
Quick smoke test: create a test user, log in via test client, POST to /checkin and verify a Post was created.
Run: python tools\test_checkin.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import app, db, User, Post
from werkzeug.security import generate_password_hash
import os

USERNAME = os.environ.get('TEST_USER', 'test_integration')
PASSWORD = os.environ.get('TEST_PASS', 'pass123')

with app.app_context():
    u = User.query.filter_by(username=USERNAME).first()
    if not u:
        u = User(username=USERNAME, password=generate_password_hash(PASSWORD), display_name=USERNAME)
        db.session.add(u)
        db.session.commit()
        print('Created test user', USERNAME)
    else:
        print('Test user exists:', USERNAME)

    client = app.test_client()
    # login
    rv = client.post('/login', data={'username': USERNAME, 'password': PASSWORD}, follow_redirects=True)
    print('Login status code:', rv.status_code)
    # post checkin
    rv2 = client.post('/checkin', data={'sport': 'running', 'minutes': '30', 'message': 'test checkin'}, follow_redirects=True)
    print('Checkin post status:', rv2.status_code)
    # verify a post exists
    p = Post.query.filter_by(user_id=u.id).order_by(Post.created_at.desc()).first()
    if p and p.message and 'test checkin' in (p.message or ''):
        print('Checkin created, id=', p.id)
    else:
        print('Checkin not found; latest post:', p)
