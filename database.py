from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from config import DATABASE_URL

engine = create_engine(DATABASE_URL, echo=False)
Base = declarative_base()
Session = sessionmaker(bind=engine)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer, unique=True, nullable=False)
    username = Column(String)
    first_name = Column(String)
    name = Column(String)
    age = Column(Integer)
    height = Column(Integer)
    weight = Column(Float)
    concerns = Column(Text)
    wake_time = Column(String)
    sleep_time = Column(String)
    face_photo_id = Column(String)
    is_premium = Column(Boolean, default=False)
    bio_age = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow)


class FoodLog(Base):
    __tablename__ = "food_log"
    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer, nullable=False)
    description = Column(Text)
    calories = Column(Integer)
    photo_id = Column(String)
    advice = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class WaterLog(Base):
    __tablename__ = "water_log"
    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer, nullable=False)
    ml = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


class FaceScan(Base):
    __tablename__ = "face_scan"
    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer, nullable=False)
    photo_id = Column(String)
    analysis = Column(Text)
    bio_age = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)


class ReminderLog(Base):
    __tablename__ = "reminder_log"
    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer, nullable=False)
    reminder_type = Column(String)
    message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    Base.metadata.create_all(engine)


def get_user(tg_id):
    session = Session()
    try:
        user = session.query(User).filter_by(tg_id=tg_id).first()
        if user:
            user.last_active = datetime.utcnow()
            session.commit()
        return user
    finally:
        session.close()


def create_user(tg_id, **kwargs):
    session = Session()
    try:
        user = User(tg_id=tg_id, **kwargs)
        session.add(user)
        session.commit()
        return user
    finally:
        session.close()


def update_user(tg_id, **kwargs):
    session = Session()
    try:
        user = session.query(User).filter_by(tg_id=tg_id).first()
        if user:
            for k, v in kwargs.items():
                setattr(user, k, v)
            session.commit()
    finally:
        session.close()


def get_all_active_users():
    session = Session()
    try:
        return session.query(User).filter_by(is_premium=True).all()
    finally:
        session.close()


def add_food(tg_id, description, calories, photo_id=None, advice=None):
    session = Session()
    try:
        entry = FoodLog(
            tg_id=tg_id, description=description,
            calories=calories, photo_id=photo_id, advice=advice,
        )
        session.add(entry)
        session.commit()
    finally:
        session.close()


def get_today_food(tg_id):
    session = Session()
    try:
        today = datetime.utcnow().date()
        entries = (
            session.query(FoodLog)
            .filter(FoodLog.tg_id == tg_id)
            .filter(FoodLog.created_at >= today)
            .all()
        )
        total_cal = sum(e.calories or 0 for e in entries)
        return entries, total_cal
    finally:
        session.close()


def add_water(tg_id, ml):
    session = Session()
    try:
        entry = WaterLog(tg_id=tg_id, ml=ml)
        session.add(entry)
        session.commit()
    finally:
        session.close()


def get_today_water(tg_id):
    session = Session()
    try:
        today = datetime.utcnow().date()
        entries = (
            session.query(WaterLog)
            .filter(WaterLog.tg_id == tg_id)
            .filter(WaterLog.created_at >= today)
            .all()
        )
        total_ml = sum(e.ml for e in entries)
        return entries, total_ml
    finally:
        session.close()


def add_face_scan(tg_id, photo_id, analysis, bio_age):
    session = Session()
    try:
        scan = FaceScan(
            tg_id=tg_id, photo_id=photo_id,
            analysis=analysis, bio_age=bio_age,
        )
        session.add(scan)
        session.commit()
    finally:
        session.close()


def get_last_face_scan(tg_id):
    session = Session()
    try:
        scan = (
            session.query(FaceScan)
            .filter(FaceScan.tg_id == tg_id)
            .order_by(FaceScan.created_at.desc())
            .first()
        )
        return scan
    finally:
        session.close()


def add_reminder(tg_id, reminder_type, message):
    session = Session()
    try:
        entry = ReminderLog(
            tg_id=tg_id, reminder_type=reminder_type, message=message,
        )
        session.add(entry)
        session.commit()
    finally:
        session.close()
