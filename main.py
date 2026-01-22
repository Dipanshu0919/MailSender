import csv
import json
import os
import random
import re
import smtplib
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from email.mime.text import MIMEText
from email.policy import SMTP

import dns.resolver
from flask import Flask, jsonify, render_template, request, send_file

app = Flask(__name__)
app.config["JSONIFY_PRETTYPRINT_REGULAR"] = False

place_holder_regex = re.compile(r"\$\((\w+)\)\$")
email_regex = re.compile(r"[A-Za-z0-9._-]+@[A-Za-z0-9._-]+\.[A-Za-z]+")
SENDER_MAIL = os.environ.get("MAILSENDER_SMTP_MAIL")
SENDER_MAIL_APP_PASSWORD = os.environ.get("MAILSENDER_SMTP_MAIL_APP_PASSWORD")
smtp_providers = {
    "gmail": ("smtp.gmail.com", 465, "google.com"),
    "yahoo": ("smtp.mail.yahoo.com", 465, "yahoodns.net"),
    "zoho": ("smtp.zoho.com", 465, "zoho.com"),
    "office365": ("smtp.office365.com", 587, "outlook.com"),
}


class mailSender:
    def __init__(self):
        self.success_mails = 0
        self.failed_mails = 0
        self.skipped_mails = 0
        self.filekeys = None
        self.filedata = None
        self.selected_mails = None
        self.smtp_provider = None
        self.email_subject = ""
        self.filename = ""
        self.pause_request = False
        self.resume_sending = False

        self.mail_thread_lock = threading.Lock()

    def find_provider(self):
        try:
            resolver = dns.resolver.Resolver()
            resolver.nameservers = ["8.8.8.8", "1.1.1.1"]
            domain = SENDER_MAIL.split("@")[1]
            answers = resolver.resolve(domain, "MX")

            for r in answers:
                result = str(r.exchange).lower()
            for k, v in smtp_providers.items():
                if v[2] in result:
                    self.smtp_provider = k
        except:
            self.smtp_provider = None
        return self.smtp_provider if self.smtp_provider else None


ms_obj = mailSender()


@app.route("/")
def home():
    MAIL = os.environ.get("MAILSENDER_SMTP_MAIL", None)
    APP_PASSWORD = os.environ.get("MAILSENDER_SMTP_MAIL_APP_PASSWORD", None)
    provider = ms_obj.find_provider() if MAIL else None
    try:
        os.mknod("mail_logs.csv")
        with open("mail_logs.csv", "w") as f:
            f.write("index,email,message,status")
    except FileExistsError as e:
        pass
    return render_template("index.html", mail=MAIL, password=APP_PASSWORD, provider=provider)


def open_browser():
    webbrowser.open("http://127.0.0.1:8000")


def send_mail():
    threads = []

    port = smtp_providers[ms_obj.smtp_provider][1]
    host = smtp_providers[ms_obj.smtp_provider][0]

    with smtplib.SMTP_SSL(host, port) as server:
        server.login(SENDER_MAIL, SENDER_MAIL_APP_PASSWORD)

        for indexx, mails in enumerate(ms_obj.selected_mails):
            index = indexx
            mail = mails
            # def mail_thread(index, mail):
            find_placeholders = place_holder_regex.findall(mail[2])

            if ms_obj.pause_request:
                break

            if (ms_obj.selected_mails[index][3] == "Processing") and (not ms_obj.pause_request):

                if find_placeholders:
                    with ms_obj.mail_thread_lock:
                        ms_obj.selected_mails[index][3] = "Skipped: " + ", ".join(find_placeholders)
                        ms_obj.skipped_mails += 1
                    # return
                    continue

                try:
                    msg = MIMEText(mail[2], "html")
                    msg["Subject"] = ms_obj.email_subject
                    msg["From"] = SENDER_MAIL
                    msg["To"] = mail[1]

                    server.sendmail(SENDER_MAIL, mail[1], msg.as_string())

                    with ms_obj.mail_thread_lock:
                        ms_obj.selected_mails[index][3] = "Success"
                        ms_obj.success_mails += 1

                except Exception as e:
                    with ms_obj.mail_thread_lock:
                        ms_obj.selected_mails[index][3] = f"Error: {e}"
                        ms_obj.failed_mails += 1

                # mode = "a" if ms_obj.resume_sending else "w"
                with open("mail_logs.csv", "w") as f:
                    writer = csv.writer(f)
                    # if mode == "w":
                    writer.writerow(["index", "email", "message", "status"])
                    writer.writerows(ms_obj.selected_mails)
                time.sleep(1)

        # t = threading.Thread(target=mail_thread, args=(indexx, mails))
        # threads.append(t)
        # t.start()
        # time.sleep(2)

        # for t in threads:
        #     t.join()


@app.route("/file", methods=["POST"])
def file():
    uploaded_file = request.files.get("file")

    ms_obj.filename = f"mailSender__{uploaded_file.filename}"
    uploaded_file.save(ms_obj.filename)

    if ms_obj.filename.endswith(".csv"):
        with open(ms_obj.filename, "r") as f:
            ms_obj.filedata = list(csv.DictReader(f))

    elif ms_obj.filename.endswith(".json"):
        with open(ms_obj.filename, "r") as f:
            ms_obj.filedata = json.load(f)

    os.remove(ms_obj.filename)
    ms_obj.filekeys = tuple(ms_obj.filedata[0].keys())
    proper_email = []
    for index, row in enumerate(ms_obj.filedata, start=0):
        if not proper_email:
            for key, value in row.items():
                if email_regex.search(value):
                    proper_email.append(key)
        row["index"] = index
    return jsonify(proper_email)


@app.route("/showemails", methods=["POST"])
def showemails():
    email_column = request.form.get("emailoption")
    mails = [
        x[email_column].strip()
        if (len(email_regex.findall(x[email_column])) == 1)
        else f"ERROR: {x[email_column]}"
        for x in ms_obj.filedata
    ]
    messages = [x.get("formated_message_mailsender", "") for x in ms_obj.filedata]

    return jsonify({"emails": mails, "allkeys": ms_obj.filekeys, "messages": messages})


@app.route("/editmessage", methods=["POST"])
def editmessage():
    message = request.form.get("message", "")
    matches = place_holder_regex.findall(message)
    for numb, ppls in enumerate(ms_obj.filedata):
        new_message = message
        for x in matches:
            if ppls.get(x):
                new_message = new_message.replace(f"$({x})$", ppls[x])

            # if new_message.startswith("placeholder_error:"):
            #     new_message = new_message[len("placeholder_error: ") :].lstrip()

            # if place_holder_regex.findall(new_message):
            #     new_message = f"placeholder_error: {new_message}"
        ms_obj.filedata[numb]["formated_message_mailsender"] = new_message

    return "OK"


@app.route("/selectemails", methods=["POST"])
def selectemails():
    selected_mails = request.form.get("selected_mails")
    to_json = json.loads(selected_mails)
    ms_obj.selected_mails = [
        [msg[0], mail, msg[1], "Processing"] for mail, msg in to_json.items()
    ]
    print(ms_obj.selected_mails)
    ms_obj.email_subject = request.form.get("subject")
    send_mail()
    return "OK"


@app.route("/show_logs")
def show_logs():
    mails = ms_obj.selected_mails
    if mails:
        processing = any(status == "Processing" for _, _, _, status in mails)
    else:
        processing = False
        with open("mail_logs.csv", "r") as f:
            reader = csv.DictReader(f)
            mails = []
            for x in reader:
                mails.append([x["index"], x["email"], x["message"], x["status"]])
                if not processing:
                    processing = True if x["status"] == "Processing" else False
    isPaused = ms_obj.pause_request
    return render_template("logs.html", mails=mails, processing=processing, isPaused=isPaused)


@app.route("/mail_control", methods=["POST"])
def mail_control():
    data = request.json
    action = data.get("action")

    if action == "pause":
        ms_obj.pause_request = True

    if action == "resume":
        ms_obj.selected_mails = []
        with open("mail_logs.csv", "r") as f:
            reader = csv.DictReader(f)
            for x in reader:
                ms_obj.selected_mails.append([x["index"], x["email"], x["message"], x["status"]])

        ms_obj.pause_request = False
        send_mail()

    return "Control Changed"

@app.route("/download/mail_logs.csv")
def download_mail_logs_csv():
    return send_file("mail_logs.csv", as_attachment=True, download_name="MailSender_email_logs.csv", mimetype="text/csv")


if __name__ == "__main__":
    # threading.Timer(1, open_browser).start()
    app.run(port=8026, debug=True)
