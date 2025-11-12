from app import db, User, app

with app.app_context():
    users = User.query.all()
    if not users:
        print('No users in database')
    else:
        for u in users:
            print(f'id={u.id}, username={u.username}, display_name={u.display_name}, avatar={u.avatar}, streak_days={u.streak_days}')
