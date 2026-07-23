from flask import Flask, request
from peewee import DoesNotExist, IntegrityError

from app.settings import Config
from app.db import init_database
from app.modules.logger import setup_json_logging
from app.i18n import register_i18n
from app.middleware import enforce_api_authentication
from app.views.admin_users_view import admin_users_bp
from app.views.alerts_view import alerts_bp
from app.views.auth_view import auth_bp
from app.views.calendar_view import calendar_bp
from app.views.channels_view import channels_bp
from app.views.escalation_policies_view import escalation_policies_bp
from app.views.docs_view import docs_bp
from app.views.groups_view import groups_bp
from app.views.health_view import HEALTH_PATHS, health_bp
from app.views.profile_view import profile_bp
from app.views.integrations_view import integrations_bp
from app.views.pages_view import pages_bp
from app.views.rotations_view import rotations_bp
from app.views.oncall_health_view import oncall_health_bp
from app.views.routes_view import routes_bp
from app.views.silences_view import silences_bp
from app.views.teams_view import teams_bp
from app.views.users_view import users_bp
from app.views.version_view import version_bp
from app.views.sso_admin_view import sso_admin_bp
from app.views.sso_auth_view import sso_auth_bp
from app.services.db_errors import handle_integrity_error, handle_not_found_error
from app.views.services_view import services_bp
from app.views.push_view import push_bp
from app.views.notification_rules_view import notification_rules_bp
from app.views.incidents_view import incidents_bp
from app.views.maintenance_view import maintenance_bp
from app.views.caldav_view import caldav_bp
from app.views.notification_center_view import notification_center_bp
from app.views.notification_policies_view import notification_policies_bp
from app.views.matcher_presets_view import matcher_presets_bp
from app.views.priority_policies_view import priority_policies_bp
from app.views.matchers_view import matchers_bp
from app.views.business_services.routes import business_services_bp
from app.views.heartbeats_view import heartbeats_bp
from app.views.orchestrations_view import orchestrations_bp


def create_app(log_role=None):
    """
    Create and configure the Flask application.
    """

    flask_app = Flask(__name__)
    flask_app.config.from_object(Config)
    register_i18n(flask_app)
    setup_json_logging(flask_app, log_role=log_role)

    flask_app.register_error_handler(IntegrityError, handle_integrity_error)
    flask_app.register_error_handler(DoesNotExist, handle_not_found_error)

    db = init_database()

    @flask_app.before_request
    def before_request():
        """
        Open a database connection before each request.

        Health probes (/healthz, /readyz) bypass the implicit DB
        connect: /healthz must work even when the database is down
        (otherwise Kubernetes would restart a healthy pod for no
        reason), and /readyz manages its own connection explicitly so
        it can return a clean 503 on DB errors.
        """

        if request.path not in HEALTH_PATHS:
            if db.is_closed():
                db.connect()

        auth_response = enforce_api_authentication()
        if auth_response is not None:
            return auth_response

    @flask_app.teardown_request
    def teardown_request(exc):
        """
        Close the database connection after each request.
        """

        if not db.is_closed():
            db.close()

    register_blueprints(flask_app)
    return flask_app


def register_blueprints(flask_app):
    """
    Register application blueprints.
    """

    flask_app.register_blueprint(pages_bp)
    flask_app.register_blueprint(docs_bp)
    flask_app.register_blueprint(health_bp)
    flask_app.register_blueprint(version_bp, url_prefix="/api/version")
    flask_app.register_blueprint(auth_bp, url_prefix="/api/auth")
    flask_app.register_blueprint(sso_auth_bp, url_prefix="/api/auth/sso")
    flask_app.register_blueprint(groups_bp, url_prefix="/api/groups")
    flask_app.register_blueprint(profile_bp, url_prefix="/api/profile")
    flask_app.register_blueprint(teams_bp, url_prefix="/api/teams")
    flask_app.register_blueprint(users_bp, url_prefix="/api/users")
    flask_app.register_blueprint(admin_users_bp, url_prefix="/api/admin/users")
    flask_app.register_blueprint(rotations_bp, url_prefix="/api/rotations")
    flask_app.register_blueprint(oncall_health_bp, url_prefix="/api/oncall-health")
    flask_app.register_blueprint(calendar_bp, url_prefix="/api/calendar")
    flask_app.register_blueprint(caldav_bp)
    flask_app.register_blueprint(alerts_bp, url_prefix="/api/alerts")
    flask_app.register_blueprint(incidents_bp, url_prefix="/api/incidents")
    flask_app.register_blueprint(maintenance_bp, url_prefix="/api/maintenance-windows")
    flask_app.register_blueprint(channels_bp, url_prefix="/api/channels")
    flask_app.register_blueprint(routes_bp, url_prefix="/api/routes")
    flask_app.register_blueprint(services_bp, url_prefix="/api/services")
    flask_app.register_blueprint(escalation_policies_bp, url_prefix="/api/escalation-policies")
    flask_app.register_blueprint(silences_bp, url_prefix="/api/silences")
    flask_app.register_blueprint(integrations_bp, url_prefix="/api/integrations")
    flask_app.register_blueprint(sso_admin_bp, url_prefix="/api/admin/sso")
    flask_app.register_blueprint(push_bp, url_prefix="/api")
    flask_app.register_blueprint(notification_rules_bp, url_prefix="/api")
    flask_app.register_blueprint(notification_center_bp, url_prefix="/api/notification-center")
    flask_app.register_blueprint(notification_policies_bp, url_prefix="/api/notification-policies")
    flask_app.register_blueprint(matcher_presets_bp, url_prefix="/api/matcher-presets")
    flask_app.register_blueprint(matchers_bp, url_prefix="/api/matchers")
    flask_app.register_blueprint(priority_policies_bp, url_prefix="/api/priority-policies")
    flask_app.register_blueprint(business_services_bp)
    flask_app.register_blueprint(heartbeats_bp, url_prefix="/api/heartbeats")
    flask_app.register_blueprint(orchestrations_bp, url_prefix="/api/event-orchestrations")
