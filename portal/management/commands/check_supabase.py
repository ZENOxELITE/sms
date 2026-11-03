from django.core.management.base import BaseCommand, CommandError

from supabase_client import get_supabase_client


class Command(BaseCommand):
    help = "Check that the configured Supabase project is reachable."

    def handle(self, *args, **options):
        try:
            response = (
                get_supabase_client()
                .table("courses")
                .select("id")
                .limit(1)
                .execute()
            )
        except RuntimeError as error:
            raise CommandError(str(error)) from error
        except Exception as error:
            raise CommandError(
                "Supabase connection failed. Check your .env settings, internet "
                "connection, project status, and database access."
            ) from error

        if not isinstance(response.data, list):
            raise CommandError(
                "Supabase returned an unexpected response. Check SUPABASE_URL."
            )

        self.stdout.write(self.style.SUCCESS("Supabase connection: OK"))
