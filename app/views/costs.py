from flask import Blueprint, render_template, request, redirect, url_for
from ..models import db, Customer

bp = Blueprint(
    "costs",
    __name__,
    template_folder="templates/costs"
)
