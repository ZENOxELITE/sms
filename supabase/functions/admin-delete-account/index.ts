import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

Deno.serve(async (request) => {
  if (request.method !== "POST") {
    return Response.json({ error: "Method not allowed" }, { status: 405 });
  }

  const authorization = request.headers.get("Authorization") ?? "";
  const authorizationToken = authorization.startsWith("Bearer ")
    ? authorization.slice("Bearer ".length)
    : "";
  const accessToken = authorizationToken ||
    request.headers.get("X-Supabase-User-Access-Token")?.trim() ||
    "";
  const url = Deno.env.get("SUPABASE_URL");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !serviceRoleKey) {
    return Response.json({
      error: "Account removal is not configured in Supabase Edge Function secrets",
    }, { status: 500 });
  }
  if (!accessToken) {
    return Response.json({
      error: "A signed-in Supabase session is required",
    }, { status: 401 });
  }

  const supabase = createClient(url, serviceRoleKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
  const { data: authResult, error: authError } = await supabase.auth.getUser(accessToken);
  if (authError || !authResult.user) {
    return Response.json({ error: "A valid signed-in admin session is required" }, { status: 401 });
  }

  const { data: callerProfile, error: callerError } = await supabase
    .from("profiles")
    .select("role")
    .eq("id", authResult.user.id)
    .maybeSingle();
  if (callerError) {
    console.error("Could not verify requesting profile", callerError.message);
    return Response.json({ error: "Could not verify administrator access" }, { status: 500 });
  }
  if (callerProfile?.role !== "admin") {
    return Response.json({ error: "Administrator access is required" }, { status: 403 });
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return Response.json({ error: "Invalid request body" }, { status: 400 });
  }

  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
    return Response.json({ error: "Invalid request body" }, { status: 400 });
  }
  const profileIdValue = (payload as Record<string, unknown>).profile_id;
  const profileId = typeof profileIdValue === "string" ? profileIdValue.trim() : "";
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(profileId)) {
    return Response.json({ error: "Choose a valid campus account" }, { status: 400 });
  }

  const { data: targetProfile, error: targetError } = await supabase
    .from("profiles")
    .select("role")
    .eq("id", profileId)
    .maybeSingle();
  if (targetError) {
    console.error("Could not verify account to remove", targetError.message);
    return Response.json({ error: "Could not verify the campus account" }, { status: 500 });
  }
  if (!targetProfile) {
    return Response.json({ error: "The campus account was not found" }, { status: 404 });
  }
  if (!["student", "teacher", "hod"].includes(targetProfile.role)) {
    return Response.json({ error: "Administrator accounts cannot be removed here" }, { status: 403 });
  }

  const { error: deleteError } = await supabase.auth.admin.deleteUser(profileId);
  if (deleteError) {
    console.error("Could not remove Auth account", deleteError.message);
    return Response.json({ error: "Could not remove this campus account" }, { status: 500 });
  }

  return Response.json({ deleted: true });
});
