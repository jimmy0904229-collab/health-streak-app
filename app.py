from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime
import base64
import io
from werkzeug.utils import secure_filename
import os
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # 用於 flash 訊息

# 社群貼文（in-memory 假資料）
posts = [
    {
        "id": 1,
        "user": "小明",
        "sport": "慢跑",
        "minutes": 30,
        "image": "",
        "created_at": datetime.now().strftime('%Y-%m-%d %H:%M'),
        "likes": 3,
        "comments": [
            {"user": "小美", "text": "太厲害了！", "time": "2025-10-23 09:10"}
        ]
    },
    {
        "id": 2,
        "user": "阿花",
        "sport": "瑜伽",
        "minutes": 45,
        "image": "",
        "created_at": datetime.now().strftime('%Y-%m-%d %H:%M'),
        "likes": 1,
        "comments": []
    }
]
next_post_id = 3

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
    password = db.Column(db.String(120), nullable=False)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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

@app.route('/')
def index():
    user_status = UserStatus.query.first()
    return render_template('index.html', status=user_status, posts=posts)

@app.route('/checkin', methods=['GET', 'POST'])
def checkin():
    global posts, next_post_id
    if request.method == 'POST':
        sport_name = request.form.get('sport_name')
        sport_time = request.form.get('sport_time')
        # 嘗試讀取上傳的照片並轉為 data URL 儲存在記憶體
        image_data = ''
        file = request.files.get('photo')
        if file and file.filename:
            try:
                data = file.read()
                encoded = base64.b64encode(data).decode('utf-8')
                mimetype = file.mimetype or 'image/png'
                image_data = f'data:{mimetype};base64,{encoded}'
            except Exception:
                image_data = ''

        # 建立貼文物件（模擬社群貼文）
        message = request.form.get('message', '').strip()
        post = {
            'id': next_post_id,
            'user': '你',
            'sport': sport_name,
            'minutes': int(sport_time) if sport_time else 0,
            'message': message,
            'image': image_data,
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'likes': 0,
            'comments': []
        }
        posts.insert(0, post)  # 新貼文放最前面
        next_post_id += 1
        flash('打卡成功！已發佈為貼文')
        return redirect(url_for('index'))
    return render_template('checkin.html', success=False)


@app.route('/like', methods=['POST'])
def like_post():
    post_id = int(request.form.get('post_id', 0))
    for p in posts:
        if p['id'] == post_id:
            p['likes'] += 1
            return jsonify({'ok': True, 'likes': p['likes']})
    return jsonify({'ok': False}), 404


@app.route('/comment', methods=['POST'])
def comment_post():
    post_id = int(request.form.get('post_id', 0))
    user = request.form.get('user', '訪客')
    text = request.form.get('text', '').strip()
    if not text:
        return jsonify({'ok': False, 'error': 'empty'}), 400
    for p in posts:
        if p['id'] == post_id:
            comment = {'user': user, 'text': text, 'time': datetime.now().strftime('%Y-%m-%d %H:%M')}
            p['comments'].append(comment)
            return jsonify({'ok': True, 'comment': comment})
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


@app.route('/badges')
def badges_page():
    badges = Badge.query.all()
    return render_template('badges.html', badges=badges)


@app.route('/profile', methods=['GET', 'POST'])
def profile_page():
    if request.method == 'POST':
        # 更新 streak_days
        try:
            streak_days = int(request.form.get('streak_days', 0))
            user_status = UserStatus.query.first()
            if user_status:
                user_status.streak_days = streak_days
                db.session.commit()
        except ValueError:
            pass

        flash('個人設定已更新')
        return redirect(url_for('profile_page'))

    user_status = UserStatus.query.first()
    return render_template('profile.html', profile=user_status)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username and password:
            new_user = User(username=username, password=password)
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
        user = User.query.filter_by(username=username, password=password).first()
        if user:
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

# 初始化資料庫
with app.app_context():
    db.create_all()

    # 插入 Leaderboard 假資料
    if not Leaderboard.query.first():
        leaderboard_data = [
            Leaderboard(name="小明", points=120),
            Leaderboard(name="小美", points=110),
            Leaderboard(name="阿強", points=95),
            Leaderboard(name="阿花", points=80),
            Leaderboard(name="你", points=75)
        ]
        db.session.add_all(leaderboard_data)
        db.session.commit()

    # 插入 Badge 假資料
    if not Badge.query.first():
        badge_data = [
            Badge(title="新秀達人", desc="連勝 7 天", achieved=False),
            Badge(title="堅持王者", desc="連勝 30 天", achieved=False)
        ]
        db.session.add_all(badge_data)
        db.session.commit()

    # 插入 UserStatus 假資料
    if not UserStatus.query.first():
        user_status_data = UserStatus(today_goal=True, streak_days=5)
        db.session.add(user_status_data)
        db.session.commit()

    # 插入 RecentActivity 假資料
    if not RecentActivity.query.first():
        recent_activity_data = [
            RecentActivity(date="10/17", minutes=30),
            RecentActivity(date="10/18", minutes=45),
            RecentActivity(date="10/19", minutes=20),
            RecentActivity(date="10/20", minutes=60),
            RecentActivity(date="10/21", minutes=50),
            RecentActivity(date="10/22", minutes=40),
            RecentActivity(date="10/23", minutes=55)
        ]
        db.session.add_all(recent_activity_data)
        db.session.commit()

    # 插入 Friend 假資料
    if not Friend.query.first():
        friend_data = [
            Friend(name="小明"),
            Friend(name="小美")
        ]
        db.session.add_all(friend_data)
        db.session.commit()

    # 插入 PendingInvite 假資料
    if not PendingInvite.query.first():
        pending_invite_data = [
            PendingInvite(from_user="阿強", time="2025-10-23 08:00"),
            PendingInvite(from_user="志明", time="2025-10-22 18:30")
        ]
        db.session.add_all(pending_invite_data)
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
