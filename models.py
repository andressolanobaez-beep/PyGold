from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import UniqueConstraint
from werkzeug.security import check_password_hash

from extensions import db


def utc_now():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    username = db.Column(db.String(24), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    bio = db.Column(db.String(180), nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    messages = db.relationship("Message", back_populates="sender")

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Game(db.Model):
    __tablename__ = "games"

    id = db.Column(db.String(12), primary_key=True)
    name = db.Column(db.String(60), nullable=False)
    description = db.Column(db.String(500), nullable=False, default="")
    filename = db.Column(db.String(80), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, server_default=db.func.now()
    )

    owner = db.relationship("User")


class FriendRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    status = db.Column(db.String(12), nullable=False, default="pending")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    sender = db.relationship("User", foreign_keys=[sender_id])
    recipient = db.relationship("User", foreign_keys=[recipient_id])


class Friendship(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_low_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    user_high_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        UniqueConstraint("user_low_id", "user_high_id", name="uq_friendship_pair"),
    )


class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    is_group = db.Column(db.Boolean, nullable=False, default=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    members = db.relationship(
        "ConversationMember", back_populates="conversation", cascade="all, delete-orphan"
    )
    messages = db.relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan"
    )


class ConversationMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer, db.ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False
    )
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    joined_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    conversation = db.relationship("Conversation", back_populates="members")
    user = db.relationship("User")
    __table_args__ = (
        UniqueConstraint("conversation_id", "user_id", name="uq_conversation_member"),
    )


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer, db.ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    body = db.Column(db.String(2000), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    conversation = db.relationship("Conversation", back_populates="messages")
    sender = db.relationship("User", back_populates="messages")
