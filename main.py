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
        """
        Initialize the email monitor.
        
        Args:
            imap_server: IMAP server hostname
            imap_port: IMAP server port (usually 993 for SSL)
            username: Email username
            password: Email password
            discord_webhook_url: Discord webhook URL
            check_interval: How often to check for new emails (seconds)
        """
        self.imap_server = imap_server
        self.imap_port = imap_port
        self.username = username
        self.password = password
        self.discord_webhook_url = discord_webhook_url
        self.check_interval = check_interval
        
        # Track processed emails to avoid duplicates
        self.processed_uids = {
            'INBOX': set(),
            'SENT': set()
        }
        
        # Discord embed colors
        self.COLORS = {
            'received': 0x00FF00,  # Green for received emails
            'sent': 0x0099FF       # Blue for sent emails
        }

    def connect_imap(self) -> imaplib.IMAP4_SSL:
        """Connect to the IMAP server."""
        try:
            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            mail.login(self.username, self.password)
            return mail
        except Exception as e:
            logger.error(f"Failed to connect to IMAP server: {e}")
            raise

    def decode_header_value(self, value: str) -> str:
        """Decode email header value."""
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
        """Extract plain text content from email message."""
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
        """Parse email addresses from a string."""
        if not address_string:
            return []
        
        addresses = []
        # Split by comma and clean up
        for addr in address_string.split(','):
            addr = addr.strip()
            # Extract email from "Name <email@domain.com>" format
            if '<' in addr and '>' in addr:
                addr = addr.split('<')[1].split('>')[0]
            addresses.append(addr)
        
        return addresses

    def send_discord_webhook(self, embed_data: Dict) -> bool:
        """Send a Discord webhook with the email information."""
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
                logger.info("Discord webhook sent successfully")
                return True
            else:
                logger.error(f"Discord webhook failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error sending Discord webhook: {e}")
            return False

    def create_embed(self, email_type: str, subject: str, sender: str, recipient: str, 
                    content: str, date_time: datetime) -> Dict:
        """Create Discord embed for email notification."""
        
        # Truncate content if too long (Discord embed limit is 4096 characters)
        max_content_length = 3000
        if len(content) > max_content_length:
            content = content[:max_content_length] + "... (truncated)"
        
        embed = {
            "color": self.COLORS[email_type],
            "timestamp": date_time.isoformat(),
            "fields": []
        }
        
        if email_type == "received":
            embed["title"] = "📧 New Email Received"
            embed["fields"] = [
                {"name": "📨 From", "value": sender, "inline": True},
                {"name": "📅 Date", "value": date_time.strftime("%Y-%m-%d %H:%M:%S UTC"), "inline": True},
                {"name": "📝 Subject", "value": subject or "(No Subject)", "inline": False},
                {"name": "💬 Content", "value": content or "(No content)", "inline": False}
            ]
        else:  # sent
            embed["title"] = "📤 New Email Sent"
            embed["fields"] = [
                {"name": "📮 To", "value": recipient, "inline": True},
                {"name": "📅 Date", "value": date_time.strftime("%Y-%m-%d %H:%M:%S UTC"), "inline": True},
                {"name": "📝 Subject", "value": subject or "(No Subject)", "inline": False},
                {"name": "💬 Content", "value": content or "(No content)", "inline": False}
            ]
        
        return embed

    def check_folder(self, mail: imaplib.IMAP4_SSL, folder: str, email_type: str) -> None:
        """Check a specific folder for new emails."""
        try:
            mail.select(folder)
            
            # Search for emails based on type
            if email_type == "received":
                # Search for unread emails
                search_criteria = 'UNSEEN'
            else:  # sent
                # Search for all emails in sent folder, we'll filter by date
                search_criteria = 'ALL'
            
            status, messages = mail.search(None, search_criteria)
            
            if status != 'OK':
                logger.error(f"Failed to search {folder}")
                return
            
            email_ids = messages[0].split()
            
            for email_id in email_ids:
                # Skip if already processed
                if email_id in self.processed_uids[folder]:
                    continue
                
                # Fetch email
                status, msg_data = mail.fetch(email_id, '(RFC822)')
                if status != 'OK':
                    continue
                
                # Parse email
                msg = email.message_from_bytes(msg_data[0][1])
                
                # Extract email information
                subject = self.decode_header_value(msg.get('Subject', ''))
                sender = self.decode_header_value(msg.get('From', ''))
                recipient = self.decode_header_value(msg.get('To', ''))
                date_header = msg.get('Date')
                
                # Parse date
                try:
                    email_date = parsedate_to_datetime(date_header)
                    if email_date.tzinfo is None:
                        email_date = email_date.replace(tzinfo=timezone.utc)
                except:
                    email_date = datetime.now(timezone.utc)
                
                # For sent emails, only process recent ones (last 5 minutes)
                if email_type == "sent":
                    time_diff = datetime.now(timezone.utc) - email_date
                    if time_diff.total_seconds() > 300:  # 5 minutes
                        self.processed_uids[folder].add(email_id)
                        continue
                
                # Extract plain text content
                content = self.get_plain_text_content(msg)
                
                # Create and send Discord embed
                if email_type == "received":
                    embed = self.create_embed("received", subject, sender, "", content, email_date)
                else:
                    # For sent emails, join multiple recipients
                    all_recipients = self.parse_email_addresses(recipient)
                    recipient_str = ", ".join(all_recipients)
                    embed = self.create_embed("sent", subject, "", recipient_str, content, email_date)
                
                # Send webhook
                if self.send_discord_webhook(embed):
                    logger.info(f"Notification sent for {email_type} email: {subject}")
                
                # Mark as processed
                self.processed_uids[folder].add(email_id)
                
        except Exception as e:
            logger.error(f"Error checking {folder}: {e}")

    def monitor_emails(self) -> None:
        """Main monitoring loop."""
        logger.info("Starting email monitor...")
        
        while True:
            try:
                # Connect to IMAP server
                mail = self.connect_imap()
                
                # Check inbox for new unread emails
                self.check_folder(mail, 'INBOX', 'received')
                
                # Check sent folder for new sent emails
                # Try common sent folder names for Hostinger
                sent_folders = ['Sent', 'INBOX.Sent', 'INBOX/Sent', 'Sent Items', 'Sent Messages']
                
                for sent_folder in sent_folders:
                    try:
                        self.check_folder(mail, sent_folder, 'sent')
                        break  # If successful, don't try other folder names
                    except:
                        continue
                
                # Close connection
                mail.close()
                mail.logout()
                
                # Wait before next check
                time.sleep(self.check_interval)
                
            except KeyboardInterrupt:
                logger.info("Email monitor stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                time.sleep(self.check_interval)

def main():
    """Main function to run the email monitor."""
    
    # Hostinger Email Configuration - using environment variables
    CONFIG = {
        'imap_server': 'imap.hostinger.com',
        'imap_port': 993,
        'username': 'newrugplay@itoj.dev',
        'password': os.environ.get("EMAIL_PASSWORD"),
        'discord_webhook_url': os.environ.get("DISCORD_WEBHOOK_URL"),
        'check_interval': int(os.environ.get("CHECK_INTERVAL", "60"))  # Default to 60 seconds
    }
    
    # Validate configuration
    if not CONFIG['password']:
        logger.error("Please set the EMAIL_PASSWORD environment variable")
        return
    
    if not CONFIG['discord_webhook_url']:
        logger.error("Please set the DISCORD_WEBHOOK_URL environment variable")
        return
    
    # Create and start monitor
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
