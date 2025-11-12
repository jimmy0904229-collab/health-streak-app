from app import app, db, User, Post
from werkzeug.security import generate_password_hash
import io


def main():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='uploader').first():
            u = User(username='uploader', password=generate_password_hash('pass'), display_name='Uploader')
            db.session.add(u)
            db.session.commit()
        user = User.query.filter_by(username='uploader').first()

    app.testing = True
    client = app.test_client()

    # login first
    resp = client.post('/login', data={'username':'uploader','password':'pass'}, follow_redirects=True)
    print('Login status:', resp.status_code)

    # create a fake image
    fake_image = io.BytesIO(b"\x89PNG\r\n\x1a\nfakepngdata")
    fake_image.seek(0)

    data = {
        'sport':'跑步',
        'minutes':'30',
        'message':'測試上傳圖片',
        'image': (fake_image, 'test.png')
    }

    resp2 = client.post('/checkin', data=data, content_type='multipart/form-data', follow_redirects=True)
    print('Checkin status:', resp2.status_code)
    print('Checkin response snippet:')
    print(resp2.get_data(as_text=True)[:400])

    # Inspect latest post in DB
    with app.app_context():
        p = Post.query.order_by(Post.id.desc()).first()
        if not p:
            print('No post created')
        else:
            print('Post id:', p.id, 'sport:', p.sport, 'minutes:', p.minutes, 'image:', p.image)
            import os
            if p.image and p.image.startswith('/static/uploads/'):
                file_path = os.path.join(os.getcwd(), p.image.lstrip('/'))
                print('Expected file path on disk:', file_path)
                print('Exists on disk?:', os.path.exists(file_path))

if __name__ == '__main__':
    main()
