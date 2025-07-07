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

    def get_available_folders(self, mail: imaplib.IMAP4_SSL) -> List[str]:
        """Get list of available folders from the server."""
        try:
            status, folders = mail.list()
            if status != 'OK':
                return []
            
            folder_names = []
            for folder in folders:
                # Parse folder name from the list response
                folder_info = folder.decode('utf-8')
                logger.debug(f"Raw folder info: {folder_info}")
                
                # Try different parsing methods
                if '"' in folder_info:
                    # Method 1: Extract text between last set of quotes
                    parts = folder_info.split('"')
                    if len(parts) >= 4:
                        folder_name = parts[-2]
                    else:
                        folder_name = parts[-1] if parts else folder_info
                else:
                    # Method 2: Take the last part after space
                    parts = folder_info.split()
                    if len(parts) >= 3:
                        folder_name = parts[-1]
                    else:
                        folder_name = folder_info
                
                # Clean up folder name
                folder_name = folder_name.strip()
                if folder_name and folder_name != '.':
                    folder_names.append(folder_name)
            
            return folder_names
        except Exception as e:
            logger.error(f"Error getting folder list: {e}")
            return []

    def find_sent_folder(self, mail: imaplib.IMAP4_SSL) -> Optional[str]:
        """Find the sent folder by trying to select common names."""
        possible_sent_folders = [
            'Sent',
            'INBOX.Sent', 
            'INBOX/Sent',
            'Sent Items',
            'Sent Messages',
            'INBOX.Sent Items',
            'INBOX.Sent Messages',
            'Gesendete Elemente',  # German
            'Elementos enviados',  # Spanish
            'Enviados',  # Spanish/Portuguese
            'Verzonden',  # Dutch
            'Skickat',  # Swedish
        ]
        
        for folder in possible_sent_folders:
            try:
                logger.info(f"Trying to select folder: {folder}")
                status, count = mail.select(folder, readonly=True)
                if status == 'OK':
                    logger.info(f"Successfully found sent folder: {folder}")
                    return folder
                else:
                    logger.debug(f"Could not select {folder}: {status}")
            except Exception as e:
                logger.debug(f"Error trying folder {folder}: {e}")
        
        return None

    def check_folder(self, mail: imaplib.IMAP4_SSL, folder: str, email_type: str) -> bool:
        """Check a specific folder for new emails. Returns True if successful."""
        try:
            # Try to select the folder
            status, count = mail.select(folder)
            if status != 'OK':
                logger.warning(f"Could not select folder '{folder}': {status}")
                return False
            
            logger.info(f"Successfully selected folder '{folder}' with {count[0].decode()} messages")
            
            # Search for emails based on type
            if email_type == "received":
                # Search for unread emails
                search_criteria = 'UNSEEN'
            else:  # sent
                # Search for all emails in sent folder, we'll filter by date
                search_criteria = 'ALL'
            
            status, messages = mail.search(None, search_criteria)
            
            if status != 'OK':
                logger.error(f"Failed to search {folder}: {status}")
                return False
            
            email_ids = messages[0].split()
            logger.info(f"Found {len(email_ids)} emails in {folder} (type: {email_type})")
            
            for email_id in email_ids:
                # Skip if already processed
                if email_id in self.processed_uids.get(folder, set()):
                    continue
                
                # Initialize folder in processed_uids if not exists
                if folder not in self.processed_uids:
                    self.processed_uids[folder] = set()
                
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
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking {folder}: {e}")
            return False

    def monitor_emails(self) -> None:
        """Main monitoring loop."""
        logger.info("Starting email monitor...")
        
        # Get available folders on first run
        first_run = True
        sent_folder = None
        
        while True:
            try:
                # Connect to IMAP server
                mail = self.connect_imap()
                
                # On first run, discover available folders
                if first_run:
                    logger.info("Discovering available folders...")
                    available_folders = self.get_available_folders(mail)
                    logger.info(f"Available folders: {available_folders}")
                    
                    # Find the sent folder by trying to select them
                    logger.info("Searching for sent folder...")
                    sent_folder = self.find_sent_folder(mail)
                    
                    if sent_folder:
                        logger.info(f"Found sent folder: {sent_folder}")
                    else:
                        logger.warning("No sent folder found, will only monitor inbox")
                    
                    first_run = False
                
                # Check inbox for new unread emails
                logger.info("Checking INBOX for new emails...")
                self.check_folder(mail, 'INBOX', 'received')
                
                # Check sent folder for new sent emails (if found)
                if sent_folder:
                    logger.info(f"Checking {sent_folder} for new sent emails...")
                    self.check_folder(mail, sent_folder, 'sent')
                
                # Close connection properly
                try:
                    mail.close()
                except:
                    pass  # Ignore errors when closing
                
                mail.logout()
                
                # Wait before next check
                logger.info(f"Waiting {self.check_interval} seconds before next check...")
                time.sleep(self.check_interval)
                
            except KeyboardInterrupt:
                logger.info("Email monitor stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                # Try to close connection if still open
                try:
                    mail.close()
                    mail.logout()
                except:
                    pass
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
