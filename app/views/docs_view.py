from flask import Blueprint, jsonify, redirect, render_template

from app.api.openapi.spec import build_openapi_spec
from app.middleware import load_jwt_user


docs_bp = Blueprint("docs", __name__)


@docs_bp.route("/docs")
@docs_bp.route("/swagger")
def swagger_ui():
    """
    Render Swagger UI.
    """

    if not load_jwt_user():
        return redirect("/login")

    return render_template("swagger.html")


@docs_bp.route("/api/openapi.json")
def openapi_json():
    """
    Return OpenAPI specification.
    """

    return jsonify(build_openapi_spec())
