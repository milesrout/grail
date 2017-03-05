import json

from grail import Grail, request

app = Grail(__name__)

@app.route('/')
async def index():
    return 'Hello World!'

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

users = [{'name': 'Miles', 'rights': ['admin']}]

@app.route('/users')
async def get_users():
    return json.dumps(users)

@app.route('/users/{id}')
async def get_user():
    return json.dumps(users[request.params.get(id, type=int)])

app.run_forever()
