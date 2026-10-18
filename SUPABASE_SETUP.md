# Supabase setup and account provisioning

## Configure Flask

1. Copy `.env.example` to `.env`.
2. Set the Supabase **Project URL**, publishable/anon key, a random `FLASK_SECRET_KEY`, and the username lookup secret described below.
3. Keep `.env` private; `.gitignore` excludes it.
4. Install dependencies and run Flask:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Visit `/health/supabase`. A connected result verifies the REST API is returning JSON from the configured project.

## Apply the database schema and policies

In the Supabase SQL Editor:

- For a **new, empty project**, run [`supabase/schema.sql`](./supabase/schema.sql), then [`supabase/role_policies.sql`](./supabase/role_policies.sql).
- If you already created the tables with the earlier schema, run the updated [`supabase/role_policies.sql`](./supabase/role_policies.sql) only. It creates missing `exams` and `departments` tables, adds the username field, seeds starting academic units, and replaces the named role policies.

The role-policy file replaces the starter policies with role-aware Row Level Security policies used by Flask. It is safe to rerun: it creates/replaces helper functions and drops/recreates the named policies. The base schema uses ordinary `create table` statements, so do not rerun it on a database where those tables already exist.

The starter department list focuses on computing and engineering: Computer Science and Information Technology, plus Biomedical, Civil, and Electrical Engineering. These are drawn from academic areas described on the [official Ziauddin University website](https://zu.edu.pk/) and its [College of Engineering & Technology page](https://zu.edu.pk/faculty-of-engineering-science-technology-management/college-of-engineering-technology/). When you rerun the current role-policy SQL, it removes the previous generic starter entries and keeps any other custom department entries you added.

## Reset application data

If you want to start with empty application tables while preserving the database schema and Supabase Auth accounts, first export/backup any records you may need. Then run [`supabase/reset_app_data.sql`](./supabase/reset_app_data.sql) in the Supabase SQL Editor. This permanently clears all rows from the app tables and resets generated numeric IDs. It does **not** delete Supabase Auth users, but it deletes every `profiles` row; those users will not be able to enter a portal until you create a fresh matching profile row for each Auth user.

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

The function requires Supabase's built-in `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` Edge Function secrets. Do not put the service-role key in Flask `.env` or browser code.

3. Generate a separate shared secret, then set the **same value** as a Supabase Edge Function secret and in Flask's private `.env`:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
supabase secrets set USERNAME_LOOKUP_SECRET=PASTE_GENERATED_VALUE
```

Add `SUPABASE_USERNAME_LOOKUP_SECRET=PASTE_THE_SAME_VALUE` to `.env`, then restart Flask. Never commit or share this secret.

4. Set each existing user's lowercase username on their `profiles` row in Supabase Table Editor, or use SQL:

```sql
update public.profiles
set username = 'student01'
where id = 'AUTH_USER_UUID';
```

Usernames must be unique and 3–32 characters: lowercase letters, numbers, periods, underscores, or hyphens; they must start with a letter or number. Set usernames for staff accounts too. Password-reset requests still use the account email address.

## Create student, teacher, and HOD accounts from the admin panel

After the first admin account is created using the SQL steps below, deploy this additional Edge Function:

```powershell
supabase functions deploy admin-create-account
```

Do **not** pass `--no-verify-jwt` for this function. It accepts only a valid signed-in Supabase session and independently checks that the caller's profile role is `admin`. It uses the Supabase service-role key only inside the hosted function to create the Auth user and matching profile. Never copy that key into Flask `.env`.

The admin opens **Students & Staff** and enters the person's email, full name, username, initial password, role, and department. Student accounts also require a student number. The function confirms the department exists, creates the email-confirmed Auth user, and inserts the matching role profile. If profile creation fails, it attempts to remove the just-created Auth user. The admin should give the initial password to the account holder privately; users can request a reset later using their email.

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

- Flask accepts email/password or username/password; username lookup uses a private Edge Function, then Supabase Auth verifies the credentials.
- Auth tokens stay in the Flask process; the browser receives only a signed session identifier.
- Each page uses the signed-in user's access token, so Supabase RLS applies to its queries.
- Students can view their own profile, enrollments, timetable, attendance, published grades, invoices, notices, and requests.
- Students can view scheduled exams for their enrolled courses.
- Teachers can view assigned courses, record attendance for enrolled students, and save unpublished grades.
- HODs can review their department's courses, enrollments, and class sessions.
- Admins can add departments, create student/teacher/HOD accounts with department assignments, manage courses, class sessions, exams, teacher assignments, and student enrollments, and publish announcements.
- Students can submit feedback and complaints. Password-reset email uses Supabase Auth.

The browser session is held in process memory for this small class-project deployment. Restarting Flask signs users out; use a persistent server-side session store before deploying multiple Flask workers or a production service.

## Testing safely

Run `python -m unittest discover -s tests`. This does not insert or modify records in Supabase. To check a real write, sign in with a provisioned test account, submit a feedback item, then confirm that one row appears in `student_requests` in the Supabase Table Editor.

Never put a Supabase service-role/secret key in Flask `.env` or browser code. The service-role key is used only inside the trusted Edge Function; Flask uses the public anon/publishable key, and portal reads/writes rely on RLS.
