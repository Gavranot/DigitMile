"""Template tags for the customized admin dashboard (admin/index.html)."""

from django import template

from digitmileapi.models import School, Teacher

register = template.Library()


@register.simple_tag
def pending_registration_count():
    """Total schools + teachers awaiting superuser review.

    Used to badge the 'Pending Registrations' promo on the admin dashboard so a
    superuser can see at a glance whether anything needs action.
    """
    return School.objects.pending().count() + Teacher.objects.pending().count()
