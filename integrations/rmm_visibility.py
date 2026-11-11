"""Who may see synced RMM data (device status, software, alerts, console
links) on asset and ticket pages.

MSP technicians only, and for the customer in question one of:
  * the `integrations_view` role flag (the flag that gates /integrations/,
    where the same devices are listed), or
  * RMM device access through rmm_permissions (`device.view`), which is how
    RMM tier technicians (L1-L3) with a technician access assignment see
    devices without holding integrations_view.

Customer users never see it, whatever their role says.
"""


def can_see_rmm_data(user, organization) -> bool:
    from psa.visibility import is_msp_staff
    if organization is None or not is_msp_staff(user):
        return False
    from accounts.permission_utils import has_perm_for_org
    if has_perm_for_org(user, organization, 'integrations_view'):
        return True
    try:
        from rmm_permissions.decision import can
        return bool(can(user, organization, 'device.view').allowed)
    except Exception:
        return False
