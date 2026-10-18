-- Permanently deletes all application records while keeping the schema and
-- Supabase Auth users. Existing Auth users will need new public.profiles rows.
begin;

truncate table
  public.attendance_records,
  public.student_requests,
  public.grades,
  public.invoices,
  public.announcements,
  public.exams,
  public.class_sessions,
  public.enrollments,
  public.course_staff,
  public.courses,
  public.profiles
restart identity;

commit;
