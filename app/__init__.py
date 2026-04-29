from flask import Flask

from app.settings import Config
from app.db import init_database
from app.modules.logger import setup_json_logging
from app.middleware import enforce_api_authentication
from app.views.admin_users_view import admin_users_bp
from app.views.alerts_view import alerts_bp
from app.views.auth_view import auth_bp
from app.views.calendar_view import calendar_bp
from app.views.channels_view import channels_bp
from app.views.docs_view import docs_bp
from app.views.groups_view import groups_bp
from app.views.profile_view import profile_bp
from app.views.integrations_view import integrations_bp
from app.views.pages_view import pages_bp
from app.views.rotations_view import rotations_bp
from app.views.routes_view import routes_bp
from app.views.silences_view import silences_bp
from app.views.teams_view import teams_bp
from app.views.users_view import users_bp
from app.views.version_view import version_bp


def create_app():
    """
    Create and configure the Flask application.
    """

    flask_app = Flask(__name__)
    flask_app.config.from_object(Config)
    setup_json_logging(flask_app)

    db = init_database()

    @flask_app.before_request
    def before_request():
        """
        Open a database connection before each request.
        """

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
    flask_app.register_blueprint(version_bp, url_prefix="/api/version")
    flask_app.register_blueprint(auth_bp, url_prefix="/api/auth")
    flask_app.register_blueprint(groups_bp, url_prefix="/api/groups")
    flask_app.register_blueprint(profile_bp, url_prefix="/api/profile")
    flask_app.register_blueprint(teams_bp, url_prefix="/api/teams")
    flask_app.register_blueprint(users_bp, url_prefix="/api/users")
    flask_app.register_blueprint(admin_users_bp, url_prefix="/api/admin/users")
    flask_app.register_blueprint(rotations_bp, url_prefix="/api/rotations")
    flask_app.register_blueprint(calendar_bp, url_prefix="/api/calendar")
    flask_app.register_blueprint(alerts_bp, url_prefix="/api/alerts")
    flask_app.register_blueprint(channels_bp, url_prefix="/api/channels")
    flask_app.register_blueprint(routes_bp, url_prefix="/api/routes")
    flask_app.register_blueprint(silences_bp, url_prefix="/api/silences")
    flask_app.register_blueprint(integrations_bp, url_prefix="/api/integrations")
