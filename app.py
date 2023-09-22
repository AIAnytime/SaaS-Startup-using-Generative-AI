from flask import Flask, request, render_template
import openai
import config
import re
import hashlib
import sqlite3
import stripe

app = Flask(__name__)

openai.api_type = "azure"
openai.api_base = config.API_ENDPOINTS
openai.api_version = "2023-03-15-preview"
openai.api_key = config.API_KEY
stripe.api_key = config.STRIPE_TEST_KEY

def initialize_database():
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    c.execute(
        '''CREATE TABLE IF NOT EXISTS users (fingerprint text primary key, usage_counter int)''')
    conn.commit()
    conn.close()


def get_fingerprint():
    browser = request.user_agent.browser
    version = request.user_agent.version and float(
        request.user_agent.version.split(".")[0])
    platform = request.user_agent.platform
    string = f"{browser}:{version}:{platform}"
    fingerprint = hashlib.sha256(string.encode("utf-8")).hexdigest()
    print(fingerprint)
    return fingerprint


def get_usage_counter(fingerprint):
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    result = c.execute('SELECT usage_counter FROM users WHERE fingerprint=?',
                       [fingerprint]).fetchone()
    conn.close()
    if result is None:
        conn = sqlite3.connect('app.db')
        c = conn.cursor()
        c.execute('INSERT INTO users (fingerprint, usage_counter) VALUES '
                  '(?, 0)', [fingerprint])
        conn.commit()
        conn.close()
        return 0
    else:
        return result[0]


def update_usage_counter(fingerprint, usage_counter):
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    c.execute('UPDATE users SET usage_counter=? WHERE fingerprint=?',
              [usage_counter, fingerprint])
    conn.commit()
    conn.close()


def preprocess_error(error):
    return re.sub(r'\\', r'\\\\', error)

@app.route("/", methods=["GET", "POST"])
def index():
    return render_template('login.html')

@app.route("/home", methods=["GET", "POST"])
def home():
    initialize_database()
    fingerprint = get_fingerprint()
    usage_counter = get_usage_counter(fingerprint)
    if request.method == "POST":
        if usage_counter > 3:
            return render_template("payment.html")
        code = request.form["code"]
        _error = request.form["error"]
        error = preprocess_error(_error)
        prompt = (f"Explain the error in this code without fixing it:"
        f"\n\n{code}\n\nError:\n\n{error}")
        model_engine = "ai-anytime07"
        explanation_completions = openai.ChatCompletion.create(
            engine=model_engine,
            messages=[
                {"role": "user", "content": prompt}
            ],
            max_tokens=1024,
            n=1,
            temperature=0.2,
        )
        explanation = explanation_completions.choices[0].message.content
        fixed_code_prompt =(f"Fix this code: \n\n{code}\n\nError:\n\n{error}."
            f" \n Respond only with the fixed code.")

        fixed_code_completions = openai.ChatCompletion.create(
            engine=model_engine,
            messages=[
                {"role": "user", "content": fixed_code_prompt}
            ],
            max_tokens=1024,
            n=1,
            temperature=0.2,
        )

        fixed_code = fixed_code_completions.choices[0].message.content
        usage_counter += 1
        print(usage_counter)
        update_usage_counter(fingerprint, usage_counter)

        return render_template("index.html", explanation=explanation, fixed_code=fixed_code, code=code, error=_error)
    return render_template("index.html")

@app.route("/charge", methods=["POST"])
def charge():
    amount = int(request.form["amount"])
    plan = str(request.form["plan"])

    customer = stripe.Customer.create(
        email=request.form["stripeEmail"],
        source=request.form["stripeToken"]
    )

    charge = stripe.PaymentIntent.create(
        customer=customer.id,
        amount=amount,
        currency="usd",
        description="App Charge"
    )

    return render_template("charge.html", amount=amount, plan=plan)

if __name__ == "__main__":
    app.run(debug=True)