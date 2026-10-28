# Supabase setup and account provisioning

## Configure FastAPI

1. Copy `.env.example` to `.env` in the project root, beside `app.py`.
2. Set the Supabase **Project URL**, publishable/anon key, and username lookup secret described below. Keep the existing `FLASK_SECRET_KEY` value as the signed-session secret; it does not need to be renamed during the framework migration.
3. Keep `.env` private; `.gitignore` excludes it.
4. Install dependencies and run FastAPI:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app:app --reload --host 127.0.0.1 --port 5000
```

Visit `http://127.0.0.1:5000/health/supabase`. A connected result verifies the REST API is returning JSON from the configured project. `python app.py` is also available for a simple local start without reload.

If account management reports that configuration is missing, make sure `SUPABASE_URL` and `SUPABASE_ANON_KEY` are non-empty in the project-root `.env` file and restart FastAPI. If it reports that Edge Function secrets are missing, confirm the function is deployed to the same Supabase project as the configured URL; Supabase provides `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` to its Edge Function runtime. A missing signed-in session is a separate authentication error.

## Apply the database schema and policies

In the Supabase SQL Editor:

- For a **new, empty project**, run [`supabase/schema.sql`](../supabase/schema.sql), then [`supabase/role_policies.sql`](../supabase/role_policies.sql).
- If you already created the tables with the earlier schema, run the updated [`supabase/role_policies.sql`](../supabase/role_policies.sql) only. It creates missing `exams` and `departments` tables, adds the username field, seeds starting academic units, and replaces the named role policies.

The role-policy file replaces the starter policies with role-aware Row Level Security policies used by the application. It is safe to rerun: it creates/replaces helper functions and drops/recreates the named policies. It adds program and semester fields to courses and student profiles, adds clearly marked unofficial sample curriculum rows, and makes account-removal attribution nullable so attendance and announcements remain after their creator is removed. The base schema uses ordinary `create table` statements, so do not rerun it on a database where those tables already exist.

The sample subject names, course codes, semesters, and credits are illustrative only, not official or complete Ziauddin curricula. The website has study-scheme tabs for [BS Cyber Security Technology](https://zu.edu.pk/faculty-of-computing-and-information-sciences/college-of-computing-and-emerging-technologies/department-of-emerging-technologies/bs-cyber-security-technology/) and [BS Software Engineering](https://zu.edu.pk/faculty-of-computing-and-information-sciences/college-of-computing-and-emerging-technologies/department-of-software-engineering/bs-software-engineering/); this project does not copy those official course lists. The requested Software Engineering Technology sample is also not verified as a current Ziauddin degree.

The starter department list focuses on computing and engineering: Computer Science and Information Technology, plus Biomedical, Civil, and Electrical Engineering. These are drawn from academic areas described on the [official Ziauddin University website](https://zu.edu.pk/) and its [College of Engineering & Technology page](https://zu.edu.pk/faculty-of-engineering-science-technology-management/college-of-engineering-technology/). When you rerun the current role-policy SQL, it removes the previous generic starter entries and keeps any other custom department entries you added.

## Reset application data

If you want to start with empty application tables while preserving the database schema and Supabase Auth accounts, first export/backup any records you may need. Then run [`supabase/reset_app_data.sql`](../supabase/reset_app_data.sql) in the Supabase SQL Editor. This permanently clears all rows from the app tables and resets generated numeric IDs. It does **not** delete Supabase Auth users, but it deletes every `profiles` row; those users will not be able to enter a portal until you create a fresh matching profile row for each Auth user.

## Enable username sign-in

The login page lets users choose email or username. Email sign-in goes directly to Supabase Auth and works without the username lookup. For username sign-in, a private Edge Function resolves the username to the Auth email on the server; the browser never receives the email mapping. Supabase Auth verifies the password in both cases.

1. Apply the updated `role_policies.sql` so existing projects get the `profiles.username` column and its uniqueness/format checks. Email login remains available even if you skip the rest of this section.
2. On Windows, install the Supabase CLI with Scoop. If Scoop is not installed, open a **non-administrator** PowerShell window and run:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
irm get.scoop.sh | iex
```

Then install the Supabase CLI:

```powershell
scoop bucket add supabase https://github.com/supabase/scoop-bucket.git
scoop install supabase
```

Close and reopen PowerShell so the updated PATH is loaded, then from this project folder run:

```powershell
supabase login
supabase link --project-ref YOUR_PROJECT_REF
supabase functions deploy username-lookup --no-verify-jwt
```

The function requires Supabase's built-in `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` Edge Function secrets. Do not put the service-role key in `.env` or browser code.

3. Generate a separate shared secret, then set the **same value** as a Supabase Edge Function secret and in the application's private `.env`:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
supabase secrets set USERNAME_LOOKUP_SECRET=PASTE_GENERATED_VALUE
```

Add `SUPABASE_USERNAME_LOOKUP_SECRET=PASTE_THE_SAME_VALUE` to `.env`, then restart the FastAPI server. Never commit or share this secret.

4. Set each existing user's lowercase username on their `profiles` row in Supabase Table Editor, or use SQL:

```sql
update public.profiles
set username = 'student01'
where id = 'AUTH_USER_UUID';
```

Usernames must be unique and 3–32 characters: lowercase letters, numbers, periods, underscores, or hyphens; they must start with a letter or number. Set usernames for staff accounts too. Password-reset requests still use the account email address.

## Create student, teacher, and HOD accounts from the admin panel

After the first admin account is created using the SQL steps below, deploy or redeploy this additional Edge Function:

```powershell
supabase functions deploy admin-create-account --no-verify-jwt
```

The function verifies the supplied session with Supabase Auth and checks that the caller's profile role is `admin` before doing anything privileged. The app sends the session token in both the standard `Authorization` header and a dedicated `X-Supabase-User-Access-Token` header; the function accepts either. Deploy the current function code after updating it. Disabling the gateway's JWT check allows the function's own verification to handle projects whose JWT signing keys are not accepted by the gateway. The service-role key stays inside the hosted function; never copy it into `.env`.

The admin opens **Students & Staff** and enters the person's email, full name, username, initial password, role, and department. Student accounts also require a student number; the optional program and semester fields identify a student's cohort. The function confirms the department exists, creates the email-confirmed Auth user, and inserts the matching role profile. If profile creation fails, it attempts to remove the just-created Auth user. The admin should give the initial password to the account holder privately; users can request a reset later using their email.

## Create synthetic demo cohorts

After applying `role_policies.sql`, redeploy `admin-create-account` if using the admin form for program/semester assignment. For the requested dataset of 25 synthetic teachers and 40 synthetic students in each of the 24 program/semester cohorts, run the local seeder:

```powershell
.\.venv\Scripts\python.exe scripts\seed_demo_accounts.py
.\.venv\Scripts\python.exe scripts\seed_demo_accounts.py --apply
```

The first command previews the batch. The second asks for the Supabase service-role key without echoing it and requires the confirmation text `CREATE DEMO DATA`. It creates 985 Auth users and matching profiles tagged by program and semester. Teacher accounts and Cyber Security/Software Engineering Technology student accounts use Computer Science; Software Engineering student accounts use Software Engineering. Names are generated from a fixed set of common first and family names and are not verified against real people; the usernames and `example.invalid` email addresses are synthetic. No real email can be delivered to them, so email-based password resets will not work. Unique passwords are written to `.demo-data\demo_credentials.csv`, which is excluded from Git. Keep that file private; username sign-in requires the username-lookup function to be configured.

If the demo accounts already exist with placeholder names, refresh their profile display names and the names in the private credentials CSV without changing login credentials:

```powershell
.\.venv\Scripts\python.exe scripts\seed_demo_accounts.py --refresh-names
```

This command requires the service-role key and the confirmation text `UPDATE DEMO NAMES`. These are still synthetic sample accounts, not actual student or staff records.

These program/semester tags identify demo cohorts only. To enable the scheduling and enrollment examples for a presentation, seed fictional courses, assign the synthetic teachers, and enroll the existing synthetic students:

```powershell
.\.venv\Scripts\python.exe scripts\seed_demo_accounts.py --seed-academic-data
```

The command requires the service-role key and the confirmation text `CREATE PRESENTATION RECORDS`. It idempotently creates 24 synthetic operational course records, 24 teacher assignments, and 960 student enrollments. The eight Software Engineering courses and their students are assigned to the `Software Engineering` department; this lets the matching HOD see those courses and enrollments. The remaining sample programs are assigned to Computer Science. Course records are marked and shown as synthetic in the admin portal; they are not official course offerings. The enrollment term is labeled `Fall 2026 (synthetic presentation)`. Rerun the command if a transient error occurs; it upserts by the existing unique keys. It does not schedule class sessions or exams; those can be entered afterwards using the now-enabled admin forms. There is no separate class-roster table in the current schema.

Alternatively, after applying `role_policies.sql` and creating the synthetic demo accounts, open `supabase/seed_presentation_rosters.sql` in the Supabase SQL Editor and run it. It creates or reuses the 24 synthetic program/semester courses, assigns one synthetic teacher to each course, and enrolls the 40 matching synthetic students per course. It moves only synthetic Software Engineering student profiles and courses to the existing `Software Engineering` department; its HOD will then see eight courses and 320 enrollments. The script checks the expected demo cohorts before writing, leaves non-synthetic accounts and courses alone, runs in a transaction, and can be rerun safely. Its final query reports the course, assignment, and enrollment counts. Use this instead of the Python `--seed-academic-data` command; both populate the same presentation records.

To enable account removal, also deploy the admin-only removal function:

```powershell
supabase functions deploy admin-delete-account --no-verify-jwt
```

Like account creation, this function verifies the supplied session with Supabase Auth and checks the caller's admin role itself. It accepts the session token in either the standard or dedicated header. Deploy the current function code after updating it. Disabling the gateway's JWT check lets that verification work with projects whose JWT signing keys are not accepted by the gateway. The admin can remove student, teacher, and HOD accounts from **Students & Staff**. This permanently deletes their Supabase Auth account and profile, along with dependent enrollments, grades, attendance as a student, invoices, requests, and course assignments. Attendance and announcements they authored are retained with the author reference cleared. Administrator accounts are protected and cannot be removed in the panel. On **Departments**, removal is blocked while any profile or course still names that department; reassign or remove those records first.

## Create the administrator first

The website does not let users pick their own role. That would let a student claim an administrator account. Instead:

1. In Supabase Dashboard, open **Authentication → Users → Add user** and create your own admin account with an email and password. For a school project, manually confirming the email in the dashboard avoids requiring an email provider.
2. Copy the new Auth user's UUID.
3. In Supabase SQL Editor, create the first profile with the `admin` role. Replace the UUID, name, username, and department with your own values:

```sql
insert into public.profiles (id, full_name, username, role, department)
values ('AUTH_USER_UUID', 'Your Name', 'youradminusername', 'admin', 'Administration');
```

4. Sign into the website with the admin username (or email) and password. The first admin profile must be inserted through the Supabase Dashboard/SQL Editor. Deploy `admin-create-account` as above, then use the admin account to manage departments, create student/teacher/HOD accounts, manage courses, assign teachers, enroll students, and publish announcements.

Only a trusted project owner should assign staff roles. For the first admin and recovery accounts, create the Auth user in **Authentication → Users**, copy its Auth UUID, and insert a matching profile. For example, a student profile:

```sql
insert into public.profiles (id, full_name, username, role, department, student_number)
values ('STUDENT_AUTH_USER_UUID', 'Student Name', 'student01', 'student', 'Business Administration', 'STU-0001');
```

Use `teacher` or `hod` for staff profiles as appropriate. Students need unique student numbers; staff may leave `student_number` null. Give every account a unique username if username sign-in is enabled.

## What is connected

- FastAPI accepts email/password or username/password; username lookup uses a private Edge Function, then Supabase Auth verifies the credentials.
- Auth tokens stay in the application process; the browser receives only a signed session identifier.
- Each page uses the signed-in user's access token, so Supabase RLS applies to its queries.
- Students can view their own profile, enrollments, timetable, attendance, published grades, invoices, notices, and requests.
- Students can view scheduled exams for their enrolled courses.
- Teachers can view assigned courses, record attendance for enrolled students, and save unpublished grades.
- HODs can review their department's courses, enrollments, and class sessions.
- Admins can add departments, create student/teacher/HOD accounts with department assignments, manage courses, class sessions, exams, teacher assignments, and student enrollments, and publish announcements.
- Students can submit feedback and complaints. Password-reset email uses Supabase Auth.

The browser session is held in process memory for this small class-project deployment. Restarting the FastAPI application signs users out; use a persistent server-side session store before deploying multiple Uvicorn workers or a production service.

## Testing safely

Run `python -m unittest discover -s tests`. This does not insert or modify records in Supabase. To check a real write, sign in with a provisioned test account, submit a feedback item, then confirm that one row appears in `student_requests` in the Supabase Table Editor.

Never put a Supabase service-role/secret key in `.env` or browser code. The service-role key is used only inside the trusted Edge Function; FastAPI uses the public anon/publishable key, and portal reads/writes rely on RLS.
