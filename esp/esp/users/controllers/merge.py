from __future__ import absolute_import
from django.db import transaction
from django.db.utils import IntegrityError

from esp.users.models import UserForwarder

__all__ = ['get_related', 'merge', 'merge_users']

#####################
# Internal use only #
#####################

def _populate_related(target, related_list, many_to_many):
    """Populate a list of related objects in a palatable format."""
    ans = []
    for related in related_list:
        name_out = related.get_accessor_name()
        name_in = related.field.name
        objects = getattr(target, name_out, None)
        if objects is None:
            continue
        for obj in objects.all():
            ans.append((obj, name_in, many_to_many))
    return ans

def _get_simply_related(target):
    """Gets objects related to 'target' through anything but many-to-many."""
    objects = [f for f in target._meta.get_fields() if (f.one_to_many or f.one_to_one) and f.auto_created and not f.concrete]
    return _populate_related(target, objects, False)

def _get_m2m_related(target):
    """Gets objects related to 'target' through a many-to-many."""
    objects = [f for f in target._meta.get_fields(include_hidden=True) if f.many_to_many and f.auto_created]
    return _populate_related(target, objects, True)


################################
# Potentially useful elsewhere #
################################

def get_related(target):
    """
    Gets objects related to 'target'.

    Returns a list of tuples (object, field_name, many_to_many).
    e.g. (<ClassSubject>, 'meeting_times', True)

    """
    return _get_simply_related(target) + _get_m2m_related(target)

from django.db import transaction

@transaction.atomic
def merge(absorber, absorbee):
    """Transfers everything from absorbee to absorber.

    This operation is wrapped in a single atomic transaction
    so that either all related data is transferred successfully
    or everything rolls back on error.
    """
    for obj, name, m2m in get_related(absorbee):
        # Handle many-to-many relations
        if m2m:
            rel = getattr(obj, name)
            if rel.through._meta.auto_created:
                rel.remove(absorbee)
                rel.add(absorber)
        else:
            # Handle ForeignKey or One-to-One relations
            setattr(obj, name, absorber)
            obj.save()

    # Also check local many-to-many fields
    for field in absorber._meta.local_many_to_many:
        getattr(absorber, field.attname).add(
            *getattr(absorbee, field.attname).all()
        )


#########################
# Usable from the shell #
#########################

def merge_users(absorber, absorbee, forward=True, deactivate=False):
    """
    Merge two accounts, transferring everything from absorbee to abosorber.

    Options:
        forward: Set up login forwarding from absorbee to absorber
        deactivate: Deactivate the absorbee

    """
    merge(absorber, absorbee)
    # Set up forwarding
    if forward:
        UserForwarder.forward(absorbee, absorber)
    # Deactivate the absorbed account.
    if deactivate:
        absorbee.is_active = False
        absorbee.save()
