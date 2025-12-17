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
from flask_migrate import Migrate

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # 用於 flash 訊息

# 上傳相關設定
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# 資料庫設定：支援本機 sqlite、直接的 DATABASE_URL，或用零散的環境變數組裝（DB_HOST/DB_NAME/DB_USER/DB_PASSWORD）
db_url = os.environ.get('DATABASE_URL') or os.environ.get('RENDER_DATABASE_URL')
if not db_url:
    db_host = os.environ.get('DB_HOST') or os.environ.get('PGHOST')
    db_name = os.environ.get('DB_NAME') or os.environ.get('PGDATABASE')
    db_user = os.environ.get('DB_USER') or os.environ.get('PGUSER')
    db_pass = os.environ.get('DB_PASSWORD') or os.environ.get('PGPASSWORD')
    db_port = os.environ.get('DB_PORT') or os.environ.get('PGPORT')
    if db_host and db_name and db_user:
        auth = f"{db_user}:{db_pass}@" if db_pass else f"{db_user}@"
        host_part = f"{db_host}:{db_port}" if db_port else db_host
        db_url = f"postgresql://{auth}{host_part}/{db_name}"

if db_url:
    # Render 以及某些服務會回傳以 postgres:// 開頭的 URL，SQLAlchemy/psycopg2 期望 postgresql://
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    # 如果是 Postgres，建議開啟 sslmode=require（可由 PGSSLMODE 環境變數覆蓋）
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'connect_args': {'sslmode': os.environ.get('PGSSLMODE', 'require')}
    }
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
# Initialize Flask-Migrate
migrate = Migrate(app, db)



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
    visibility = db.Column(db.String(20), default='public')
    image = db.Column(db.String(300), nullable=True)
    shared_from_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    likes = db.Column(db.Integer, default=0)
    user = db.relationship('User', backref=db.backref('posts', lazy=True))

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user = db.Column(db.String(120), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    avatar = db.Column(db.String(300), nullable=True)
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


# Likes: one per (user, post)
class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='uix_user_post_like'),)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # recipient
    actor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # who triggered
    verb = db.Column(db.String(50), nullable=False)  # like, comment, share, mention
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=True)
    data = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    read = db.Column(db.Boolean, default=False)


def create_notification(recipient_id, actor_id=None, verb='notify', post_id=None, comment_id=None, data=None):
    try:
        n = Notification(user_id=recipient_id, actor_id=actor_id, verb=verb, post_id=post_id, comment_id=comment_id, data=data)
        db.session.add(n)
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        return False

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
 


@app.route('/like', methods=['POST'])
@login_required
def like_post():
    post_id = int(request.form.get('post_id', 0))
    p = Post.query.get(post_id)
    if not p:
        return jsonify({'ok': False}), 404

    existing = Like.query.filter_by(user_id=current_user.id, post_id=post_id).first()
    if existing:
        # unlike
        try:
            db.session.delete(existing)
            p.likes = max((p.likes or 1) - 1, 0)
            db.session.commit()
            return jsonify({'ok': True, 'likes': p.likes, 'liked': False})
        except Exception:
            db.session.rollback()
            return jsonify({'ok': False}), 500
    else:
        # add like
        try:
            lk = Like(user_id=current_user.id, post_id=post_id)
            db.session.add(lk)
            p.likes = (p.likes or 0) + 1
            db.session.commit()
            # create notification for post owner
            if p.user_id and p.user_id != current_user.id:
                create_notification(recipient_id=p.user_id, actor_id=current_user.id, verb='like', post_id=p.id)
            return jsonify({'ok': True, 'likes': p.likes, 'liked': True})
        except Exception:
            db.session.rollback()
            return jsonify({'ok': False}), 500


@app.route('/comment', methods=['POST'])
def comment_post():
    post_id = int(request.form.get('post_id', 0))
    # determine commenter: if logged-in use current_user, else use provided user field
    if current_user.is_authenticated:
        commenter_name = current_user.display_name or current_user.username
        commenter_id = current_user.id
        commenter_avatar = current_user.avatar
    else:
        commenter_name = request.form.get('user') or '匿名'
        commenter_id = None
        commenter_avatar = None

    text = request.form.get('text', '').strip()
    if not text:
        return jsonify({'ok': False, 'error': 'empty'}), 400
    p = Post.query.get(post_id)
    if p:
        comment = Comment(post_id=p.id, user=commenter_name, user_id=commenter_id, avatar=commenter_avatar, text=text)
        db.session.add(comment)
        db.session.commit()
        # notify post owner if different
        try:
            if p.user_id and commenter_id != p.user_id:
                create_notification(recipient_id=p.user_id, actor_id=commenter_id, verb='comment', post_id=p.id, comment_id=comment.id, data=text)
        except Exception:
            pass
        # notify mentioned users in the comment text
        try:
            mentions = re.findall(r'@([A-Za-z0-9_\-]+)', text)
            for uname in set(mentions):
                u = User.query.filter_by(username=uname).first()
                if u and u.id != commenter_id:
                    create_notification(recipient_id=u.id, actor_id=commenter_id, verb='mention', post_id=p.id, comment_id=comment.id, data=text)
        except Exception:
            pass
        return jsonify({'ok': True, 'comment': {'user': comment.user, 'avatar': comment.avatar, 'text': comment.text, 'time': comment.time.strftime('%Y-%m-%d %H:%M')}})
    return jsonify({'ok': False}), 404

from sqlalchemy import case, and_
from sqlalchemy import or_
import re


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

    # allow mode: friends or all
    mode = (request.args.get('mode') or 'all')
    q = db.session.query(User.id, User.display_name, User.username, minutes_expr).outerjoin(Post, Post.user_id == User.id).group_by(User.id)
    if mode == 'friends' and current_user.is_authenticated:
        # collect friend ids (friends of current user) and include current user
        friend_entries = Friend.query.filter_by(owner_id=current_user.id).all()
        friend_usernames = [f.friend_name for f in friend_entries]
        # include self
        friend_usernames.append(current_user.username)
        # get user ids
        friend_users = User.query.filter(User.username.in_(friend_usernames)).all()
        friend_ids = [u.id for u in friend_users]
        if friend_ids:
            q = q.filter(User.id.in_(friend_ids))

    q = q.order_by(db.desc('points'))
    results = q.all()

    leaderboard = []
    for r in results:
        name = r.display_name or r.username
        # fetch avatar if available
        u = User.query.get(r.id)
        avatar = u.avatar if u else None
        leaderboard.append({'id': r.id, 'name': name, 'points': int(r.points) if r.points is not None else 0, 'avatar': avatar})

    return render_template('leaderboard.html', leaderboard=leaderboard, badges=badges, mode=mode)


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
        friends = []
        for f in friends_q:
            # try to get user object for avatar/display
            u = User.query.filter_by(username=f.friend_name).first()
            friends.append({'username': f.friend_name, 'display': (u.display_name if u and u.display_name else f.friend_name), 'avatar': (u.avatar if u else None)})
        pending_q = PendingInvite.query.filter_by(to_user=current_user.username).all()
        pending_invites = []
        for p in pending_q:
            u = User.query.filter_by(username=p.from_user).first()
            pending_invites.append({'id': p.id, 'from_user': p.from_user, 'time': p.time, 'avatar': (u.avatar if u else None)})
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
        visibility = request.form.get('visibility', 'public')
        image = None
        file = request.files.get('image')
        if file and file.filename and allowed_file(file.filename):
            image = save_uploaded_file(file)

        # create post (mentions will be rendered into links when displaying)
            post = Post(user_id=current_user.id, sport=sport or None, minutes=minutes, message=message or None, image=image, visibility=visibility)
            db.session.add(post)
            db.session.commit()
            # notify mentioned users in the post message
            try:
                if message:
                    mentions = re.findall(r'@([A-Za-z0-9_\-]+)', message)
                    for uname in set(mentions):
                        u = User.query.filter_by(username=uname).first()
                        if u and u.id != current_user.id:
                            create_notification(recipient_id=u.id, actor_id=current_user.id, verb='mention', post_id=post.id, data=message)
            except Exception:
                pass
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
    # return list of dicts with username, display_name and avatar
    out = []
    for u in users:
        out.append({'username': u.username, 'display': u.display_name or u.username, 'avatar': u.avatar})
    return jsonify(out)


@app.route('/share', methods=['POST'])
@login_required
def share_post():
    try:
        orig_id = int(request.form.get('original_id', 0))
    except Exception:
        return jsonify({'ok': False}), 400
    message = request.form.get('message', '').strip()
    orig = Post.query.get(orig_id)
    if not orig:
        return jsonify({'ok': False}), 404
    # create a new post that references the original
    newp = Post(user_id=current_user.id, sport=None, minutes=0, message=message or None, image=None, visibility='public', shared_from_id=orig.id)
    db.session.add(newp)
    db.session.commit()
    # notify original post owner
    try:
        if orig.user_id and orig.user_id != current_user.id:
            create_notification(recipient_id=orig.user_id, actor_id=current_user.id, verb='share', post_id=orig.id, data=message)
    except Exception:
        pass
    return jsonify({'ok': True, 'post_id': newp.id})


@app.route('/user/<username>')
def user_page(username):
    u = User.query.filter_by(username=username).first()
    if not u:
        flash('找不到使用者')
        return redirect(url_for('index'))
    # show user's public posts
    posts_q = Post.query.filter_by(user_id=u.id).order_by(Post.created_at.desc()).all()
    posts = []
    for p in posts_q:
        posts.append({'id': p.id, 'sport': p.sport, 'minutes': p.minutes, 'message': p.message, 'image': p.image, 'created_at': p.created_at.strftime('%Y-%m-%d %H:%M')})
    return render_template('user.html', user=u, posts=posts)


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
        # visibility: include post if public OR if it's friends-only and the current user is allowed
        include = False
        try:
            vis = getattr(p, 'visibility', 'public')
        except Exception:
            vis = 'public'
        if vis == 'public':
            include = True
        else:
            # friends-only: include if current_user is author or current_user is friend with author
            if current_user.is_authenticated and (current_user.id == p.user_id):
                include = True
            else:
                # check Friend table for owner=current_user and friend_name=post author username
                if current_user.is_authenticated:
                    is_friend = Friend.query.filter_by(owner_id=current_user.id, friend_name=p.user.username).first()
                    if is_friend:
                        include = True

        if not include:
            continue

        # determine if current user liked this post
        liked_flag = False
        if current_user.is_authenticated:
            liked_flag = bool(Like.query.filter_by(user_id=current_user.id, post_id=p.id).first())

        # build comment list with avatars if available
        comments_list = []
        for c in p.comments:
            c_avatar = getattr(c, 'avatar', None)
            if not c_avatar:
                # try to resolve by username
                u_c = User.query.filter_by(username=c.user).first()
                if u_c:
                    c_avatar = u_c.avatar
            comments_list.append({'user': c.user, 'avatar': c_avatar, 'text': c.text, 'time': c.time.strftime('%Y-%m-%d %H:%M')})

        # convert mentions (@username) in message to links
        msg_html = None
        if p.message:
            def repl_mention(m):
                uname = m.group(1)
                return f'<a href="{url_for("user_page", username=uname)}">@{uname}</a>'
            msg_html = re.sub(r'@([A-Za-z0-9_\-]+)', repl_mention, p.message)

        # include shared original post if present
        original = None
        if getattr(p, 'shared_from_id', None):
            orig = Post.query.get(p.shared_from_id)
            if orig:
                original = {
                    'id': orig.id,
                    'user': orig.user.display_name or orig.user.username,
                    'avatar': orig.user.avatar,
                    'sport': orig.sport,
                    'minutes': orig.minutes,
                    'message': orig.message,
                    'image': orig.image
                }

        posts.append({
            'id': p.id,
            'user': p.user.display_name or p.user.username,
            'username': p.user.username,
            'avatar': p.user.avatar,
            'sport': p.sport,
            'minutes': p.minutes,
            'message': p.message,
            'message_html': msg_html,
            'image': p.image,
            'created_at': p.created_at.strftime('%Y-%m-%d %H:%M'),
            'likes': p.likes,
            'liked': liked_flag,
            'comments': comments_list,
            'original': original,
            'visibility': vis
        })
    # 未讀通知數
    unread_count = 0
    if current_user.is_authenticated:
        try:
            unread_count = Notification.query.filter_by(user_id=current_user.id, read=False).count()
        except Exception:
            unread_count = 0
    # 傳遞目前使用者狀態給模板
    return render_template('index.html', status=current_user, posts=posts, unread_count=unread_count)


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

    # also show user's own posts
    user_posts = Post.query.filter_by(user_id=current_user.id).order_by(Post.created_at.desc()).all()
    # build simple post dicts for profile
    p_list = []
    for p in user_posts:
        p_list.append({'id': p.id, 'sport': p.sport, 'minutes': p.minutes, 'message': p.message, 'image': p.image, 'created_at': p.created_at.strftime('%Y-%m-%d %H:%M')})
    return render_template('profile.html', profile=current_user, posts=p_list)


@app.route('/post/<int:post_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    p = Post.query.get(post_id)
    if not p:
        flash('找不到貼文')
        return redirect(url_for('index'))
    if p.user_id != current_user.id:
        flash('沒有權限')
        return redirect(url_for('index'))
    if request.method == 'POST':
        message = request.form.get('message', '').strip()
        visibility = request.form.get('visibility', 'public')
        file = request.files.get('image')
        if file and file.filename and allowed_file(file.filename):
            p.image = save_uploaded_file(file)
        p.message = message or None
        p.visibility = visibility
        db.session.commit()
        flash('已更新貼文')
        return redirect(url_for('profile_page'))
    return render_template('edit_post.html', post=p)


@app.route('/post/<int:post_id>/delete', methods=['POST'])
@login_required
def delete_post(post_id):
    p = Post.query.get(post_id)
    if not p:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({'ok': False}), 404
        flash('找不到貼文')
        return redirect(url_for('index'))
    if p.user_id != current_user.id:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({'ok': False, 'error': 'no permission'}), 403
        flash('沒有權限刪除該貼文')
        return redirect(url_for('index'))
    try:
        # delete related comments and likes
        Comment.query.filter_by(post_id=p.id).delete()
        Like.query.filter_by(post_id=p.id).delete()
        db.session.delete(p)
        db.session.commit()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({'ok': True})
        flash('貼文已刪除')
        return redirect(url_for('profile_page'))
    except Exception:
        db.session.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({'ok': False}), 500
        flash('刪除貼文失敗')
        return redirect(url_for('profile_page'))


@app.route('/delete_account', methods=['POST'])
@login_required
def delete_account():
    # copy info we need then logout to avoid deleting object referenced by flask-login
    uid = current_user.id
    uname = current_user.username
    try:
        logout_user()
    except Exception:
        pass

    try:
        # delete user's posts, comments, likes
        Post.query.filter_by(user_id=uid).delete()
        Comment.query.filter_by(user_id=uid).delete()
        Like.query.filter_by(user_id=uid).delete()
        # delete friend relations owned by user and references to user's username
        Friend.query.filter_by(owner_id=uid).delete()
        Friend.query.filter(Friend.friend_name == uname).delete()
        # pending invites involving this user
        PendingInvite.query.filter(or_(PendingInvite.from_user == uname, PendingInvite.to_user == uname)).delete()
        # notifications where user is recipient or actor
        Notification.query.filter(or_(Notification.user_id == uid, Notification.actor_id == uid)).delete()
        # finally delete user row
        User.query.filter_by(id=uid).delete()
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash('刪除帳號失敗')
        return redirect(url_for('profile_page'))

    flash('帳號已刪除')
    return redirect(url_for('register'))


@app.route('/notifications')
@login_required
def notifications_page():
    notes = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
    # build display info
    out = []
    for n in notes:
        actor = User.query.get(n.actor_id) if n.actor_id else None
        post = Post.query.get(n.post_id) if n.post_id else None
        out.append({'id': n.id, 'verb': n.verb, 'actor': (actor.display_name or actor.username) if actor else None, 'actor_avatar': actor.avatar if actor else None, 'post_id': n.post_id, 'comment_id': n.comment_id, 'data': n.data, 'created_at': n.created_at.strftime('%Y-%m-%d %H:%M'), 'read': n.read})
    return render_template('notifications.html', notifications=out)


@app.route('/notifications/mark_read', methods=['POST'])
@login_required
def notifications_mark_read():
    nid = request.form.get('id')
    if nid == 'all':
        Notification.query.filter_by(user_id=current_user.id, read=False).update({'read': True})
        db.session.commit()
        return jsonify({'ok': True})
    try:
        nid_i = int(nid)
    except Exception:
        return jsonify({'ok': False}), 400
    n = Notification.query.get(nid_i)
    if not n or n.user_id != current_user.id:
        return jsonify({'ok': False}), 404
    n.read = True
    db.session.commit()
    return jsonify({'ok': True})

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
    # ensure DB tables exist for simple local runs; migrations should be used for schema changes
    try:
        db.create_all()
    except Exception:
        # if create_all fails, defer to migrations
        pass

if __name__ == '__main__':
    app.run(debug=True, port=5000)
