from flask import Blueprint, render_template

bp = Blueprint('main', __name__)

@bp.route('/')
def top():
    return render_template('main/top.html')