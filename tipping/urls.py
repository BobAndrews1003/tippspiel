from django.urls import path

from . import views


urlpatterns = [
    path(
        "privacidad/",
        views.privacy_policy,
        name="privacy_policy",
    ),
    path(
        "terminos/",
        views.terms_of_use,
        name="terms_of_use",
    ),
    path(
        "contacto/",
        views.legal_contact,
        name="legal_contact",
    ),
    path(
        "reglas/",
        views.rules,
        name="rules",
    ),
    path(
        "perfil/notificaciones/",
        views.notification_settings,
        name="notification_settings",
    ),
    path(
        "groups/<int:group_id>/pronosticar/",
        views.group_tip_redirect,
        name="group_tip_redirect",
    ),
    path(
        "tippen/",
        views.tippen,
        name="tippen",
    ),
    path(
        "bonus/",
        views.bonus_tips,
        name="bonus_tips",
    ),
    path(
        "spieltag/",
        views.spieltag,
        name="spieltag",
    ),
    path(
        "tabelle/",
        views.tabelle,
        name="tabelle",
    ),
    path(
        "join/",
        views.join_group,
        name="join_group",
    ),
    path(
        "create-group/",
        views.create_group,
        name="create_group",
    ),
    path(
        "groups/",
        views.my_groups,
        name="my_groups",
    ),
    path(
        "groups/<int:group_id>/",
        views.group_detail,
        name="group_detail",
    ),
    path(
        "groups/<int:group_id>/rotate-code/",
        views.rotate_group_join_code,
        name="rotate_group_join_code",
    ),
    path(
        "groups/<int:group_id>/members/<int:user_id>/remove/",
        views.remove_group_member,
        name="remove_group_member",
    ),
    path(
        "groups/<int:group_id>/leave/",
        views.leave_group,
        name="leave_group",
    ),
    
    path(
    "groups/<int:group_id>/transfer/",
    views.transfer_group_ownership,
    name="transfer_group_ownership",
    ),
    path(
    "groups/<int:group_id>/delete/",
    views.delete_group,
    name="delete_group",
    ),
    
    path(
        "set-active-group/",
        views.set_active_group,
        name="set_active_group",
    ),
    path(
        "stats/<int:user_id>/",
        views.user_stats,
        name="user_stats",
    ),
    path(
    "account/delete/",
    views.delete_account,
    name="delete_account",  
    ),
    
    
    path(
    "inicio/",
    views.dashboard,
    name="dashboard",
),
    
    
]
