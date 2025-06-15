from flask import Blueprint

bp = Blueprint('reports', __name__, template_folder='templates/reports')

@bp.route('/')
def pl_report():
    pass