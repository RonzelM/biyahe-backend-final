from pathlib import Path

import joblib
from flask import Blueprint, jsonify, request

demand_bp = Blueprint("demand", __name__)

MODEL_PATH = Path(__file__).resolve().parent / "linear" / "linear_regression_demand_model.joblib"

try:
    demand_model = joblib.load(MODEL_PATH)
except Exception:
    demand_model = None

DEMAND_FEATURES = ["day_of_week", "month", "is_weekend"]


def _row_from_named_payload(payload):
    missing = [feature for feature in DEMAND_FEATURES if feature not in payload]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")
    return [float(payload[feature]) for feature in DEMAND_FEATURES]


@demand_bp.route("/predict-demand", methods=["POST"])
def predict_demand():
    if demand_model is None:
        return jsonify({"error": "Demand model failed to load"}), 500

    data = request.get_json(silent=True) or {}

    if "instances" in data and isinstance(data["instances"], list):
        instances = data["instances"]
    elif all(feature in data for feature in DEMAND_FEATURES):
        instances = [data]
    elif "features" in data:
        instances = [data["features"]]
    else:
        return (
            jsonify(
                {
                    "error": "Provide named demand fields, or 'features', or 'instances'"
                }
            ),
            400,
        )

    if not isinstance(instances, list) or not instances:
        return jsonify({"error": "'instances' must be a non-empty list"}), 400

    try:
        cleaned = []
        for row in instances:
            if isinstance(row, dict):
                cleaned.append(_row_from_named_payload(row))
            elif isinstance(row, list) and row:
                cleaned.append([float(value) for value in row])
            else:
                return jsonify({"error": "Each instance must be a dict or non-empty list"}), 400

        preds = demand_model.predict(cleaned).tolist()
    except Exception as exc:
        return jsonify({"error": f"Prediction failed: {str(exc)}"}), 400

    return jsonify({"predictions": preds}), 200
