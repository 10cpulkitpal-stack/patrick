"""Authentication support services shared by Patrick's auth routes."""

import hashlib
import os
import secrets
import smtplib
import time
from email.message import EmailMessage

from flask import request, url_for
from sqlalchemy import select

from backend.models import EmailVerificationToken


class AuthService:
    def __init__(self, app, session_factory):
        self.app = app
        self.session_factory = session_factory

    @staticmethod
    def mail_settings():
        try:
            port = int(os.environ.get("MAIL_PORT", "587"))
        except ValueError:
            return None
        settings = {
            "host": os.environ.get("MAIL_SERVER"), "port": port,
            "username": os.environ.get("MAIL_USERNAME"),
            "password": os.environ.get("MAIL_PASSWORD"),
            "sender": os.environ.get("MAIL_FROM"),
        }
        if not all(settings[key] for key in ("host", "username", "password", "sender")) or not 1 <= port <= 65535:
            return None
        return settings

    def send_verification_email(self, email, token):
        settings = self.mail_settings()
        if not settings:
            return False
        base_url = os.environ.get("PUBLIC_BASE_URL", request.url_root.rstrip("/"))
        verification_url = f"{base_url.rstrip('/')}{url_for('verify_email')}?token={token}"
        message = EmailMessage()
        message["Subject"] = "Verify your Patrick account"
        message["From"] = settings["sender"]
        message["To"] = email
        message.set_content(
            "Verify your email address to finish creating your Patrick account.\n\n"
            f"{verification_url}\n\nThis link expires in 30 minutes."
        )
        try:
            if settings["port"] == 465:
                with smtplib.SMTP_SSL(settings["host"], settings["port"], timeout=10) as smtp:
                    smtp.login(settings["username"], settings["password"])
                    smtp.send_message(message)
            else:
                with smtplib.SMTP(settings["host"], settings["port"], timeout=10) as smtp:
                    smtp.ehlo()
                    smtp.starttls()
                    smtp.ehlo()
                    smtp.login(settings["username"], settings["password"])
                    smtp.send_message(message)
            return True
        except Exception:
            self.app.logger.exception("Failed to send a verification email")
            return False

    def issue_verification_token(self, user_id, email):
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.session_factory.begin() as db:
            for old_token in db.scalars(select(EmailVerificationToken).where(EmailVerificationToken.user_id == user_id)):
                db.delete(old_token)
            db.add(EmailVerificationToken(token_hash=token_hash, user_id=user_id, expires_at=time.time() + 1800))
        if not self.send_verification_email(email, token):
            with self.session_factory.begin() as db:
                for token_row in db.scalars(select(EmailVerificationToken).where(EmailVerificationToken.user_id == user_id)):
                    db.delete(token_row)
            return False
        return True
