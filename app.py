from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime, date
from database_hr import db, Applicant, Interview, Employee, Attendance, Task, LeaveRequest, Candidates
import os
import re
import json
from langchain_community.document_loaders import PyPDFLoader, UnstructuredWordDocumentLoader
from langchain_ollama import OllamaLLM
from collections import OrderedDict
import mysql.connector
import sys

app = Flask(__name__)
EXTRACTOR_MODEL = os.environ.get("EXTRACTOR_MODEL", "llama3.2:1b")
# ------------------ DATABASE CONFIG ------------------ #
app.config['SECRET_KEY'] = 'your_secret_key'
# Use proper encoding of @ in password -> admin@123 → admin%40123

app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:admin%40123@localhost/hr'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

with app.app_context():
    db.create_all()
# Temporary storage (replace with DB later)
applications = {}
interviews = {}
statuses = {}
# Employees storage: keyed by employee id
employee = {}
# Simple counters for IDs
_interview_counter = 1
_employee_counter = 1
# Leave requests storage
leave_requests = {}
# Tasks storage
tasks = {}
_leave_request_counter = 1

def flatten_for_db(value):
    if isinstance(value, list):
        return ", ".join(map(str, value))
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in value.items())
    return str(value) if value is not None else ""

def extract_text_from_file(filepath):
    """Load text from PDF or Word file using LangChain loaders."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".pdf":
        loader = PyPDFLoader(filepath)
    elif ext in [".doc", ".docx"]:
        loader = UnstructuredWordDocumentLoader(filepath)
    else:
        raise ValueError("Unsupported file type. Only PDF, DOC, DOCX allowed.")
    
    docs = loader.load()
    return "\n".join([d.page_content for d in docs])

def extract_candidate_data(text, llm_model=EXTRACTOR_MODEL):
    llm = OllamaLLM(model=llm_model)

    def ask_llm(prompt):
        try:
            return llm.invoke(prompt)
        except Exception as e:
            print(" LLM invocation failed:", e)
            return ""

    base_prompt = f"""
You are an AI resume parser that always outputs JSON — never plain text.

Analyze the following resume and extract structured candidate information.

Output ONLY valid JSON, no extra text, no markdown, no explanations.

contact, phone no ,mob and moblie no are same and hold the 10 digits to 12 digits 

The JSON must follow this structure exactly:
 

{{
  "fullname": "",
  "contact": "",
  "email": "",
  "position": "",
  "language": "",
  "qualification": "",
  "experience": "",
  "current_company": "",
  "current_salary": "",
  "expected_salary": "",
  "in_hand_salary": "",
  "permanent_address": "",
  "current_address": "",
  "skill": "",
  "switching_reason": ""
}}

If a field is missing, leave it blank ("").

Resume text:
{text}
"""

    
    response = ask_llm(base_prompt)
    raw = str(response).strip()
    # --- Fix for cases when Ollama adds explanations or markdown ---
    if "```" in raw:
        raw = re.sub(r"(?s)```(?:json)?(.*?)```", r"\1", raw).strip()

    # Try to extract JSON block from anywhere in text
    match = re.search(r'\{[\s\S]*\}', raw)
    if not match:
        print(" No JSON object found in model output.")
        print(" Raw output sample:", raw[:300])
        return {}

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError as e:
        print(" JSON parse failed:", e)
        print(" Raw text sample:", raw[:300])
        return {}

    # Remove code fences and explanations
    json_str = re.search(r'\{[\s\S]*\}', raw)
    if not json_str:
        print(" No JSON object found in model output.")
        return {}

    try:
        data = json.loads(json_str.group())
    except json.JSONDecodeError as e:
        print(" JSON decode error:", e)
        print(" Raw text was:", raw[:300])
        return {}

    # Flatten nested dicts/lists for DB storage
    def flatten(value):
        if isinstance(value, dict):
            return ", ".join(f"{k}: {v}" for k, v in value.items())
        if isinstance(value, list):
            return ", ".join(map(str, value))
        return str(value)

    data = {k: flatten(v) for k, v in data.items()}
    print(" Clean extracted data:", data)
    return data


def get_valid_candidate(extracted_json_list):
    for data in extracted_json_list:
        if data.get('fullname'):
            # Optional: normalize keys if needed
            return {
                'fullname': data.get('fullname', ''),
                'contact': data.get('contact', ''),
                'email': data.get('email', ''),
                'position': data.get('position', ''),
                'qualification': data.get('qualification', ''),
                'experience': data.get('experience', {}),
                'current_company': data.get('current_company', ''),
                'current_salary': data.get('current_salary', ''),
                'expected_salary': data.get('expected_salary', ''),
                'in_hand_salary': data.get('in_hand_salary', ''),
                'permanent_address': data.get('permanent_address', ''),
                'current_address': data.get('address', ''),
                'skill': ', '.join(data.get('skills', [])),
                'switching_reason': data.get('switching_reason', '')
            }
    return None

def save_candidate(data, file_name=None):
    candidate = Candidates(
        fullname=data.get('fullname'),
        contact=data.get('contact'),
        email=data.get('email'),
        position=data.get('position'),
        language=data.get('language'),
        qualification=data.get('qualification'),
        experience=data.get('experience'),
        current_company=data.get('current_company'),
        current_salary=data.get('current_salary'),
        expected_salary=data.get('expected_salary'),
        in_hand_salary=data.get('in_hand_salary'),
        permanent_address=data.get('permanent_address'),
        current_address=data.get('current_address'),
        skill=data.get('skill'),
        switching_reason=data.get('switching_reason'),
        file_name=file_name,
        status="Pending Review"
    )
    db.session.add(candidate)
    db.session.commit()

def flatten_candidate(raw):
    candidate = {}

    # Top-level fields
    candidate['fullname'] = raw.get('fullname', '')
    candidate['contact'] = raw.get('contact', '')
    candidate['email'] = raw.get('email', '')
    candidate['position'] = raw.get('position', '')
    candidate['language'] = raw.get('language', '')
    candidate['qualification'] = raw.get('qualification', '')
    candidate['address'] = raw.get('address', '')
    candidate['current_address'] = raw.get('current_address', '')

    # Flatten skills array
    skills = raw.get('skills', [])
    candidate['skills'] = [s.get('fullname', '') for s in skills if s.get('fullname')]

    # Flatten experience
    exp = raw.get('experience', {})
    candidate['current_company'] = exp.get('current_company', '')
    candidate['current_salary'] = exp.get('current_salary', '')
    candidate['expected_salary'] = exp.get('expected_salary', '')
    candidate['in_hand_salary'] = exp.get('in_hand_salary', '')
    candidate['switching_reason'] = exp.get('switching_reason', '')
    
    # Flatten personal details if missing top-level
    personal = raw.get('personal_details', [])
    for item in personal:
        if not candidate['fullname'] and 'fullname' in item:
            candidate['fullname'] = item['fullname']
        if not candidate['contact'] and 'contact' in item:
            candidate['contact'] = item['contact']
        if not candidate['email'] and 'email' in item:
            candidate['email'] = item['email']

    return candidate

# ---------------- HOME ---------------- #
@app.route('/')
def index():
    return render_template('index.html')


# ---------------- APPLICANT FORM ---------------- #
@app.route('/applicants', methods=['GET', 'POST'])
def applicants():
    if request.method == 'POST':
        form_data = request.form.to_dict()
        email = form_data.get('email')
        applications[email] = form_data
        statuses[email] = 'Submitted'
        try:
            # Safely handle file upload
            resume_file = request.files.get('resume')
            resume_filename = resume_file.filename if resume_file else None

            # Create new applicant record
            applicant = Applicant(
                job_type=request.form.get('job_type'),
                position=request.form.get('position'),
                fullname=request.form.get('fullname'),
                gender=request.form.get('gender'),
                contact=request.form.get('contact'),
                email=request.form.get('email'),
                qualification=request.form.get('qualification'),
                computer_skills=request.form.get('computer_skills'),
                erp_skills=request.form.get('erp_skills'),
                written_english=request.form.get('written_english'),
                spoken_english=request.form.get('spoken_english'),
                understanding_english=request.form.get('understanding_english'),
                expected_salary=request.form.get('expected_salary'),
                experience=request.form.get('experience'),
                last_job=request.form.get('last_job'),
                salary=request.form.get('salary'),
                why_switch=request.form.get('why_switch'),
                family_members=request.form.get('family_members'),
                father_details=request.form.get('father_details'),
                permanent_address=request.form.get('permanent_address'),
                current_address=request.form.get('current_address'),
                joining_time=request.form.get('joining_time'),
                resume=resume_filename,
                status='Applied'
            )

            db.session.add(applicant)
            db.session.commit()

            print(f"Applicant '{applicant.fullname}' saved successfully with email {applicant.email}")
            return redirect(url_for('applicants_dashboard', email=applicant.email))

        except Exception as e:
            db.session.rollback()
            print(f"Error saving applicant: {e}")
            return f"Database Error: {e}", 500

    return render_template('applicants.html')


# ---------------- APPLICANT DASHBOARD ---------------- #
@app.route('/applicants/dashboard/<email>')
def applicants_dashboard(email):
    applicant = Applicant.query.filter_by(email=email).first()
    candidate_data = Candidates.query.filter_by(email=email).first()

    if not applicant and not candidate_data:
        return render_template('applicants_dashboard.html', user=None, status="No record found")

    data_source = applicant or candidate_data

    # ✅ Explicit check removes Pylance warning and runtime risk
    if data_source is None or not hasattr(data_source, "__table__"):
        return render_template('applicants_dashboard.html', user=None, status="Invalid record")

    user_data = {c.name: getattr(data_source, c.name) for c in data_source.__table__.columns}

    return render_template(
        'applicants_dashboard.html',
        user=user_data,
        status=user_data.get("status", "Pending Review")
    )

@app.route('/applicants/status/<email>')
def applicant_status(email):
    applicant = Applicant.query.filter_by(email=email).first()
    status = applicant.status if applicant else "No record found"
    return render_template('status.html', status=status, email=email)



@app.route('/applicants/interview/<email>')
def applicant_interview(email):
    applicant = Applicant.query.filter_by(email=email).first()
    
    if not applicant:
        return render_template('interview.html', interview=None, email=email)

    interview = Interview.query.filter_by(applicant_id=applicant.id).first()
    return render_template('interview.html', interview=interview, email=email)


@app.route('/candidates/by_placement')
def by_placement():
    candidates = Candidates.query.all()
    return render_template("by_placement.html", candidates=candidates)

@app.route('/upload_resume', methods=['GET', 'POST'])
def upload_resume():
    
    if request.method == 'POST':
        resume_file = request.files.get('resume')

        if not resume_file or not resume_file.filename:
            flash("Please upload a valid resume file.", "error")
            return redirect(url_for('by_placement'))

        upload_folder = os.path.join(os.getcwd(), "uploads")
        os.makedirs(upload_folder, exist_ok=True)

        filepath = os.path.join(upload_folder, resume_file.filename)
        resume_file.save(filepath)

        # Extract text and data
        text = extract_text_from_file(filepath)
        extracted_data = extract_candidate_data(text)
        print(" Extracted Data:", extracted_data)

        if not extracted_data:
            flash("AI could not extract candidate details. Please verify the resume.", "error")
            return redirect(url_for('by_placement'))

        # Save to DB
        candidates = Candidates(
            fullname=extracted_data.get("fullname", ""),
            contact=extracted_data.get("contact", ""),
            email=extracted_data.get("email", ""),
            position=extracted_data.get("position", ""),
            language=extracted_data.get("language", ""),
            qualification=extracted_data.get("qualification", ""),
            experience=extracted_data.get("experience", ""),
            current_company=extracted_data.get("current_company", ""),
            current_salary=extracted_data.get("current_salary", ""),
            expected_salary=extracted_data.get("expected_salary", ""),
            in_hand_salary=extracted_data.get("in_hand_salary", ""),
            permanent_address=extracted_data.get("permanent_address", ""),
            current_address=extracted_data.get("current_address", ""),
            skill=extracted_data.get("skill", ""),
            switching_reason=extracted_data.get("switching_reason", ""),
            file_name=resume_file.filename,
            status="Pending Review"
        )

        db.session.add(candidates)
        db.session.commit()
        flash(f"Candidate '{candidates.fullname}' uploaded successfully!", "success")
        return redirect(url_for('applicants_dashboard', email=candidates.email))


    return render_template('by_placement.html')

@app.route('/admin/upload_candidates', methods=['GET'])
def upload_candidates():
    candidates = Candidates.query.order_by(Candidates.id.desc()).all()
    return render_template('upload_candidates.html', candidates=candidates)


# ---------------- ADMIN PANEL ---------------- #
@app.route('/admin')
def admin():
    applications = Applicant.query.all()
    employees = Employee.query.all()
    leave_requests = LeaveRequest.query.all()
    interviews = Interview.query.all()
    attendance_records = Attendance.query.order_by(Attendance.date.desc()).all()
    candidates = Candidates.query.all()
    return render_template(
        'admin.html',
        applications=applications,
        employees=employees,
        leave_requests=leave_requests,
        interviews=interviews,
        attendance_records=attendance_records,
        candidates=candidates
    )

# ------------------ ADMIN DASHBOARD ------------------ #
@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('is_admin'):
        flash("Please log in as admin to continue.", "error")
        return redirect(url_for('admin_login'))
    
    applications = Applicant.query.all()
    employees = Employee.query.all()
    leave_requests = LeaveRequest.query.all()
    interviews = Interview.query.all()
    attendance_records = Attendance.query.order_by(Attendance.date.desc()).all()

    return render_template(
        'admin.html',
        applications=applications,
        employees=employees,
        leave_requests=leave_requests,
        interviews=interviews,
        attendance_records=attendance_records
    )


@app.route('/admin/schedule_interview', methods=['POST'])
def schedule_interview():
    email = request.form.get('email')
    date = request.form.get('date')
    time = request.form.get('time')
    mode = request.form.get('mode')

    applicant = Applicant.query.filter_by(email=email).first()
    if not applicant:
        return "Applicant not found", 404

    interview = Interview(
        applicant_id=applicant.id,
        date=date,
        time=time,
        mode=mode,
        interviewer='HR Manager',
        result='Scheduled'
    )
    applicant.status = 'Interview Scheduled'
    db.session.add(interview)
    db.session.commit()
    return redirect(url_for('admin'))

@app.route('/admin/update_status', methods=['POST'])
def admin_update_status():
    applicant_id = request.form.get('applicant_id')
    new_status = request.form.get('status')
    applicant = Applicant.query.get(applicant_id)
    if applicant:
        applicant.status = new_status
        db.session.commit()
    return redirect(url_for('admin'))

@app.route('/admin/hire', methods=['POST'])
def admin_hire():
    applicant_id = request.form.get('applicant_id')
    applicant = Applicant.query.get(applicant_id)
    if not applicant:
        return redirect(url_for('admin'))

    # Clean the salary input before converting
    raw_salary = applicant.expected_salary or ""
    clean_salary = ''.join(ch for ch in raw_salary if ch.isdigit() or ch == '.' )

    employee = Employee(
        name=applicant.fullname,
        contact=applicant.contact,
        position=applicant.position,
        email=applicant.email,
        salary=float(clean_salary) if clean_salary else None,
        joining_date=datetime.today()
    )


    applicant.status = 'Hired'
    db.session.add(employee)
    db.session.commit()

    return redirect(url_for('admin'))

# ---------------- EMPLOYEE SECTION ---------------- #
@app.route('/employee/login', methods=['GET', 'POST'])
def employee_login():
    if request.method == 'POST':
        name = request.form.get('name')
        contact = request.form.get('contact')  # contact input, matches contact in DB

        # Corrected: use contact instead of phone
        emp = Employee.query.filter_by(name=name, contact=contact).first()
        if emp:
            session['emp_id'] = emp.id
            flash(f"Welcome {emp.name}!", "success")
            return redirect(url_for('employee_dashboard', emp_id=emp.id))
        else:
            flash("Invalid name or contact number.", "error")

    return render_template('employee_dashboard.html')

# ---------------- MARK ATTENDANCE ---------------- #
@app.route('/attendance/mark', methods=['GET', 'POST'])
def mark_attendance():
    employees = Employee.query.all()

    if request.method == 'POST':
        today_date = date.today()
        added_count = 0  

        # Identify who is marking attendance
        marked_by = "Admin" if session.get('is_admin') else "Employee"

        for emp in employees:
            status = request.form.get(f"status_{emp.id}")
            if status:
                existing = Attendance.query.filter_by(employee_id=emp.id, date=today_date).first()
                if existing:
                    flash(f" Attendance for {emp.name} already marked today.", "warning")
                    continue

                attendance = Attendance(
                    employee_id=emp.id,
                    fullname=emp.name,
                    position=emp.position,
                    date=today_date,
                    status=status,
                    action_by=f"Added by {marked_by}"
                )
                db.session.add(attendance)
                added_count += 1

        db.session.commit()

        if added_count > 0:
            flash(f" Attendance marked successfully for {added_count} employees!", "success")
        else:
            flash("No new attendance entries were added (all already marked).", "info")

        # Redirect logic — admin vs employee
        if emp_id := session.get('emp_id'):
            return redirect(url_for('employee_dashboard', emp_id=emp_id))

    return render_template('mark_attendance.html', employees=employees, today=date.today())
@app.route('/employee/attendance')
def employee_attendance():
    emp_id = session.get('emp_id')
    if not emp_id:
        flash("Please log in to view your attendance.", "warning")
        return redirect(url_for('employee_login'))

    emp = Employee.query.get(emp_id)
    attendance_records = Attendance.query.filter_by(employee_id=emp).order_by(Attendance.date.desc()).all()

    return render_template('employee_attendance.html', emp=emp, attendance_records=attendance_records)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        # Simple admin check
        if username == 'admin' and password == 'admin@123':
            session['is_admin'] = True
            flash("Login successful!", "success")
            return redirect(url_for('admin_dashboard'))
        else:
            flash("Invalid credentials.", "error")
    
    return render_template('admin_login.html')

@app.route('/admin/attendance/edit/<int:attendance_id>', methods=['GET', 'POST'])
def edit_attendance(attendance_id):
    if not session.get('is_admin'):
        flash("Unauthorized access.", "error")
        return redirect(url_for('admin_login'))

    attendance = Attendance.query.get_or_404(attendance_id)

    if request.method == 'POST':
        new_status = request.form.get('status')
        attendance.status = new_status
        attendance.action_by = f"Edited by Admin on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        db.session.commit()
        flash("Attendance updated successfully!", "success")
        return redirect(url_for('admin_attendance'))

    return render_template('edit_attendance.html', attendance=attendance)   

@app.route('/admin/attendance/delete/<int:attendance_id>', methods=['POST', 'GET'])
def admin_attendance_delete(attendance_id):
    if not session.get('is_admin'):
        flash("Unauthorized access.", "error")
        return redirect(url_for('admin_login'))

    attendance = Attendance.query.get_or_404(attendance_id)
    db.session.delete(attendance)
    db.session.commit()

    flash("Attendance record deleted successfully!", "success")
    return redirect(url_for('admin_attendance'))

@app.route('/employees')
def employees():
    employees = Employee.query.all()   # fetch all employees from DB
    return render_template('employees.html', employees=employees)

@app.route('/employee/add', methods=['GET', 'POST'])
def add_employee():
    if request.method == 'POST':
        name = request.form.get('fullname')
        contact = request.form.get('contact')
        position = request.form.get('position')
        email = request.form.get('email')
        salary = request.form.get('salary')
        joining_date = request.form.get('joining_date')

        try:
            # Safely parse salary and joining date
            salary_float = float(salary) if salary else 0.0
            joining_dt = datetime.strptime(joining_date, "%Y-%m-%d") if joining_date else None

            new_emp = Employee(
                name=name,
                contact=contact,
                position=position,
                email=email,
                salary=salary_float,
                joining_date=joining_dt
            )

            db.session.add(new_emp)
            db.session.commit()
            return redirect(url_for('employees'))

        except Exception as e:
            db.session.rollback()
            return f"Error adding employee: {e}", 500

    return render_template('add_employee.html')


@app.route('/employee/dashboard/<int:emp_id>')
def employee_dashboard(emp_id):
    emp = Employee.query.get(emp_id)
    if not emp:
        return "Employee not found", 404

    leave_requests = LeaveRequest.query.filter_by(employee_id=emp.id).order_by(LeaveRequest.start_date.desc()).all()

    today = date.today()
    return render_template(
        'employee_dashboard.html',
        emp=emp,
        leave_requests=leave_requests,
        today=today
    )


@app.route('/employee/update/<int:emp_id>', methods=['POST'])
def update_employee(emp_id):
    emp = db.session.get(Employee, emp_id)
    if not emp:
        return "Employee not found", 404

    emp.name = request.form.get('fullname')
    emp.contact = request.form.get('contact')
    emp.position = request.form.get('position')
    emp.email = request.form.get('email')

    salary_base = request.form.get('salary_base')
    try:
        emp.salary = float(salary_base) if salary_base not in (None, '') else 0.0
    except (TypeError, ValueError):
        emp.salary = 0.0

    db.session.commit()
    return redirect(url_for('employee_dashboard', emp_id=emp_id))


# ---------------- LEAVE REQUEST ---------------- #
@app.route('/leave/request', methods=['GET', 'POST'])
def leave_request():
    if request.method == 'POST':
        emp_id = request.form.get('emp_id')
        fullname = request.form.get('fullname')
        leave_type = request.form.get('leave_type')
        start_date = request.form.get('date_from')
        end_date = request.form.get('date_to')
        reason = request.form.get('reason')

        try:
            new_leave = LeaveRequest(
                employee_id=emp_id,
                fullname=fullname,
                leave_type=leave_type,
                start_date=start_date,
                end_date=end_date,
                reason=reason,
                status='Pending'
            )
            db.session.add(new_leave)
            db.session.commit()
            # Redirect to that employee’s dashboard
            return redirect(url_for('employee_dashboard', emp_id=emp_id))
        except Exception as e:
            db.session.rollback()
            return f"Error submitting leave request: {e}", 500

    # GET method — show a standalone leave form
    emp_id = session.get('emp_id')
    if not emp_id:
        return redirect(url_for('employee_login'))
    emp = db.session.get(Employee, emp_id)
    return render_template('leave_form.html', emp=emp)

@app.route('/leave/status/<int:emp_id>')
def view_leave_status(emp_id):
    emp = db.session.get(Employee, emp_id)
    if not emp:
        return "Employee not found", 404

    leave_requests = LeaveRequest.query.filter_by(employee_id=emp.id).all()
    return render_template('leave_status.html', emp=emp, leave_requests=leave_requests)

@app.route('/employee/salary')
@app.route('/employee/salary/<int:emp_id>')
def employee_salary(emp_id=None):
    if emp_id is None:
        emp_id = session.get('emp_id')
        if not emp_id:
            flash("Please log in to view your salary slip.", "warning")
            return redirect(url_for('employee_login'))

    emp = db.session.get(Employee, emp_id)
    if not emp:
        return "Employee not found", 404

    # ---- Salary calculation logic (same as before) ----
    salary_base = emp.salary or 0
    total_days = 30
    sundays = 4
    working_days = total_days - sundays
    attendance_records = Attendance.query.filter_by(employee_id=emp.id).all()

    late_count = sum(1 for record in attendance_records if record.status == 'Late')
    half_days = sum(1 for record in attendance_records if record.status == 'Half Day')
    full_absents = sum(1 for record in attendance_records if record.status == 'Absent')

    deducted_days = 0
    if late_count > 3:
        deducted_days += 0.5
    if half_days > 2:
        deducted_days += 0.5
    if full_absents > 1:
        deducted_days += 1

    per_day_salary = salary_base / working_days
    deduction_amount = per_day_salary * deducted_days
    net_salary = salary_base - deduction_amount

    slip_data = {
        'emp_id': emp.id,
        'name': emp.name,
        'salary_base': salary_base,
        'late_count': late_count,
        'half_days': half_days,
        'full_absents': full_absents,
        'deducted_days': round(deducted_days, 2),
        'deduction_amount': round(deduction_amount, 2),
        'net_salary': round(net_salary, 2),
        'sundays': sundays,
        'working_days': working_days,
        'total_days': total_days
    }

    return render_template('salary_slip.html', slip=slip_data)



@app.route('/admin/attendance/add', methods=['GET', 'POST'])
def add_employee_attendance():
    if request.method == 'POST':
        employee_id = request.form.get('employee_id')
        date_value = request.form.get('date')
        status_value = request.form.get('status')

        emp = Employee.query.get(employee_id)
        if not emp:
            flash("Employee not found.", "error")
            return redirect(url_for('admin_attendance'))

        # Check if already marked for that date
        existing = Attendance.query.filter_by(employee_id=emp.id, date=date_value).first()
        if existing:
            flash(f"Attendance already marked for {emp.name} on {date_value}.", "warning")
            return redirect(url_for('admin_attendance'))

        # Create new attendance entry
        attendance = Attendance(
            employee_id=emp.id,
            fullname=emp.name,
            position=emp.position,
            date=date_value,
            status=status_value,
            action_by="Added by Admin"
        )

        try:
            db.session.add(attendance)
            db.session.commit()
            flash("Attendance added successfully!", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Database error: {e}", "error")

        return redirect(url_for('admin_attendance'))

    # GET request – show the form
    employees = Employee.query.all()
    return render_template('add_employee_attendance.html', employees=employees)


@app.route('/admin/leave_action', methods=['POST'])
def admin_leave_action():
    lr_id = request.form.get('leave_id')
    action = request.form.get('action')
    leave = LeaveRequest.query.get(lr_id)
    if leave:
        leave.status = 'Approved' if action == 'approve' else 'Rejected'
        db.session.commit()
    return redirect(url_for('admin'))

@app.route('/admin/attendance')
def admin_attendance():
    # Only admin can view and edit attendance records
    if not session.get('is_admin'):
        flash("Unauthorized access.", "error")  
        return redirect(url_for('admin_login'))
    attendance_records = Attendance.query.order_by(Attendance.date.desc()).all()
    return render_template('admin_attendance.html', attendance_records=attendance_records)

# ---------------- TASK MANAGEMENT ---------------- #
@app.route('/employee/task/add/<int:emp_id>', methods=['POST'])
def add_task(emp_id):
    title = request.form.get('title')
    status = request.form.get('status', 'Pending')
    task = Task(employee_id=emp_id, title=title, status=status)
    db.session.add(task)
    db.session.commit()
    return redirect(url_for('employee_dashboard', emp_id=emp_id))

@app.route('/employee/logout')
def employee_logout():
    session.clear()
    return redirect(url_for('employee_login'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    flash("Admin logged out successfully.", "info")
    return redirect(url_for('admin_login'))

# ---------------- RUN ---------------- #
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

  
