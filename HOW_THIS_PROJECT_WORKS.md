# How this project works

This is a beginner-friendly guide for understanding and presenting the Student Management System. Read it from top to bottom: browser → Flask → Supabase.

## Project structure

```text
sms/
├── app.py                         Flask routes, login, role checks, form handling
├── auth_sessions.py               Keeps Supabase tokens on the Flask server
├── portal_data.py                 Reads Supabase records for each portal page
├── supabase_client.py             Creates Supabase clients from environment settings
├── requirements.txt               Python packages needed by the project
├── .env                           Private project URL, public key, Flask secret
├── .env.example                   Safe template showing required setting names
├── templates/
│   ├── login.html                 Username/password sign-in and reset link
│   ├── portal.html                Shared template for every role and section
│   ├── map.html                   Interactive project map page
│   └── dashboard.html             Earlier dashboard mock-up
├── static/
│   ├── style.css                  Login and portal design
│   ├── map.css                    Project map design
│   ├── mindmap.js                 Tree/radial map behavior
│   ├── mindmap-data.js            Map content and layout test examples
│   └── mindmap-layout.test.js     Browser layout checks for sample maps
├── supabase/
│   ├── schema.sql                 Tables, columns, indexes, starter RLS
│   ├── role_policies.sql          Role-aware database access rules
│   ├── reset_app_data.sql         Clears app records but keeps Auth users/schema
│   └── functions/
│       ├── admin-create-account/
│       │   └── index.ts           Admin-only Auth account and profile setup
│       └── username-lookup/
│           └── index.ts           Private username-to-auth-email lookup
└── tests/
    └── test_app.py                Local route and auth behavior tests
```

## What happens when someone signs in

```text
1. User chooses email or username and enters the account name + password
             │
             ▼
2. If username was chosen, Flask asks a private Supabase Edge Function to resolve it to Auth email
             │
             ▼
3. Flask sends email + password to Supabase Auth (email is used directly when chosen)
             │
             ▼
4. Supabase checks the password and returns tokens
             │
             ├── no profile or unknown role → access is refused
             │
             ▼
5. Flask looks up the user's row in public.profiles
             │
             ▼
6. Flask stores tokens on the server and gives browser a session cookie
             │
             ▼
7. Flask reads the role from profiles, never from a user-selected tab
             │
             ▼
8. Flask displays the matching portal and navigation
```

## The roles and their sections

```text
Student
├── Dashboard
├── Profile
├── Attendance
├── Results and exams
├── Exam datasheet
├── Notifications
├── Feedback
├── Timetable
├── Invoices
└── Complaints

Teacher
├── Dashboard
├── Classes
├── Attendance entry
└── Results entry

HOD
├── Dashboard
├── Department overview
└── Class and result review

Admin
├── Dashboard
├── Students and staff
├── Departments
├── Courses, classes, exams, teacher assignments, and enrollments
└── Announcements
```

All role sections share `templates/portal.html`. Flask supplies the page title, table columns, records, and allowed form fields; Jinja fills those into one layout. This avoids writing a separate copy of the same sidebar and table markup for every page.

## How a page reads and saves data

```text
GET /portal/student/attendance
    → app.py checks signed-in session and role
    → portal_data.py queries attendance using the user's access token
    → Supabase checks Row Level Security policies
    → portal.html renders only the records Supabase allowed

POST /portal/student/feedback
    → app.py checks session and CSRF token
    → validates the subject and message
    → inserts into student_requests using the signed-in student's ID
    → Supabase RLS checks that this student may submit their own request
    → Flask redirects and shows a success message
```

## What the Supabase tables represent

```text
profiles ── account name, role, department, student number
courses ── course names, course codes, department and credits
course_staff ── which teachers are assigned to which courses
enrollments ── which students take which courses in each term
departments ── academic units used to assign people and courses
class_sessions ── scheduled course meetings
exams ── exam name, course, type, date, and location
attendance_records ── attendance status for a student at a session
grades ── course grades and whether they have been published
invoices ── student fees, due dates and payment status
announcements ── published campus notices
student_requests ── feedback and complaints submitted by students
```

The admin Departments page adds academic units. The Students & Staff page creates student, teacher, and HOD Auth accounts with matching profiles assigned to a department. The admin course page adds courses, schedules classes and exams, assigns teachers, and enrolls students. The student exam datasheet reads from `exams`, while the timetable reads from `class_sessions`.

The database, not just the Flask page, checks access. Row Level Security (RLS) means a request for one student's data must not return another student's private data, even if someone tries to change a URL.

## Build and run

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`. Configure `.env`, deploy the username lookup Edge Function, and set a unique username on each matching `profiles` row. For a new Supabase project, apply `schema.sql` and then `role_policies.sql`; if the earlier tables already exist, apply the updated `role_policies.sql`. Follow [SUPABASE_SETUP.md](./SUPABASE_SETUP.md) for the function and secret setup. Run local checks with:

```powershell
python -m unittest discover -s tests
```

## Short presentation explanation

> “I built this student management system with Flask and Jinja templates. Flask handles URLs, sessions, and page data; HTML and CSS build the pages; Supabase Auth checks account passwords; and Supabase Postgres stores student, course, class, exam, attendance, grade, invoice, announcement, and request records. A private Edge Function lets people sign in with usernames without exposing their email mapping. The role is read from the database, and Row Level Security protects the data. The shared portal template lets all four roles use the same layout while showing different navigation and records.”

For a live demonstration, sign in with a prepared test account, show its role-specific pages, submit a feedback request, and then show the new row in Supabase Table Editor. Do not show `.env` or copy its values into slides.
