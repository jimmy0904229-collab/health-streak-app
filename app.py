from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime
import base64
import io

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # 用於 flash 訊息

# 假資料
user_status = {
    "today_goal": True,  # 今日是否達標
    "streak_days": 5     # 目前連勝天數
}

leaderboard = [
    {"name": "小明", "points": 120},
    {"name": "小美", "points": 110},
    {"name": "阿強", "points": 95},
    {"name": "阿花", "points": 80},
    {"name": "你", "points": 75}
]

badges = [
    {"title": "新秀達人", "desc": "連勝 7 天", "achieved": user_status["streak_days"] >= 7},
    {"title": "堅持王者", "desc": "連勝 30 天", "achieved": False}
]

recent_7_days = [
    {"date": "10/17", "minutes": 30},
    {"date": "10/18", "minutes": 45},
    {"date": "10/19", "minutes": 20},
    {"date": "10/20", "minutes": 60},
    {"date": "10/21", "minutes": 50},
    {"date": "10/22", "minutes": 40},
    {"date": "10/23", "minutes": 55}
]

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

@app.route('/')
def index():
    # 顯示社群動態牆（貼文）
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
        post = {
            'id': next_post_id,
            'user': '你',
            'sport': sport_name,
            'minutes': int(sport_time) if sport_time else 0,
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
    return render_template('leaderboard.html', leaderboard=leaderboard, badges=badges)

@app.route('/stats')
def stats():
    return render_template('stats.html', recent_7_days=recent_7_days)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
