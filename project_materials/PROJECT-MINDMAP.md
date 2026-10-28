# Student Management System — Project Mind Map

```mermaid
mindmap
  root((Student Management System))
    Actors
      Student
        View dashboard
        View profile
        Check attendance
        View results and exams
        Check timetable
        View notifications
        View invoices
        Send feedback or complaints
      Teacher
        View assigned classes
        Record attendance
        Submit student results
      HOD
        Review department classes
        Review attendance and results
      Admin
        Manage student and staff accounts
        Manage courses and classes
        Publish announcements
    Pages
      Login
        Sign in with email and password
        Load assigned role from profile
      Student portal
        Dashboard
        Profile
        Attendance
        Results and exams
        Exam datasheet
        Notifications
        Feedback
        Timetable
        Invoices
        Complaints
      Teacher portal
        Dashboard
        Classes
        Attendance entry
        Results entry
      HOD portal
        Dashboard
        Department overview
        Class and result review
      Admin portal
        Dashboard
        Students and staff
        Courses and classes
        Announcements
    Application
      FastAPI routes
      HTML templates
      CSS styling
      Supabase database
```

## Build scope

The project includes the **Login** page and role-specific portal pages. Authentication and portal reads/writes use Supabase after the schema and role policies are applied and accounts have matching `profiles` rows.

## Simple page flow

```text
Login → Student dashboard → Select a section from the sidebar
```

## Interactive project map

Open `/map` to explore this structure. Radial is the default for up to 60 nodes; use the Layout buttons to switch between Radial and Tree. Search, filters, node expansion, and layout preference work in the current browser session. `/map?test=1` runs the radial label-collision checks for the 2-page, 30-page, and 40-page sample sites.

The map loads D3 v7 from jsDelivr, so its interactive layout requires an internet connection. Supabase setup steps are documented in [SUPABASE_SETUP.md](./SUPABASE_SETUP.md).
