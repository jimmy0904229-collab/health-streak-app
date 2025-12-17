from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
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
BADGE_FOLDER = 'static/badges'
os.makedirs(BADGE_FOLDER, exist_ok=True)
app.config['BADGE_FOLDER'] = BADGE_FOLDER

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg'}

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
# --- Runtime DB inspection to be resilient to schema differences ---
from sqlalchemy import inspect as sa_inspect

def _get_existing_tables_and_columns():
    try:
        insp = sa_inspect(db.engine)
        tables = set(insp.get_table_names())
        cols = {}
        for t in tables:
            try:
                cols[t] = {c['name'] for c in insp.get_columns(t)}
            except Exception:
                cols[t] = set()
        return tables, cols
    except Exception:
        return set(), {}

EXISTING_TABLES, EXISTING_COLUMNS = _get_existing_tables_and_columns()
# choose which user table exists (prefer 'users' then 'user')
if 'users' in EXISTING_TABLES:
    USER_TABLE = 'users'
elif 'user' in EXISTING_TABLES:
    USER_TABLE = 'user'
else:
    # fallback to 'users' as our code default; migrations can create it later
    USER_TABLE = 'users'


# 確保診斷程式僅執行一次
_db_diagnostics_ran = False

@app.before_request
def _run_db_diagnostics_once():
    global _db_diagnostics_ran
    if not _db_diagnostics_ran:
        _db_diagnostics_ran = True
        _log_db_diagnostics()


def _log_db_diagnostics():
    try:
        db_url = os.environ.get('DATABASE_URL') or os.environ.get('RENDER_DATABASE_URL') or ''
        app.logger.info('DB diagnostics starting. DATABASE_URL present=%s; USER_TABLE=%s', bool(db_url), USER_TABLE)
        app.logger.debug('DB env PGSSLMODE=%s; PGHOST=%s; PGPORT=%s', os.environ.get('PGSSLMODE'), os.environ.get('PGHOST') or os.environ.get('DB_HOST'), os.environ.get('PGPORT') or os.environ.get('DB_PORT'))
        # quick connectivity check
        try:
            with db.engine.connect() as conn:
                try:
                    val = conn.execute(text('SELECT 1')).scalar()
                    app.logger.info('DB simple query returned: %s', val)
                except Exception as e:
                    app.logger.warning('DB simple query failed: %s', str(e))
                # server-side SSL setting (if Postgres supports SHOW ssl)
                try:
                    ssl_setting = conn.execute(text("SHOW ssl"))
                    ssl_val = ssl_setting.scalar()
                    app.logger.info('Postgres "ssl" setting: %s', ssl_val)
                except Exception as e:
                    app.logger.debug('Could not read Postgres ssl setting: %s', str(e))
                # try pg_stat_ssl join for active sessions (may not exist on older versions or restricted roles)
                try:
                    rows = conn.execute(text('SELECT pid, ssl, client_addr FROM pg_stat_ssl JOIN pg_stat_activity USING (pid) LIMIT 5')).fetchall()
                    app.logger.info('pg_stat_ssl sample rows: %s', rows)
                except Exception as e:
                    app.logger.debug('pg_stat_ssl not available or query failed: %s', str(e))
        except Exception as e:
            app.logger.exception('DB engine.connect() failed: %s', str(e))
    except Exception:
        app.logger.exception('Unexpected error during DB diagnostics')



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
    filename = secure_filename(file.filename or '')
    if not filename:
        return None
    # generate unique name to avoid collisions
    unique_name = f"{uuid.uuid4().hex}_{filename}"
    s3 = get_s3_client()
    # Try S3 first (if configured)
    if s3:
        bucket = os.environ.get('AWS_S3_BUCKET')
        key = f'uploads/{unique_name}'
        content_type = getattr(file, 'content_type', None) or 'application/octet-stream'
        try:
            # ensure stream at start
            try:
                file.stream.seek(0)
            except Exception:
                pass
            data = file.read()
            s3.put_object(Bucket=bucket, Key=key, Body=data, ACL='public-read', ContentType=content_type)
            base = get_s3_base_url()
            if base:
                # if base includes formatting token for bucket
                if '{bucket}' in base:
                    url = base.format(bucket=bucket).rstrip('/') + f'/{key}'
                else:
                    url = base.rstrip('/') + f'/{key}'
            else:
                # default AWS URL
                region = os.environ.get('AWS_REGION')
                if region:
                    url = f'https://{bucket}.s3.{region}.amazonaws.com/{key}'
                else:
                    url = f'https://{bucket}.s3.amazonaws.com/{key}'
            app.logger.info('Uploaded file to S3: %s', url)
            return url
        except Exception as e:
            app.logger.warning('S3 upload failed (%s), falling back to local: %s', getattr(e, 'message', str(e)), filename)

    # Local fallback storage
    try:
        dest_folder = app.config.get('UPLOAD_FOLDER', 'static/uploads')
        os.makedirs(dest_folder, exist_ok=True)
        filepath = os.path.join(dest_folder, unique_name)
        try:
            file.stream.seek(0)
        except Exception:
            pass
        file.save(filepath)
        url = url_for('static', filename=f'uploads/{unique_name}')
        app.logger.info('Saved uploaded file locally: %s', url)
        return url
    except Exception as e:
        app.logger.error('Failed to save uploaded file: %s', str(e))
        return None


def to_local_str(dt):
    """Convert a stored UTC datetime (naive or tz-aware) to Asia/Taipei formatted string."""
    if not dt:
        return ''
    try:
        tz = ZoneInfo('Asia/Taipei')
        if dt.tzinfo is None:
            # treat naive as UTC
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(tz)
        return local.strftime('%Y-%m-%d %H:%M')
    except Exception:
        try:
            return dt.strftime('%Y-%m-%d %H:%M')
        except Exception:
            return ''


# 登入管理
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = '請先登入以存取此頁面'
login_manager.login_message_category = 'info'

# 定義資料模型
class User(UserMixin, db.Model):
    # tablename chosen at runtime to match existing DB ('users' or 'user')
    __tablename__ = USER_TABLE
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    display_name = db.Column(db.String(120), nullable=True)
    avatar = db.Column(db.String(300), nullable=True)
    # optionally map avatar_blob/avatar_mime only if DB has those columns
    if USER_TABLE in EXISTING_COLUMNS and 'avatar_blob' in EXISTING_COLUMNS.get(USER_TABLE, set()):
        avatar_blob = db.Column(db.LargeBinary, nullable=True)
    if USER_TABLE in EXISTING_COLUMNS and 'avatar_mime' in EXISTING_COLUMNS.get(USER_TABLE, set()):
        avatar_mime = db.Column(db.String(100), nullable=True)
    notify = db.Column(db.Boolean, default=True)
    streak_days = db.Column(db.Integer, default=0)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey(f"{USER_TABLE}.id"), nullable=False)
    sport = db.Column(db.String(80), nullable=True)
    minutes = db.Column(db.Integer, default=0)
    message = db.Column(db.Text, nullable=True)
    visibility = db.Column(db.String(20), default='public')
    image = db.Column(db.String(300), nullable=True)
    # optionally map image_blob/image_mime only if DB has those columns
    if 'post' in EXISTING_COLUMNS and 'image_blob' in EXISTING_COLUMNS.get('post', set()):
        image_blob = db.Column(db.LargeBinary, nullable=True)
    if 'post' in EXISTING_COLUMNS and 'image_mime' in EXISTING_COLUMNS.get('post', set()):
        image_mime = db.Column(db.String(100), nullable=True)
    shared_from_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    likes = db.Column(db.Integer, default=0)
    user = db.relationship('User', backref=db.backref('posts', lazy=True))

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user = db.Column(db.String(120), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey(f"{USER_TABLE}.id"), nullable=True)
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
    # Badge metadata (static)
    title = db.Column(db.String(80), nullable=False)
    desc = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(80), unique=True, nullable=False)
    image_filename = db.Column(db.String(300), nullable=True)
    criteria_json = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)

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
    owner_id = db.Column(db.Integer, db.ForeignKey(f"{USER_TABLE}.id"), nullable=False)
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
    user_id = db.Column(db.Integer, db.ForeignKey(f"{USER_TABLE}.id"), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='uix_user_post_like'),)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey(f"{USER_TABLE}.id"), nullable=False)  # recipient
    actor_id = db.Column(db.Integer, db.ForeignKey(f"{USER_TABLE}.id"), nullable=True)  # who triggered
    verb = db.Column(db.String(50), nullable=False)  # like, comment, share, mention
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=True)
    data = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    read = db.Column(db.Boolean, default=False)


# association: which user earned which badge
class UserBadge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    badge_id = db.Column(db.Integer, db.ForeignKey('badge.id'), nullable=False)
    earned_at = db.Column(db.DateTime, default=datetime.utcnow)
    pinned = db.Column(db.Boolean, default=False)
    user = db.relationship('User', backref=db.backref('user_badges', lazy=True))
    badge = db.relationship('Badge', backref=db.backref('earned_by', lazy=True))


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
 
# Admin helper: simple username-based admin check (configure ADMIN_USERNAMES env var comma-separated)
def is_admin_user():
    if not current_user or not getattr(current_user, 'is_authenticated', False):
        return False
    admin_list = os.environ.get('ADMIN_USERNAMES', 'admin')
    admins = [a.strip() for a in admin_list.split(',') if a.strip()]
    return current_user.username in admins



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
            # award like-count-based badges for post owner
            try:
                if p.user_id and p.user_id != current_user.id:
                    run_award_checks_on_user(p.user_id)
            except Exception:
                pass
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
        # award comment-count-based badges for post owner
        try:
            if p.user_id and p.user_id != commenter_id:
                run_award_checks_on_user(p.user_id)
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
        return jsonify({'ok': True, 'comment': {'user': comment.user, 'avatar': comment.avatar, 'text': comment.text, 'time': to_local_str(comment.time)}})
    return jsonify({'ok': False}), 404

from sqlalchemy import case, and_
from sqlalchemy import or_
from sqlalchemy import text
import re


# --- Badge awarding helpers ---
BADGE_DEFINITIONS = {
    'streak_3': {'title': '3 Day Streak', 'desc': 'Complete 3 consecutive check-ins', 'slug': 'streak_3', 'image_files': ['3 day.png']},
    'streak_7': {'title': '7 Day Streak', 'desc': 'Complete 7 consecutive check-ins', 'slug': 'streak_7', 'image_files': ['7 day.png']},
    'hours_50': {'title': '50 Hours', 'desc': 'Accumulate 50 hours of activity', 'slug': 'hours_50', 'image_files': ['50 hour.png']},
    'hours_100': {'title': '100 Hours', 'desc': 'Accumulate 100 hours of activity', 'slug': 'hours_100', 'image_files': ['100hour.png']},
    'likes_10': {'title': '10 Likes', 'desc': 'Receive 10 likes on your posts', 'slug': 'likes_10', 'image_files': ['10good.png']},
    'friends_3': {'title': '3 Friends', 'desc': 'Have 3 friends', 'slug': 'friends_3', 'image_files': ['3friend.png']},
    'friends_10': {'title': '10 Friends', 'desc': 'Have 10 friends', 'slug': 'friends_10', 'image_files': ['10friend.png']},
}


def ensure_badge_record(slug):
    """Ensure a Badge record exists for given slug; create it using BADGE_DEFINITIONS and any matching image in static/badges."""
    if slug not in BADGE_DEFINITIONS:
        return None
    bdef = BADGE_DEFINITIONS[slug]
    b = Badge.query.filter_by(slug=bdef['slug']).first()
    if b:
        return b
    # find image file in static/badges
    img = None
    for fname in bdef.get('image_files', []):
        candidate = os.path.join(app.config.get('BADGE_FOLDER', 'static/badges'), fname)
        if os.path.exists(candidate):
            img = fname
            break
    # create badge
    try:
        b = Badge(title=bdef['title'], desc=bdef['desc'], slug=bdef['slug'], image_filename=img, is_active=True)
        db.session.add(b)
        db.session.commit()
        return b
    except Exception:
        db.session.rollback()
        return Badge.query.filter_by(slug=bdef['slug']).first()


def award_badge_if_needed(user_id, slug):
    if not user_id:
        return False
    b = Badge.query.filter_by(slug=slug).first()
    if not b:
        b = ensure_badge_record(slug)
    if not b:
        return False
    # check if already awarded
    exists = UserBadge.query.filter_by(user_id=user_id, badge_id=b.id).first()
    if exists:
        return False
    try:
        ub = UserBadge(user_id=user_id, badge_id=b.id)
        db.session.add(ub)
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        return False


def run_award_checks_on_user(user_id):
    """Run all badge checks for a user (id). Uses posts/comments/likes/friends/streak/minutes thresholds."""
    u = User.query.get(user_id)
    if not u:
        return
    # ensure badge records exist
    for slug in BADGE_DEFINITIONS.keys():
        ensure_badge_record(slug)

    # 1) streak badges
    try:
        sd = int(getattr(u, 'streak_days', 0) or 0)
        if sd >= 3:
            award_badge_if_needed(user_id, 'streak_3')
        if sd >= 7:
            award_badge_if_needed(user_id, 'streak_7')
    except Exception:
        pass

    # 2) cumulative minutes -> hours
    try:
        total_minutes = db.session.query(db.func.coalesce(db.func.sum(Post.minutes), 0)).filter(Post.user_id == user_id).scalar() or 0
        if total_minutes >= 50 * 60:
            award_badge_if_needed(user_id, 'hours_50')
        if total_minutes >= 100 * 60:
            award_badge_if_needed(user_id, 'hours_100')
        if total_minutes >= 500 * 60:
            award_badge_if_needed(user_id, 'hours_500')
    except Exception:
        pass

    # 3) comments received on user's posts
    try:
        post_ids = [r[0] for r in db.session.query(Post.id).filter(Post.user_id == user_id).all()]
        comment_count = 0
        like_count = 0
        if post_ids:
            comment_count = db.session.query(db.func.count(Comment.id)).filter(Comment.post_id.in_(post_ids)).scalar() or 0
            like_count = db.session.query(db.func.count(Like.id)).filter(Like.post_id.in_(post_ids)).scalar() or 0
        if comment_count >= 5:
            award_badge_if_needed(user_id, 'comments_5')
        if like_count >= 10:
            award_badge_if_needed(user_id, 'likes_10')
    except Exception:
        pass

    # 4) friend counts
    try:
        friend_count = Friend.query.filter_by(owner_id=user_id).count()
        if friend_count >= 3:
            award_badge_if_needed(user_id, 'friends_3')
        if friend_count >= 10:
            award_badge_if_needed(user_id, 'friends_10')
    except Exception:
        pass



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
    badges = Badge.query.filter_by(is_active=True).all()
    user_badge_ids = set()
    if current_user.is_authenticated:
        ub = UserBadge.query.filter_by(user_id=current_user.id).all()
        user_badge_ids = set([u.badge_id for u in ub])

    # build badge display info
    badge_list = []
    for b in badges:
        img_url = None
        if b.image_filename:
            img_url = url_for('static', filename=f'badges/{b.image_filename}')
        badge_list.append({'id': b.id, 'title': b.title, 'desc': b.desc, 'slug': b.slug, 'image': img_url, 'earned': (b.id in user_badge_ids)})

    return render_template('badges.html', badges=badge_list)


@app.route('/admin/badges', methods=['GET', 'POST'])
@login_required
def admin_badges():
    if not is_admin_user():
        flash('沒有權限')
        return redirect(url_for('index'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        desc = request.form.get('desc', '').strip()
        slug = request.form.get('slug', '').strip() or (title.replace(' ', '_').lower() if title else '')
        file = request.files.get('image')
        image_filename = None
        if file and file.filename and allowed_file(file.filename):
            fn = secure_filename(file.filename)
            unique = f"{uuid.uuid4().hex}_{fn}"
            dest = os.path.join(app.config.get('BADGE_FOLDER', 'static/badges'), unique)
            # ensure folder
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            file.stream.seek(0)
            file.save(dest)
            image_filename = unique

        # create badge record
        try:
            b = Badge(title=title or (slug or 'unnamed'), desc=desc or '', slug=slug or str(uuid.uuid4().hex), image_filename=image_filename, is_active=True)
            db.session.add(b)
            db.session.commit()
            flash('徽章已新增')
            return redirect(url_for('admin_badges'))
        except Exception:
            db.session.rollback()
            flash('新增徽章失敗')

    # GET: list badges
    badges = Badge.query.order_by(Badge.id.desc()).all()
    badge_list = []
    for b in badges:
        img_url = url_for('static', filename=f'badges/{b.image_filename}') if b.image_filename else None
        badge_list.append({'id': b.id, 'title': b.title, 'desc': b.desc, 'slug': b.slug, 'image': img_url, 'active': b.is_active})
    return render_template('badges_admin.html', badges=badge_list)

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
        image_blob = None
        image_mime = None
        file = request.files.get('image')
        if file and file.filename and allowed_file(file.filename):
            # If configured to store uploads in DB, save bytes to Post.image_blob
            if os.environ.get('STORE_UPLOADS_IN_DB') == '1':
                try:
                    try:
                        file.stream.seek(0)
                    except Exception:
                        pass
                    data = file.read()
                    if data:
                        image_blob = data
                        image_mime = getattr(file, 'content_type', None) or 'application/octet-stream'
                except Exception:
                    image_blob = None
                    image_mime = None
            else:
                image = save_uploaded_file(file)

        # determine post created_at in UTC (store UTC in DB)
        date_str = request.form.get('date')
        time_str = request.form.get('time')
        post_created_utc = None
        try:
            if date_str and time_str:
                # parse user-provided local datetime (assume Asia/Taipei)
                dt_local = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                dt_local = dt_local.replace(tzinfo=ZoneInfo('Asia/Taipei'))
                dt_utc = dt_local.astimezone(timezone.utc)
                # store naive UTC
                post_created_utc = dt_utc.replace(tzinfo=None)
            else:
                post_created_utc = datetime.utcnow()
        except Exception:
            post_created_utc = datetime.utcnow()

        # compute streak based on dates in Asia/Taipei (consecutive days)
        try:
            local_tz = ZoneInfo('Asia/Taipei')
            this_local_date = post_created_utc.replace(tzinfo=timezone.utc).astimezone(local_tz).date()

            # fetch last previous post (before this one) - do this before adding the new post
            last_post = Post.query.filter(Post.user_id == current_user.id).order_by(Post.created_at.desc()).first()
            last_date = None
            if last_post:
                try:
                    last_date = (last_post.created_at.replace(tzinfo=timezone.utc).astimezone(local_tz)).date()
                except Exception:
                    last_date = None

            if last_post is None:
                new_streak = 1
            else:
                if last_date == this_local_date:
                    new_streak = current_user.streak_days or 1
                elif last_date == (this_local_date - timedelta(days=1)):
                    new_streak = (current_user.streak_days or 0) + 1
                else:
                    new_streak = 1
        except Exception:
            new_streak = (current_user.streak_days or 0) + 1

        # ensure the current_user exists in the DB table referenced by the Post FK
        # If the auth session has a user id that doesn't exist in the DB (dirty/mismatched schema),
        # create a minimal placeholder user so foreign key constraint won't fail.
        try:
            user_in_db = User.query.get(current_user.id)
            if user_in_db is None:
                # create a placeholder password hash so the not-null constraint is satisfied
                placeholder_pw = generate_password_hash(str(uuid.uuid4()))
                placeholder_username = getattr(current_user, 'username', f'user{current_user.id}')
                placeholder_display = getattr(current_user, 'display_name', None)
                placeholder = User(id=current_user.id, username=placeholder_username, password=placeholder_pw, display_name=placeholder_display, avatar=None)
                db.session.add(placeholder)
                # flush so the new user exists for the upcoming Post insert
                try:
                    db.session.flush()
                except Exception:
                    # if flush fails, rollback to avoid leaving the session in a bad state
                    db.session.rollback()
        except Exception:
            # be defensive: if anything goes wrong, continue and let the Post insertion raise a clear error
            pass

        # create post with created_at set (UTC naive)
        # Determine a safe user_id to use for the Post. If current_user.id isn't present
        # in the DB, try to find an existing user to attach to; if none, attempt to
        # create a placeholder with a unique username. This avoids FK violations.
        final_user_id = None
        try:
            if User.query.get(current_user.id):
                final_user_id = current_user.id
            else:
                # try to find a user with the same username
                base_username = getattr(current_user, 'username', None)
                if base_username:
                    u = User.query.filter_by(username=base_username).first()
                    if u:
                        final_user_id = u.id
                # otherwise pick any existing user as fallback
                if final_user_id is None:
                    any_u = User.query.first()
                    if any_u:
                        final_user_id = any_u.id
                # if still None, try creating a placeholder user with unique username
                if final_user_id is None:
                    placeholder_pw = generate_password_hash(str(uuid.uuid4()))
                    uname = base_username or f'user_{uuid.uuid4().hex[:8]}'
                    for _ in range(3):
                        try:
                            placeholder = User(id=current_user.id, username=uname, password=placeholder_pw, display_name=getattr(current_user, 'display_name', None), avatar=None)
                            db.session.add(placeholder)
                            db.session.flush()
                            final_user_id = placeholder.id
                            break
                        except Exception:
                            db.session.rollback()
                            uname = f"{uname}_{uuid.uuid4().hex[:6]}"
                    # as a last resort, create a placeholder without forcing id (autoincrement)
                    if final_user_id is None:
                        try:
                            placeholder = User(username=uname, password=placeholder_pw, display_name=getattr(current_user, 'display_name', None), avatar=None)
                            db.session.add(placeholder)
                            db.session.flush()
                            final_user_id = placeholder.id
                        except Exception:
                            db.session.rollback()
                            # leave final_user_id as None; insertion below will likely raise a clear error
                            final_user_id = None
        except Exception:
            final_user_id = None

        # Only include image_blob/image_mime if the Post model actually defines those attributes
        post_kwargs = {
            'user_id': final_user_id if final_user_id is not None else current_user.id,
            'sport': sport or None,
            'minutes': minutes,
            'message': message or None,
            'image': image,
            'visibility': visibility,
            'created_at': post_created_utc,
        }
        if hasattr(Post, 'image_blob') and image_blob is not None:
            post_kwargs['image_blob'] = image_blob
        if hasattr(Post, 'image_mime') and image_mime is not None:
            post_kwargs['image_mime'] = image_mime

        post = Post(**post_kwargs)
        db.session.add(post)
        try:
            current_user.streak_days = new_streak
        except Exception:
            pass
        db.session.commit()
        # run award checks for this user (streaks and cumulative minutes)
        try:
            run_award_checks_on_user(current_user.id)
        except Exception:
            pass
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

    # prepare defaults for date/time inputs (use Asia/Taipei local time)
    try:
        now_local = datetime.now(ZoneInfo('Asia/Taipei'))
        default_date = now_local.strftime('%Y-%m-%d')
        default_time = now_local.strftime('%H:%M')
    except Exception:
        now = datetime.utcnow()
        default_date = now.strftime('%Y-%m-%d')
        default_time = now.strftime('%H:%M')
    return render_template('checkin.html', default_date=default_date, default_time=default_time)


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
    # Award share does not currently affect badges, but we can run a generic check
    try:
        run_award_checks_on_user(current_user.id)
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
        try:
            if getattr(p, 'image_blob', None):
                image_url = url_for('post_image', post_id=p.id)
            else:
                image_url = p.image
        except Exception:
            image_url = p.image
        posts.append({'id': p.id, 'sport': p.sport, 'minutes': p.minutes, 'message': p.message, 'image': image_url, 'created_at': to_local_str(p.created_at)})
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
            # award friend-count-based badges for both users
            try:
                other_user = User.query.filter_by(username=invite.from_user).first()
                if other_user:
                    run_award_checks_on_user(other_user.id)
                run_award_checks_on_user(current_user.id)
            except Exception:
                pass
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
    inv_time = datetime.now(ZoneInfo('Asia/Taipei')).strftime('%Y-%m-%d %H:%M')
    inv = PendingInvite(from_user=current_user.username, to_user=username, time=inv_time)
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
                    if getattr(u_c, 'avatar_blob', None):
                        try:
                            c_avatar = url_for('user_avatar', user_id=u_c.id)
                        except Exception:
                            c_avatar = u_c.avatar
                    else:
                        c_avatar = u_c.avatar
            comments_list.append({'user': c.user, 'avatar': c_avatar, 'text': c.text, 'time': to_local_str(c.time)})

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
                    'avatar': (url_for('user_avatar', user_id=orig.user.id) if getattr(orig.user, 'avatar_blob', None) else orig.user.avatar),
                    'sport': orig.sport,
                    'minutes': orig.minutes,
                    'message': orig.message,
                    'image': orig.image
                }
        # fetch the user's pinned badges (up to 3) if any
        pinned_badges = []
        try:
            ubps = UserBadge.query.filter_by(user_id=p.user.id, pinned=True).order_by(UserBadge.earned_at.asc()).limit(3).all()
            for ubp in ubps:
                try:
                    bimg = ubp.badge.image_filename
                    if bimg:
                        pinned_badges.append(url_for('static', filename=f'badges/{bimg}'))
                except Exception:
                    continue
        except Exception:
            pinned_badges = []

        # compute avatar and image urls (prefer DB blobs when present)
        try:
            # 如果 p.user 存在且有 avatar_blob，從 DB blob 產生 URL
            if p.user and getattr(p.user, 'avatar_blob', None):
                avatar_url = url_for('user_avatar', user_id=p.user.id)
            else:
                # 如果 p.user 存在就取他的 avatar 屬性，否則使用預設頭像
                if p.user:
                    avatar_url = p.user.avatar
                else:
                    avatar_url = "https://ui-avatars.com/api/?name=Unknown"
        except Exception:
            # 發生任何例外時也不要崩潰，改用預設頭像
            avatar_url = "https://ui-avatars.com/api/?name=Unknown"

        try:
            if getattr(p, 'image_blob', None):
                image_url = url_for('post_image', post_id=p.id)
            else:
                image_url = p.image
        except Exception:
            image_url = p.image

        posts.append({
            'id': p.id,
            # 如果 p.user 存在就顯示 display_name 或 username，否則使用 "未知使用者"
            'user': (p.user.display_name or p.user.username) if p.user else "未知使用者",
            'username': p.user.username if p.user else "unknown",
            'avatar': avatar_url,
            'sport': p.sport,
            'minutes': p.minutes,
            'message': p.message,
            'message_html': msg_html,
            'image': image_url,
            'pinned_badges': pinned_badges,
            'created_at': to_local_str(p.created_at),
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
    # 顯示目前使用者的個人資料與貼文（設定移至 /settings）
    user_posts = Post.query.filter_by(user_id=current_user.id).order_by(Post.created_at.desc()).all()
    p_list = []
    for p in user_posts:
        try:
            if getattr(p, 'image_blob', None):
                image_url = url_for('post_image', post_id=p.id)
            else:
                image_url = p.image
        except Exception:
            image_url = p.image
        p_list.append({'id': p.id, 'sport': p.sport, 'minutes': p.minutes, 'message': p.message, 'image': image_url, 'created_at': to_local_str(p.created_at)})
    # fetch user's earned badges
    earned = []
    try:
        ubs = UserBadge.query.filter_by(user_id=current_user.id).all()
        for ub in ubs:
            b = Badge.query.get(ub.badge_id)
            if b:
                img = url_for('static', filename=f'badges/{b.image_filename}') if b.image_filename else None
                earned.append({'title': b.title, 'desc': b.desc, 'image': img, 'earned_at': ub.earned_at})
    except Exception:
        earned = []

    return render_template('profile.html', profile=current_user, posts=p_list, earned_badges=earned)


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
        # update sport/minutes/message/visibility/image and optional date/time
        sport = request.form.get('sport', '').strip()
        try:
            minutes = int(request.form.get('minutes', 0))
        except Exception:
            minutes = 0
        message = request.form.get('message', '').strip()
        visibility = request.form.get('visibility', 'public')
        # handle optional image replacement
        file = request.files.get('image')
        if file and file.filename and allowed_file(file.filename):
            if os.environ.get('STORE_UPLOADS_IN_DB') == '1':
                try:
                    try:
                        file.stream.seek(0)
                    except Exception:
                        pass
                    data = file.read()
                    if data:
                        p.image_blob = data
                        p.image_mime = getattr(file, 'content_type', None) or 'application/octet-stream'
                        p.image = None
                except Exception:
                    pass
            else:
                p.image = save_uploaded_file(file)

        # parse date/time fields (assume Asia/Taipei local)
        date_str = request.form.get('date')
        time_str = request.form.get('time')
        if date_str and time_str:
            try:
                local_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                local_dt = local_dt.replace(tzinfo=ZoneInfo('Asia/Taipei'))
                utc_dt = local_dt.astimezone(timezone.utc)
                # store naive UTC
                p.created_at = utc_dt.replace(tzinfo=None)
            except Exception:
                pass

        p.sport = sport or None
        p.minutes = minutes
        p.message = message or None
        p.visibility = visibility
        db.session.commit()
        flash('已更新貼文')
        return redirect(url_for('profile_page'))

    # prepare defaults for date/time inputs based on post created_at (convert to Taipei)
    try:
        local_tz = ZoneInfo('Asia/Taipei')
        local_dt = p.created_at.replace(tzinfo=timezone.utc).astimezone(local_tz)
        default_date = local_dt.strftime('%Y-%m-%d')
        default_time = local_dt.strftime('%H:%M')
    except Exception:
        default_date = ''
        default_time = ''
    return render_template('edit_post.html', post=p, default_date=default_date, default_time=default_time)


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
        # delete comments and likes associated with the post
        Comment.query.filter_by(post_id=p.id).delete()
        Like.query.filter_by(post_id=p.id).delete()
        # delete notifications that reference this post to avoid FK constraint
        Notification.query.filter_by(post_id=p.id).delete()
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
        # First, delete comments and likes attached to the user's posts (other users' interactions)
        user_posts = db.session.query(Post.id).filter_by(user_id=uid).all()
        post_ids = [r[0] for r in user_posts]
        if post_ids:
            # Use raw SQL to ensure child rows are deleted before parent rows and avoid FK constraint errors
            try:
                db.session.execute(text('DELETE FROM "comment" WHERE post_id = ANY(:ids)'), {'ids': post_ids})
                db.session.execute(text('DELETE FROM "like" WHERE post_id = ANY(:ids)'), {'ids': post_ids})
                # also delete notifications that reference these posts
                try:
                    db.session.execute(text('DELETE FROM "notification" WHERE post_id = ANY(:ids)'), {'ids': post_ids})
                except Exception:
                    # ignore and fallback to ORM below
                    pass
                db.session.commit()
            except Exception:
                db.session.rollback()
                # fallback to ORM delete if raw SQL fails
                Comment.query.filter(Comment.post_id.in_(post_ids)).delete(synchronize_session=False)
                Like.query.filter(Like.post_id.in_(post_ids)).delete(synchronize_session=False)
                db.session.commit()
        # Then delete the user's own comments and likes (authored by the user)
        Comment.query.filter_by(user_id=uid).delete()
        Like.query.filter_by(user_id=uid).delete()
        # Now delete the user's posts
        Post.query.filter_by(user_id=uid).delete()
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
        try:
            if actor and getattr(actor, 'avatar_blob', None):
                actor_avatar = url_for('user_avatar', user_id=actor.id)
            else:
                actor_avatar = actor.avatar if actor else None
        except Exception:
            actor_avatar = actor.avatar if actor else None
        out.append({'id': n.id, 'verb': n.verb, 'actor': (actor.display_name or actor.username) if actor else None, 'actor_avatar': actor_avatar, 'post_id': n.post_id, 'comment_id': n.comment_id, 'data': n.data, 'created_at': to_local_str(n.created_at), 'read': n.read})
    return render_template('notifications.html', notifications=out)


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings_page():
    # Move user settings here: display name, streak days, notify, avatar upload
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

        # handle avatar upload
        file = request.files.get('avatar')
        if file and file.filename and allowed_file(file.filename):
            if os.environ.get('STORE_UPLOADS_IN_DB') == '1':
                try:
                    try:
                        file.stream.seek(0)
                    except Exception:
                        pass
                    data = file.read()
                    if data:
                        current_user.avatar_blob = data
                        current_user.avatar_mime = getattr(file, 'content_type', None) or 'application/octet-stream'
                        current_user.avatar = None
                except Exception:
                    pass
            else:
                current_user.avatar = save_uploaded_file(file)

        db.session.commit()
        flash('個人設定已更新')
        return redirect(url_for('settings_page'))

    return render_template('settings.html', profile=current_user)


@app.route('/badge/pin', methods=['POST'])
@login_required
def badge_pin():
    data = request.get_json() or {}
    title = data.get('title') or request.form.get('title')
    if not title:
        return jsonify({'ok': False, 'error': 'no badge specified'}), 400
    # find badge by title
    b = Badge.query.filter_by(title=title).first()
    if not b:
        return jsonify({'ok': False, 'error': 'badge not found'}), 404
    # check user earned it
    ub = UserBadge.query.filter_by(user_id=current_user.id, badge_id=b.id).first()
    if not ub:
        return jsonify({'ok': False, 'error': 'not earned'}), 403
    # check pinned count
    pinned_count = UserBadge.query.filter_by(user_id=current_user.id, pinned=True).count()
    if ub.pinned:
        return jsonify({'ok': True})
    if pinned_count >= 3:
        return jsonify({'ok': False, 'error': 'max pinned (3) reached'}), 400
    try:
        ub.pinned = True
        db.session.commit()
        return jsonify({'ok': True})
    except Exception:
        db.session.rollback()
        return jsonify({'ok': False}), 500


@app.route('/badge/unpin', methods=['POST'])
@login_required
def badge_unpin():
    data = request.get_json() or {}
    title = data.get('title') or request.form.get('title')
    if not title:
        return jsonify({'ok': False, 'error': 'no badge specified'}), 400
    b = Badge.query.filter_by(title=title).first()
    if not b:
        return jsonify({'ok': False, 'error': 'badge not found'}), 404
    ub = UserBadge.query.filter_by(user_id=current_user.id, badge_id=b.id).first()
    if not ub:
        return jsonify({'ok': False, 'error': 'not earned'}), 403
    try:
        ub.pinned = False
        db.session.commit()
        return jsonify({'ok': True})
    except Exception:
        db.session.rollback()
        return jsonify({'ok': False}), 500


@app.route('/uploads/post/<int:post_id>/image')
def post_image(post_id):
    """Serve image bytes stored in DB for a post."""
    p = Post.query.get(post_id)
    if not p or not p.image_blob:
        return ('', 404)
    mime = p.image_mime or 'application/octet-stream'
    return Response(p.image_blob, mimetype=mime)


@app.route('/uploads/user/<int:user_id>/avatar')
def user_avatar(user_id):
    """Serve avatar bytes stored in DB for a user."""
    u = User.query.get(user_id)
    if not u or not u.avatar_blob:
        return ('', 404)
    mime = u.avatar_mime or 'application/octet-stream'
    return Response(u.avatar_blob, mimetype=mime)


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
