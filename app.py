from flask import Flask, render_template, request, redirect, url_for, flash
from datetime import datetime

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

@app.route('/')
def index():
    return render_template('index.html', status=user_status)

@app.route('/checkin', methods=['GET', 'POST'])
def checkin():
    if request.method == 'POST':
        sport_name = request.form.get('sport_name')
        sport_time = request.form.get('sport_time')
        # 照片只做預覽，不存檔
        flash('打卡成功！')
        return render_template('checkin.html', success=True, sport_name=sport_name, sport_time=sport_time)
    return render_template('checkin.html', success=False)

@app.route('/leaderboard')
def leaderboard_page():
    return render_template('leaderboard.html', leaderboard=leaderboard, badges=badges)

@app.route('/stats')
def stats():
    return render_template('stats.html', recent_7_days=recent_7_days)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
