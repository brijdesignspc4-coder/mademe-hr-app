from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
import json
from langchain_community.document_loaders import PyPDFLoader, UnstructuredWordDocumentLoader
from langchain_ollama import OllamaLLM
db = SQLAlchemy()
EXTRACTOR_MODEL = os.environ.get("EXTRACTOR_MODEL", "gemma3:4b")

import pymysql
conn = pymysql.connect(
    host="localhost",
    user="root",
    password="admin@123",
    database="hr"
)
print("Connected!")
conn.close()

# ------------------ APPLICANT MODEL ------------------ #
class Applicant(db.Model):
    __tablename__ = 'applicant'
    
    id = db.Column(db.Integer, primary_key=True)
    job_type = db.Column(db.String(20))
    position = db.Column(db.String(100))
    fullname = db.Column(db.String(100), nullable=False)
    gender = db.Column(db.String(10))
    contact = db.Column(db.String(15))
    email = db.Column(db.String(100), unique=True, nullable=False)
    qualification = db.Column(db.String(50))
    computer_skills = db.Column(db.String(20))
    erp_skills = db.Column(db.String(20))
    written_english = db.Column(db.String(20))
    spoken_english = db.Column(db.String(20))
    understanding_english = db.Column(db.String(20))
    expected_salary = db.Column(db.String(50))
    experience = db.Column(db.String(20))
    last_job = db.Column(db.Text)
    salary = db.Column(db.String(50))
    why_switch = db.Column(db.Text)
    family_members = db.Column(db.Integer)
    father_details = db.Column(db.String(150))
    permanent_address = db.Column(db.Text)
    current_address = db.Column(db.Text)
    joining_time = db.Column(db.String(50))
    resume = db.Column(db.String(200))
    status = db.Column(db.String(20), default='Applied')
    
    interview = db.relationship('Interview', backref='applicant', lazy=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

# ------------------ INTERVIEW MODEL ------------------ #
class Interview(db.Model):
    __tablename__ = 'interview'

    id = db.Column(db.Integer, primary_key=True)
    applicant_id = db.Column(db.Integer, db.ForeignKey('applicant.id'))
    date = db.Column(db.String(50))
    time = db.Column(db.String(50))
    mode = db.Column(db.String(50))
    interviewer = db.Column(db.String(100))
    feedback = db.Column(db.Text)
    result = db.Column(db.String(50))


    def __init__(self, **kwargs):
        super().__init__(**kwargs)




# ------------------ EMPLOYEE MODEL ------------------ #
class Employee(db.Model):
    __tablename__ = 'employee'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)   
    contact = db.Column(db.String(15))
    position = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True, nullable=False)
    salary = db.Column(db.String(50))
    joining_date = db.Column(db.DateTime, default=datetime.utcnow)
    attendance = db.relationship('Attendance', backref='employee', lazy=True)
    tasks = db.relationship('Task', backref='employee', lazy=True)
    leave_requests = db.relationship('LeaveRequest', backref='employee', lazy=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


# ------------------ ATTENDANCE MODEL ------------------ #
class Attendance(db.Model):
    __tablename__ = 'attendance'

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    fullname = db.Column(db.String(50))  
    position = db.Column(db.String(100))
    date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20))
    action_by = db.Column(db.String(100))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

# ------------------ LEAVE REQUEST MODEL ------------------ #
class LeaveRequest(db.Model):
    __tablename__ = 'leave_request'

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    fullname = db.Column(db.String(50))  
    leave_type = db.Column(db.String(20))  
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.Text)
    status = db.Column(db.Enum('Pending', 'Approved', 'Rejected'), default='Pending')


    def __init__(self, **kwargs):
        super().__init__(**kwargs)

# ------------------ TASK MODEL ------------------ #
class Task(db.Model):
    __tablename__ = 'task'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False) 
    due_date = db.Column(db.DateTime)
    status = db.Column(db.String(50))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

#------------------ candidate model---------- #
class Candidates(db.Model):
    __tablename__ = 'candidates'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    fullname = db.Column(db.String(225))
    contact = db.Column(db.Text)                  
    email = db.Column(db.String(225))
    position = db.Column(db.String(225))
    language = db.Column(db.Text)
    qualification = db.Column(db.Text)
    experience = db.Column(db.Text)
    current_company = db.Column(db.String(225))
    current_salary = db.Column(db.String(100))
    expected_salary = db.Column(db.String(100))
    in_hand_salary = db.Column(db.String(100))
    permanent_address = db.Column(db.Text)
    current_address = db.Column(db.Text)
    skill = db.Column(db.Text)
    switching_reason = db.Column(db.Text)
    file_name = db.Column(db.String(225))
    status = db.Column(db.String(50))


    def __init__(self, **kwargs):
        super().__init__(**kwargs)

