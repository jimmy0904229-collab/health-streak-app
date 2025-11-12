from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime
import base64
import io
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import current_user
import os
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # 用於 flash 訊息

# 上傳相關設定
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# 資料庫設定
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# 登入管理
login_manager = LoginManager()
login_manager.init_app(app)

# 定義資料模型
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    display_name = db.Column(db.String(120), nullable=True)
    avatar = db.Column(db.String(300), nullable=True)
    notify = db.Column(db.Boolean, default=True)
    streak_days = db.Column(db.Integer, default=0)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sport = db.Column(db.String(80), nullable=True)
    minutes = db.Column(db.Integer, default=0)
    message = db.Column(db.Text, nullable=True)
    image = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    likes = db.Column(db.Integer, default=0)
    user = db.relationship('User', backref=db.backref('posts', lazy=True))

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user = db.Column(db.String(120), nullable=False)
    text = db.Column(db.Text, nullable=False)
    time = db.Column(db.DateTime, default=datetime.utcnow)
    post = db.relationship('Post', backref=db.backref('comments', lazy=True))

# 定義 Leaderboard 和 Badge 資料模型
class Leaderboard(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    points = db.Column(db.Integer, nullable=False)

class Badge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(80), nullable=False)
    desc = db.Column(db.String(200), nullable=False)
    achieved = db.Column(db.Boolean, default=False)

# 定義 UserStatus 和 RecentActivity 資料模型
class UserStatus(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    today_goal = db.Column(db.Boolean, default=False)
    streak_days = db.Column(db.Integer, default=0)

class RecentActivity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(10), nullable=False)
    minutes = db.Column(db.Integer, nullable=False)

# 定義 Friend 和 PendingInvite 資料模型
class Friend(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)

class PendingInvite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    from_user = db.Column(db.String(80), nullable=False)
    time = db.Column(db.String(20), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
 


@app.route('/like', methods=['POST'])
def like_post():
    post_id = int(request.form.get('post_id', 0))
    p = Post.query.get(post_id)
    if p:
        p.likes = (p.likes or 0) + 1
        db.session.commit()
        return jsonify({'ok': True, 'likes': p.likes})
    return jsonify({'ok': False}), 404


@app.route('/comment', methods=['POST'])
def comment_post():
    post_id = int(request.form.get('post_id', 0))
    user = request.form.get('user') or (current_user.display_name or current_user.username)
    text = request.form.get('text', '').strip()
    if not text:
        return jsonify({'ok': False, 'error': 'empty'}), 400
    p = Post.query.get(post_id)
    if p:
        comment = Comment(post_id=p.id, user=user, text=text)
        db.session.add(comment)
        db.session.commit()
        return jsonify({'ok': True, 'comment': {'user': comment.user, 'text': comment.text, 'time': comment.time.strftime('%Y-%m-%d %H:%M')}})
    return jsonify({'ok': False}), 404

@app.route('/leaderboard')
def leaderboard_page():
    leaderboard = Leaderboard.query.all()
    badges = Badge.query.all()
    return render_template('leaderboard.html', leaderboard=leaderboard, badges=badges)

@app.route('/stats')
def stats():
    recent_7_days = RecentActivity.query.all()
    return render_template('stats.html', recent_7_days=recent_7_days)


@app.route('/friends')
def friends_page():
    friends = Friend.query.all()
    pending_invites = PendingInvite.query.all()
    return render_template('friends.html', friends=friends, pending=pending_invites)


@app.route('/friends/search')
def friends_search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    matches = Friend.query.filter(Friend.name.contains(q)).all()
    return jsonify([f.name for f in matches])


@app.route('/friends/accept', methods=['POST'])
def friends_accept():
    try:
        invite_id = int(request.form.get('invite_id', 0))
    except Exception:
        return jsonify({'ok': False}), 400

    invite = PendingInvite.query.get(invite_id)
    if invite:
        new_friend = Friend(name=invite.from_user)
        db.session.add(new_friend)
        db.session.delete(invite)
        db.session.commit()
        return jsonify({'ok': True, 'friend': invite.from_user})

    return jsonify({'ok': False}), 404


@app.route('/')
@login_required
def index():
    # 以資料庫的貼文為主（沒有假資料）
    posts_q = Post.query.order_by(Post.created_at.desc()).all()
    posts = []
    for p in posts_q:
        posts.append({
            'id': p.id,
            'user': p.user.display_name or p.user.username,
            'sport': p.sport,
            'minutes': p.minutes,
            'message': p.message,
            'image': p.image,
            'created_at': p.created_at.strftime('%Y-%m-%d %H:%M'),
            'likes': p.likes,
            'comments': [{'user': c.user, 'text': c.text, 'time': c.time.strftime('%Y-%m-%d %H:%M')} for c in p.comments]
        })
    # 傳遞目前使用者狀態給模板
    return render_template('index.html', status=current_user, posts=posts)


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile_page():
    # 顯示與更新目前使用者的個人設定
    if request.method == 'POST':
        display = request.form.get('display_name', '').strip()
        notify = request.form.get('notify', 'off') == 'on'
        try:
            sd = int(request.form.get('streak_days', current_user.streak_days or 0))
        except Exception:
            sd = current_user.streak_days or 0

        if display:
            current_user.display_name = display
        current_user.notify = notify
        current_user.streak_days = sd

        # 處理上傳大頭貼
        file = request.files.get('avatar')
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            current_user.avatar = url_for('static', filename=f'uploads/{filename}')

        db.session.commit()
        flash('個人設定已更新')
        return redirect(url_for('profile_page'))

    return render_template('profile.html', profile=current_user)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username and password:
            hashed = generate_password_hash(password)
            new_user = User(username=username, password=hashed, display_name=username)
            db.session.add(new_user)
            db.session.commit()
            flash('註冊成功！請登入')
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash('登入成功！')
            return redirect(url_for('index'))
        flash('登入失敗，請檢查帳號或密碼')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('已登出')
    return redirect(url_for('login'))

# 初始化資料庫（建立必要的資料表，暫不插入假資料）
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
