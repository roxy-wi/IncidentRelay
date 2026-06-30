from app.views.services.blueprint import services_bp

from app.views.services import core as core_routes  # noqa: F401,E402
from app.views.services import details as details_routes  # noqa: F401,E402
from app.views.services import owners as owners_routes  # noqa: F401,E402
from app.views.services import match_rules as match_rules_routes  # noqa: F401,E402
from app.views.services import links as links_routes  # noqa: F401,E402
from app.views.services import runbooks as runbooks_routes  # noqa: F401,E402
from app.views.services import dependencies as dependencies_routes  # noqa: F401,E402
from app.views.services import sli_slo as sli_slo_routes  # noqa: F401,E402
from app.views.services import readiness as readiness_routes  # noqa: F401,E402
from app.views.services import standards as standards_routes  # noqa: F401,E402
from app.views.services import impact as impact_routes  # noqa: F401,E402
from app.views.services import analytics as analytics_routes  # noqa: F401,E402

__all__ = ["services_bp"]
