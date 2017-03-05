import json

from grail import Grail, request, log

app = Grail(__name__)

@app.route('/')
async def index():
    return 'Hello World!'

users = [
    {'name': 'Miles', 'rights': ['admin', 'user']},
    {'name': 'Louis', 'rights': ['user']},
]

@app.route('/users/')
async def get_users():
    return json.dumps(users)

@app.route('/users/{id}', methods=['PUT', 'GET'])
async def get_user():
    i = request.params.get('id', type=int) - 1
    return json.dumps(users[i])

@app.route('/login', methods=['POST', 'GET'])
async def login():
    error = None
    if request.method == 'POST':
        if valid_login(request.form['username'],
                       request.form['password']):
            return log_me_in(request.form['username'])
        else:
            error = 'Invalid username/password'
    return render_template('login.html', error=error)

app.run_forever()
