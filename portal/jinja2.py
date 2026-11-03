from django.templatetags.static import static
from django.urls import reverse
from jinja2 import Environment, pass_context
from jinja2.utils import htmlsafe_json_dumps


@pass_context
def url_for(_context, viewname, **kwargs):
    if viewname == "static":
        return static(kwargs["path"])
    return reverse(viewname, kwargs=kwargs or None)


@pass_context
def get_flashed_messages(context, with_categories=False):
    request = context.get("request")
    if request is None:
        return []
    messages = request.session.pop("_flashes", [])
    if with_categories:
        return messages
    return [message for _category, message in messages]


def environment(**options):
    env = Environment(**options)
    env.globals.update(
        url_for=url_for,
        get_flashed_messages=get_flashed_messages,
    )
    env.filters["tojson"] = htmlsafe_json_dumps
    return env
