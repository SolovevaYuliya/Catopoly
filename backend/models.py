from sqlalchemy import Column, Integer, String, ForeignKey, Numeric, Boolean, DateTime
from .database import Base

class cells(Base):
    __tablename__ = "cells"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    color_group = Column(String)
    purchase_price = Column(Numeric)
    rent_base = Column(Numeric)

class users(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=False)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    avatar_url = Column(String, nullable=True)

class games(Base):
    __tablename__ = "games"
    id = Column(Integer, primary_key=True, index=True)
    status = Column(String, nullable=False) # 'waiting', 'playing', 'finished'
    current_player_turn = Column(Integer, nullable=False, default=1)
    turn_number = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    max_players = Column(Integer, nullable=False, default=5)
    is_private = Column(Boolean, nullable=False, default=False)
    last_dice1 = Column(Integer, default=1)
    last_dice2 = Column(Integer, default=1)
    dice_roll_at = Column(DateTime(timezone=True))
    has_rolled = Column(Boolean, default=False)
    owner_id = Column(Integer, ForeignKey("users.id"))
    winner_id = Column(Integer, ForeignKey("users.id"), nullable=True)

class game_player(Base):
    __tablename__ = "game_player"
    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    balance = Column(Numeric, nullable=False, default=1500)
    position = Column(Integer, nullable=False, default=0)
    turn_order = Column(Integer, nullable=False, default=1)
    is_bankrupt = Column(Boolean, nullable=False, default=False)
    jail_turns = Column(Integer, nullable=False, default=0)
    is_in_jail = Column(Boolean, default=False)
    doubles_count = Column(Integer, default=0)


class property_ownership(Base):
    __tablename__ = "property_ownership"
    id = Column(Integer, primary_key=True, nullable=False)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    cell_id = Column(Integer, ForeignKey("cells.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("game_player.id"))
    houses_count = Column(Integer, default=0)
    is_mortgaged = Column(Boolean, nullable=False, default=False)
    fish_count = Column(Integer, default=0)
    mortgage_turns_left = Column(Integer, default=10)

class game_log(Base):
    __tablename__ = "game_log"
    id = Column(Integer, primary_key=True, nullable=False)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    player_id = Column(Integer, ForeignKey("game_player.id"), nullable=False)
    action_text = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)

class game_chat(Base):
    __tablename__ = "game_chat"
    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)

class friendships(Base):
    __tablename__ = "friendships"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    friend_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String, default="pending")

class invitations(Base):
    __tablename__ = "invitations"
    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    recipient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    status = Column(String, default="pending")

class trades(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    sender_id = Column(Integer, ForeignKey("game_player.id"), nullable=False)
    recipient_id = Column(Integer, ForeignKey("game_player.id"), nullable=False)
    offer_money = Column(Integer, default=0)
    request_money = Column(Integer, default=0)
    offer_properties = Column(String)  # Список ID клеток через запятую "1,5,10"
    request_properties = Column(String) # Список ID клеток через запятую
    status = Column(String, default="pending") # pending, accepted, declined