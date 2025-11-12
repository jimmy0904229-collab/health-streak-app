from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime, timedelta
import base64
import io
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import current_user
import os
import uuid
from urllib.parse import urljoin
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

# --- Optional S3 upload support ---
def s3_configured():
    return bool(os.environ.get('AWS_S3_BUCKET'))

def get_s3_client():
    if not s3_configured():
        return None
    import boto3
    session = boto3.session.Session()
    s3 = session.client(
        's3',
        aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
        region_name=os.environ.get('AWS_REGION'),
        endpoint_url=os.environ.get('S3_ENDPOINT')  # optional custom endpoint (e.g. DigitalOcean Spaces)
    )
    return s3

def get_s3_base_url():
    # Optional explicit base URL (useful for Spaces or custom endpoints)
    base = os.environ.get('S3_BASE_URL')
    if base:
        return base.rstrip('/')
    # Fallback to AWS-style public URL if region provided
    bucket = os.environ.get('AWS_S3_BUCKET')
    region = os.environ.get('AWS_REGION')
    if bucket and region:
        return f'https://{bucket}.s3.{region}.amazonaws.com'
    return None

def save_uploaded_file(file):
    """Save uploaded file either to S3 (if configured) or local static/uploads.
    Returns the public URL path to store in DB/template.
    """
    filename = secure_filename(file.filename)
    # generate unique name to avoid collisions
    unique_name = f"{uuid.uuid4().hex}_{filename}"
    # Try S3
    s3 = get_s3_client()
    if s3:
        bucket = os.environ.get('AWS_S3_BUCKET')
        key = f'uploads/{unique_name}'
        content_type = getattr(file, 'content_type', None) or 'application/octet-stream'
        # read file content
        file.stream.seek(0)
        data = file.read()
        try:
            s3.put_object(Bucket=bucket, Key=key, Body=data, ACL='public-read', ContentType=content_type)
        except Exception:
            # fallback to local if upload fails
            pass
        else:
            base = get_s3_base_url()
            if base:
                # if base explicitly provided, it may already include bucket
                if base.startswith('http') and ('{bucket}' not in base):
                    # For DO Spaces, base should be like https://{bucket}.{endpoint}
                    if '{bucket}' in base:
                        url = base.format(bucket=bucket) + f'/{key}'
                    else:
                        # if base contains the bucket already, just append key
                        url = base + f'/{key}'
                else:
                    url = f'https://{bucket}.s3.amazonaws.com/{key}'
            else:
                url = f'https://{bucket}.s3.amazonaws.com/{key}'
            return url

    # Local fallback
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
    # ensure folder exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    file.stream.seek(0)
    file.save(filepath)
    return url_for('static', filename=f'uploads/{unique_name}')


# 登入管理
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = '請先登入以存取此頁面'
login_manager.login_message_category = 'info'

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
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    friend_name = db.Column(db.String(80), nullable=False)
    owner = db.relationship('User', backref=db.backref('friends', lazy=True))

class PendingInvite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    from_user = db.Column(db.String(80), nullable=False)
    to_user = db.Column(db.String(80), nullable=False)
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

from sqlalchemy import case, and_


@app.route('/leaderboard')
def leaderboard_page():
    # Calculate leaderboard based on total minutes in the last 7 days
    badges = Badge.query.all()
    today = datetime.utcnow().date()
    start_date = datetime.combine(today - timedelta(days=6), datetime.min.time())
    end_date = datetime.combine(today, datetime.max.time())

    # Sum minutes per user for posts in the last 7 days; include users with zero via outerjoin
    minutes_expr = db.func.coalesce(db.func.sum(
        case((and_(Post.created_at >= start_date, Post.created_at <= end_date), Post.minutes), else_=0)
    ), 0).label('points')

    q = db.session.query(User.id, User.display_name, User.username, minutes_expr).outerjoin(Post, Post.user_id == User.id).group_by(User.id).order_by(db.desc('points'))
    results = q.all()

    leaderboard = []
    for r in results:
        name = r.display_name or r.username
        leaderboard.append({'id': r.id, 'name': name, 'points': int(r.points) if r.points is not None else 0})

    return render_template('leaderboard.html', leaderboard=leaderboard, badges=badges)


@app.route('/badges')
def badges_page():
    badges = Badge.query.all()
    return render_template('badges.html', badges=badges)

@app.route('/stats')
def stats():
    # Compute recent 7 days activity for current_user from Post table
    recent_7_days = []
    if current_user.is_authenticated:
        today = datetime.utcnow().date()
        # build list of last 7 dates (oldest first)
        dates = [(today - timedelta(days=i)) for i in range(6, -1, -1)]
        for d in dates:
            start = datetime.combine(d, datetime.min.time())
            end = datetime.combine(d, datetime.max.time())
            minutes_sum = db.session.query(db.func.coalesce(db.func.sum(Post.minutes), 0)).filter(
                Post.user_id == current_user.id,
                Post.created_at >= start,
                Post.created_at <= end
            ).scalar() or 0
            recent_7_days.append({'date': d.strftime('%m-%d'), 'minutes': int(minutes_sum)})
    else:
        # not logged in, show zeros
        today = datetime.utcnow().date()
        dates = [(today - timedelta(days=i)) for i in range(6, -1, -1)]
        for d in dates:
            recent_7_days.append({'date': d.strftime('%m-%d'), 'minutes': 0})

    return render_template('stats.html', recent_7_days=recent_7_days)


@app.route('/friends')
def friends_page():
    # show friends for current user and invites addressed to current user
    if current_user.is_authenticated:
        friends_q = Friend.query.filter_by(owner_id=current_user.id).all()
        friends = [f.friend_name for f in friends_q]
        pending_invites = PendingInvite.query.filter_by(to_user=current_user.username).all()
    else:
        friends = []
        pending_invites = []
    return render_template('friends.html', friends=friends, pending=pending_invites)


@app.route('/checkin', methods=['GET', 'POST'])
@login_required
def checkin():
    # Simple checkin page: on GET render form, on POST create a Post and redirect to home
    if request.method == 'POST':
        sport = request.form.get('sport', '').strip()
        try:
            minutes = int(request.form.get('minutes', 0))
        except Exception:
            minutes = 0
        message = request.form.get('message', '').strip()
        image = None
        file = request.files.get('image')
        if file and file.filename and allowed_file(file.filename):
            image = save_uploaded_file(file)

        post = Post(user_id=current_user.id, sport=sport or None, minutes=minutes, message=message or None, image=image)
        db.session.add(post)
        db.session.commit()
        flash('已新增打卡貼文')
        return redirect(url_for('index'))

    return render_template('checkin.html')


@app.route('/friends/search')
def friends_search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    # Search users by username or display_name
    users = User.query.filter((User.username.contains(q)) | (User.display_name.contains(q))).all()
    # return list of usernames
    return jsonify([u.username for u in users])


@app.route('/friends/accept', methods=['POST'])
def friends_accept():
    try:
        invite_id = int(request.form.get('invite_id', 0))
    except Exception:
        return jsonify({'ok': False}), 400

    invite = PendingInvite.query.get(invite_id)
    if invite and invite.to_user == current_user.username:
        # create friend entries for both users (owner -> friend)
        try:
            f1 = Friend(owner_id=current_user.id, friend_name=invite.from_user)
            # try to find the other user's id
            other = User.query.filter_by(username=invite.from_user).first()
            if other:
                f2 = Friend(owner_id=other.id, friend_name=current_user.username)
                db.session.add(f2)
            db.session.add(f1)
            db.session.delete(invite)
            db.session.commit()
            return jsonify({'ok': True, 'friend': invite.from_user})
        except Exception:
            db.session.rollback()
            return jsonify({'ok': False}), 500

    return jsonify({'ok': False}), 404


@app.route('/friends/invite', methods=['POST'])
@login_required
def friends_invite():
    username = request.form.get('username', '').strip()
    if not username:
        return jsonify({'ok': False}), 400
    # can't invite yourself
    if username == current_user.username:
        return jsonify({'ok': False, 'error': "不能邀請自己"}), 400
    # check target exists
    target = User.query.filter_by(username=username).first()
    if not target:
        return jsonify({'ok': False, 'error': "找不到使用者"}), 404
    # check existing invite
    existing = PendingInvite.query.filter_by(from_user=current_user.username, to_user=username).first()
    if existing:
        return jsonify({'ok': False, 'error': '已發送邀請'}), 400
    # check already friends
    already = Friend.query.filter_by(owner_id=current_user.id, friend_name=username).first()
    if already:
        return jsonify({'ok': False, 'error': '已是好友'}), 400
    inv = PendingInvite(from_user=current_user.username, to_user=username, time=datetime.utcnow().strftime('%Y-%m-%d %H:%M'))
    db.session.add(inv)
    db.session.commit()
    return jsonify({'ok': True})


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
            current_user.avatar = save_uploaded_file(file)

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
