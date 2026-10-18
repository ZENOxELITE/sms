window.mindmapData = {
  name: "Student Management System",
  type: "root",
  description: "A simple student, teacher, HOD and admin portal.",
  children: [
    { name: "Actors", type: "actor", children: [
      { name: "Student", type: "actor", children: [
        { name: "View dashboard", type: "page" }, { name: "View profile", type: "page" },
        { name: "Check attendance", type: "page" }, { name: "View results and exams", type: "page" },
        { name: "Check timetable", type: "page" }, { name: "View notifications", type: "page" },
        { name: "View invoices", type: "page" }, { name: "Send feedback or complaints", type: "page" }
      ] },
      { name: "Teacher", type: "actor", children: [
        { name: "View assigned classes", type: "page" }, { name: "Record attendance", type: "page" },
        { name: "Submit student results", type: "page" }
      ] },
      { name: "HOD", type: "actor", children: [
        { name: "Review department classes", type: "page" }, { name: "Review attendance and results", type: "page" }
      ] },
      { name: "Admin", type: "actor", children: [
        { name: "Manage student and staff accounts", type: "page" }, { name: "Manage courses and classes", type: "page" },
        { name: "Publish announcements", type: "page" }
      ] }
    ] },
    { name: "Pages", type: "group", children: [
      { name: "Login", type: "page", children: [
        { name: "Enter email and password", type: "page" }, { name: "Load assigned role from profile", type: "page" }
      ] },
      { name: "Student portal", type: "group", children: [
        { name: "Dashboard", type: "page" }, { name: "Profile", type: "page" },
        { name: "Attendance", type: "page" }, { name: "Results and exams", type: "page" },
        { name: "Exam datasheet", type: "page" }, { name: "Notifications", type: "page" },
        { name: "Feedback", type: "page" }, { name: "Timetable", type: "page" },
        { name: "Invoices", type: "page" }, { name: "Complaints", type: "page" }
      ] },
      { name: "Teacher portal", type: "group", children: [
        { name: "Dashboard", type: "page" }, { name: "Classes", type: "page" },
        { name: "Attendance entry", type: "page" }, { name: "Results entry", type: "page" }
      ] },
      { name: "HOD portal", type: "group", children: [
        { name: "Dashboard", type: "page" }, { name: "Department overview", type: "page" },
        { name: "Class and result review", type: "page" }
      ] },
      { name: "Admin portal", type: "group", children: [
        { name: "Dashboard", type: "page" }, { name: "Students and staff", type: "page" },
        { name: "Courses and classes", type: "page" }, { name: "Announcements", type: "page" }
      ] }
    ] },
    { name: "Application", type: "group", children: [
      { name: "Flask routes", type: "page" }, { name: "HTML templates", type: "page" },
      { name: "CSS styling", type: "page" }, { name: "Supabase database", type: "page" }
    ] }
  ]
};

window.mindmapFixtures = {
  oneNode: { name: "One node site" },
  twoPages: { name: "Two-page site", children: [{ name: "Page 1" }, { name: "Page 2" }] },
  thirtyPages: { name: "Thirty-page site", children: Array.from({ length: 30 }, (_, index) => ({ name: `Page ${index + 1}` })) },
  fortyFlatPages: { name: "Forty-page site", children: Array.from({ length: 40 }, (_, index) => ({ name: `A longer example page ${index + 1}` })) }
};
