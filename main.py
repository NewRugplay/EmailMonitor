##############################################################
# HEALTH CHECK SERVER: ENSURES RENDER DEPLOY COMPLETES       #
##############################################################

import threading
from flask import Flask, jsonify
from flask_socketio import SocketIO, emit
import os
from collections import deque
import time

HEALTHSERVER_APP = Flask(__name__)
HEALTHSERVER_APP.config['SECRET_KEY'] = 'your-secret-key-here'
HEALTHSERVER_CONSOLE_SOCKETIO = SocketIO(HEALTHSERVER_APP, cors_allowed_origins="*")

CURRENT_STATUS = "healthy"
CONSOLE_BUFFER = deque(maxlen=10)
CONSOLE_LOCK = threading.Lock()

def HealthServerLog(message):
    timestamp = time.strftime("%H:%M:%S")
    formatted_message = f"[{timestamp}] {message}"
    
    with CONSOLE_LOCK:
        CONSOLE_BUFFER.append(formatted_message)
        HEALTHSERVER_CONSOLE_SOCKETIO.emit("console_update", {
            "message": formatted_message,
            "history": list(CONSOLE_BUFFER)
        })

@HEALTHSERVER_APP.route("/health")
def HEALTHSERVER_ENDPOINT_HEALTH():
    return jsonify({'status': CURRENT_STATUS})

@HEALTHSERVER_APP.route("/")
def HEALTHSERVER_ENDPOINT_ROOT():
    return jsonify({"status": CURRENT_STATUS, "note_for_humans": "See /humans for human-readable information."})

@HEALTHSERVER_APP.route("/humans")
def HEALTHSERVER_ENDPOINT_HUMANS():
    return f"""
    <!DOCTYPE HTML>
    <html>
        <head>
            <title>EmailMonitor Health: Humans</title>
            <style>
                .inline-code {{
                    background-color: #2d2d2d;
                    color: #ff8c42;
                    padding: 2px 6px;
                    border-radius: 4px;
                    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
                    font-size: 0.9em;
                    font-weight: 500;
                }}
                .top-right-text {{
                    position: fixed;
                    top: 0;
                    right: 0;
                    padding: 16px;
                    background-color: #333;
                    color: white;
                    max-width: 300px;
                    word-wrap: break-word;
                    box-sizing: border-box;
                    z-index: 1000;
                }}
                .no-link-style {{
                    color: inherit;
                    text-decoration: none;
                }}
                .no-link-style:hover {{
                    color: inherit;
                    text-decoration: none;
                }}
                .console-output {{
                    background-color: #1a1a1a;
                    color: #00ff00;
                    padding: 15px;
                    border-radius: 8px;
                    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
                    font-size: 0.9em;
                    margin: 20px 0;
                    min-height: 150px;
                    max-height: 300px;
                    overflow-y: auto;
                }}
                .console-line {{
                    margin-bottom: 2px;
                    word-wrap: break-word;
                }}
            </style>
            <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
        </head>
        <body>
            <h1>EmailMonitor Health: Humans</h1>
            <p><strong>STATUS: <code class="inline-code">{CURRENT_STATUS}</code></strong></p>
            
            <div class="top-right-text">
                <p>Made with &#10084;&#65039; by ItsThatOneJack!</p>
                <br/>
                <p>Copyright <a href="https://github.com/NewRugplay" class="no-link-style">The NewRugplay Development Team</a>.</p>
            </div>
            
            <h2>Live Console Output</h2>
            <div class="console-output" id="console">
                <div class="console-line">Console output will appear here...</div>
            </div>
            
            <p>
                This endpoint is meant to be for you to check on EmailMonitor!</br>
                If you have code checking on it, you should use the <code class="inline-code">/</code> (or <code class="inline-code">/health</code> for more exact info) endpoint.
            </p>
            
            <script>
                const socket = io();
                const consoleDiv = document.getElementById('console');
                
                socket.on('connect', function() {{
                    console.log('Connected to server');
                }});
                
                socket.on('console_update', function(data) {{
                    // Clear and update with full history
                    consoleDiv.innerHTML = '';
                    data.history.forEach(function(line) {{
                        const lineDiv = document.createElement('div');
                        lineDiv.className = 'console-line';
                        lineDiv.textContent = line;
                        consoleDiv.appendChild(lineDiv);
                    }});
                    
                    // Auto-scroll to bottom
                    consoleDiv.scrollTop = consoleDiv.scrollHeight;
                }});
                
                socket.on('disconnect', function() {{
                    console.log('Disconnected from server');
                }});
            </script>
        </body>
    </html>
    """

@HEALTHSERVER_CONSOLE_SOCKETIO.on("connect")
def HEALTHSERVER_CONSOLE_CONNECT():
    print("Client connected!")
    with CONSOLE_LOCK:
        HEALTHSERVER_CONSOLE_SOCKETIO.emit("console_update", {
            "message": "Connected to live console!",
            "history": list(CONSOLE_BUFFER)
        })

@HEALTHSERVER_CONSOLE_SOCKETIO.on("disconnect")
def HEALTHSERVER_CONSOLE_DISCONNECT():
    print("Client disconnected!")

def HEALTHSERVER_RUN():
    PORT = int(os.environ.get("PORT", 5000))
    HEALTHSERVER_CONSOLE_SOCKETIO.run(HEALTHSERVER_APP, host="0.0.0.0", port=PORT, debug=False)

HEALTHSERVER_THREAD = threading.Thread(target=HEALTHSERVER_RUN)
HEALTHSERVER_THREAD.daemon = True
HEALTHSERVER_THREAD.start()
##############################################################
# PROGRAM LOGIC                                              #
##############################################################

import imaplib
import email
import json
import time
import requests
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import parsedate_to_datetime
import logging
import os
from typing import Dict, List, Optional, Tuple

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class EmailMonitor:
    def __init__(self, imap_server: str, imap_port: int, username: str, password: str, 
                 discord_webhook_url: str, check_interval: int = 60):
        self.imap_server = imap_server
        self.imap_port = imap_port
        self.username = username
        self.password = password
        self.discord_webhook_url = discord_webhook_url
        self.check_interval = int(os.environ.get("CHECK_INTERVAL", "60"))

        self.processed_uids = {
            'INBOX': set(),
            'SENT': set()
        }
        
        self.COLORS = {
            'received': 0x00FF00,
            'sent': 0x0099FF
        }

    def connect_imap(self) -> imaplib.IMAP4_SSL:
        try:
            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            mail.login(self.username, self.password)
            return mail
        except Exception as e:
            logger.error(f"Failed to connect to IMAP server: {e}!")
            HealthServerLog("[ ERR ] IMAP connection failiure!")
            raise

    def decode_header_value(self, value: str) -> str:
        if not value:
            return ""
        
        decoded_parts = decode_header(value)
        decoded_value = ""
        
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                if encoding:
                    decoded_value += part.decode(encoding)
                else:
                    decoded_value += part.decode('utf-8', errors='ignore')
            else:
                decoded_value += part
        
        return decoded_value.strip()

    def get_plain_text_content(self, msg: email.message.Message) -> str:
        content = ""
        
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    charset = part.get_content_charset() or 'utf-8'
                    payload = part.get_payload(decode=True)
                    if payload:
                        content += payload.decode(charset, errors='ignore')
        else:
            if msg.get_content_type() == "text/plain":
                charset = msg.get_content_charset() or 'utf-8'
                payload = msg.get_payload(decode=True)
                if payload:
                    content = payload.decode(charset, errors='ignore')
        
        return content.strip()

    def parse_email_addresses(self, address_string: str) -> List[str]:
        if not address_string:
            return []
        
        addresses = []
        for addr in address_string.split(','):
            addr = addr.strip()
            if '<' in addr and '>' in addr:
                addr = addr.split('<')[1].split('>')[0]
            addresses.append(addr)
        
        return addresses

    def send_discord_webhook(self, embed_data: Dict) -> bool:
        try:
            payload = {
                "embeds": [embed_data]
            }
            
            response = requests.post(
                self.discord_webhook_url,
                json=payload,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 204:
                logger.info("Discord webhook sent successfully!")
                HealthServerLog("[INFOR] Fired Discord webhook!")
                return True
            else:
                logger.error(f"Discord webhook failed: {response.status_code} - {response.text}!")
                HealthServerLog("[ ERR ] Failied to fire Discord webhook!")
                return False
                
        except Exception as e:
            logger.error(f"Error sending Discord webhook: {e}!")
            HealthServerLog("[ ERR ] Failied to fire Discord webhook!")
            return False

    def create_embed(self, email_type: str, subject: str, sender: str, recipient: str, 
                    content: str, date_time: datetime) -> Dict:
        max_content_length = 3000
        if len(content) > max_content_length:
            content = content[:max_content_length] + "... (truncated)"
        
        embed = {
            "color": self.COLORS[email_type],
            "timestamp": date_time.isoformat(),
            "fields": []
        }
        
        if email_type == "received":
            embed["title"] = "Received"
            embed["fields"] = [
                {"name": "From", "value": sender, "inline": True},
                {"name": "Date", "value": date_time.strftime("%Y-%m-%d %H:%M:%S UTC"), "inline": True},
                {"name": "Subject", "value": subject or "(No Subject)", "inline": False},
                {"name": "Content", "value": content or "(No content)", "inline": False}
            ]
        else:  # sent
            embed["title"] = "Sent"
            embed["fields"] = [
                {"name": "To", "value": recipient, "inline": True},
                {"name": "Date", "value": date_time.strftime("%Y-%m-%d %H:%M:%S UTC"), "inline": True},
                {"name": "Subject", "value": subject or "(No Subject)", "inline": False},
                {"name": "Content", "value": content or "(No content)", "inline": False}
            ]
        
        return embed

    def get_available_folders(self, mail: imaplib.IMAP4_SSL) -> List[str]:
        try:
            status, folders = mail.list()
            if status != 'OK':
                return []
            
            folder_names = []
            for folder in folders:
                folder_info = folder.decode('utf-8')
                logger.debug(f"Raw folder info: {folder_info}")
                
                if '"' in folder_info:
                    parts = folder_info.split('"')
                    if len(parts) >= 4:
                        folder_name = parts[-2]
                    else:
                        folder_name = parts[-1] if parts else folder_info
                else:
                    parts = folder_info.split()
                    if len(parts) >= 3:
                        folder_name = parts[-1]
                    else:
                        folder_name = folder_info
                
                folder_name = folder_name.strip()
                if folder_name and folder_name != '.':
                    folder_names.append(folder_name)
            
            return folder_names
        except Exception as e:
            logger.error(f"Error getting folder list: {e}!")
            HealthServerLog("[ ERR ] Failed to get folder list!")
            return []

    def find_sent_folder(self, mail: imaplib.IMAP4_SSL) -> Optional[str]:
        possible_sent_folders = [
            'Sent',
            'INBOX.Sent', 
            'INBOX/Sent',
            'Sent Items',
            'Sent Messages',
            'INBOX.Sent Items',
            'INBOX.Sent Messages'
        ]
        
        for folder in possible_sent_folders:
            try:
                logger.info(f"Trying to select folder: {folder}...")
                HealthServerLog(f"[INFORM] Trying to select folder: '{folder}'...")
                status, count = mail.select(folder, readonly=True)
                if status == 'OK':
                    logger.info(f"Successfully found sent folder: {folder}!")
                    HealthServerLog(f"[INFORM] Found sent folder: '{folder}'!")
                    return folder
                else:
                    logger.debug(f"Could not select {folder}: {status}.")
            except Exception as e:
                logger.debug(f"Error trying folder {folder}: {e}.")
        
        return None

    def check_folder(self, mail: imaplib.IMAP4_SSL, folder: str, email_type: str) -> bool:
        try:
            status, count = mail.select(folder)
            if status != 'OK':
                logger.warning(f"Could not select folder '{folder}': {status}")
                return False
            
            logger.info(f"Successfully selected folder '{folder}' with {count[0].decode()} messages.")
            HealthServerLog(f"[INFORM] Found {count[0].decode()} new emails.")
            
            if email_type == "received":search_criteria = 'UNSEEN'
            else:search_criteria = 'ALL'
            
            status, messages = mail.search(None, search_criteria)
            
            if status != 'OK':
                logger.error(f"Failed to search {folder}: {status}")
                return False
            
            email_ids = messages[0].split()
            logger.info(f"Found {len(email_ids)} emails in {folder} (type: {email_type}).")
            HealthServerLog(f"[INFORM] Found {len(email_ids)} emails in '{folder}'.")
            
            for email_id in email_ids:
                if email_id in self.processed_uids.get(folder, set()):
                    continue
                
                if folder not in self.processed_uids:
                    self.processed_uids[folder] = set()
                
                status, msg_data = mail.fetch(email_id, '(RFC822)')
                if status != 'OK':
                    continue
                
                msg = email.message_from_bytes(msg_data[0][1])
                
                subject = self.decode_header_value(msg.get('Subject', ''))
                sender = self.decode_header_value(msg.get('From', ''))
                recipient = self.decode_header_value(msg.get('To', ''))
                date_header = msg.get('Date')
                
                try:
                    email_date = parsedate_to_datetime(date_header)
                    if email_date.tzinfo is None:
                        email_date = email_date.replace(tzinfo=timezone.utc)
                except:
                    email_date = datetime.now(timezone.utc)
                
                if email_type == "sent":
                    time_diff = datetime.now(timezone.utc) - email_date
                    if time_diff.total_seconds() > 300:
                        self.processed_uids[folder].add(email_id)
                        continue
                
                content = self.get_plain_text_content(msg)
                
                if email_type == "received":
                    embed = self.create_embed("received", subject, sender, "", content, email_date)
                else:
                    all_recipients = self.parse_email_addresses(recipient)
                    recipient_str = ", ".join(all_recipients)
                    embed = self.create_embed("sent", subject, "", recipient_str, content, email_date)
                
                if self.send_discord_webhook(embed):
                    logger.info(f"Notification sent for {email_type} email: {subject}.")
                    HealthServerLog(f"[INFORM] Discord webhook fired for {email_type} email.")
                
                self.processed_uids[folder].add(email_id)
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking {folder}: {e}")
            return False

    def monitor_emails(self) -> None:
        """Main monitoring loop."""
        logger.info("Starting email monitor...")

        first_run = True
        sent_folder = None
        
        while True:
            try:
                mail = self.connect_imap()
                
                if first_run:
                    logger.info("Discovering available folders...")
                    HealthServerLog(f"[INFORM] Discovering available folders...")
                    available_folders = self.get_available_folders(mail)
                    logger.info(f"Available folders: {available_folders}")
                    HealthServerLog(f"[INFORM] Found: {available_folders}")
                    
                    logger.info("Searching for sent folder...")
                    HealthServerLog(f"[INFORM] Searching for sent folder...")
                    sent_folder = self.find_sent_folder(mail)
                    
                    if sent_folder:
                        logger.info(f"Found sent folder: {sent_folder}!")
                        HealthServerLog(f"[INFORM] Found sent folder: '{sent_folder}'!")
                    else:
                        logger.warning("No sent folder found, will only monitor inbox.")
                        HealthServerLog(f"[INFORM] Could not find sent folder. Only received emails will be monitored.")
                    
                    first_run = False
                
                logger.info("Checking INBOX for new emails...")
                HealthServerLog(f"[INFORM] Looking for received emails...")
                self.check_folder(mail, 'INBOX', 'received')
                
                if sent_folder:
                    logger.info(f"Checking {sent_folder} for new sent emails...")
                    HealthServerLog(f"[INFORM] Looking for sent emails....")
                    self.check_folder(mail, sent_folder, 'sent')
                
                try:
                    mail.close()
                except:
                    pass
                
                mail.logout()
                
                logger.info(f"Waiting {self.check_interval} seconds before next check...")
                HealthServerLog(f"[INFORM] Waiting {self.check_interval} seconds...")
                time.sleep(self.check_interval)
                
            except KeyboardInterrupt:
                HealthServerLog(f"[INFORM] Shutting down...")
                logger.info("Email monitor stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                HealthServerLog(f"[ ERR ] An error has occured within the monitoring loop.")
                try:
                    mail.close()
                    mail.logout()
                except:
                    pass
                HealthServerLog(f"[INFORM] Waiting {self.check_interval} seconds...")
                time.sleep(self.check_interval)

def main():
    CONFIG = {
        'imap_server': 'imap.hostinger.com',
        'imap_port': 993,
        'username': 'newrugplay@itoj.dev',
        'password': os.environ.get("EMAIL_PASSWORD"),
        'discord_webhook_url': os.environ.get("DISCORD_WEBHOOK_URL"),
        'check_interval': int(os.environ.get("CHECK_INTERVAL", "60"))
    }

    if not CONFIG['password']:
        logger.error("Set the EMAIL_PASSWORD environment variable!")
        return
    
    if not CONFIG['discord_webhook_url']:
        logger.error("Set the DISCORD_WEBHOOK_URL environment variable!")
        return
    
    monitor = EmailMonitor(
        imap_server=CONFIG['imap_server'],
        imap_port=CONFIG['imap_port'],
        username=CONFIG['username'],
        password=CONFIG['password'],
        discord_webhook_url=CONFIG['discord_webhook_url'],
        check_interval=CONFIG['check_interval']
    )
    
    monitor.monitor_emails()

if __name__ == "__main__":
    main()
